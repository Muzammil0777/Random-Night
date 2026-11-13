"""Task 9: ratings (only for stops you checked in at), auto-pause below the floor, report/block."""
import secrets
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app import auth, staff
from app.feedback import MIN_RATINGS
from app.matching import form_groups, match
from app.models import Block, DropEntry, GroupMember, Rating, Report, User, UserSession, Venue
from app.seed import load

D = auth.today_ist() + timedelta(days=3)
CAFE = "Sample Live Music Cafe"  # both stops of the chill Jubilee Hills night


def _friday(after):
    return after + timedelta(days=(4 - after.weekday()) % 7 or 7)


@pytest.fixture
def seeded(db, monkeypatch):
    load(db)
    monkeypatch.setattr(staff, "tonight", lambda: D)
    monkeypatch.setattr(staff, "now", lambda: datetime.combine(D, time(21, 30), auth.IST))
    return db


def _user(db, name="Asha Rao"):
    u = User(email=f"{secrets.token_hex(4)}@example.com", name=name, dob=date(1995, 1, 1), id_verified=True)
    db.add(u)
    db.flush()
    return u


def _as(client, db, user):
    token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=auth._hash(token), user_id=user.id, expires_at=auth.now() + timedelta(days=1)))
    db.commit()
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, token)


def _night(client, db, user):
    _as(client, db, user)
    r = client.post("/api/plans", json={"area": "Jubilee Hills", "budget_inr": 2000, "hours": 4, "vibe": "chill",
                                        "company": "solo", "date": D.isoformat()})
    assert r.status_code == 201, r.text
    return r.json()


def _checked_in_guest(client, db, name="Asha Rao"):
    """A guest who booked the chill night and was checked in at its first stop. Returns (user, stop_id)."""
    user = _user(db, name)
    stop = _night(client, db, user)["stops"][0]
    key = staff.create_key(db, CAFE, "Door")
    client.cookies.clear()
    client.post("/api/staff/login", json={"key": key})
    assert client.post("/api/staff/checkin", json={"code": stop["code"]}).status_code == 200
    _as(client, db, user)
    return user, stop["plan_stop_id"]


def _rate(client, stop_id, stars):
    return client.post("/api/ratings", json={"plan_stop_id": stop_id, "stars": stars})


def _cafe(db):
    db.expire_all()
    return db.scalar(select(Venue).where(Venue.name == CAFE))


def _preview_venues(client, db):
    _as(client, db, _user(db))
    r = client.post("/api/plans/preview", json={"area": "Jubilee Hills", "budget_inr": 2000, "hours": 4,
                                                "vibe": "chill", "company": "solo", "date": D.isoformat()})
    return set() if r.status_code == 404 else {s["venue"] for s in r.json()["stops"]}


# ---- ratings ----
def test_only_checked_in_stops_can_be_rated(client, seeded):
    night = _night(client, seeded, _user(seeded))  # booked, never checked in
    assert _rate(client, night["stops"][0]["plan_stop_id"], 5).status_code == 403
    _, stop_id = _checked_in_guest(client, seeded)
    assert _rate(client, stop_id, 4).status_code == 200
    _as(client, seeded, _user(seeded))  # someone else can't rate that stop
    assert _rate(client, stop_id, 1).status_code == 403


def test_rating_again_updates_and_shows_on_the_night(client, seeded):
    _, stop_id = _checked_in_guest(client, seeded)
    _rate(client, stop_id, 2)
    _rate(client, stop_id, 5)
    assert [r.stars for r in seeded.scalars(select(Rating))] == [5]
    last = client.get("/api/plans/last").json()
    assert last["stops"][0]["my_stars"] == 5 and last["stops"][0]["checked_in"] is True


@pytest.mark.parametrize("stars", [0, 6])
def test_stars_must_be_1_to_5(client, seeded, stars):
    _, stop_id = _checked_in_guest(client, seeded)
    assert _rate(client, stop_id, stars).status_code == 422


def test_last_night_needs_a_check_in(client, seeded):
    _night(client, seeded, _user(seeded))
    assert client.get("/api/plans/last").json() is None


def test_venue_average_waits_for_enough_ratings(client, seeded):
    start = _cafe(seeded).rating_avg  # the admin's starting value
    stops = [_checked_in_guest(client, seeded, f"G{i} X") for i in range(MIN_RATINGS)]
    for user, stop_id in stops[:-1]:
        _as(client, seeded, user)
        _rate(client, stop_id, 1)
    assert _cafe(seeded).rating_avg == start  # a few angry guests can't pause a venue on their own
    user, stop_id = stops[-1]
    _as(client, seeded, user)
    _rate(client, stop_id, 1)
    assert _cafe(seeded).rating_avg == 1.0


def test_venue_under_the_floor_is_excluded_from_the_next_generation(client, seeded):
    assert CAFE in _preview_venues(client, seeded)
    for i in range(MIN_RATINGS):
        user, stop_id = _checked_in_guest(client, seeded, f"G{i} X")
        _as(client, seeded, user)
        _rate(client, stop_id, 2)
    assert _cafe(seeded).rating_avg == 2.0
    assert CAFE not in _preview_venues(client, seeded)


def test_well_rated_venue_keeps_getting_routed(client, seeded):
    for i in range(MIN_RATINGS):
        user, stop_id = _checked_in_guest(client, seeded, f"G{i} X")
        _as(client, seeded, user)
        _rate(client, stop_id, 5)
    assert _cafe(seeded).rating_avg == 5.0 and CAFE in _preview_venues(client, seeded)


# ---- report / block ----
def _group(db, n=4, friday=None):
    friday = friday or _friday(D)
    users = [_user(db, f"M{i} Surname") for i in range(n)]
    db.add_all(DropEntry(user_id=u.id, date=friday, area="Jubilee Hills", vibe="chill", budget_inr=2000)
               for u in users)
    db.commit()
    match(db, friday)
    return users


def test_group_night_lists_the_others_by_first_name_only(client, seeded):
    a, *others = _group(seeded)
    _as(client, seeded, a)
    night = client.get(f"/api/drops/{_friday(D)}").json()["night"]
    assert night["members"] == [{"id": u.id, "name": u.name.split()[0]} for u in others]
    assert "Surname" not in str(night) and "@example.com" not in str(night)


def test_report_needs_a_shared_group_and_also_blocks(client, seeded):
    a, b, *_ = _group(seeded)
    stranger = _user(seeded)
    _as(client, seeded, a)
    assert client.post("/api/reports", json={"user_id": stranger.id, "reason": "rude"}).status_code == 404
    assert client.post("/api/reports", json={"user_id": a.id, "reason": "self"}).status_code == 404
    assert client.post("/api/reports", json={"user_id": b.id, "reason": "x"}).status_code == 422  # too short
    r = client.post("/api/reports", json={"user_id": b.id, "reason": "Made me uncomfortable"})
    assert r.status_code == 201 and r.json() == {"reported": True, "blocked": True}
    assert [(x.reporter_id, x.reported_id) for x in seeded.scalars(select(Report))] == [(a.id, b.id)]
    assert [(x.blocker_id, x.blocked_id) for x in seeded.scalars(select(Block))] == [(a.id, b.id)]


def test_block_needs_a_shared_group_and_is_idempotent(client, seeded):
    a, b, *_ = _group(seeded)
    _as(client, seeded, a)
    assert client.post("/api/blocks", json={"user_id": _user(seeded).id}).status_code == 404
    assert client.post("/api/blocks", json={"user_id": b.id}).status_code == 204
    assert client.post("/api/blocks", json={"user_id": b.id}).status_code == 204
    assert len(seeded.scalars(select(Block)).all()) == 1


def test_blocked_people_are_never_grouped_again(client, seeded):
    a, b, c, d = _group(seeded)
    _as(client, seeded, a)
    client.post("/api/blocks", json={"user_id": b.id})
    next_friday = _friday(_friday(D))
    e = _user(seeded)
    seeded.add_all(DropEntry(user_id=u.id, date=next_friday, area="Jubilee Hills", vibe="chill", budget_inr=2000)
                   for u in (a, b, c, d, e))
    seeded.commit()
    assert match(seeded, next_friday) == {"groups": 1, "matched": 4, "waiting": 1}
    entries = {x.user_id: x.group_id for x in seeded.scalars(select(DropEntry).where(DropEntry.date == next_friday))}
    assert entries[b.id] is None and entries[a.id] is not None  # a joined first, so b waits


def test_form_groups_never_seats_a_clash_and_drops_short_groups():
    people = list(range(12))
    clashes = {frozenset((0, 1)), frozenset((0, 2)), frozenset((5, 6))}
    groups = form_groups(people, lambda x, y: frozenset((x, y)) in clashes)
    assert all(4 <= len(g) <= 6 for g in groups)
    assert not any(frozenset((x, y)) in clashes for g in groups for x in g for y in g if x != y)
    # 4 people where two clash: nobody can make a full group
    assert form_groups([0, 1, 2, 3], lambda x, y: {x, y} == {0, 1}) == []


def test_group_members_of_others_stay_private(client, seeded):
    _group(seeded)
    outsider = _user(seeded)
    _as(client, seeded, outsider)
    assert client.get(f"/api/drops/{_friday(D)}").status_code == 404
    assert seeded.scalars(select(GroupMember)).all()  # groups exist, just not visible to outsiders


def test_one_guest_rating_two_stops_counts_once(client, seeded, monkeypatch):
    guests = [_checked_in_guest(client, seeded, f"G{i} X") for i in range(MIN_RATINGS - 1)]
    for user, stop_id in guests:
        _as(client, seeded, user)
        _rate(client, stop_id, 1)
    # the first guest also checks in at the second stop (same venue) and rates it: still only 4 people
    user, _ = guests[0]
    _as(client, seeded, user)
    second = client.get("/api/plans/next").json()["stops"][1]
    key = staff.create_key(seeded, CAFE, "Door 2")
    client.cookies.clear()
    client.post("/api/staff/login", json={"key": key})
    monkeypatch.setattr(staff, "now", lambda: datetime.combine(D, time(22, 0), auth.IST))  # second stop's slot
    assert client.post("/api/staff/checkin", json={"code": second["code"]}).status_code == 200
    _as(client, seeded, user)
    assert _rate(client, second["plan_stop_id"], 1).status_code == 200
    assert _cafe(seeded).rating_avg == 4.5  # unchanged: 4 distinct raters < MIN_RATINGS


def test_ratings_close_after_a_week(client, seeded, monkeypatch):
    _, stop_id = _checked_in_guest(client, seeded)
    monkeypatch.setattr("app.feedback.tonight", lambda: D + timedelta(days=8))
    assert _rate(client, stop_id, 5).status_code == 409


def test_repeat_reports_against_one_person_count_once(client, seeded):
    a, b, *_ = _group(seeded)
    _as(client, seeded, a)
    for _ in range(3):
        assert client.post("/api/reports", json={"user_id": b.id, "reason": "Again and again"}).status_code == 201
    assert len(seeded.scalars(select(Report)).all()) == 1
