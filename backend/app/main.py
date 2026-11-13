from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import auth, bookings, drops, models, nights, staff  # noqa: F401  (models registers tables on Base.metadata)
from app.admin import mount_admin
from app.db import Base, engine, get_db

DbDep = Annotated[Session, Depends(get_db)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ponytail: create_all at boot is fine before real data exists; switch to Alembic before the first Neon deploy (plan task 11).
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Random Night API", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(nights.router)
app.include_router(drops.router)
app.include_router(bookings.router)
app.include_router(staff.router)
mount_admin(app)


@app.get("/api/health")
def health(db: DbDep) -> dict[str, bool]:
    db.execute(text("SELECT 1"))  # proves the DB (Neon in prod) is reachable
    return {"ok": True}
