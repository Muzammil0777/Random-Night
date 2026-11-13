"""Task 6: Random Friday sign-ups, group matching (4–6, age-safe, women-only) and leftovers."""
import secrets
from collections import Counter
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app import auth
from app.drops import upcoming_friday
from app.matching import group_sizes, match
from app.models import DropEntry, GroupMember, Night, Plan, PlanStop, User, UserSession
from app.seed import load


def _friday():
    """A Friday whose joins are still open (closes 11 PM the Thursday before), whatever day the suite runs."""
    f = upcoming_friday(auth.today_ist())
    return f if (f - auth.today_ist()).days >= 2 else f + timedelta(days=7)


FRI = _friday()
ADULT, YOUNG = date(1995, 1, 1), FRI.replace(year=FRI.year - 19)  # YOUNG is 19 on the night


@pytest.fixture
def seeded(db):
    load(db)
    return db


def _user(db, dob=ADULT, verified=True, gender=None, name="Asha Rao"):
    u = User(email=f"{secrets.token_hex(4)}@example.com", name=name, dob=dob, id_verified=verified, gender=gender)
    db.add(u)
    db.flush()
    return u


def _join(db, n, **over):
    picks = {"area": "Jubilee Hills", "vibe": "chill", "budget_inr": 2000, "women_only": False}
    user_kw = {k: over.pop(k) for k in ("dob", "verified", "gender") if k in over}
    users = [_user(db, **user_kw) for _ in range(n)]
    db.add_all(DropEntry(user_id=u.id, date=FRI, **{**picks, **over}) for u in users)
    db.commit()
    return users


def _groups(db):
    """{group_id: [User, ...]} for every formed group."""
    out: dict[int, list[User]] = {}
    for gm in db.scalars(select(GroupMember)):
        out.setdefault(gm.group_id, []).append(db.get(User, gm.user_id))
    return out


def _login(client, db, **kw):
    u = _user(db, **kw)
    token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=auth._hash(token), user_id=u.id, expires_at=auth.now() + timedelta(days=1)))
    db.commit()
    client.cookies.set(auth.COOKIE, token)
    return u


# ---- group sizes ----
@pytest.mark.parametrize("n", range(0, 41))
def test_group_sizes_are_4_to_6_and_place_everyone_possible(n):
    sizes = group_sizes(n)
    assert all(4 <= s <= 6 for s in sizes)
    expected = 0 if n < 4 else 6 if n == 7 else n  # 7 can't split into 4–6s, so one waits
    assert sum(sizes) == expected
    assert not sizes or max(sizes) - min(sizes) <= 1  # as even as possible


# ---- matching job ----
def test_thirteen_people_form_three_groups_with_one_shared_night(seeded):
    _join(seeded, 13)
    assert match(seeded, FRI) == {"groups": 3, "matched": 13, "waiting": 0}
    groups = _groups(seeded)
    assert sorted(len(m) for m in groups.values()) == [4, 4, 5]
    assert len(seeded.scalars(select(Night)).all()) == 1  # one Night per date + area
    for gid in groups:
        plan = seeded.scalar(select(Plan).where(Plan.group_id == gid))
        stops = seeded.scalars(select(PlanStop).where(PlanStop.plan_id == plan.id)).all()
        assert len(stops) >= 2 and all(len(s.code) == 6 for s in stops)


def test_no_under_21_in_a_licensed_night_group(seeded):
    _join(seeded, 4, vibe="surprise")                    # 21+ and ID-checked
    _join(seeded, 4, vibe="surprise", dob=YOUNG)          # 19 on the night
    _join(seeded, 4, vibe="surprise", verified=False)     # 21+ but no ID check yet
    assert match(seeded, FRI)["groups"] == 3
    licensed_nights = 0
    for gid, members in _groups(seeded).items():
        plan = seeded.scalar(select(Plan).where(Plan.group_id == gid))
        stops = seeded.scalars(select(PlanStop).where(PlanStop.plan_id == plan.id)).all()
        if any(s.experience.venue.licensed for s in stops):
            licensed_nights += 1
            assert all(auth.can_enter_licensed(m, FRI) for m in members)
        assert len({auth.can_enter_licensed(m, FRI) for m in members}) == 1  # never mixed
    assert licensed_nights >= 1  # the rule was actually exercised


def test_different_picks_never_share_a_group(seeded):
    _join(seeded, 4, budget_inr=1000)
    _join(seeded, 4, budget_inr=2000)
    _join(seeded, 4, vibe="food", area="Financial District")
    assert match(seeded, FRI)["groups"] == 3
    for members in _groups(seeded).values():
        picks = {(e.area, e.vibe, e.budget_inr) for e in seeded.scalars(
            select(DropEntry).where(DropEntry.user_id.in_([m.id for m in members])))}
        assert len(picks) == 1


def test_women_only_groups_contain_only_women_only_signups(seeded):
    women = _join(seeded, 4, gender="woman", women_only=True)
    _join(seeded, 4, gender="woman")  # mixed group is fine for them
    _join(seeded, 4)
    assert match(seeded, FRI)["groups"] == 3  # 4 women-only + 8 mixed (4+4)
    women_ids = {u.id for u in women}
    for members in _groups(seeded).values():
        ids = {m.id for m in members}
        assert ids <= women_ids or not ids & women_ids


def test_leftovers_wait_and_are_retried_on_the_next_run(seeded):
    users = _join(seeded, 3)
    assert match(seeded, FRI) == {"groups": 0, "matched": 0, "waiting": 3}
    entries = seeded.scalars(select(DropEntry)).all()
    assert all(e.group_id is None and e.tried_at is not None for e in entries)
    _join(seeded, 1)
    assert match(seeded, FRI) == {"groups": 1, "matched": 4, "waiting": 0}
    assert {m.id for m in next(iter(_groups(seeded).values()))} >= {u.id for u in users}


def test_seven_people_one_waits_the_last_to_join(seeded):
    users = _join(seeded, 7)
    assert match(seeded, FRI) == {"groups": 1, "matched": 6, "waiting": 1}
    waiting = seeded.scalars(select(DropEntry).where(DropEntry.group_id.is_(None))).one()
    assert waiting.user_id == users[-1].id


def test_no_fitting_night_leaves_people_unmatched(seeded):
    _join(seeded, 4, vibe="party", dob=YOUNG)  # every party stop in the seed is at a bar
    assert match(seeded, FRI) == {"groups": 0, "matched": 0, "waiting": 4}


def test_rerun_does_not_rematch_people_already_in_a_group(seeded):
    _join(seeded, 4)
    match(seeded, FRI)
    assert match(seeded, FRI) == {"groups": 0, "matched": 0, "waiting": 0}
    assert Counter(gm.user_id for gm in seeded.scalars(select(GroupMember))).most_common(1)[0][1] == 1


# ---- API ----
def _body(**over):
    return {"date": FRI.isoformat(), "area": "Jubilee Hills", "vibe": "chill", "budget_inr": 2000, **over}


def test_join_requires_login(client, seeded):
    assert client.post("/api/drops", json=_body()).status_code == 401


@pytest.mark.parametrize("over", [
    {"date": (FRI + timedelta(days=1)).isoformat()},   # a Saturday
    {"date": (FRI - timedelta(days=7)).isoformat()},   # this week's Friday is closed (or past)
    {"date": (FRI + timedelta(days=35)).isoformat()},  # too far ahead
    {"budget_inr": 1500},                              # not a tier
    {"area": "Mars"},
])
def test_join_rejects_bad_picks(client, seeded, over):
    _login(client, seeded)
    assert client.post("/api/drops", json=_body(**over)).status_code == 422


def test_women_only_rechecked_at_match_time(seeded):
    women = _join(seeded, 4, gender="woman", women_only=True)
    women[0].gender = "man"  # profile edited after joining
    seeded.commit()
    assert match(seeded, FRI) == {"groups": 0, "matched": 0, "waiting": 4}


def test_joins_close_thursday_11pm_ist(client, seeded, monkeypatch):
    _login(client, seeded)
    thursday_close = datetime.combine(FRI - timedelta(days=1), time(23, 0), auth.IST)
    monkeypatch.setattr("app.drops.now", lambda: thursday_close - timedelta(minutes=1))
    assert client.post("/api/drops", json=_body()).status_code == 201
    client.delete(f"/api/drops/{FRI}")
    monkeypatch.setattr("app.drops.now", lambda: thursday_close)
    assert client.post("/api/drops", json=_body()).status_code == 422


def test_women_only_needs_a_woman_profile(client, seeded):
    _login(client, seeded, gender="man")
    assert client.post("/api/drops", json=_body(women_only=True)).status_code == 422
    _login(client, seeded, gender="Woman")
    assert client.post("/api/drops", json=_body(women_only=True)).status_code == 201


def test_join_status_match_and_leave_flow(client, seeded):
    me = _login(client, seeded, name="Ravi Kumar")
    r = client.post("/api/drops", json=_body())
    assert r.status_code == 201 and r.json()["status"] == "waiting"
    assert client.post("/api/drops", json=_body()).status_code == 409  # once per Friday
    assert client.delete(f"/api/drops/{FRI}").status_code == 204      # can leave before matching
    assert client.get(f"/api/drops/{FRI}").status_code == 404
    client.post("/api/drops", json=_body())
    _join(seeded, 3)
    match(seeded, FRI)
    body = client.get(f"/api/drops/{FRI}").json()
    assert body["status"] == "matched" and len(body["group"]) == 4 and "Ravi" in body["group"]
    assert "Kumar" not in body["group"]  # strangers see first names only
    assert len(body["night"]["stops"]) >= 2 and body["night"]["bars_unlocked"] is True
    assert client.delete(f"/api/drops/{FRI}").status_code == 409  # group formed: can't silently drop out
    assert me.id in {m.id for g in _groups(seeded).values() for m in g}


def test_status_says_unmatched_after_a_run_without_a_group(client, seeded):
    _login(client, seeded)
    client.post("/api/drops", json=_body())
    match(seeded, FRI)
    assert client.get(f"/api/drops/{FRI}").json() == {
        "date": FRI.isoformat(), "area": "Jubilee Hills", "vibe": "chill", "budget_inr": 2000,
        "status": "unmatched", "group": None, "night": None}


def test_match_job_needs_the_cron_secret(client, seeded, monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert client.get("/api/jobs/match").status_code == 401  # unset secret: nobody can trigger it
    monkeypatch.setenv("CRON_SECRET", "s" * 24)
    assert client.get("/api/jobs/match", headers={"Authorization": "Bearer wrong"}).status_code == 401
    _join(seeded, 4)
    r = client.get(f"/api/jobs/match?night_date={FRI}", headers={"Authorization": f"Bearer {'s' * 24}"})
    assert r.status_code == 200 and r.json() == {"groups": 1, "matched": 4, "waiting": 0}
