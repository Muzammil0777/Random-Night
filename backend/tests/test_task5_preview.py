"""Task 5: options + plan preview API (the UI's only data source)."""
import secrets
from datetime import date, timedelta

import pytest

from app import auth
from app.models import User, UserSession, Venue
from app.seed import load

BARS = {"Sample Rooftop Bar", "Sample Brewpub", "Sample Comedy Club"}  # licensed in seed/venues.csv


def _next_friday():
    t = auth.today_ist()
    return t + timedelta(days=(4 - t.weekday()) % 7)


def _login_as(client, db, dob=date(1995, 1, 1), verified=True):
    u = User(email=f"{secrets.token_hex(4)}@example.com", name="T", dob=dob, id_verified=verified)
    db.add(u)
    db.flush()
    token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=auth._hash(token), user_id=u.id, expires_at=auth.now() + timedelta(days=1)))
    db.commit()
    client.cookies.set(auth.COOKIE, token)


def _inputs(**over):
    return {"area": "Jubilee Hills", "budget_inr": 2000, "hours": 4, "vibe": "party",
            "company": "solo", "date": _next_friday().isoformat(), **over}


@pytest.fixture
def seeded(db):
    load(db)
    return db


def test_options_lists_choices(client):
    o = client.get("/api/options").json()
    assert "Jubilee Hills" in o["areas"] and o["budgets"] == [1000, 2000, 5000] and o["hours"] == [2, 4, None]


def test_preview_requires_login(client, seeded):
    assert client.post("/api/plans/preview", json=_inputs()).status_code == 401


def test_verified_adult_gets_a_labelled_night(client, seeded):
    _login_as(client, seeded)
    r = client.post("/api/plans/preview", json=_inputs())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bars_unlocked"] is True and len(body["stops"]) >= 2
    assert body["total_inr"] == sum(s["price_per_head_inr"] for s in body["stops"]) <= 2000
    assert all("is_partner" in s for s in body["stops"])
    assert body["stops"][0]["starts_at"].endswith("+05:30")  # IST for the UI


@pytest.mark.parametrize("dob,verified", [(date(1995, 1, 1), False), (date(2006, 1, 1), True)],
                         ids=["id-not-checked", "under-21"])
def test_no_bars_until_21_and_id_checked(client, seeded, dob, verified):
    _login_as(client, seeded, dob=dob, verified=verified)
    r = client.post("/api/plans/preview", json=_inputs(vibe="chill", area="HITEC City", budget_inr=1000))
    assert r.status_code == 200, r.text
    assert r.json()["bars_unlocked"] is False
    assert not {s["venue"] for s in r.json()["stops"]} & BARS


def test_no_fitting_night_is_a_clear_404(client, seeded):
    _login_as(client, seeded, verified=False)  # every party experience in the seed is at a bar
    r = client.post("/api/plans/preview", json=_inputs())
    assert r.status_code == 404 and "Try a bigger budget" in r.json()["detail"]


def test_inactive_venues_never_appear(client, seeded):
    for v in seeded.query(Venue).filter(Venue.name.in_(BARS)):
        v.active = False
    seeded.commit()
    _login_as(client, seeded)
    assert client.post("/api/plans/preview", json=_inputs()).status_code == 404


@pytest.mark.parametrize("over", [
    {"area": "Mars"}, {"hours": 3}, {"vibe": "rave"}, {"company": "boss"}, {"budget_inr": 10},
    {"date": (date.today() - timedelta(days=2)).isoformat()},
    {"date": (date.today() + timedelta(days=60)).isoformat()},
], ids=["area", "hours", "vibe", "company", "budget", "past", "too-far"])
def test_bad_inputs_are_rejected(client, seeded, over):
    _login_as(client, seeded)
    assert client.post("/api/plans/preview", json=_inputs(**over)).status_code == 422
