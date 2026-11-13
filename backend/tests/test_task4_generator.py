"""Task 4: the night generator. Every routing rule that protects guests or money is pinned here."""
from dataclasses import replace
from datetime import datetime, time, timedelta

import pytest

from app.auth import IST
from app.generator import _NEAR, TRAVEL, NightRequest, generate, nearby
from app.models import Experience, Venue

START = datetime(2026, 11, 20, 21, 0, tzinfo=IST)  # Friday 9 PM
REQ = NightRequest(area="Jubilee Hills", budget_inr=2000, start=START, hours=4, vibe="party",
                   youngest_age=25, licensed_ok=True)


def venue(name, area="Jubilee Hills", licensed=False, closes="01:00", rating=4.5, cpa=0, partner=False, active=True):
    return Venue(name=name, area=area, licensed=licensed, closes_at=time.fromisoformat(closes),
                 rating_avg=rating, cpa_rate_inr=cpa, is_partner=partner, active=active)


def exp(v, kind, vibes=("party",), price=400, mins=60, title=None):
    return Experience(venue=v, title=title or f"{v.name} {kind}", kind=kind, vibes=list(vibes),
                      price_per_head_inr=price, duration_min=mins, min_age=21 if v.licensed else 18)


def venues_in(plan):
    return [s.experience.venue.name for s in plan]


@pytest.fixture
def cafe():
    return venue("Cafe")


@pytest.fixture
def bar():
    return venue("Bar", licensed=True)


# ---- basics ----
def test_builds_a_timed_night_in_slot_order(cafe, bar):
    # 4 x 50 min + one 20-min venue change = 220 min, fits the 4 h window
    plan = generate(REQ, [exp(bar, "finale", mins=50), exp(cafe, "meet", mins=50),
                          exp(cafe, "music", mins=50), exp(bar, "challenge", mins=50)])
    assert [s.experience.kind for s in plan] == ["meet", "music", "challenge", "finale"]
    assert plan[0].starts_at == START
    assert all(a.ends_at <= b.starts_at for a, b in zip(plan, plan[1:]))
    assert plan[-1].ends_at <= START + timedelta(hours=4)


def test_adds_travel_time_between_different_venues(cafe, bar):
    plan = generate(REQ, [exp(cafe, "meet"), exp(bar, "music")])
    assert plan[1].starts_at - plan[0].ends_at == TRAVEL


def test_no_valid_night_returns_none_never_a_broken_plan(cafe):
    assert generate(REQ, [exp(cafe, "meet")]) is None   # one stop isn't a night
    assert generate(REQ, []) is None


# ---- age: never route an under-21 to a licensed venue ----
def test_group_that_fails_21_check_never_gets_a_bar(cafe, bar):
    req = replace(REQ, licensed_ok=False, youngest_age=20)
    plan = generate(req, [exp(bar, "meet"), exp(bar, "music"), exp(cafe, "meet"), exp(cafe, "music")])
    assert "Bar" not in venues_in(plan)


def test_bar_excluded_even_if_caller_wrongly_says_licensed_ok(bar):
    # Defence in depth: experience min_age still blocks a 19-year-old.
    assert generate(replace(REQ, youngest_age=19), [exp(bar, "meet"), exp(bar, "music")]) is None


def test_bar_with_mis_entered_min_age_still_blocked_for_under_21(bar):
    e1, e2 = exp(bar, "meet"), exp(bar, "music")
    e1.min_age = e2.min_age = 18  # bad data slipped in
    assert generate(replace(REQ, licensed_ok=False, youngest_age=19), [e1, e2]) is None


# ---- money: fit first, bid second ----
def test_paying_venue_outside_area_is_never_chosen(cafe):
    far = venue("Far Partner", area="Financial District", cpa=10_000, partner=True)
    plan = generate(REQ, [exp(far, "meet"), exp(far, "music"), exp(cafe, "meet"), exp(cafe, "music")])
    assert "Far Partner" not in venues_in(plan)
    assert generate(REQ, [exp(far, "meet"), exp(far, "music")]) is None


def test_paying_venue_with_wrong_vibe_is_never_chosen(cafe):
    quiet = venue("Quiet Partner", cpa=10_000, partner=True)
    plan = generate(REQ, [exp(quiet, "meet", vibes=["chill"]), exp(quiet, "music", vibes=["chill"]),
                          exp(cafe, "meet"), exp(cafe, "music")])
    assert "Quiet Partner" not in venues_in(plan)


def test_low_rated_paying_venue_is_excluded(cafe):
    bad = venue("Bad Partner", rating=3.0, cpa=10_000, partner=True)
    plan = generate(REQ, [exp(bad, "meet"), exp(bad, "music"), exp(cafe, "meet"), exp(cafe, "music")])
    assert "Bad Partner" not in venues_in(plan)
    assert generate(REQ, [exp(bad, "meet"), exp(bad, "music")]) is None  # even as the only option


def test_inactive_venue_is_excluded(cafe):
    off = venue("Paused", active=False, cpa=500, partner=True)
    plan = generate(REQ, [exp(off, "meet"), exp(off, "music"), exp(cafe, "meet"), exp(cafe, "music")])
    assert "Paused" not in venues_in(plan)


def test_higher_bid_wins_between_equal_fit_venues():
    free, paid = venue("Free Cafe"), venue("Paid Cafe", cpa=150, partner=True)
    plan = generate(REQ, [exp(free, "meet"), exp(free, "music"), exp(paid, "meet"), exp(paid, "music")])
    assert venues_in(plan) == ["Paid Cafe", "Paid Cafe"]
    assert all(s.is_partner for s in plan)


def test_bid_cannot_beat_a_clearly_better_fit():
    great = venue("Great Local", rating=4.8)                                   # same area, top rated
    meh = venue("Meh Partner", area="Banjara Hills", rating=3.6, cpa=10_000, partner=True)
    plan = generate(REQ, [exp(meh, "meet"), exp(meh, "music"), exp(great, "meet"), exp(great, "music")])
    assert venues_in(plan) == ["Great Local", "Great Local"]
    assert not any(s.is_partner for s in plan)


def test_neighbouring_area_is_allowed_when_it_is_all_there_is():
    nb = venue("Neighbour", area="Banjara Hills")
    assert venues_in(generate(REQ, [exp(nb, "meet"), exp(nb, "music")])) == ["Neighbour", "Neighbour"]


# ---- time & budget ----
def test_respects_venue_closing_time():
    early = venue("Early Cafe", closes="22:00")
    late = venue("Late Cafe")
    plan = generate(REQ, [exp(early, "meet", mins=90), exp(late, "meet"), exp(late, "music")])
    assert "Early Cafe" not in venues_in(plan)
    assert all(s.ends_at <= datetime(2026, 11, 21, 1, 0, tzinfo=IST) for s in plan)


def test_respects_budget(cafe):
    pricey = venue("Pricey")
    plan = generate(REQ, [exp(pricey, "meet", price=1500), exp(pricey, "music", price=1500),
                          exp(cafe, "meet", price=600), exp(cafe, "music", price=700)])
    assert sum(s.experience.price_per_head_inr for s in plan) <= REQ.budget_inr
    assert "Pricey" not in venues_in(plan)


def test_two_hour_window_is_respected(cafe):
    stops = [exp(cafe, k, mins=50) for k in ("meet", "music", "challenge", "finale")]
    plan = generate(replace(REQ, hours=2), stops)
    assert plan[-1].ends_at <= START + timedelta(hours=2) and len(plan) == 2


def test_all_night_runs_until_closing(cafe):
    stops = [exp(cafe, k, mins=55) for k in ("meet", "music", "challenge", "finale")]
    assert len(generate(replace(REQ, hours=3), stops)) == 3      # 4 x 55 = 220 min doesn't fit in 3 h
    assert len(generate(replace(REQ, hours=None), stops)) == 4   # but does before the 01:00 close


def test_ties_keep_the_meet_your_group_stop(cafe, bar):
    plan = generate(REQ, [exp(bar, "finale"), exp(cafe, "meet"), exp(cafe, "music"), exp(bar, "challenge")])
    assert plan[0].experience.kind == "meet"


# ---- vibes & areas ----
def test_surprise_accepts_any_vibe(cafe):
    plan = generate(replace(REQ, vibe="surprise"), [exp(cafe, "meet", vibes=["chill"]), exp(cafe, "music", vibes=["food"])])
    assert len(plan) == 2


def test_neighbour_map_is_symmetric():
    for area, near in _NEAR.items():
        for other in near:
            assert area in nearby(other), f"{other} -> {area} missing"
