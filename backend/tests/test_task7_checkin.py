"""Task 7: booking + per-guest check-in codes + venue staff check-in."""
import secrets
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app import auth, bookings, staff
from app.matching import match
from app.models import CheckIn, DropEntry, User, UserSession, VenueKey
from app.seed import load

D = auth.today_ist() + timedelta(days=3)  # the booked night


@pytest.fixture
def seeded(db):
    load(db)
    return db


@pytest.fixture
def on_night(monkeypatch):
    """Pretend it's 9:30 PM IST on `day` at the door (nights start at 9 PM)."""
    def go(day, at=time(21, 30)):
        monkeypatch.setattr(staff, "tonight", lambda: day)
        monkeypatch.setattr(staff, "now", lambda: datetime.combine(day, at, auth.IST))
    go(D)
    return go


def _login(client, db, dob=date(1995, 1, 1), verified=True, name="Asha Rao"):
    u = User(email=f"{secrets.token_hex(4)}@example.com", name=name, dob=dob, id_verified=verified)
    db.add(u)
    db.flush()
    token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=auth._hash(token), user_id=u.id, expires_at=auth.now() + timedelta(days=1)))
    db.commit()
    client.cookies.set(auth.COOKIE, token)
    return u


def _inputs(**over):
    return {"area": "Jubilee Hills", "budget_inr": 2000, "hours": 4, "vibe": "chill", "company": "solo",
            "date": D.isoformat(), **over}


def _book(client, db, **kw):
    user = _login(client, db, **kw)
    r = client.post("/api/plans", json=_inputs())
    assert r.status_code == 201, r.text
    return user, r.json()


def _staff(client, db, venue):
    """Log the client in as door staff of `venue` (guest cookie removed so only staff auth counts)."""
    key = staff.create_key(db, venue, "Front door")
    client.cookies.clear()
    assert client.post("/api/staff/login", json={"key": key}).status_code == 200
    return key


# ---- booking ----
def test_booking_needs_login(client, seeded):
    assert client.post("/api/plans", json=_inputs()).status_code == 401


def test_booking_saves_the_night_with_a_code_per_stop(client, seeded):
    _, night = _book(client, seeded)
    codes = [s["code"] for s in night["stops"]]
    assert len(codes) >= 2 and len(set(codes)) == len(codes)
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert not any(s["checked_in"] for s in night["stops"])
    assert all("is_partner" in s for s in night["stops"])  # label still reaches the UI
    first = datetime.fromisoformat(night["stops"][0]["starts_at"])
    assert first.astimezone(auth.IST) == datetime.combine(D, time(21, 0), auth.IST)  # 9 PM IST, also on SQLite
    assert client.get("/api/plans/next").json() == night


def test_booking_regenerates_server_side_and_keeps_the_age_gate(client, seeded):
    _login(client, seeded, dob=D.replace(year=D.year - 19))  # 19 on the night
    r = client.post("/api/plans", json=_inputs(vibe="surprise", stops=[{"venue": "Sample Rooftop Bar"}]))
    assert r.status_code == 201
    assert r.json()["bars_unlocked"] is False
    assert not any(s["venue"] in {"Sample Rooftop Bar", "Sample Brewpub", "Sample Comedy Club"}
                   for s in r.json()["stops"])


@pytest.mark.parametrize("over,code", [({"company": "new_people"}, 422), ({"date": "2000-01-01"}, 422)])
def test_booking_rejects(client, seeded, over, code):
    _login(client, seeded)
    assert client.post("/api/plans", json=_inputs(**over)).status_code == code


def test_one_night_per_date_across_booking_and_random_friday(client, seeded):
    user, _ = _book(client, seeded)
    assert client.post("/api/plans", json=_inputs()).status_code == 409
    friday = D + timedelta(days=(4 - D.weekday()) % 7 or 7)
    seeded.add(DropEntry(user_id=user.id, date=friday, area="Jubilee Hills", vibe="chill", budget_inr=2000))
    seeded.commit()
    assert client.post("/api/plans", json=_inputs(date=friday.isoformat())).status_code == 409


def test_cancel_before_check_in_only(client, seeded, on_night):
    _, night = _book(client, seeded)
    session = client.cookies.get(auth.COOKIE)
    _login(client, seeded)  # someone else can't cancel it
    assert client.delete(f"/api/plans/{night['id']}").status_code == 404
    client.cookies.set(auth.COOKIE, session)
    assert client.delete(f"/api/plans/{night['id']}").status_code == 204
    assert client.get("/api/plans/next").json() is None

    _, night = _book(client, seeded)
    session = client.cookies.get(auth.COOKIE)
    _staff(client, seeded, night["stops"][0]["venue"])
    client.post("/api/staff/checkin", json={"code": night["stops"][0]["code"]})
    client.cookies.set(auth.COOKIE, session)
    assert client.delete(f"/api/plans/{night['id']}").status_code == 409


# ---- staff login ----
def test_staff_login(client, seeded):
    assert client.post("/api/staff/login", json={"key": "nope"}).status_code == 401
    key = staff.create_key(seeded, "Sample Live Music Cafe", "Front door")
    r = client.post("/api/staff/login", json={"key": key})
    assert r.json() == {"venue": "Sample Live Music Cafe", "label": "Front door"}
    assert "httponly" in r.headers["set-cookie"].lower()
    assert key not in r.text  # never echoed back in the body
    assert seeded.scalar(select(VenueKey.key_hash)) == auth._hash(key)  # stored hashed only
    seeded.scalar(select(VenueKey)).active = False  # revoked in /admin
    seeded.commit()
    assert client.get("/api/staff/me").status_code == 401


def test_guest_session_is_not_staff_login(client, seeded):
    _, night = _book(client, seeded)
    assert client.post("/api/staff/checkin", json={"code": night["stops"][0]["code"]}).status_code == 401


# ---- check-in rules ----
def test_code_works_once(client, seeded, on_night):
    user, night = _book(client, seeded, name="Ravi Kumar")
    stop = night["stops"][0]
    _staff(client, seeded, stop["venue"])
    r = client.post("/api/staff/checkin", json={"code": stop["code"]})
    assert r.status_code == 200 and r.json() == {"guest": "Ravi", "stop": stop["title"]}
    assert client.post("/api/staff/checkin", json={"code": stop["code"]}).status_code == 409
    rows = seeded.scalars(select(CheckIn)).all()
    assert len(rows) == 1 and rows[0].user_id == user.id and rows[0].entered_by == "Front door"


def test_code_only_works_at_the_right_venue(client, seeded, on_night):
    _, night = _book(client, seeded)
    assert "Sample Biryani House" not in {s["venue"] for s in night["stops"]}
    _staff(client, seeded, "Sample Biryani House")
    assert client.post("/api/staff/checkin", json={"code": night["stops"][0]["code"]}).status_code == 404
    assert seeded.scalars(select(CheckIn)).all() == []


@pytest.mark.parametrize("shift", [-1, 1, 7])
def test_code_only_works_on_that_night(client, seeded, on_night, shift):
    _, night = _book(client, seeded)
    _staff(client, seeded, night["stops"][0]["venue"])
    on_night(D + timedelta(days=shift))
    assert client.post("/api/staff/checkin", json={"code": night["stops"][0]["code"]}).status_code == 404
    assert seeded.scalars(select(CheckIn)).all() == []


def test_check_in_records_the_staff_venue_server_side(client, seeded, on_night):
    _, night = _book(client, seeded)
    key = _staff(client, seeded, night["stops"][0]["venue"])
    client.post("/api/staff/checkin", json={"code": night["stops"][0]["code"], "venue_id": 999})
    row = seeded.scalar(select(CheckIn))
    assert row.venue_id == seeded.scalar(select(VenueKey.venue_id).where(VenueKey.key_hash == auth._hash(key)))


@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", ""])
def test_malformed_codes_rejected(client, seeded, code):
    _staff(client, seeded, "Sample Live Music Cafe")
    assert client.post("/api/staff/checkin", json={"code": code}).status_code == 422


def test_checked_in_shows_on_the_guests_night(client, seeded, on_night):
    _, night = _book(client, seeded)
    session = client.cookies.get(auth.COOKIE)
    _staff(client, seeded, night["stops"][0]["venue"])
    client.post("/api/staff/checkin", json={"code": night["stops"][0]["code"]})
    client.cookies.set(auth.COOKIE, session)
    stops = client.get("/api/plans/next").json()["stops"]
    assert stops[0]["checked_in"] is True and stops[1]["checked_in"] is False


def test_code_only_works_around_its_stop_time(client, seeded, on_night):
    _, night = _book(client, seeded)
    stop = night["stops"][0]  # 9 PM; door opens an hour early
    _staff(client, seeded, stop["venue"])
    on_night(D, time(19, 59))
    assert client.post("/api/staff/checkin", json={"code": stop["code"]}).status_code == 409
    ends = datetime.fromisoformat(stop["ends_at"]).astimezone(auth.IST)
    on_night(D, (ends + timedelta(hours=1, minutes=1)).time())
    assert client.post("/api/staff/checkin", json={"code": stop["code"]}).status_code == 409
    assert seeded.scalars(select(CheckIn)).all() == []
    on_night(D, time(20, 0))
    assert client.post("/api/staff/checkin", json={"code": stop["code"]}).status_code == 200


def test_deactivated_venue_keys_stop_working(client, seeded):
    _staff(client, seeded, "Sample Live Music Cafe")
    seeded.scalar(select(VenueKey)).venue.active = False
    seeded.commit()
    assert client.get("/api/staff/me").status_code == 401


def test_group_members_each_get_their_own_code(client, seeded, on_night):
    friday = D + timedelta(days=(4 - D.weekday()) % 7 or 7)
    users = []
    for i in range(4):
        u = User(email=f"g{i}@example.com", name=f"G{i} X", dob=date(1995, 1, 1), id_verified=True)
        seeded.add(u)
        seeded.flush()
        seeded.add(DropEntry(user_id=u.id, date=friday, area="Jubilee Hills", vibe="chill", budget_inr=2000))
        users.append(u)
    seeded.commit()
    match(seeded, friday)
    codes = {}
    for u in users:
        token = secrets.token_urlsafe(32)
        seeded.add(UserSession(token_hash=auth._hash(token), user_id=u.id, expires_at=auth.now() + timedelta(days=1)))
        seeded.commit()
        client.cookies.set(auth.COOKIE, token)
        night = client.get(f"/api/drops/{friday}").json()["night"]
        assert night["group"] == ["G0", "G1", "G2", "G3"]
        codes[u.id] = night["stops"][0]["code"]
        assert client.delete(f"/api/plans/{night['id']}").status_code == 404  # group nights aren't cancelled here
    assert len(set(codes.values())) == 4
    on_night(friday)
    _staff(client, seeded, night["stops"][0]["venue"])
    for code in codes.values():
        assert client.post("/api/staff/checkin", json={"code": code}).status_code == 200
    assert {c.user_id for c in seeded.scalars(select(CheckIn))} == set(codes)


def test_night_rolls_over_at_6am_ist(monkeypatch):
    fri = date(2026, 11, 20)
    monkeypatch.setattr(bookings, "now", lambda: datetime.combine(fri + timedelta(days=1), time(1, 0), auth.IST))
    assert bookings.tonight() == fri  # 1 AM Saturday is still Friday's night
    monkeypatch.setattr(bookings, "now", lambda: datetime.combine(fri + timedelta(days=1), time(6, 0), auth.IST))
    assert bookings.tonight() == fri + timedelta(days=1)
