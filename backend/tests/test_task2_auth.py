"""Task 2: magic-link login, sessions, profile, age rules."""
from datetime import date, timedelta

import httpx
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
    return {"session": client.cookies.get(auth.COOKIE), "user": r.json()}


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
def test_session_lives_only_in_an_httponly_cookie(client, outbox):
    client.post("/api/auth/request", json=ADULT)
    r = client.post("/api/auth/verify", json={"token": _token(outbox)})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "session" not in r.json()                       # never handed to page JavaScript
    assert client.get("/api/me").status_code == 200        # cookie alone is enough


def test_logout_clears_the_cookie(client, outbox):
    _login(client, outbox)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.cookies.get(auth.COOKIE) is None
    assert client.get("/api/me").status_code == 401



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
    assert r.json()["emergency_contact"] == "+919000000000"  # normalised for tel:/WhatsApp links
    assert r.json()["dob"] == "1999-05-10"  # unchanged


def _years_ago(n):
    t = auth.today_ist()
    try:
        return t.replace(year=t.year - n)
    except ValueError:  # today is Feb 29
        return t.replace(year=t.year - n, day=28)


@pytest.mark.parametrize("dob,code", [
    (lambda: _years_ago(18), 202),                       # 18th birthday today (India date)
    (lambda: _years_ago(18) + timedelta(days=1), 422),   # turns 18 tomorrow
    (lambda: date(1800, 1, 1), 422),                     # nonsense DOB
], ids=["18-today", "18-tomorrow", "year-1800"])
def test_signup_age_boundary(client, outbox, dob, code):
    assert client.post("/api/auth/request", json={**ADULT, "dob": dob().isoformat()}).status_code == code


def test_used_links_do_not_count_toward_rate_limit(client, outbox):
    for _ in range(3):
        _login(client, outbox)
    assert client.post("/api/auth/request", json=ADULT).status_code == 202


def test_failed_email_returns_502_and_frees_quota(client, db, monkeypatch):
    def down(email, link):
        raise httpx.ConnectError("resend down")
    monkeypatch.setattr(auth, "send_login_email", down)
    assert client.post("/api/auth/request", json=ADULT).status_code == 502
    assert db.query(LoginToken).count() == 0


@pytest.mark.parametrize("name", [None, "   "], ids=["null", "blank"])
def test_profile_name_cannot_be_blanked(client, outbox, name):
    h = {"Authorization": f"Bearer {_login(client, outbox)['session']}"}
    assert client.patch("/api/me", headers=h, json={"name": name}).status_code == 422
    assert client.get("/api/me", headers=h).json()["name"] == "Asha"


def test_production_never_logs_login_links(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(auth.HTTPException) as e:
        auth.send_login_email("a@example.com", "https://randomnight.in/login?token=abc")
    assert e.value.status_code == 503


@pytest.mark.parametrize("given,stored", [
    ("98765 43210", "+919876543210"),       # Indian mobile, no country code
    ("098765-43210", "+919876543210"),      # trunk 0
    ("+91 98765 43210", "+919876543210"),
    ("+44 20 7946 0958", "+442079460958"),  # abroad is fine
    ("", None),                             # clears it
])
def test_emergency_contact_is_normalised(client, outbox, given, stored):
    h = {"Authorization": f"Bearer {_login(client, outbox)['session']}"}
    r = client.patch("/api/me", headers=h, json={"emergency_contact": given})
    assert r.status_code == 200 and r.json()["emergency_contact"] == stored


@pytest.mark.parametrize("bad", ["12345", "call my mum", "+0 123456789", "5876543210", "javascript:alert(1)"])
def test_emergency_contact_must_be_a_phone_number(client, outbox, bad):
    h = {"Authorization": f"Bearer {_login(client, outbox)['session']}"}
    assert client.patch("/api/me", headers=h, json={"emergency_contact": bad}).status_code == 422
