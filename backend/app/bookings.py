"""Booking (task 7): save a night and give each guest a 6-digit check-in code per stop."""
import secrets
from datetime import date, timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.auth import IST, UserDep, _aware, first_name, now
from app.generator import Stop
from app.models import CheckIn, DropEntry, Experience, GroupMember, Night, Plan, PlanStop, Rating, Ticket, User
from app.nights import DbDep, PlanInputs, StopOut, build_night, stop_out

router = APIRouter(prefix="/api", tags=["bookings"])
ROLLOVER = timedelta(hours=6)  # a night runs until 6 AM, so 1 AM Saturday still belongs to Friday


def tonight() -> date:
    """The night the current moment belongs to (IST, rolling over at 6 AM)."""
    return (now().astimezone(IST) - ROLLOVER).date()


class TicketStopOut(StopOut):
    plan_stop_id: int
    code: str           # show to venue staff; works once, only here, only that night
    checked_in: bool
    my_stars: int | None  # this guest's rating (only checked-in stops can be rated)


class Member(BaseModel):
    id: int             # to report or block them; never their email or full name
    name: str


class BookedNight(BaseModel):
    id: int
    inputs: dict
    stops: list[TicketStopOut]
    total_inr: int
    bars_unlocked: bool
    group: list[str] | None = None  # Random Friday group: first names only
    members: list[Member] = []      # the others in the group


def get_night(db: Session, night_date: date, area: str) -> Night:
    night = db.scalar(select(Night).where(Night.date == night_date, Night.area == area))
    if night is None:
        night = Night(date=night_date, area=area)
        db.add(night)
        db.flush()
    return night


def save_plan(db: Session, night: Night, stops: list[Stop], user_ids: list[int], inputs: dict,
              user_id: int | None = None, group_id: int | None = None) -> Plan:
    """Plan + stops + one ticket per guest per stop. Caller commits."""
    plan = Plan(user_id=user_id, group_id=group_id, night_id=night.id, inputs=inputs)
    db.add(plan)
    db.flush()
    # Stored in UTC: SQLite drops the offset, and _aware() reads naive values back as UTC.
    rows = [PlanStop(plan_id=plan.id, experience_id=s.experience.id, starts_at=s.starts_at.astimezone(timezone.utc),
                     is_partner=s.is_partner) for s in stops]
    db.add_all(rows)
    db.flush()
    # Codes are unique per night (DB key), so a code typed at the door points to exactly one guest.
    # shortcut: two bookings racing to the same new code hit that key and fail (about 1 in a million).
    taken = set(db.scalars(select(Ticket.code).where(Ticket.night_date == night.date)))
    for ps in rows:
        for uid in user_ids:
            while (code := f"{secrets.randbelow(10**6):06d}") in taken:
                pass
            taken.add(code)
            db.add(Ticket(plan_stop_id=ps.id, user_id=uid, night_date=night.date, code=code))
    return plan


def has_night(db: Session, user: User, night_date: date) -> bool:
    return db.scalar(select(Ticket.id).where(Ticket.user_id == user.id, Ticket.night_date == night_date)
                     .limit(1)) is not None


def _members(db: Session, group_id: int) -> list[Member]:
    rows = db.execute(select(User.id, User.name).join(GroupMember, GroupMember.user_id == User.id)
                      .where(GroupMember.group_id == group_id).order_by(User.id))
    return [Member(id=i, name=first_name(n)) for i, n in rows]


def booked_night(db: Session, plan: Plan, user: User) -> BookedNight:
    rows = db.execute(
        select(PlanStop, Ticket.code, CheckIn.id, Rating.stars)
        .join(Ticket, (Ticket.plan_stop_id == PlanStop.id) & (Ticket.user_id == user.id))
        .outerjoin(CheckIn, (CheckIn.plan_stop_id == PlanStop.id) & (CheckIn.user_id == user.id))
        .outerjoin(Rating, (Rating.plan_stop_id == PlanStop.id) & (Rating.user_id == user.id))
        .where(PlanStop.plan_id == plan.id).order_by(PlanStop.starts_at)
        .options(joinedload(PlanStop.experience).joinedload(Experience.venue))).all()
    stops = [TicketStopOut(**stop_out(ps.experience, _aware(ps.starts_at), ps.is_partner).model_dump(),
                           plan_stop_id=ps.id, code=code, checked_in=checkin is not None, my_stars=stars)
             for ps, code, checkin, stars in rows]
    members = _members(db, plan.group_id) if plan.group_id else []
    return BookedNight(id=plan.id, inputs=plan.inputs, stops=stops,
                       total_inr=sum(s.price_per_head_inr for s in stops), bars_unlocked=plan.inputs["licensed_ok"],
                       group=[m.name for m in members] if plan.group_id else None,
                       members=[m for m in members if m.id != user.id])


@router.post("/plans", status_code=status.HTTP_201_CREATED)
def book_night(body: PlanInputs, user: UserDep, db: DbDep) -> BookedNight:
    if body.company == "new_people":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "To meet new people, join Random Friday.")
    if has_night(db, user, body.date):
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a night booked for that date.")
    if db.scalar(select(DropEntry.id).where(DropEntry.user_id == user.id, DropEntry.date == body.date)):
        raise HTTPException(status.HTTP_409_CONFLICT, "You've joined Random Friday that night. Leave it first.")
    stops, licensed_ok = build_night(db, user, body)  # regenerated here: never trust stops sent by the client
    plan = save_plan(db, get_night(db, body.date, body.area), stops, [user.id],
                     {**body.model_dump(mode="json"), "licensed_ok": licensed_ok}, user_id=user.id)
    db.commit()
    return booked_night(db, plan, user)


@router.get("/plans/next")
def next_night(user: UserDep, db: DbDep) -> BookedNight | None:
    """The user's next booked night (solo or Random Friday group), from tonight on."""
    ticket = db.scalar(select(Ticket).where(Ticket.user_id == user.id, Ticket.night_date >= tonight())
                       .order_by(Ticket.night_date).limit(1))
    if ticket is None:
        return None
    return booked_night(db, db.get(Plan, ticket.plan_stop.plan_id), user)


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_night(plan_id: int, user: UserDep, db: DbDep) -> None:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.user_id != user.id:  # group plans have no user_id, so they can't be cancelled here
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No booking of yours with that id.")
    stop_ids = select(PlanStop.id).where(PlanStop.plan_id == plan.id)
    # A check-in racing this cancel can't leave a billable orphan: the FK from checkins to plan_stops makes one fail.
    if db.scalar(select(CheckIn.id).where(CheckIn.plan_stop_id.in_(stop_ids)).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "You've already checked in, so this night can't be cancelled.")
    db.execute(delete(Ticket).where(Ticket.plan_stop_id.in_(stop_ids)))
    db.execute(delete(PlanStop).where(PlanStop.plan_id == plan.id))
    db.delete(plan)
    db.commit()
