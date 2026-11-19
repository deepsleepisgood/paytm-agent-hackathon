"""Stage 0 — the service starts, answers /health, serves the console, and keeps the
frozen decision constants in exactly one place."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import clock, config


def test_health_matches_contract(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "paytm_agent"}


def test_console_is_served_as_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


def test_decision_constants_match_the_contract():
    # If any of these drift, the demo, the tests and the pitch stop agreeing.
    assert config.AUTO_DOC_CONFIDENCE == 0.90
    assert config.REFUND_AUTO_LIMIT_INR == 2000
    assert config.URGENT_HOURS == 12
    assert config.UNKNOWN_UTR_LIMIT == 3


def test_clock_can_be_frozen_so_deadline_maths_is_exact(frozen_clock):
    from tests.conftest import FROZEN_NOW

    assert clock.now() == FROZEN_NOW

    # A deadline six hours out must read as exactly six hours left, not 5.999.
    deadline = clock.plus_hours(6)
    assert clock.hours_until(deadline.isoformat()) == 6.0

    # A deadline in the past reads negative, which is what "has it passed?" will test.
    past = (FROZEN_NOW - timedelta(hours=2)).isoformat()
    assert clock.hours_until(past) == -2.0


def test_clock_is_timezone_aware():
    # Naive datetimes compared against stored ISO strings are a silent source of
    # off-by-hours bugs, so the clock must always be UTC-aware.
    assert clock.now().tzinfo is not None
    assert clock.now().utcoffset() == timedelta(0)


def test_cors_origins_come_from_env_not_hardcoded(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://console.example.com, https://two.example.com")
    s = config.Settings()
    assert s.cors_origins == ("https://console.example.com", "https://two.example.com")


def test_cors_falls_back_to_person1_env_name(monkeypatch):
    # Person 1's service uses CORS_ORIGINS. Accepting both means neither of us has to
    # rename anything mid-hackathon.
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("CORS_ORIGINS", "https://only.example.com")
    assert config.Settings().cors_origins == ("https://only.example.com",)


def test_port_comes_from_env(monkeypatch):
    monkeypatch.setenv("PORT", "9002")
    assert config.Settings().port == 9002
