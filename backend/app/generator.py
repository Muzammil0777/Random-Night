"""Night generator (task 4). Pure function: no DB, no I/O. Fit first, bid second.

Hard filter -> every candidate already fits the guest (area, vibe, age, budget, rating floor, active).
Scoring    -> each stop's fit is rounded into FIT_BAND bands; a venue's per-guest rate only breaks ties
              between plans in the same band, so paying can never beat a clearly better match.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from itertools import product

from app.models import Experience

RATING_FLOOR = 3.5
UNRATED = 4.0                 # new venues aren't punished for having no ratings yet
FIT_BAND = 0.5                # the "cap" on paid influence: bids only reorder plans whose fit is in the same band
TRAVEL = timedelta(minutes=20)  # between two different venues
SURPRISE = "surprise"
SLOTS = (("meet",), ("music", "food"), ("challenge",), ("finale", "food"))  # meet -> main -> challenge -> finale

# Hyderabad areas close enough to hop between in one night. Must stay symmetric (tested).
_NEAR = {
    "Jubilee Hills": {"Banjara Hills", "HITEC City"},
    "Banjara Hills": {"Jubilee Hills"},
    "HITEC City": {"Gachibowli", "Jubilee Hills", "Madhapur"},
    "Madhapur": {"HITEC City", "Gachibowli"},
    "Gachibowli": {"HITEC City", "Financial District", "Madhapur"},
    "Financial District": {"Gachibowli"},
}
AREAS = sorted(_NEAR)


def nearby(area: str) -> set[str]:
    return {area} | _NEAR.get(area, set())


@dataclass(frozen=True)
class NightRequest:
    area: str
    budget_inr: int          # max total spend per head across all stops
    start: datetime          # timezone-aware, e.g. Friday 21:00 IST
    hours: int | None        # None = all night (until venues close)
    vibe: str                # party | food | chill | surprise
    youngest_age: int        # youngest person in the group, on the night
    licensed_ok: bool        # every member passes auth.can_enter_licensed() for this night


@dataclass(frozen=True)
class Stop:
    experience: Experience
    starts_at: datetime
    ends_at: datetime
    is_partner: bool         # drives the "Partner venue" label (CCPA/ASCI disclosure)


def _eligible(e: Experience, req: NightRequest) -> bool:
    v = e.venue
    return (v.active
            and v.area in nearby(req.area)
            and (v.rating_avg is None or v.rating_avg >= RATING_FLOOR)
            and (req.vibe == SURPRISE or req.vibe in e.vibes)
            and e.min_age <= req.youngest_age
            and (req.licensed_ok or not v.licensed)  # 21+ rule, independent of how min_age was entered
            and e.price_per_head_inr <= req.budget_inr)


def _fit(e: Experience, req: NightRequest) -> float:
    v = e.venue
    return ((1.0 if v.area == req.area else 0.0)
            + (v.rating_avg if v.rating_avg is not None else UNRATED) / 5
            + (0.5 if req.vibe == SURPRISE and SURPRISE in e.vibes else 0.0))


def _bid(e: Experience) -> int:
    return e.venue.cpa_rate_inr if e.venue.is_partner else 0


def _closing(e: Experience, start: datetime) -> datetime:
    closes = datetime.combine(start.date(), e.venue.closes_at, start.tzinfo)
    return closes + timedelta(days=1) if e.venue.closes_at < time(12) else closes  # 01:00 = after midnight


def _schedule(picked: list[Experience], start: datetime, window_end: datetime | None) -> list[Stop] | None:
    stops, t, prev = [], start, None
    for e in picked:
        if prev is not None and e.venue.name != prev.venue.name:
            t += TRAVEL
        end = t + timedelta(minutes=e.duration_min)
        if end > _closing(e, start) or (window_end is not None and end > window_end):
            return None
        stops.append(Stop(e, t, end, e.venue.is_partner))
        t, prev = end, e
    return stops


def generate(req: NightRequest, experiences: list[Experience]) -> list[Stop] | None:
    """Best night for the request, or None if no valid night of 2+ stops exists (never a broken plan)."""
    pool = [e for e in experiences if _eligible(e, req)]
    # "skip this slot" (None) goes last, so among equal plans the one keeping earlier slots (e.g. meet) wins.
    options = [[e for e in pool if e.kind in kinds] + [None] for kinds in SLOTS]
    window_end = req.start + timedelta(hours=req.hours) if req.hours else None
    best, best_key = None, None
    # ponytail: exhaustive search over slot combos is instant for a pilot catalogue (~20 experiences);
    # prune each slot to its top-N by fit if the catalogue grows into the hundreds.
    for combo in product(*options):
        picked = [e for e in combo if e is not None]
        if len(picked) < 2 or len({id(e) for e in picked}) < len(picked):
            continue
        if sum(e.price_per_head_inr for e in picked) > req.budget_inr:
            continue
        stops = _schedule(picked, req.start, window_end)
        if stops is None:
            continue
        fits = [_fit(e, req) for e in picked]
        key = (sum(round(f / FIT_BAND) for f in fits),  # 1. fit band (more/better stops win)
               sum(_bid(e) for e in picked),            # 2. paid rate, only within the same band
               sum(fits))                               # 3. exact fit
        if best_key is None or key > best_key:          # strict ">" keeps the first of equal plans: deterministic
            best, best_key = stops, key
    return best
