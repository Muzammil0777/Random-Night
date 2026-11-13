"""Magic-link login, sessions, profile, and age rules (task 2)."""
import hashlib
import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import LoginToken, User, UserSession

log = logging.getLogger("randomnight.auth")
router = APIRouter(prefix="/api", tags=["auth"])
DbDep = Annotated[Session, Depends(get_db)]

LOGIN_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=30)
MAX_LINKS_PER_WINDOW = 3  # per email per LOGIN_TTL; stops inbox-bombing
MIN_AGE = 18
LICENSED_MIN_AGE = 21  # Telangana excise: bars/pubs/clubs


IST = timezone(timedelta(hours=5, minutes=30))  # India has no DST, so a fixed offset is exact


def now() -> datetime:
    return datetime.now(timezone.utc)


def today_ist() -> date:
    return now().astimezone(IST).date()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite drops tzinfo on read


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def age_on(dob: date, on: date) -> int:
    """Whole years on a given date. Feb-29 birthdays count from Mar 1 in non-leap years (conservative)."""
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def can_enter_licensed(user: User, on: date) -> bool:
    """21+ on the night itself, and an admin has checked their ID (a typed DOB alone isn't proof)."""
    return user.id_verified and age_on(user.dob, on) >= LICENSED_MIN_AGE


def send_login_email(email: str, link: str) -> None:
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        if not link.startswith("http://localhost"):
            # Never fall back to logging live login links outside local dev.
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Email is not configured")
        log.warning("DEV ONLY, no RESEND_API_KEY. Login link for %s: %s", email, link)
        return
    r = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "from": os.environ.get("EMAIL_FROM", "Random Night <onboarding@resend.dev>"),
            "to": [email],
            "subject": "Your Random Night login link",
            "html": f'<p><a href="{link}">Log in to Random Night</a></p><p>This link works once and expires in 15 minutes.</p>',
        },
        timeout=10,
    )
    r.raise_for_status()


# ---- schemas ----
class LinkRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}
    email: EmailStr
    name: str | None = Field(default=None, min_length=1, max_length=80)
    dob: date | None = Field(default=None, ge=date(1900, 1, 1))


class VerifyRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class Me(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    email: str
    name: str
    dob: date
    id_verified: bool
    gender: str | None
    emergency_contact: str | None


class MeUpdate(BaseModel):  # dob and email are deliberately not editable (age gate integrity)
    model_config = {"str_strip_whitespace": True}
    name: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def name_not_null(cls, v: str | None) -> str:
        if v is None:
            raise ValueError("name can't be empty")
        return v

    gender: str | None = Field(default=None, max_length=30)
    emergency_contact: str | None = Field(default=None, max_length=120)


class LoginResult(BaseModel):
    session: str
    user: Me


# ---- dependency ----
def current_user(db: DbDep, authorization: Annotated[str | None, Header()] = None) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in", {"WWW-Authenticate": "Bearer"})
    if not authorization or not authorization.startswith("Bearer "):
        raise unauthorized
    s = db.scalar(select(UserSession).where(UserSession.token_hash == _hash(authorization[7:])))
    if s is None or _aware(s.expires_at) <= now():
        raise unauthorized
    return db.get(User, s.user_id)


UserDep = Annotated[User, Depends(current_user)]


# ---- routes ----
@router.post("/auth/request", status_code=status.HTTP_202_ACCEPTED)
def request_link(body: LinkRequest, db: DbDep) -> dict[str, bool]:
    """Always 202 for valid input, whether or not the email has an account (no account enumeration)."""
    email = body.email.lower()
    if body.dob and age_on(body.dob, today_ist()) < MIN_AGE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Random Night is 18+")
    pending = db.scalar(select(func.count(LoginToken.id)).where(
        LoginToken.email == email, LoginToken.used_at.is_(None), LoginToken.expires_at > now()))
    if pending >= MAX_LINKS_PER_WINDOW:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many links requested, try again later")
    token = secrets.token_urlsafe(32)
    row = LoginToken(token_hash=_hash(token), email=email, name=body.name, dob=body.dob,
                     expires_at=now() + LOGIN_TTL)
    db.add(row)
    db.commit()
    try:
        send_login_email(email, f"{os.environ.get('APP_URL', 'http://localhost:5173')}/login?token={token}")
    except httpx.HTTPError:
        log.exception("login email failed for %s", email)
        db.delete(row)  # a failed send must not eat the user's rate-limit quota
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Couldn't send the email, please try again")
    return {"sent": True}


@router.post("/auth/verify")
def verify_link(body: VerifyRequest, db: DbDep) -> LoginResult:
    h = _hash(body.token)
    # Atomic single-use: only one request can flip used_at from NULL.
    used = db.execute(update(LoginToken)
                      .where(LoginToken.token_hash == h, LoginToken.used_at.is_(None), LoginToken.expires_at > now())
                      .values(used_at=now()))
    if used.rowcount != 1:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link is invalid, used or expired")
    lt = db.scalar(select(LoginToken).where(LoginToken.token_hash == h))
    user = db.scalar(select(User).where(User.email == lt.email))
    if user is None:
        if not (lt.name and lt.dob):
            db.commit()  # the link stays burned
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "New here? Sign up with your name and date of birth")
        user = User(email=lt.email, name=lt.name, dob=lt.dob)
        db.add(user)
        db.flush()
    session_token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=_hash(session_token), user_id=user.id, expires_at=now() + SESSION_TTL))
    db.commit()
    return LoginResult(session=session_token, user=Me.model_validate(user))


@router.get("/me")
def get_me(user: UserDep) -> Me:
    return Me.model_validate(user)


@router.patch("/me")
def update_me(body: MeUpdate, user: UserDep, db: DbDep) -> Me:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    return Me.model_validate(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(db: DbDep, user: UserDep, authorization: Annotated[str, Header()]) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == _hash(authorization[7:])))
    db.commit()
