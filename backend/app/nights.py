"""Plan preview API (task 5): the four inputs + company mode -> a timed night. Nothing is saved yet (task 7)."""
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import IST, UserDep, age_on, can_enter_licensed, today_ist
from app.db import get_db
from app.generator import AREAS, NightRequest, generate
from app.models import VIBES, Experience, Venue

router = APIRouter(prefix="/api", tags=["nights"])
DbDep = Annotated[Session, Depends(get_db)]

NIGHT_STARTS = time(21, 0)          # 9 PM, as in the deck
BUDGETS = (1000, 2000, 5000)        # ₹1K · ₹2K · ₹5K+
HOURS = (2, 4, None)                # 2 h · 4 h · all night
COMPANY = ("solo", "friends", "new_people")
MAX_DAYS_AHEAD = 30


class Options(BaseModel):
    areas: list[str]
    budgets: list[int]
    hours: list[int | None]
    vibes: list[str]
    company: list[str]


class PlanInputs(BaseModel):
    area: str
    budget_inr: int = Field(ge=500, le=50_000)
    hours: Literal[2, 4] | None            # None = all night
    vibe: Literal["party", "food", "chill", "surprise"]
    company: Literal["solo", "friends", "new_people"]  # matching uses it from task 6
    date: date

    @field_validator("area")
    @classmethod
    def known_area(cls, v: str) -> str:
        if v not in AREAS:
            raise ValueError(f"area must be one of {', '.join(AREAS)}")
        return v

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


@router.get("/options")
def options() -> Options:
    return Options(areas=AREAS, budgets=list(BUDGETS), hours=list(HOURS), vibes=list(VIBES), company=list(COMPANY))


@router.post("/plans/preview")
def preview_plan(body: PlanInputs, user: UserDep, db: DbDep) -> PlanOut:
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
    stops = [StopOut(title=s.experience.title, kind=s.experience.kind, venue=s.experience.venue.name,
                     area=s.experience.venue.area, starts_at=s.starts_at, ends_at=s.ends_at,
                     price_per_head_inr=s.experience.price_per_head_inr, is_partner=s.is_partner) for s in plan]
    return PlanOut(stops=stops, total_inr=sum(s.price_per_head_inr for s in stops), bars_unlocked=licensed_ok)
