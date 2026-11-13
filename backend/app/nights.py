"""Plan preview API (task 5): the four inputs + company mode -> a timed night. Nothing is saved yet (task 7)."""
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AfterValidator, BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import IST, UserDep, age_on, can_enter_licensed, today_ist
from app.db import get_db
from app.generator import AREAS, NightRequest, Stop, generate
from app.models import VIBES, Experience, User, Venue

router = APIRouter(prefix="/api", tags=["nights"])
DbDep = Annotated[Session, Depends(get_db)]

NIGHT_STARTS = time(21, 0)          # 9 PM, as in the deck
BUDGETS = (1000, 2000, 5000)        # ₹1K · ₹2K · ₹5K+
HOURS = (2, 4, None)                # 2 h · 4 h · all night
COMPANY = ("solo", "friends", "new_people")
MAX_DAYS_AHEAD = 30


def _known_area(v: str) -> str:
    if v not in AREAS:
        raise ValueError(f"area must be one of {', '.join(AREAS)}")
    return v


Area = Annotated[str, AfterValidator(_known_area)]


class Options(BaseModel):
    areas: list[str]
    budgets: list[int]
    hours: list[int | None]
    vibes: list[str]
    company: list[str]


class PlanInputs(BaseModel):
    area: Area
    budget_inr: int = Field(ge=500, le=50_000)
    hours: Literal[2, 4] | None            # None = all night
    vibe: Literal["party", "food", "chill", "surprise"]
    company: Literal["solo", "friends", "new_people"]  # matching uses it from task 6
    date: date

    @field_validator("date")
    @classmethod
    def upcoming(cls, v: date) -> date:
        today = today_ist()
        if not today <= v <= today + timedelta(days=MAX_DAYS_AHEAD):
            raise ValueError(f"pick a date from today up to {MAX_DAYS_AHEAD} days ahead")
        return v


class StopOut(BaseModel):
    title: str
    kind: str
    venue: str
    area: str
    starts_at: datetime
    ends_at: datetime
    price_per_head_inr: int
    is_partner: bool        # UI must show "Partner venue" (CCPA dark-patterns guidelines / ASCI)


class PlanOut(BaseModel):
    stops: list[StopOut]
    total_inr: int
    bars_unlocked: bool     # False -> UI explains bars/clubs need 21+ and an ID check


def stop_out(exp: Experience, starts_at: datetime, is_partner: bool) -> StopOut:
    return StopOut(title=exp.title, kind=exp.kind, venue=exp.venue.name, area=exp.venue.area, starts_at=starts_at,
                   ends_at=starts_at + timedelta(minutes=exp.duration_min),
                   price_per_head_inr=exp.price_per_head_inr, is_partner=is_partner)


@router.get("/options")
def options() -> Options:
    return Options(areas=AREAS, budgets=list(BUDGETS), hours=list(HOURS), vibes=list(VIBES), company=list(COMPANY))


def build_night(db: Session, user: User, body: PlanInputs) -> tuple[list[Stop], bool]:
    """The night the generator picks for this user, or 404. Booking reuses it so it never trusts client stops."""
    licensed_ok = can_enter_licensed(user, body.date)
    experiences = db.scalars(select(Experience).join(Venue).where(Venue.active)
                             .options(joinedload(Experience.venue))).all()
    req = NightRequest(area=body.area, budget_inr=body.budget_inr,
                       start=datetime.combine(body.date, NIGHT_STARTS, IST), hours=body.hours,
                       vibe=body.vibe, youngest_age=age_on(user.dob, body.date), licensed_ok=licensed_ok)
    plan = generate(req, list(experiences))
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No night fits that yet. Try a bigger budget, more time, or another vibe.")
    return plan, licensed_ok


@router.post("/plans/preview")
def preview_plan(body: PlanInputs, user: UserDep, db: DbDep) -> PlanOut:
    plan, licensed_ok = build_night(db, user, body)
    stops = [stop_out(s.experience, s.starts_at, s.is_partner) for s in plan]
    return PlanOut(stops=stops, total_inr=sum(s.price_per_head_inr for s in stops), bars_unlocked=licensed_ok)
