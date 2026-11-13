"""Venue door staff (task 7): log in with the venue's key, enter a guest's 6-digit code to check them in.

Create a key (shown once):  python -m app.staff "Venue name" "Front door"
Turn a key off in /admin (Venue keys -> untick active).
"""
import os
import secrets
import sys
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import _aware, _hash, first_name, now
from app.auth import IST
from app.bookings import tonight
from app import ratelimit
from app.db import SessionLocal
from app.models import CheckIn, Experience, PlanStop, Ticket, User, Venue, VenueKey, VenueVisit
from app.nights import DbDep

router = APIRouter(prefix="/api/staff", tags=["staff"])
COOKIE = "rn_staff"  # httpOnly, separate from guest sessions
COOKIE_TTL = timedelta(days=30)  # door phones stay logged in
# A mistyping door phone shouldn't lock the venue mid-rush, but walking a million codes stays impossible.
MAX_WRONG_CODES, WRONG_CODE_WINDOW = 30, timedelta(minutes=10)
DOOR_OPEN = timedelta(hours=1)  # a stop's codes work from 1 h before it starts until 1 h after it ends


def _key_row(db: Session, key: str) -> VenueKey | None:
    # Turning a venue off in /admin also stops its door keys.
    return db.scalar(select(VenueKey).join(Venue).where(VenueKey.key_hash == _hash(key), VenueKey.active, Venue.active))


def current_key(db: DbDep, request: Request) -> VenueKey:
    key = request.cookies.get(COOKIE)
    row = _key_row(db, key) if key else None
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Staff login needed")
    return row


StaffDep = Annotated[VenueKey, Depends(current_key)]


class StaffLogin(BaseModel):
    key: str = Field(min_length=1, max_length=100)


class StaffMe(BaseModel):
    venue: str
    label: str


class CodeIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class CheckedIn(BaseModel):
    guest: str  # first name, so staff can greet them
    stop: str


@router.post("/login")
def staff_login(body: StaffLogin, db: DbDep, response: Response) -> StaffMe:
    row = _key_row(db, body.key.strip())
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That key isn't valid. Ask Random Night for a new one.")
    response.set_cookie(COOKIE, body.key.strip(), max_age=int(COOKIE_TTL.total_seconds()), httponly=True,
                        secure=os.environ.get("APP_URL", "").startswith("https://"), samesite="lax", path="/")
    return StaffMe(venue=row.venue.name, label=row.label)


@router.get("/me")
def staff_me(key: StaffDep) -> StaffMe:
    return StaffMe(venue=key.venue.name, label=key.label)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def staff_logout(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


@router.post("/checkin")
def check_in(body: CodeIn, key: StaffDep, db: DbDep) -> CheckedIn:
    # Wrong codes are capped per key, so a leaked key can't walk the million codes to bill no-shows.
    if ratelimit.count(db, f"door:{key.id}", WRONG_CODE_WINDOW) >= MAX_WRONG_CODES:
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong codes. Wait a bit or call Random Night.")
    # One lookup enforces all three rules: this code, tonight, at a stop of this venue.
    ticket = db.scalar(select(Ticket).join(PlanStop).join(Experience).where(
        Ticket.code == body.code, Ticket.night_date == tonight(), Experience.venue_id == key.venue_id))
    if ticket is None:
        ratelimit.record(db, f"door:{key.id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That code isn't for a stop here tonight.")
    stop = ticket.plan_stop
    opens = _aware(stop.starts_at) - DOOR_OPEN
    closes = _aware(stop.starts_at) + timedelta(minutes=stop.experience.duration_min) + DOOR_OPEN
    if not opens <= now() <= closes:  # billing counts check-ins, so the guest must be here around the stop's time
        raise HTTPException(status.HTTP_409_CONFLICT, "This code is for another time tonight: "
                            f"{stop.experience.title}, {_aware(stop.starts_at).astimezone(IST):%I:%M %p}.")
    checkin = CheckIn(plan_stop_id=ticket.plan_stop_id, user_id=ticket.user_id, venue_id=key.venue_id,
                      entered_by=key.label)
    db.add(checkin)
    try:
        db.flush()
    except IntegrityError:  # unique (plan_stop_id, user_id): a code works once
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Already checked in.")
    # Billing: the first check-in of this guest here tonight creates the visit, at today's rate.
    # shortcut: two stops of one guest checked in at the same instant could race on the visit's unique key (one 409s).
    if not db.scalar(select(VenueVisit.id).where(VenueVisit.venue_id == key.venue_id,
                                                 VenueVisit.user_id == ticket.user_id,
                                                 VenueVisit.night_date == ticket.night_date)):
        db.add(VenueVisit(venue_id=key.venue_id, user_id=ticket.user_id, night_date=ticket.night_date,
                          rate_inr=key.venue.cpa_rate_inr, checkin_id=checkin.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Already checked in.")
    name = db.get(User, ticket.user_id).name
    return CheckedIn(guest=first_name(name), stop=stop.experience.title)


def create_key(db: Session, venue_name: str, label: str) -> str:
    venue = db.scalar(select(Venue).where(Venue.name == venue_name))
    if venue is None:
        raise SystemExit(f"No venue named {venue_name!r}")
    key = secrets.token_urlsafe(18)
    db.add(VenueKey(venue_id=venue.id, key_hash=_hash(key), label=label))
    db.commit()
    return key


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit('usage: python -m app.staff "Venue name" "Label, e.g. Front door"')
    with SessionLocal() as session:
        print(f"Staff key for {sys.argv[1]} ({sys.argv[2]}), shown once: {create_key(session, *sys.argv[1:])}")
