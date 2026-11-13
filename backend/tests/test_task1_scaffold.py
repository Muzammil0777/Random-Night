"""Task 1: app boots, seed loads safely, DB constraints protect records and billing."""
from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import CheckIn, Experience, Night, Plan, PlanStop, Rating, User, Venue
from app.seed import load

VENUES_HEADER = "name,area,licensed,closes_at,rating_avg,cpa_rate_inr,is_partner\n"
EXPS_HEADER = "venue,title,kind,vibes,price_per_head_inr,duration_min,min_age\n"


def test_health_reports_db_reachable(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_seed_loads_founding_venues_once(db):
    assert load(db) == (6, 10)
    assert load(db) == (0, 0)  # idempotent: second run inserts nothing
    assert db.scalar(select(func.count(Venue.id))) == 6


def test_seeded_licensed_venues_are_21_plus_only(db):
    load(db)
    rows = db.execute(select(Experience.min_age).join(Venue).where(Venue.licensed)).scalars().all()
    assert rows and all(age >= 21 for age in rows)


def test_seed_keeps_unrated_venue_as_none(db):
    load(db)
    assert db.scalar(select(Venue.rating_avg).where(Venue.name == "Sample Biryani House")) is None


def _write_seed(tmp_path, venue_row, exp_row):
    (tmp_path / "venues.csv").write_text(VENUES_HEADER + venue_row + "\n", encoding="utf-8")
    (tmp_path / "experiences.csv").write_text(EXPS_HEADER + exp_row + "\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("venue_row,exp_row,msg", [
    ("Bar,Jubilee Hills,true,01:00,4.0,100,true", "Bar,Shots,meet,party,500,60,18", "min_age >= 21"),
    ("Bar,Jubilee Hills,true,01:00,4.0,100,true", "Nowhere,Shots,meet,party,500,60,21", "unknown venue"),
    ("Cafe,Gachibowli,false,23:00,,0,false", "Cafe,Chat,meet,romance,200,60,18", "bad kind/vibes"),
], ids=["licensed-under-21", "unknown-venue", "unknown-vibe"])
def test_seed_rejects_bad_rows(db, tmp_path, venue_row, exp_row, msg):
    with pytest.raises(ValueError, match=msg):
        load(db, _write_seed(tmp_path, venue_row, exp_row))


@pytest.fixture
def stop(db):
    """A user with a one-stop plan at a seeded venue."""
    load(db)
    exp = db.scalar(select(Experience).limit(1))
    user = User(email="a@example.com", name="A", dob=date(2000, 1, 1))
    night = Night(date=date(2026, 11, 20), area="Jubilee Hills")
    db.add_all([user, night])
    db.flush()
    plan = Plan(user_id=user.id, night_id=night.id, inputs={"budget": 2000})
    db.add(plan)
    db.flush()
    s = PlanStop(plan_id=plan.id, experience_id=exp.id, is_partner=True, code="123456",
                 starts_at=datetime(2026, 11, 20, 21, 0, tzinfo=timezone.utc))
    db.add(s)
    db.commit()
    return s


def test_one_checkin_per_user_per_stop(db, stop):
    venue_id = db.get(Experience, stop.experience_id).venue_id
    db.add(CheckIn(plan_stop_id=stop.id, user_id=1, venue_id=venue_id, entered_by="staff"))
    db.commit()
    db.add(CheckIn(plan_stop_id=stop.id, user_id=1, venue_id=venue_id, entered_by="staff"))
    with pytest.raises(IntegrityError):  # a duplicate would double-bill the venue
        db.commit()


def test_plan_needs_exactly_one_owner(db, stop):
    night_id = db.get(Plan, stop.plan_id).night_id
    db.add(Plan(user_id=None, group_id=None, night_id=night_id, inputs={}))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("make", [
    lambda s: Rating(user_id=1, plan_stop_id=s.id, stars=6),
    lambda s: Experience(venue_id=1, title="x", kind="meet", vibes=["chill"],
                         price_per_head_inr=100, duration_min=30, min_age=17),
    lambda s: Venue(name="Neg", area="X", licensed=False, closes_at=time(23), cpa_rate_inr=-1),
], ids=["stars-over-5", "under-18-experience", "negative-cpa"])
def test_check_constraints_reject_bad_records(db, stop, make):
    db.add(make(stop))
    with pytest.raises(IntegrityError):
        db.commit()
