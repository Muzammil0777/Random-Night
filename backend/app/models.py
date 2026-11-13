"""Tables from tasks/plan.md §3. Money is whole rupees (int). Times are timezone-aware."""
from datetime import date, datetime, time

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, UniqueConstraint, func
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
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_partner: Mapped[bool]  # snapshot at generation time, drives the "Partner" label
    code: Mapped[str] = mapped_column(index=True)  # check-in code, rules added in task 7


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
