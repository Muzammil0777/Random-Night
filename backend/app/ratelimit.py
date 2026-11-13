"""Fixed-window rate limits stored in the database (task 11a): serverless instances share no memory."""
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import RateHit


def now() -> datetime:
    return datetime.now(timezone.utc)


def client_ip(request: Request) -> str | None:
    """The caller's IP, or None if unknown (then IP limits are skipped rather than lumping everyone together)."""
    # On Vercel the edge sets x-forwarded-for itself (a client can't spoof the first hop); elsewhere use the peer.
    if os.environ.get("VERCEL"):
        return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or None
    return request.client.host if request.client else None


def count(db: Session, key: str, window: timedelta) -> int:
    """Attempts under `key` inside the window. Prunes older ones for that key as it goes."""
    db.execute(delete(RateHit).where(RateHit.key == key, RateHit.at < now() - window))
    return db.scalar(select(func.count(RateHit.id)).where(RateHit.key == key))


def record(db: Session, key: str) -> None:
    db.add(RateHit(key=key, at=now()))
    db.commit()


def prune(db: Session, older_than: timedelta = timedelta(days=1)) -> None:
    """Drop hits nobody will look at again (keys that never come back aren't pruned by count())."""
    db.execute(delete(RateHit).where(RateHit.at < now() - older_than))


def limit(db: Session, key: str, max_hits: int, window: timedelta) -> None:
    """Count this attempt; 429 once `max_hits` attempts fall inside the window."""
    if count(db, key, window) >= max_hits:
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please wait a few minutes.")
    record(db, key)
