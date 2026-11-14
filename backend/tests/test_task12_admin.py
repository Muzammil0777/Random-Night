"""Task 12: always-dark admin, and creating venue door keys from the admin."""
import re

import pytest
from sqlalchemy import select

from app import auth
from app.models import Venue, VenueKey
from tests.test_task3_admin import _logged_in, admin_client  # noqa: F401  (fixture + login helper)

URL = "/admin/venue/action/create-door-key"


def _cafe_id(db):
    return db.scalar(select(Venue.id).where(Venue.name == "Sample Live Music Cafe"))


def test_creating_a_key_needs_admin_login(admin_client, db):
    r = admin_client.get(f"{URL}?pks={_cafe_id(db)}", follow_redirects=False)
    assert r.status_code in (302, 303) and "/admin/login" in r.headers["location"]
    assert db.scalars(select(VenueKey)).all() == []


def test_admin_creates_a_working_door_key_shown_once(admin_client, db):
    r = _logged_in(admin_client).get(f"{URL}?pks={_cafe_id(db)}")
    assert r.status_code == 200 and "Sample Live Music Cafe" in r.text
    assert r.headers["cache-control"] == "no-store"
    key = re.search(r'id="door-key"[^>]*value="([^"]+)"', r.text).group(1)
    row = db.scalar(select(VenueKey))
    assert row.key_hash == auth._hash(key) and key not in (row.label, row.key_hash)  # only the hash is stored
    admin_client.cookies.clear()
    assert admin_client.post("/api/staff/login", json={"key": key}).json()["venue"] == "Sample Live Music Cafe"


@pytest.mark.parametrize("pks,code", [("", 400), ("1,2", 400), ("abc", 400), ("99999", 404)])
def test_create_key_needs_exactly_one_real_venue(admin_client, db, pks, code):
    assert _logged_in(admin_client).get(f"{URL}?pks={pks}").status_code == code
    assert db.scalars(select(VenueKey)).all() == []


def test_admin_is_always_dark(admin_client):
    for page in ("/admin/login", "/admin/"):
        html = _logged_in(admin_client).get(page).text
        assert '<html lang="en" data-bs-theme="dark">' in html
