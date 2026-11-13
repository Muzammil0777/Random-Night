"""Task 11a-2: Sign in with Google. Google's token check is faked here; its wiring is tested separately."""
from datetime import date

import pytest
from sqlalchemy import select

from app import auth
from app.models import User

CRED = "header.payload.signature-from-google"


def _claims(**over):
    return {"iss": "https://accounts.google.com", "aud": "test-client", "sub": "1234567890",
            "email": "Asha.Rao@gmail.com", "email_verified": True, "given_name": "Asha", "name": "Asha Rao", **over}


@pytest.fixture
def google(monkeypatch):
    """Make verify_google return these claims (or raise like a bad token)."""
    state = {"claims": _claims(), "error": None}

    def fake(credential):
        assert credential == CRED
        if state["error"]:
            raise state["error"]
        return state["claims"]
    monkeypatch.setattr(auth, "verify_google", fake)
    return state


def _sign_in(client, dob=None):
    body = {"credential": CRED, **({"dob": dob.isoformat()} if dob else {})}
    return client.post("/api/auth/google", json=body)


def test_new_user_adds_date_of_birth_once(client, db, google):
    r = _sign_in(client)
    assert r.status_code == 428  # Google doesn't share DOB; the age rules need it
    assert db.scalars(select(User)).all() == []
    r = _sign_in(client, dob=date(1998, 4, 2))
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == "asha.rao@gmail.com" and me["name"] == "Asha" and me["dob"] == "1998-04-02"
    assert me["id_verified"] is False  # Google proves the email, not the age: bars still need the door ID check
    session = client.cookies.get(auth.COOKIE)
    assert session and session not in r.text  # session only in the httpOnly cookie, never the body
    assert client.get("/api/me").json()["id"] == me["id"]
    r = _sign_in(client)  # next time: no DOB step
    assert r.status_code == 200 and r.json()["id"] == me["id"]


def test_same_email_reaches_the_email_link_account(client, db, google):
    u = User(email="asha.rao@gmail.com", name="Asha R", dob=date(1990, 1, 1), id_verified=True)
    db.add(u)
    db.commit()
    r = _sign_in(client)
    assert r.status_code == 200 and r.json()["id"] == u.id and r.json()["id_verified"] is True
    assert len(db.scalars(select(User)).all()) == 1


def test_under_18_cannot_sign_up_with_google(client, db, google):
    today = auth.today_ist()
    r = _sign_in(client, dob=today.replace(year=today.year - 17))
    assert r.status_code == 422 and db.scalars(select(User)).all() == []


def test_unverified_google_email_is_rejected(client, db, google):
    google["claims"] = _claims(email_verified=False)
    assert _sign_in(client, dob=date(1995, 1, 1)).status_code == 401
    assert db.scalars(select(User)).all() == []


def test_bad_or_expired_token_is_rejected(client, db, google):
    google["error"] = ValueError("Token expired")
    r = _sign_in(client, dob=date(1995, 1, 1))
    assert r.status_code == 401 and "Token expired" not in r.text  # no library internals leak


def test_name_falls_back_when_google_has_no_given_name(client, db, google):
    google["claims"] = _claims(given_name=None, name=None, email="no.name@gmail.com")
    assert _sign_in(client, dob=date(1995, 1, 1)).json()["name"] == "no.name"


def test_verify_google_checks_against_our_client_id(monkeypatch):
    seen = {}

    def fake_verify(token, request, audience):
        seen.update(token=token, audience=audience)
        return _claims()
    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "our-client.apps.googleusercontent.com")
    auth.verify_google(CRED)
    assert seen == {"token": CRED, "audience": "our-client.apps.googleusercontent.com"}  # a token for another app fails


def test_google_sign_in_off_without_a_client_id(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert client.post("/api/auth/google", json={"credential": CRED}).status_code == 503


def test_account_is_bound_to_the_first_google_account(client, db, google):
    u = User(email="asha.rao@gmail.com", name="Asha", dob=date(1990, 1, 1))
    db.add(u)
    db.commit()
    assert _sign_in(client).status_code == 200
    db.refresh(u)
    assert u.google_sub == "1234567890"
    google["claims"] = _claims(sub="someone-else")  # the email moved to another Google account
    client.cookies.clear()
    assert _sign_in(client).status_code == 401


def test_google_outage_is_503_not_a_crash(client, google):
    from google.auth.exceptions import TransportError
    google["error"] = TransportError("certs unreachable")
    assert _sign_in(client, dob=date(1995, 1, 1)).status_code == 503


def test_google_sign_in_is_rate_limited_per_ip(client, google):
    google["error"] = ValueError("bad")
    for _ in range(auth.MAX_LINKS_PER_IP):
        assert _sign_in(client).status_code == 401
    assert _sign_in(client).status_code == 429
