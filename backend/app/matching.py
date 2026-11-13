"""Random Friday (task 6): bucket the week's sign-ups into groups of 4–6, each with one shared night."""
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import IST, age_on, can_enter_licensed, now
from app.bookings import get_night, has_night, save_plan
from app.generator import NightRequest, generate
from app.models import DropEntry, Experience, Group, GroupMember, User, Venue
from app.nights import NIGHT_STARTS

MIN_GROUP, MAX_GROUP = 4, 6
DROP_HOURS = 4  # every Random Friday runs 9 PM to 1 AM
WOMEN = {"woman", "female", "f"}  # gender is free, self-declared text in the profile


def is_woman(user: User) -> bool:
    return (user.gender or "").strip().lower() in WOMEN


def group_sizes(n: int) -> list[int]:
    """Split n people into groups of 4–6, as even as possible. 1–3 people can't form a group,
    and 7 can't be split into 4–6s, so the last one to join waits."""
    if n < MIN_GROUP:
        return []
    if n == 7:
        return [6]
    k = -(-n // MAX_GROUP)  # fewest groups; every n >= 8 then gives sizes of at least 4
    return [n // k + (i < n % k) for i in range(k)]


def match(db: Session, night_date: date) -> dict[str, int]:
    """Match every unmatched sign-up for night_date. Safe to rerun: leftovers are retried with newcomers."""
    # shortcut: no row locking, so two runs at once (or a leave mid-run) could misfire; the cron runs once a week
    # after joins close. Add .with_for_update() on entries if runs ever overlap.
    entries = db.scalars(select(DropEntry).where(DropEntry.date == night_date, DropEntry.group_id.is_(None))
                         .order_by(DropEntry.created_at, DropEntry.id).options(joinedload(DropEntry.user))).all()
    buckets: dict[tuple, list[DropEntry]] = defaultdict(list)
    for e in entries:
        if e.women_only and not is_woman(e.user):
            continue  # profile changed after joining: never put them in a women-only group
        if has_night(db, e.user, night_date):
            continue  # already booked another night for that date
        # 21+ verified and everyone else never share a group, so nobody under 21 is in a licensed-night group.
        buckets[(e.area, e.vibe, e.budget_inr, e.women_only, can_enter_licensed(e.user, night_date))].append(e)

    experiences = list(db.scalars(select(Experience).join(Venue).where(Venue.active)
                                  .options(joinedload(Experience.venue))))
    start = datetime.combine(night_date, NIGHT_STARTS, IST)
    groups = matched = 0
    for (area, vibe, budget, women_only, licensed_ok), people in buckets.items():
        taken = 0
        for size in group_sizes(len(people)):
            members, taken = people[taken:taken + size], taken + size
            stops = generate(NightRequest(
                area=area, budget_inr=budget, start=start, hours=DROP_HOURS, vibe=vibe, licensed_ok=licensed_ok,
                youngest_age=min(age_on(m.user.dob, night_date) for m in members)), experiences)
            if stops is None:
                continue  # no night fits these picks; they stay unmatched
            night = get_night(db, night_date, area)
            group = Group(night_id=night.id)
            db.add(group)
            db.flush()
            db.add_all(GroupMember(group_id=group.id, user_id=m.user_id) for m in members)
            save_plan(db, night, stops, [m.user_id for m in members], {
                "area": area, "vibe": vibe, "budget_inr": budget, "hours": DROP_HOURS, "company": "new_people",
                "date": night_date.isoformat(), "women_only": women_only, "licensed_ok": licensed_ok},
                group_id=group.id)
            for m in members:
                m.group_id = group.id
            groups, matched = groups + 1, matched + size
    for e in entries:
        e.tried_at = now()
    db.commit()
    return {"groups": groups, "matched": matched, "waiting": len(entries) - matched}
