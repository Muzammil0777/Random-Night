"""Task 2: magic-link login, sessions, profile, age rules."""
from datetime import date, timedelta

import pytest
from sqlalchemy import update

from app import auth
from app.models import LoginToken, User, UserSession

ADULT = {"email": "Asha@Example.com", "name": "Asha", "dob": "1999-05-10"}


@pytest.fixture
def outbox(monkeypatch):
    """Capture login links instead of emailing them."""
    sent = []
    monkeypatch.setattr(auth, "send_login_email", lambda email, link: sent.append((email, link)))
    return sent


def _token(outbox):
    return outbox[-1][1].split("token=")[1]


def _login(client, outbox, **body):
    assert client.post("/api/auth/request", json=body or ADULT).status_code == 202
    r = client.post("/api/auth/verify", json={"token": _token(outbox)})
    assert r.status_code == 200, r.text
    return r.json()


# ---- age rules ----
@pytest.mark.parametrize("dob,on,expected", [
    (date(2005, 6, 15), date(2026, 6, 14), 20),  # day before 21st birthday
    (date(2005, 6, 15), date(2026, 6, 15), 21),  # on the birthday
    (date(2004, 2, 29), date(2025, 2, 28), 20),  # leap-day birthday, non-leap year: not yet
    (date(2004, 2, 29), date(2025, 3, 1), 21),
    (date(2004, 2, 29), date(2028, 2, 29), 24),
], ids=["day-before-21", "21st-birthday", "leap-feb28", "leap-mar1", "leap-year"])
def test_age_on_boundaries(dob, on, expected):
    assert auth.age_on(dob, on) == expected


@pytest.mark.parametrize("dob,verified,on,allowed", [
    (date(2005, 6, 15), True, date(2026, 6, 14), False),   # 20 on the night
    (date(2005, 6, 15), True, date(2026, 6, 15), True),    # turns 21 that night
    (date(1995, 1, 1), False, date(2026, 6, 15), False),   # old enough but ID not checked
], ids=["under-21", "turns-21-tonight", "id-not-verified"])
def test_licensed_venues_need_21_and_checked_id(dob, verified, on, allowed):
    assert auth.can_enter_licensed(User(dob=dob, id_verified=verified), on) is allowed


# ---- login ----
def test_signup_creates_user_and_session(client, outbox, db):
    res = _login(client, outbox)
    assert res["user"]["email"] == "asha@example.com"  # normalised
    assert res["user"]["id_verified"] is False
    me = client.get("/api/me", headers={"Authorization": f"Bearer {res['session']}"})
    assert me.status_code == 200 and me.json()["name"] == "Asha"
    assert db.query(LoginToken).one().token_hash != _token(outbox)  # only the hash is stored


def test_returning_user_logs_in_with_email_only(client, outbox, db):
    first = _login(client, outbox)
    again = _login(client, outbox, email="asha@example.com")
    assert again["user"]["id"] == first["user"]["id"]
    assert db.query(User).count() == 1


def test_link_works_only_once(client, outbox):
    _login(client, outbox)
    r = client.post("/api/auth/verify", json={"token": _token(outbox)})
    assert r.status_code == 400


def test_expired_link_is_rejected(client, outbox, db):
    client.post("/api/auth/request", json=ADULT)
    db.execute(update(LoginToken).values(expires_at=auth.now() - timedelta(seconds=1)))
    db.commit()
    assert client.post("/api/auth/verify", json={"token": _token(outbox)}).status_code == 400


def test_unknown_link_is_rejected(client):
    assert client.post("/api/auth/verify", json={"token": "x" * 43}).status_code == 400


def test_new_email_without_signup_details_gets_no_account(client, outbox, db):
    client.post("/api/auth/request", json={"email": "new@example.com"})
    r = client.post("/api/auth/verify", json={"token": _token(outbox)})
    assert r.status_code == 400 and db.query(User).count() == 0


def test_under_18_cannot_sign_up(client, outbox):
    dob = (auth.now().date() - timedelta(days=365 * 17)).isoformat()
    r = client.post("/api/auth/request", json={**ADULT, "dob": dob})
    assert r.status_code == 422 and outbox == []


def test_link_requests_are_rate_limited(client, outbox):
    codes = [client.post("/api/auth/request", json=ADULT).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]


# ---- sessions & profile ----
def test_me_requires_valid_session(client, outbox, db):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    token = _login(client, outbox)["session"]
    db.execute(update(UserSession).values(expires_at=auth.now() - timedelta(seconds=1)))
    db.commit()
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_logout_revokes_session(client, outbox):
    h = {"Authorization": f"Bearer {_login(client, outbox)['session']}"}
    assert client.post("/api/auth/logout", headers=h).status_code == 204
    assert client.get("/api/me", headers=h).status_code == 401


def test_profile_update_cannot_change_dob(client, outbox):
    h = {"Authorization": f"Bearer {_login(client, outbox)['session']}"}
    r = client.patch("/api/me", headers=h, json={"emergency_contact": "+91 90000 00000", "dob": "1980-01-01"})
    assert r.status_code == 200
    assert r.json()["emergency_contact"] == "+91 90000 00000"
    assert r.json()["dob"] == "1999-05-10"  # unchanged


def test_production_never_logs_login_links(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(auth.HTTPException) as e:
        auth.send_login_email("a@example.com", "https://randomnight.in/login?token=abc")
    assert e.value.status_code == 503
