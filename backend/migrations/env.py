"""Alembic env (task 11a). Uses the app's own engine setup, so the URL rules match the app.

Production (Neon): run with the *direct* URL, e.g.
    DATABASE_URL=$DATABASE_URL_UNPOOLED .venv/Scripts/alembic upgrade head
(env.py prefers DATABASE_URL_UNPOOLED automatically when it is set, as `neon env pull` writes it.)
"""
import os
from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.db import Base, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
# Migrations need a direct connection: PgBouncer (the pooled URL) drops session state between statements.
URL = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL", "sqlite:///./randomnight.db")
if "-pooler" in URL:
    raise SystemExit("Run migrations on the direct Neon URL: set DATABASE_URL_UNPOOLED (neon env pull writes it).")


def run_migrations_offline() -> None:
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, render_as_batch=URL.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with make_engine(URL).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=connection.dialect.name == "sqlite", compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
