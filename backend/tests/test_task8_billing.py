"""Task 8: venue dashboard + monthly invoice CSV. Bill only checked-in guests, at the rate when they checked in."""
import csv
import io
import secrets
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app import auth, staff
from app.billing import month_range
from app.models import User, UserSession, Venue, VenueVisit
from app.seed import load

D = auth.today_ist() + timedelta(days=3)
MONTH = D.strftime("%Y-%m")
CAFE = "Sample Live Music Cafe"  # the chill night in Jubilee Hills is both stops here


@pytest.fixture
def seeded(db, monkeypatch):
    load(db)
    db.scalar(select(Venue).where(Venue.name == CAFE)).cpa_rate_inr = 120
    db.commit()
    monkeypatch.setattr(staff, "tonight", lambda: D)
    monkeypatch.setattr(staff, "now", lambda: datetime.combine(D, time(21, 30), auth.IST))
    return db


def _guest(client, db, name="Asha Rao"):
    """A user who books the chill night on D; returns their stop codes."""
    u = User(email=f"{secrets.token_hex(4)}@example.com", name=name, dob=date(1995, 1, 1), id_verified=True)
    db.add(u)
    db.flush()
    token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=auth._hash(token), user_id=u.id, expires_at=auth.now() + timedelta(days=1)))
    db.commit()
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, token)
    r = client.post("/api/plans", json={"area": "Jubilee Hills", "budget_inr": 2000, "hours": 4, "vibe": "chill",
                                        "company": "solo", "date": D.isoformat()})
    assert r.status_code == 201, r.text
    assert {s["venue"] for s in r.json()["stops"]} == {CAFE}
    return [s["code"] for s in r.json()["stops"]]


def _door(client, db, venue=CAFE):
    key = staff.create_key(db, venue, "Front door")
    client.cookies.clear()
    assert client.post("/api/staff/login", json={"key": key}).status_code == 200


def _check_in(client, code):
    assert client.post("/api/staff/checkin", json={"code": code}).status_code == 200


def _invoice(client, month=MONTH):
    r = client.get(f"/api/staff/invoice.csv?month={month}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(r.text)))


def test_invoice_bills_only_checked_in_guests(client, seeded):
    guests = [_guest(client, seeded, f"Guest{i} X") for i in range(4)]
    _door(client, seeded)
    for codes in guests[:3]:          # the 4th is a no-show
        _check_in(client, codes[0])
    d = client.get(f"/api/staff/dashboard?month={MONTH}").json()
    assert d["nights"] == [{"date": D.isoformat(), "routed": 4, "checked_in": 3}]
    assert d["billable_guests"] == 3 and d["total_inr"] == 3 * 120
    rows = _invoice(client)
    assert rows[1] == ["night", "checked_in_at_ist", "guest", "stop", "entered_by", "rate_inr"]
    assert len(rows[2:-1]) == 3 and {r[2] for r in rows[2:-1]} == {"Guest0", "Guest1", "Guest2"}
    assert rows[-1] == ["TOTAL", "", "3 guests", "", "", "360"]
    assert 'filename="random-night-sample-live-music-cafe-' in client.get(
        f"/api/staff/invoice.csv?month={MONTH}").headers["content-disposition"]


def test_a_guest_at_two_stops_of_one_venue_is_billed_once(client, seeded):
    codes = _guest(client, seeded)
    assert len(codes) == 2
    _door(client, seeded)
    _check_in(client, codes[0])
    _check_in(client, codes[1])
    assert len(seeded.scalars(select(VenueVisit)).all()) == 1
    assert client.get(f"/api/staff/dashboard?month={MONTH}").json()["total_inr"] == 120


def test_rate_is_fixed_when_the_guest_checks_in(client, seeded):
    first, second = _guest(client, seeded), _guest(client, seeded)
    _door(client, seeded)
    _check_in(client, first[0])
    seeded.scalar(select(Venue).where(Venue.name == CAFE)).cpa_rate_inr = 200  # renegotiated mid-month
    seeded.commit()
    _check_in(client, second[0])
    d = client.get(f"/api/staff/dashboard?month={MONTH}").json()
    assert d["rate_inr"] == 200 and d["total_inr"] == 120 + 200
    assert _invoice(client)[-1][-1] == "320"


def test_other_months_and_other_venues_see_nothing(client, seeded):
    codes = _guest(client, seeded)
    _door(client, seeded)
    _check_in(client, codes[0])
    next_month = month_range(MONTH)[2].strftime("%Y-%m")
    assert client.get(f"/api/staff/dashboard?month={next_month}").json()["total_inr"] == 0
    assert _invoice(client, next_month)[-1] == ["TOTAL", "", "0 guests", "", "", "0"]
    _door(client, seeded, "Sample Biryani House")
    d = client.get(f"/api/staff/dashboard?month={MONTH}").json()
    assert d["venue"] == "Sample Biryani House" and d["nights"] == [] and d["total_inr"] == 0


def test_csv_neutralises_formula_names(client, seeded):
    codes = _guest(client, seeded, name="=HYPERLINK(\"http://evil\")")
    _door(client, seeded)
    _check_in(client, codes[0])
    assert _invoice(client)[2][2].startswith("'=")


def test_dashboard_and_invoice_need_a_staff_login(client, seeded):
    _guest(client, seeded)  # a guest session is not a venue login
    for path in ("/api/staff/dashboard", "/api/staff/invoice.csv"):
        assert client.get(path).status_code == 401


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "november", "2026-11-01"])
def test_bad_month_rejected(client, seeded, month):
    _door(client, seeded)
    assert client.get(f"/api/staff/dashboard?month={month}").status_code == 422


def test_month_range_wraps_the_year():
    assert month_range("2026-12") == ("2026-12", date(2026, 12, 1), date(2027, 1, 1))
    assert month_range("2026-02")[2] == date(2026, 3, 1)
