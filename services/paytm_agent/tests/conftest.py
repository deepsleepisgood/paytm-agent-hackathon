"""Shared test fixtures.

Two rules every test in this suite relies on:
  - state is reset between tests, because the service keeps everything in memory and a
    leaked ticket from one test silently changes another test's metrics;
  - time is frozen by default, so deadline arithmetic is exact and nothing sleeps.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import clock, main, store

# The demo's "today". The seed settlement is dated 2026-11-18 and the loan deduction
# 2026-11-19, so tests run at a fixed point on 2026-11-19.
FROZEN_NOW = datetime(2026, 11, 19, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def frozen_clock():
    clock.freeze(FROZEN_NOW)
    yield clock
    clock.unfreeze()


@pytest.fixture(autouse=True)
def clean_state(frozen_clock):
    """Every test starts from a fresh ledger with no summaries, tickets or sessions.

    Ordered after frozen_clock on purpose: the ledger's chargeback deadline is built
    from clock.now(), so it must be created while time is already frozen.
    """
    store.reset()
    yield store


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)
