import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Local dev reads backend/.env; on Vercel the env vars are set in the dashboard and this is a no-op.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def make_engine(url: str, **kwargs):
    # Neon hands out postgres:// or postgresql:// URLs; route them to the psycopg 3 driver.
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    if url.startswith("sqlite"):
        kwargs.setdefault("connect_args", {"check_same_thread": False})
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    if url.startswith("sqlite"):
        # SQLite ignores foreign keys unless asked; keep dev/test behaviour aligned with Postgres.
        event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    return engine


engine = make_engine(os.environ.get("DATABASE_URL", "sqlite:///./randomnight.db"))
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    # Named constraints keep future Alembic migrations deterministic.
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


def get_db():
    with SessionLocal() as db:
        yield db
