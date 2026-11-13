"""Task 3: admin panel auth, venue/experience management, ID verification."""
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import admin as admin_mod
from app.models import Experience, User, Venue
from app.seed import load

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def admin_client(client, db, monkeypatch):
    """Admin panel wired to the per-test DB, with ADMIN_PASSWORD set."""
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    maker = sessionmaker(db.get_bind(), expire_on_commit=False)
    for view in admin_mod.admin.views:
        monkeypatch.setattr(view, "session_maker", maker)
    load(db)
    return client


def _login(c, password=PASSWORD):
    return c.post("/admin/login", data={"username": "admin", "password": password}, follow_redirects=False)


def _logged_in(c):
    assert _login(c).status_code == 302
    return c


# ---- auth ----
def test_admin_requires_login(admin_client):
    r = admin_client.get("/admin/venue/list", follow_redirects=False)
    assert r.status_code in (302, 303) and "/admin/login" in r.headers["location"]


def test_wrong_password_is_rejected(admin_client):
    assert _login(admin_client, "wrong-password-123").status_code == 400
    assert admin_client.get("/admin/venue/list", follow_redirects=False).status_code in (302, 303)


@pytest.mark.parametrize("configured", [None, "short"], ids=["unset", "too-short"])
def test_no_login_without_a_strong_admin_password(admin_client, monkeypatch, configured):
    if configured is None:
        monkeypatch.delenv("ADMIN_PASSWORD")
    else:
        monkeypatch.setenv("ADMIN_PASSWORD", configured)
    assert _login(admin_client, configured or "").status_code == 400


def test_correct_password_opens_admin(admin_client):
    c = _logged_in(admin_client)
    r = c.get("/admin/venue/list")
    assert r.status_code == 200 and "Sample Rooftop Bar" in r.text


# ---- venues & experiences ----
def test_admin_can_add_a_venue(admin_client, db):
    c = _logged_in(admin_client)
    r = c.post("/admin/venue/create", follow_redirects=False, data={
        "name": "New Rooftop", "area": "Jubilee Hills", "licensed": "y", "closes_at": "01:00",
        "cpa_rate_inr": "120", "is_partner": "y", "active": "y"})
    assert r.status_code == 302, r.text
    db.expire_all()
    v = db.scalar(select(Venue).where(Venue.name == "New Rooftop"))
    assert v.licensed and v.is_partner and v.cpa_rate_inr == 120 and v.rating_avg is None


def _exp_form(venue_id, **over):
    return {"venue": str(venue_id), "title": "Late set", "kind": "music", "vibes": '["party"]',
            "price_per_head_inr": "500", "duration_min": "60", "min_age": "21", **over}


def _venue_id(db, licensed):
    return db.scalar(select(Venue.id).where(Venue.licensed.is_(licensed)).limit(1))


def test_admin_can_add_an_experience(admin_client, db):
    c = _logged_in(admin_client)
    r = c.post("/admin/experience/create", data=_exp_form(_venue_id(db, True)), follow_redirects=False)
    assert r.status_code == 302, r.text
    db.expire_all()
    assert db.scalar(select(Experience).where(Experience.title == "Late set")).vibes == ["party"]


@pytest.mark.parametrize("licensed,over,error", [
    (True, {"min_age": "18"}, "min_age must be 21"),
    (False, {"vibes": '["romance"]'}, "vibes must be"),
    (False, {"kind": "karaoke"}, "kind must be"),
], ids=["under-21-at-bar", "unknown-vibe", "unknown-kind"])
def test_admin_cannot_save_invalid_experience(admin_client, db, licensed, over, error):
    c = _logged_in(admin_client)
    r = c.post("/admin/experience/create", data=_exp_form(_venue_id(db, licensed), **over))
    assert r.status_code == 400 and error in r.text
    db.expire_all()
    assert db.scalar(select(Experience).where(Experience.title == "Late set")) is None


def test_editing_existing_experience_is_validated_too(admin_client, db):
    exp = db.scalar(select(Experience).join(Venue).where(Venue.licensed).limit(1))
    c = _logged_in(admin_client)
    r = c.post(f"/admin/experience/edit/{exp.id}", data=_exp_form(exp.venue_id, title=exp.title, min_age="18"))
    assert r.status_code == 400
    db.expire_all()
    assert db.get(Experience, exp.id).min_age >= 21


def test_cannot_mark_venue_licensed_while_it_has_under_21_experiences(admin_client, db):
    cafe = db.scalar(select(Venue).join(Experience).where(~Venue.licensed, Experience.min_age < 21).limit(1))
    c = _logged_in(admin_client)
    r = c.post(f"/admin/venue/edit/{cafe.id}", data={
        "name": cafe.name, "area": cafe.area, "licensed": "y", "closes_at": cafe.closes_at.strftime("%H:%M"),
        "cpa_rate_inr": str(cafe.cpa_rate_inr), "active": "y"})
    assert r.status_code == 400 and "open to under-21s" in r.text
    db.expire_all()
    assert db.get(Venue, cafe.id).licensed is False


def test_non_ascii_admin_password_is_rejected_not_crashed(admin_client):
    assert _login(admin_client, "pässwörd-ünïcode-123").status_code == 400


# ---- users ----
@pytest.fixture
def user(db):
    u = User(email="guest@example.com", name="Guest", dob=date(2000, 1, 1))
    db.add(u)
    db.commit()
    return u


def test_admin_marks_id_verified_but_cannot_change_identity(admin_client, db, user):
    c = _logged_in(admin_client)
    r = c.post(f"/admin/user/edit/{user.id}", follow_redirects=False,
               data={"id_verified": "y", "dob": "1980-01-01", "email": "hacker@example.com"})
    assert r.status_code == 302, r.text
    db.expire_all()
    u = db.get(User, user.id)
    assert u.id_verified is True
    assert (u.dob, u.email) == (date(2000, 1, 1), "guest@example.com")


def test_admin_cannot_create_or_delete_users(admin_client, user):
    c = _logged_in(admin_client)
    assert c.get("/admin/user/create").status_code in (403, 404)
    assert c.delete(f"/admin/user/delete?pks={user.id}").status_code in (403, 404, 405)
