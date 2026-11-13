import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import auth, billing, bookings, drops, feedback, models, nights, staff  # noqa: F401  (models registers tables on Base.metadata)
from app.admin import mount_admin
from app.db import Base, engine, get_db

DbDep = Annotated[Session, Depends(get_db)]


def check_production_env(env=os.environ) -> None:
    """In production (Vercel prod or an https APP_URL), refuse to start with missing or weak settings."""
    # Every Vercel deployment (previews too) may point at real data, so all of them are checked.
    if not env.get("VERCEL") and not env.get("APP_URL", "").startswith("https://"):
        return
    problems = []
    if not env.get("APP_URL", "").startswith("https://"):
        problems.append("APP_URL must be the https site address")
    if env.get("DATABASE_URL", "sqlite").startswith("sqlite"):
        problems.append("DATABASE_URL must be the Neon (Postgres) URL")
    for name, minimum in (("SECRET_KEY", 32), ("ADMIN_PASSWORD", 12), ("CRON_SECRET", 16)):
        if len(env.get(name, "")) < minimum:
            problems.append(f"{name} needs {minimum}+ characters")
    for name in ("RESEND_API_KEY", "EMAIL_FROM"):
        if not env.get(name):
            problems.append(f"{name} is missing")
    if problems:
        raise RuntimeError("Refusing to start in production: " + "; ".join(problems))


check_production_env()
HTTPS = os.environ.get("APP_URL", "").startswith("https://")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)  # local dev only; Postgres schema comes from `alembic upgrade head`
    yield


# No interactive API docs on the live site.
app = FastAPI(title="Random Night API", lifespan=lifespan,
              docs_url=None if HTTPS else "/docs", redoc_url=None, openapi_url=None if HTTPS else "/openapi.json")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if HTTPS:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
app.include_router(auth.router)
app.include_router(nights.router)
app.include_router(drops.router)
app.include_router(bookings.router)
app.include_router(staff.router)
app.include_router(billing.router)
app.include_router(feedback.router)
mount_admin(app)


@app.get("/api/health")
def health(db: DbDep) -> dict[str, bool]:
    db.execute(text("SELECT 1"))  # proves the DB (Neon in prod) is reachable
    return {"ok": True}
