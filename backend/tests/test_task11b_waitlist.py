"""Task 11b: launch waitlist with a referral bump."""
import pytest

from app import ratelimit, waitlist


def _join(client, email, **over):
    return client.post("/api/waitlist", json={"email": email, **over})


def test_join_gives_a_place_and_a_share_code(client):
    first = _join(client, "a@example.com", area="Jubilee Hills").json()
    second = _join(client, "b@example.com").json()
    assert (first["position"], second["position"], second["total"]) == (1, 2, 2)
    assert first["referrals"] == 0 and len(first["ref_code"]) >= 8 and first["ref_code"] != second["ref_code"]


def test_each_referral_moves_you_up(client):
    _join(client, "a@example.com")
    _join(client, "b@example.com")
    c = _join(client, "c@example.com").json()
    assert c["position"] == 3
    _join(client, "friend1@example.com", ref=c["ref_code"])
    status = client.get(f"/api/waitlist/{c['ref_code']}").json()
    assert status["referrals"] == 1 and status["position"] == 1  # one referral beats any number of plain sign-ups


def test_ties_go_to_whoever_joined_first(client):
    a = _join(client, "a@example.com").json()
    b = _join(client, "b@example.com").json()
    _join(client, "x@example.com", ref=a["ref_code"])
    _join(client, "y@example.com", ref=b["ref_code"])
    assert client.get(f"/api/waitlist/{a['ref_code']}").json()["position"] == 1
    assert client.get(f"/api/waitlist/{b['ref_code']}").json()["position"] == 2


def test_joining_again_shows_the_place_but_not_the_share_code(client):
    first = _join(client, "A@Example.com").json()
    again = _join(client, "a@example.com")  # same email, any case
    assert again.status_code == 200 and again.json()["position"] == first["position"]
    assert again.json()["ref_code"] is None  # typing someone's email doesn't hand you their link
    assert again.json()["total"] == 1


def test_unknown_referral_code_is_ignored(client):
    r = _join(client, "a@example.com", ref="nope")
    assert r.status_code == 200 and r.json()["position"] == 1


def test_responses_never_contain_other_peoples_emails(client):
    a = _join(client, "secret.person@example.com").json()
    r = _join(client, "b@example.com", ref=a["ref_code"])
    assert "secret.person" not in r.text
    assert "secret.person" not in client.get(f"/api/waitlist/{a['ref_code']}").text


@pytest.mark.parametrize("body", [{"email": "not-an-email"}, {"email": "a@example.com", "area": "Mars"}])
def test_bad_input_rejected(client, body):
    assert client.post("/api/waitlist", json=body).status_code == 422


def test_unknown_code_is_404(client):
    assert client.get("/api/waitlist/doesnotexist").status_code == 404


def test_joins_are_limited_per_ip(client):
    for i in range(waitlist.MAX_JOINS_PER_IP):
        assert _join(client, f"u{i}@example.com").status_code == 200
    assert _join(client, "one-more@example.com").status_code == 429


def test_unknown_ip_is_not_limited(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "client_ip", lambda request: None)
    for i in range(waitlist.MAX_JOINS_PER_IP + 1):
        assert _join(client, f"u{i}@example.com").status_code == 200
