"""Random Friday API (task 6): join or leave a Friday, see your group, and the weekly matching job."""
import os
import secrets
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth import IST, UserDep, now, today_ist
from app.db import get_db
from app.matching import is_woman, match
from app.models import DropEntry, Experience, GroupMember, Plan, PlanStop, User
from app.nights import MAX_DAYS_AHEAD, Area, PlanOut, stop_out

router = APIRouter(prefix="/api", tags=["drops"])
DbDep = Annotated[Session, Depends(get_db)]
FRIDAY = 4
JOINS_CLOSE = time(23, 0)  # Thursday 11 PM IST; the weekly match cron runs after this (plan task 11)


def upcoming_friday(today: date) -> date:
    return today + timedelta(days=(FRIDAY - today.weekday()) % 7)


class DropJoin(BaseModel):
    date: date
    area: Area
    vibe: Literal["party", "food", "chill", "surprise"]
    budget_inr: Literal[1000, 2000, 5000]  # tiers, so people with the same pick can share a group
    women_only: bool = False

    @field_validator("date")
    @classmethod
    def open_friday(cls, v: date) -> date:
        if v.weekday() != FRIDAY:
            raise ValueError("Random Friday is on Fridays")
        if now() >= datetime.combine(v - timedelta(days=1), JOINS_CLOSE, IST):
            raise ValueError("Joining closes at 11 PM on the Thursday before")
        if v > today_ist() + timedelta(days=MAX_DAYS_AHEAD):
            raise ValueError(f"You can join up to {MAX_DAYS_AHEAD} days ahead")
        return v


class DropStatus(BaseModel):
    date: date
    area: str
    vibe: str
    budget_inr: int
    status: Literal["waiting", "matched", "unmatched"]
    group: list[str] | None = None   # first names only
    night: PlanOut | None = None


def _status(db: Session, entry: DropEntry) -> DropStatus:
    picks = {"date": entry.date, "area": entry.area, "vibe": entry.vibe, "budget_inr": entry.budget_inr}
    if entry.group_id is None:
        return DropStatus(**picks, status="unmatched" if entry.tried_at else "waiting")
    names = db.scalars(select(User.name).join(GroupMember, GroupMember.user_id == User.id)
                       .where(GroupMember.group_id == entry.group_id).order_by(User.id)).all()
    plan = db.scalar(select(Plan).where(Plan.group_id == entry.group_id))
    stops = [stop_out(s.experience, s.starts_at, s.is_partner) for s in db.scalars(
        select(PlanStop).where(PlanStop.plan_id == plan.id).order_by(PlanStop.starts_at)
        .options(joinedload(PlanStop.experience).joinedload(Experience.venue)))]
    return DropStatus(**picks, status="matched", group=[n.split()[0] for n in names],
                      night=PlanOut(stops=stops, total_inr=sum(s.price_per_head_inr for s in stops),
                                    bars_unlocked=plan.inputs["licensed_ok"]))


def _entry(db: Session, user: User, night_date: date) -> DropEntry:
    entry = db.scalar(select(DropEntry).where(DropEntry.user_id == user.id, DropEntry.date == night_date))
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You haven't joined that Friday.")
    return entry


@router.post("/drops", status_code=status.HTTP_201_CREATED)
def join_drop(body: DropJoin, user: UserDep, db: DbDep) -> DropStatus:
    if body.women_only and not is_woman(user):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Women-only groups are for women.")
    entry = DropEntry(user_id=user.id, **body.model_dump())
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "You've already joined that Friday.")
    return _status(db, entry)


@router.get("/drops/{night_date}")
def my_drop(night_date: date, user: UserDep, db: DbDep) -> DropStatus:
    return _status(db, _entry(db, user, night_date))


@router.delete("/drops/{night_date}", status_code=status.HTTP_204_NO_CONTENT)
def leave_drop(night_date: date, user: UserDep, db: DbDep) -> None:
    entry = _entry(db, user, night_date)
    if entry.group_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your group is already formed, so you can't leave now.")
    db.delete(entry)
    db.commit()


@router.get("/jobs/match")
def run_match(request: Request, db: DbDep, night_date: date | None = None) -> dict[str, int]:
    """Weekly cron (Vercel sends `Authorization: Bearer $CRON_SECRET`). Matches the coming Friday by default."""
    secret = os.environ.get("CRON_SECRET", "")
    given = request.headers.get("authorization", "")
    if len(secret) < 16 or not secrets.compare_digest(given.encode(), f"Bearer {secret}".encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not allowed")
    return match(db, night_date or upcoming_friday(today_ist()))
