import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db import Base, get_db, make_engine
from app.main import app

# Default: in-memory SQLite. Set TEST_DATABASE_URL to a Neon *test branch* to run the same suite on Postgres.
TEST_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_URL and TEST_URL == os.environ.get("DATABASE_URL"):
    # Each run drops all tables and each test truncates them; never let that point at real data.
    raise RuntimeError("TEST_DATABASE_URL must be a separate Neon branch, not DATABASE_URL")


@pytest.fixture(scope="session")
def pg_engine():
    # Rebuild the schema once per run (picks up model changes), then each test only empties the tables.
    engine = make_engine(TEST_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(request):
    if TEST_URL:
        engine = request.getfixturevalue("pg_engine")
        quote = engine.dialect.identifier_preparer.quote
        tables = ", ".join(quote(t.name) for t in Base.metadata.sorted_tables)
        with engine.begin() as conn:  # clean slate: one round trip instead of drop/create per test
            conn.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    else:
        # StaticPool shares the one in-memory connection across threads.
        engine = make_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    if not TEST_URL:
        engine.dispose()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)  # not a context manager: skips lifespan, so no dev DB file is touched
    app.dependency_overrides.clear()
