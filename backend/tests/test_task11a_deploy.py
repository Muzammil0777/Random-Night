"""Task 11a: migrations match the models, production refuses weak config, rate limits, security headers."""
import secrets
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from starlette.requests import Request

from app import auth, ratelimit, staff
from app.db import Base, make_engine
from app.main import check_production_env
from app.models import User, UserSession
from app.seed import load
from tests.conftest import TEST_URL

BACKEND = Path(__file__).resolve().parent.parent


# ---- migrations ----
def _migrate_and_diff(url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    engine = make_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    return engine, diff


def test_migrations_build_the_models_schema_sqlite(tmp_path, monkeypatch):
    engine, diff = _migrate_and_diff(f"sqlite:///{tmp_path / 'm.db'}", monkeypatch)
    engine.dispose()
    assert diff == []


@pytest.mark.skipif(not TEST_URL, reason="needs the Neon test branch")
def test_migrations_build_the_models_schema_postgres(pg_engine, monkeypatch):
    Base.metadata.drop_all(pg_engine)
    try:
        engine, diff = _migrate_and_diff(TEST_URL, monkeypatch)
        engine.dispose()
        assert diff == []
    finally:  # hand the session's schema back to the other tests
        Base.metadata.drop_all(pg_engine)
        with pg_engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        Base.metadata.create_all(pg_engine)


# ---- production config ----
GOOD = {"VERCEL": "1", "APP_URL": "https://randomnight.in", "DATABASE_URL": "postgresql://x/y",
        "SECRET_KEY": "s" * 32, "ADMIN_PASSWORD": "a" * 12, "CRON_SECRET": "c" * 16,
        "RESEND_API_KEY": "re_test", "EMAIL_FROM": "Random Night <hi@randomnight.in>"}


def test_production_boots_with_complete_config():
    check_production_env(GOOD)


@pytest.mark.parametrize("override,problem", [
    ({"SECRET_KEY": "short"}, "SECRET_KEY"),
    ({"ADMIN_PASSWORD": ""}, "ADMIN_PASSWORD"),
    ({"CRON_SECRET": "x"}, "CRON_SECRET"),
    ({"RESEND_API_KEY": ""}, "RESEND_API_KEY"),
    ({"DATABASE_URL": "sqlite:///x.db"}, "DATABASE_URL"),
    ({"APP_URL": "http://localhost:5173"}, "APP_URL"),
])
def test_production_refuses_missing_or_weak_config(override, problem):
    with pytest.raises(RuntimeError, match=problem):
        check_production_env({**GOOD, **override})


def test_local_dev_is_not_checked():
    check_production_env({"APP_URL": "http://localhost:5173"})


def test_vercel_previews_are_checked_too():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        check_production_env({**GOOD, "VERCEL_ENV": "preview", "SECRET_KEY": ""})


# ---- rate limits ----
@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(auth, "send_login_email", lambda email, link: sent.append(email))
    return sent


def test_login_links_are_limited_per_ip(client, outbox):
    for i in range(auth.MAX_LINKS_PER_IP):
        assert client.post("/api/auth/request", json={"email": f"u{i}@example.com"}).status_code == 202
    r = client.post("/api/auth/request", json={"email": "one-more@example.com"})
    assert r.status_code == 429 and len(outbox) == auth.MAX_LINKS_PER_IP


def _request(headers=None, host="10.0.0.9"):
    scope = {"type": "http", "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()],
             "client": (host, 1234)}
    return Request(scope)


def test_client_ip_trusts_forwarded_for_only_on_vercel(monkeypatch):
    spoofed = _request({"x-forwarded-for": "1.2.3.4"})
    monkeypatch.delenv("VERCEL", raising=False)
    assert ratelimit.client_ip(spoofed) == "10.0.0.9"  # a client can't pick its own rate-limit bucket
    monkeypatch.setenv("VERCEL", "1")
    assert ratelimit.client_ip(_request({"x-forwarded-for": "1.2.3.4, 10.1.1.1"})) == "1.2.3.4"


def test_old_hits_age_out(db):
    for _ in range(3):
        ratelimit.record(db, "k")
    assert ratelimit.count(db, "k", timedelta(minutes=5)) == 3
    assert ratelimit.count(db, "k", timedelta(seconds=-1)) == 0  # everything is older than "the future"


def test_wrong_door_codes_lock_the_key(client, db, monkeypatch):
    load(db)
    night = auth.today_ist() + timedelta(days=3)
    monkeypatch.setattr(staff, "tonight", lambda: night)
    monkeypatch.setattr(staff, "now", lambda: datetime.combine(night, time(21, 30), auth.IST))
    u = User(email="g@example.com", name="Guest X", dob=date(1995, 1, 1), id_verified=True)
    db.add(u)
    db.flush()
    token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=auth._hash(token), user_id=u.id, expires_at=auth.now() + timedelta(days=1)))
    db.commit()
    client.cookies.set(auth.COOKIE, token)
    code = client.post("/api/plans", json={"area": "Jubilee Hills", "budget_inr": 2000, "hours": 4, "vibe": "chill",
                                           "company": "solo", "date": night.isoformat()}).json()["stops"][0]["code"]
    key = staff.create_key(db, "Sample Live Music Cafe", "Door")
    client.cookies.clear()
    client.post("/api/staff/login", json={"key": key})
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(staff.MAX_WRONG_CODES):
        assert client.post("/api/staff/checkin", json={"code": wrong}).status_code == 404
    assert client.post("/api/staff/checkin", json={"code": code}).status_code == 429  # locked, even for a real code


# ---- headers ----
def test_security_headers(client):
    h = client.get("/api/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"


def test_unknown_ip_is_not_limited(client, outbox, monkeypatch):
    monkeypatch.setattr(ratelimit, "client_ip", lambda request: None)
    for i in range(auth.MAX_LINKS_PER_IP + 1):  # nobody shares an "unknown" bucket
        assert client.post("/api/auth/request", json={"email": f"x{i}@example.com"}).status_code == 202


def test_prune_drops_old_hits(db, monkeypatch):
    ratelimit.record(db, "old")
    monkeypatch.setattr(ratelimit, "now", lambda: auth.now() + timedelta(days=2))
    ratelimit.prune(db)
    db.commit()
    assert db.scalar(text("SELECT count(*) FROM rate_hits")) == 0
