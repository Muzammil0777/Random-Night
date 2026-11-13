"""Load founding venues + experiences from CSV. Run: python -m app.seed"""
import csv
from datetime import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KINDS, VIBES, Experience, Venue

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def _bool(s: str) -> bool:
    return s.strip().lower() in ("true", "1", "yes")


def load(db: Session, seed_dir: Path = SEED_DIR) -> tuple[int, int]:
    """Insert seed data once. Returns (venues, experiences) inserted; (0, 0) if venues already exist."""
    if db.scalar(select(Venue.id).limit(1)) is not None:
        return 0, 0

    venues = {}
    with open(seed_dir / "venues.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            v = Venue(
                name=r["name"], area=r["area"], licensed=_bool(r["licensed"]),
                closes_at=time.fromisoformat(r["closes_at"]),
                rating_avg=float(r["rating_avg"]) if r["rating_avg"] else None,
                cpa_rate_inr=int(r["cpa_rate_inr"]), is_partner=_bool(r["is_partner"]),
            )
            venues[v.name] = v
            db.add(v)

    exps = []
    with open(seed_dir / "experiences.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            venue = venues.get(r["venue"])
            if venue is None:
                raise ValueError(f"experience {r['title']!r}: unknown venue {r['venue']!r}")
            vibes = r["vibes"].split("|")
            if r["kind"] not in KINDS or not set(vibes) <= set(VIBES):
                raise ValueError(f"experience {r['title']!r}: bad kind/vibes {r['kind']!r} {vibes}")
            min_age = int(r["min_age"])
            if venue.licensed and min_age < 21:
                # Telangana: under-21s can't enter licensed venues. Fail loudly instead of guessing.
                raise ValueError(f"experience {r['title']!r} at licensed venue needs min_age >= 21")
            exps.append(Experience(
                venue=venue, title=r["title"], kind=r["kind"], vibes=vibes,
                price_per_head_inr=int(r["price_per_head_inr"]),
                duration_min=int(r["duration_min"]), min_age=min_age,
            ))
    db.add_all(exps)
    db.commit()
    return len(venues), len(exps)


if __name__ == "__main__":
    from app.db import Base, SessionLocal, engine

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        print("seeded venues=%d experiences=%d" % load(db))
