"""Supabase mode for merchant_agent: memory and the `merchant` schema must tell the same story.

    MERCHANT_DB_URL=postgresql://merchant_svc.<ref>:<pw>@<pooler-host>:6543/postgres python -m pytest test_supabase_mode.py

Skipped when MERCHANT_DB_URL is unset. Plus a fallback test that always runs.
"""
from __future__ import annotations

import json
import logging
import os

import pytest

import repository
from conftest import MID, REAL_DATASET, ask, use_dataset
from state import STATE

HAS_DB = bool(os.getenv("MERCHANT_DB_URL"))


@pytest.fixture()
def supabase_on(monkeypatch):
    monkeypatch.setenv("USE_SUPABASE", "true")
    repository._repo._down_until = 0.0
    yield
    repository.flush()


def scenario_phrases() -> list[tuple[str, str]]:
    path = REAL_DATASET / "seed" / "scenarios.json"
    if not path.exists():
        pytest.skip("data/seed/scenarios.json not found")
    return [(s["intent"], s["trigger_hinglish"]) for s in json.loads(path.read_text())["scenarios"]]


@pytest.mark.skipif(not HAS_DB, reason="MERCHANT_DB_URL not set")
def test_eight_scenarios_are_mirrored_then_reset(client, supabase_on):
    psycopg = pytest.importorskip("psycopg")
    use_dataset(REAL_DATASET)
    assert client.post("/reset").status_code == 200

    phrases = scenario_phrases()
    assert len(phrases) == 8
    for intent, text in phrases:
        assert ask(client, text).status_code == 200, intent
    repository.flush()

    with psycopg.connect(os.environ["MERCHANT_DB_URL"], autocommit=True, prepare_threshold=None) as c:
        q = lambda sql: c.execute(sql).fetchall()  # noqa: E731
        db_events = [r[0] for r in q("select type from merchant.a2a_events order by seq")]
        assert db_events == [e["type"] for e in STATE.a2a_events]
        assert {r[0] for r in q("select session_id from merchant.a2a_events")} == {STATE.session_id}
        assert q("select count(*) from merchant.gst_itc_log")[0][0] == len(STATE.local_gst_itc_log)
        assert q("select count(*) from merchant.strategy_memory where not seeded")[0][0] == len(STATE.strategy_memory)
        assert q("select count(*) from merchant.fraud_alerts")[0][0] == len(STATE.fraud_alerts)
        assert q("select value from merchant.agent_state where key = 'loan_edi_status'") == [(STATE.loan_edi_status,)]

        assert client.post("/reset").status_code == 200
        assert q("select count(*) from merchant.a2a_events")[0][0] == 0
        assert q("select count(*) from merchant.strategy_memory where not seeded")[0][0] == 0
        assert q("select value from merchant.agent_state where key = 'loan_edi_status'") == [("ACTIVE",)]
        assert q("select count(*) from merchant.strategy_memory where seeded")[0][0] == 8


@pytest.mark.skipif(not HAS_DB, reason="MERCHANT_DB_URL not set")
def test_merchant_role_cannot_read_paytm_tables():
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(os.environ["MERCHANT_DB_URL"], autocommit=True, prepare_threshold=None) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select 1 from paytm.chargebacks limit 1")


def test_unreachable_supabase_falls_back_to_memory(client, monkeypatch, caplog):
    pytest.importorskip("psycopg_pool")
    repository._repo.close()
    monkeypatch.setenv("USE_SUPABASE", "true")
    monkeypatch.setenv("MERCHANT_DB_URL", "postgresql://merchant_svc:x@127.0.0.1:1/postgres")
    repository._repo._down_until = 0.0
    try:
        with caplog.at_level(logging.WARNING, logger="merchant_agent.repository"):
            r = ask(client, "UTR 632184920111 ka payment aaya kya?")
            repository.flush()
        assert r.status_code == 200 and STATE.a2a_events
        assert "Supabase unreachable" in caplog.text
        assert repository.enabled() is False
        assert client.post("/reset").status_code == 200       # does not hang on the dead database
    finally:
        repository._repo.close()
        repository._repo._down_until = 0.0
