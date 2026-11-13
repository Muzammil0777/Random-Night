"""Launch waitlist (task 11b): join with an email, share your link, move up for each friend who joins through it.

Order: more referrals first, then earlier sign-up. The app stays open; the list picks who's invited to the first
Random Friday. Nobody's email is ever shown to anyone else.
"""
import secrets
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import ratelimit
from app.models import WaitlistEntry
from app.nights import Area, DbDep

router = APIRouter(prefix="/api", tags=["waitlist"])
MAX_JOINS_PER_IP, JOIN_WINDOW = 10, timedelta(hours=1)  # slows one person faking friends to jump the queue


class WaitlistIn(BaseModel):
    model_config = {"str_strip_whitespace": True}
    email: EmailStr
    area: Area | None = None
    ref: str | None = Field(default=None, max_length=32)  # the code from a friend's link


class WaitlistOut(BaseModel):
    position: int
    total: int
    referrals: int
    ref_code: str | None  # only ever returned to its owner: on joining, or when they open their own link


def _referrals(db: Session, entry: WaitlistEntry) -> int:
    return db.scalar(select(func.count(WaitlistEntry.id)).where(WaitlistEntry.referred_by_id == entry.id))


def _status(db: Session, entry: WaitlistEntry, show_code: bool) -> WaitlistOut:
    refs = (select(WaitlistEntry.referred_by_id.label("owner"), func.count().label("n"))
            .where(WaitlistEntry.referred_by_id.is_not(None)).group_by(WaitlistEntry.referred_by_id).subquery())
    n, mine = func.coalesce(refs.c.n, 0), _referrals(db, entry)
    ahead = db.scalar(select(func.count(WaitlistEntry.id)).outerjoin(refs, refs.c.owner == WaitlistEntry.id)
                      .where(or_(n > mine, and_(n == mine, WaitlistEntry.id < entry.id))))
    return WaitlistOut(position=ahead + 1, total=db.scalar(select(func.count(WaitlistEntry.id))), referrals=mine,
                       ref_code=entry.ref_code if show_code else None)


@router.post("/waitlist")
def join_waitlist(body: WaitlistIn, request: Request, db: DbDep) -> WaitlistOut:
    email = body.email.lower()
    existing = db.scalar(select(WaitlistEntry).where(WaitlistEntry.email == email))
    if existing:  # already on it: show the place, not the share code (someone else may have typed their email)
        return _status(db, existing, show_code=False)
    if ip := ratelimit.client_ip(request):
        ratelimit.limit(db, f"waitlist-ip:{ip}", MAX_JOINS_PER_IP, JOIN_WINDOW)
    referrer = db.scalar(select(WaitlistEntry).where(WaitlistEntry.ref_code == body.ref)) if body.ref else None
    entry = WaitlistEntry(email=email, area=body.area, ref_code=secrets.token_urlsafe(6),
                          referred_by_id=referrer.id if referrer else None)
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:  # same email submitted twice at once
        db.rollback()
        return _status(db, db.scalar(select(WaitlistEntry).where(WaitlistEntry.email == email)), show_code=False)
    return _status(db, entry, show_code=True)


@router.get("/waitlist/{code}")
def waitlist_status(code: str, db: DbDep) -> WaitlistOut:
    """Your place, from your own share code (the frontend keeps it on your phone)."""
    entry = db.scalar(select(WaitlistEntry).where(WaitlistEntry.ref_code == code))
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on the list.")
    return _status(db, entry, show_code=True)
