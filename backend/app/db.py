import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Local dev: `neon env pull` writes DATABASE_URL (pooled) + DATABASE_URL_UNPOOLED to the repo-root .env.local;
# backend/.env holds TEST_DATABASE_URL. On Vercel the vars come from the dashboard and these are no-ops.
_BACKEND = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND.parent / ".env.local")
load_dotenv(_BACKEND / ".env")


def make_engine(url: str, **kwargs):
    # Neon hands out postgres:// or postgresql:// URLs; route them to the psycopg 3 driver.
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
        # Neon's pooled URL goes through PgBouncer (transaction mode): skip server-side prepared statements.
        kwargs.setdefault("connect_args", {"prepare_threshold": None})
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
