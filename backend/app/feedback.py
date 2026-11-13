"""Task 9: rate the stops you went to, report or block people from your group.

A venue's rating_avg becomes the app average once it has MIN_RATINGS ratings. Below the generator's
RATING_FLOOR it is paused automatically: the fit filter stops routing anyone there.
"""
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.auth import UserDep
from app.bookings import BookedNight, booked_night, tonight
from app.models import Block, CheckIn, Experience, GroupMember, Plan, PlanStop, Rating, Report, Ticket, User, Venue
from app.nights import DbDep

router = APIRouter(prefix="/api", tags=["feedback"])
MIN_RATINGS = 5        # distinct guests needed before the app average counts: one account can't pause a venue
RECENT_RATERS = 30     # only the latest raters count, so a venue can recover after the admin un-pauses it
RATE_WITHIN_DAYS = 7   # how long after a night it can still be rated


class RatingIn(BaseModel):
    plan_stop_id: int
    stars: int = Field(ge=1, le=5)
    text: str | None = Field(default=None, max_length=500)


class PersonIn(BaseModel):
    user_id: int


class ReportIn(PersonIn):
    reason: str = Field(min_length=3, max_length=1000)


def refresh_venue_rating(db: Session, venue_id: int) -> None:
    """Average of each guest's latest rating here, over the most recent RECENT_RATERS guests."""
    latest: dict[int, int] = {}
    for user_id, stars in db.execute(select(Rating.user_id, Rating.stars).join(PlanStop).join(Experience)
                                     .where(Experience.venue_id == venue_id).order_by(Rating.id.desc())):
        latest.setdefault(user_id, stars)  # newest first, so the first one seen per guest is their latest
    recent = list(latest.values())[:RECENT_RATERS]
    if len(recent) >= MIN_RATINGS:  # until then the admin's starting value (or "unrated") stands
        db.get(Venue, venue_id).rating_avg = round(sum(recent) / len(recent), 2)


@router.post("/ratings")
def rate_stop(body: RatingIn, user: UserDep, db: DbDep) -> dict[str, int]:
    if not db.scalar(select(CheckIn.id).where(CheckIn.plan_stop_id == body.plan_stop_id, CheckIn.user_id == user.id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only rate stops you checked in at.")
    night = db.scalar(select(Ticket.night_date).where(Ticket.plan_stop_id == body.plan_stop_id,
                                                      Ticket.user_id == user.id))
    if night < tonight() - timedelta(days=RATE_WITHIN_DAYS):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Nights can be rated for {RATE_WITHIN_DAYS} days.")
    for _ in range(2):  # a double tap can race the first insert; the retry then updates it
        rating = db.scalar(select(Rating).where(Rating.plan_stop_id == body.plan_stop_id, Rating.user_id == user.id))
        if rating is None:
            rating = Rating(plan_stop_id=body.plan_stop_id, user_id=user.id, stars=body.stars, text=body.text)
            db.add(rating)
        else:  # changing your mind just updates it
            rating.stars, rating.text = body.stars, body.text
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
    refresh_venue_rating(db, db.get(PlanStop, body.plan_stop_id).experience.venue_id)
    db.commit()
    return {"stars": rating.stars}


@router.get("/plans/last")
def last_night(user: UserDep, db: DbDep) -> BookedNight | None:
    """The most recent night (within a week) where the user checked in somewhere: the one to rate."""
    since = tonight() - timedelta(days=RATE_WITHIN_DAYS)
    ticket = db.scalar(
        select(Ticket).where(Ticket.user_id == user.id, Ticket.night_date >= since,
                             exists().where(CheckIn.plan_stop_id == Ticket.plan_stop_id, CheckIn.user_id == user.id))
        .order_by(Ticket.night_date.desc()).limit(1))
    return booked_night(db, db.get(Plan, ticket.plan_stop.plan_id), user) if ticket else None


def _shared_group(db: Session, a: int, b: int) -> bool:
    other = aliased(GroupMember)
    return db.scalar(select(GroupMember.group_id).join(other, other.group_id == GroupMember.group_id)
                     .where(GroupMember.user_id == a, other.user_id == b).limit(1)) is not None


def _check_target(db: Session, user: User, target_id: int) -> None:
    # Only people you were grouped with: you can't report or block strangers by guessing ids.
    if target_id == user.id or not _shared_group(db, user.id, target_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You can only report or block people from your groups.")


def _block(db: Session, user: User, target_id: int) -> None:
    if not db.scalar(select(Block.id).where(Block.blocker_id == user.id, Block.blocked_id == target_id)):
        db.add(Block(blocker_id=user.id, blocked_id=target_id))


@router.post("/blocks", status_code=status.HTTP_204_NO_CONTENT)
def block_person(body: PersonIn, user: UserDep, db: DbDep) -> None:
    _check_target(db, user, body.user_id)
    _block(db, user, body.user_id)
    try:
        db.commit()
    except IntegrityError:  # a double tap raced; the block exists either way
        db.rollback()


@router.post("/reports", status_code=status.HTTP_201_CREATED)
def report_person(body: ReportIn, user: UserDep, db: DbDep) -> dict[str, bool]:
    _check_target(db, user, body.user_id)
    if not db.scalar(select(Report.id).where(Report.reporter_id == user.id, Report.reported_id == body.user_id)):
        # One report per person you report: repeats can't pile up against someone.
        db.add(Report(reporter_id=user.id, reported_id=body.user_id, reason=body.reason.strip()))
    _block(db, user, body.user_id)  # reporting someone also means never matching you with them again
    db.commit()
    return {"reported": True, "blocked": True}
