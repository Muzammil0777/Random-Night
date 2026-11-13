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
    # Every test drops all tables first; never let that point at real data.
    raise RuntimeError("TEST_DATABASE_URL must be a separate Neon branch, not DATABASE_URL")


@pytest.fixture
def db():
    if TEST_URL:
        engine = make_engine(TEST_URL)
        Base.metadata.drop_all(engine)  # clean slate on the reused test branch
    else:
        # StaticPool shares the one in-memory connection across threads.
        engine = make_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)  # not a context manager: skips lifespan, so no dev DB file is touched
    app.dependency_overrides.clear()
