"""Tables from tasks/plan.md §3. Money is whole rupees (int). Times are timezone-aware."""
from datetime import date, datetime, time

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, UniqueConstraint, event, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

KINDS = ("meet", "music", "challenge", "food", "finale")
VIBES = ("party", "food", "chill", "surprise")


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def fk(target: str, nullable: bool = False):
    return mapped_column(ForeignKey(target), index=True, nullable=nullable)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    dob: Mapped[date]
    id_verified: Mapped[bool] = mapped_column(default=False)
    gender: Mapped[str | None]
    emergency_contact: Mapped[str | None]
    created_at: Mapped[datetime] = created_at()


class LoginToken(Base):
    """Single-use magic link. Only the SHA-256 of the token is stored."""
    __tablename__ = "login_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str] = mapped_column(index=True)
    name: Mapped[str | None]  # signup details, used only if the email has no account yet
    dob: Mapped[date | None]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    """Revocable login session (bearer token, stored hashed)."""
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(unique=True)
    user_id: Mapped[int] = fk("users.id")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Venue(Base):
    __tablename__ = "venues"
    __table_args__ = (
        CheckConstraint("cpa_rate_inr >= 0", name="cpa_non_negative"),
        CheckConstraint("rating_avg IS NULL OR rating_avg BETWEEN 0 AND 5", name="rating_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    area: Mapped[str] = mapped_column(index=True)
    licensed: Mapped[bool]  # serves alcohol -> 21+ only (Telangana)
    closes_at: Mapped[time]
    rating_avg: Mapped[float | None]  # None = not rated yet
    cpa_rate_inr: Mapped[int] = mapped_column(default=0)  # paid per checked-in guest
    is_partner: Mapped[bool] = mapped_column(default=False)  # must be labelled in plans
    active: Mapped[bool] = mapped_column(default=True)


class Experience(Base):
    __tablename__ = "experiences"
    __table_args__ = (
        CheckConstraint(f"kind IN {KINDS}", name="kind_valid"),
        CheckConstraint("price_per_head_inr >= 0", name="price_non_negative"),
        CheckConstraint("duration_min > 0", name="duration_positive"),
        CheckConstraint("min_age >= 18", name="adults_only"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = fk("venues.id")
    venue: Mapped[Venue] = relationship()
    title: Mapped[str]
    kind: Mapped[str]
    vibes: Mapped[list[str]] = mapped_column(JSON)
    price_per_head_inr: Mapped[int]
    duration_min: Mapped[int]
    min_age: Mapped[int] = mapped_column(default=18)


def check_experience(exp: Experience, licensed: bool) -> None:
    """Rules every writer (seed, admin, future API) must pass. Raises ValueError with a readable message."""
    if exp.kind not in KINDS:
        raise ValueError(f"{exp.title!r}: kind must be one of {', '.join(KINDS)}")
    if not exp.vibes or not set(exp.vibes) <= set(VIBES):
        raise ValueError(f"{exp.title!r}: vibes must be a non-empty list from {', '.join(VIBES)}")
    if licensed and exp.min_age < 21:
        # Telangana: under-21s can't enter licensed venues.
        raise ValueError(f"{exp.title!r} is at a licensed venue, so min_age must be 21 or more")


@event.listens_for(Experience, "before_insert")
@event.listens_for(Experience, "before_update")
def _validate_experience(mapper, connection, target: Experience) -> None:
    venue = target.__dict__.get("venue")  # already-loaded relationship; never lazy-load inside a flush
    licensed = venue.licensed if venue is not None else connection.scalar(
        select(Venue.licensed).where(Venue.id == target.venue_id))
    check_experience(target, bool(licensed))


@event.listens_for(Venue, "before_update")
def _licensed_venue_needs_21(mapper, connection, target: Venue) -> None:
    # Flipping a venue to licensed must not leave experiences there open to under-21s.
    if target.licensed and connection.scalar(select(func.count(Experience.id)).where(
            Experience.venue_id == target.id, Experience.min_age < 21)):
        raise ValueError(f"{target.name!r} has experiences open to under-21s; "
                         "set their min_age to 21 before marking it licensed")


class Night(Base):
    __tablename__ = "nights"
    __table_args__ = (UniqueConstraint("date", "area"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date]
    area: Mapped[str]


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    night_id: Mapped[int] = fk("nights.id")


class GroupMember(Base):
    __tablename__ = "group_members"
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)


class DropEntry(Base):
    """A sign-up for one Random Friday (task 6). The Thursday job sets group_id when it matches the user."""
    __tablename__ = "drop_entries"
    __table_args__ = (UniqueConstraint("user_id", "date"), CheckConstraint(f"vibe IN {VIBES}", name="vibe_valid"))
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = fk("users.id")
    user: Mapped[User] = relationship()
    date: Mapped[date]
    area: Mapped[str]
    vibe: Mapped[str]
    budget_inr: Mapped[int]
    women_only: Mapped[bool] = mapped_column(default=False)
    group_id: Mapped[int | None] = fk("groups.id", nullable=True)
    tried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # last matching run that saw it
    created_at: Mapped[datetime] = created_at()


class Plan(Base):
    __tablename__ = "plans"
    # A plan belongs to exactly one owner: a solo user or a matched group.
    __table_args__ = (CheckConstraint("(user_id IS NULL) <> (group_id IS NULL)", name="one_owner"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = fk("users.id", nullable=True)
    group_id: Mapped[int | None] = fk("groups.id", nullable=True)
    night_id: Mapped[int] = fk("nights.id")
    inputs: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = created_at()


class PlanStop(Base):
    __tablename__ = "plan_stops"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = fk("plans.id")
    experience_id: Mapped[int] = fk("experiences.id")
    experience: Mapped[Experience] = relationship()
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_partner: Mapped[bool]  # snapshot at generation time, drives the "Partner" label
    # Unused since task 7 (codes are per guest, in tickets); kept because create_all can't drop columns.
    code: Mapped[str] = mapped_column(index=True, default="")


class Ticket(Base):
    """One guest's pass for one stop (task 7). Staff enter `code` at the door; it only works at that
    stop's venue on that night, and CheckIn's unique key makes it work once."""
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("plan_stop_id", "user_id"), UniqueConstraint("night_date", "code"))
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_stop_id: Mapped[int] = fk("plan_stops.id")
    plan_stop: Mapped[PlanStop] = relationship()
    user_id: Mapped[int] = fk("users.id")
    night_date: Mapped[date] = mapped_column(index=True)
    code: Mapped[str]


class VenueKey(Base):
    """Login key for a venue's door staff (task 7). Only the SHA-256 is stored; check-ins record the label."""
    __tablename__ = "venue_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = fk("venues.id")
    venue: Mapped[Venue] = relationship()
    key_hash: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = created_at()


class CheckIn(Base):
    __tablename__ = "checkins"
    # Billing counts rows here, so one check-in per user per stop is enforced by the DB.
    __table_args__ = (UniqueConstraint("plan_stop_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_stop_id: Mapped[int] = fk("plan_stops.id")
    user_id: Mapped[int] = fk("users.id")
    venue_id: Mapped[int] = fk("venues.id")
    at: Mapped[datetime] = created_at()
    entered_by: Mapped[str]


class VenueVisit(Base):
    """The billable unit (task 8): one checked-in guest at one venue on one night, however many stops there.
    Written at the first check-in, with the venue's rate copied so later rate changes never rewrite invoices."""
    __tablename__ = "venue_visits"
    __table_args__ = (UniqueConstraint("venue_id", "user_id", "night_date"),
                      CheckConstraint("rate_inr >= 0", name="rate_non_negative"))
    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = fk("venues.id")
    venue: Mapped[Venue] = relationship()
    user_id: Mapped[int] = fk("users.id")
    night_date: Mapped[date] = mapped_column(index=True)
    rate_inr: Mapped[int]
    checkin_id: Mapped[int] = fk("checkins.id")  # the first check-in, for disputes


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "plan_stop_id"),
        CheckConstraint("stars BETWEEN 1 AND 5", name="stars_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = fk("users.id")
    plan_stop_id: Mapped[int] = fk("plan_stops.id")
    stars: Mapped[int]
    text: Mapped[str | None]


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (CheckConstraint("reporter_id <> reported_id", name="not_self"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = fk("users.id")
    reported_id: Mapped[int] = fk("users.id")
    reason: Mapped[str]
    created_at: Mapped[datetime] = created_at()


class Block(Base):
    """Task 9: the blocker never shares a Random Friday group with the blocked user again."""
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("blocker_id", "blocked_id"),
                      CheckConstraint("blocker_id <> blocked_id", name="not_self"))
    id: Mapped[int] = mapped_column(primary_key=True)
    blocker_id: Mapped[int] = fk("users.id")
    blocked_id: Mapped[int] = fk("users.id")
    created_at: Mapped[datetime] = created_at()
