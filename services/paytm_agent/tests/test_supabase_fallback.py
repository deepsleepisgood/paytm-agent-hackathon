"""USE_SUPABASE=false, or Supabase unreachable: the service must behave exactly as it does in memory."""
from __future__ import annotations

import logging
import time

import pytest

from app import repository

MID = "PAYTM_MERCH_8821"


@pytest.fixture(autouse=True)
def fresh_repo():
    repository._repo.close()
    repository._repo._down_until = 0.0
    repository._repo._warned_off = False
    yield
    repository._repo.close()
    repository._repo._down_until = 0.0


def utr_body(rid: str) -> dict:
    return {"request_id": rid, "session_id": "s", "mid": MID, "intent": "UTR_VERIFY", "language_code": "hi-IN",
            "merchant_said": "", "payload": {"utr": "632184920111"}, "consent_token": "ct-abc"}


def test_flag_off_means_memory_only(client, monkeypatch):
    monkeypatch.setenv("USE_SUPABASE", "false")
    monkeypatch.setattr(repository._Repo, "_get_pool", lambda self: pytest.fail("touched the database"))
    assert repository.enabled() is False
    r = client.post("/a2a/dispatch", json=utr_body("fb-off"))
    assert r.status_code == 200 and r.json()["status"] == "RESOLVED"


def test_flag_on_without_url_falls_back_with_a_log_line(client, monkeypatch, caplog):
    monkeypatch.setenv("USE_SUPABASE", "true")
    monkeypatch.delenv("PAYTM_DB_URL", raising=False)
    with caplog.at_level(logging.WARNING, logger="paytm_agent.repository"):
        r = client.post("/a2a/dispatch", json=utr_body("fb-nourl"))
    assert r.status_code == 200
    assert "falling back to in-memory state" in caplog.text


def test_unreachable_supabase_falls_back_and_opens_the_breaker(client, monkeypatch, caplog):
    pytest.importorskip("psycopg_pool")
    monkeypatch.setenv("USE_SUPABASE", "true")
    monkeypatch.setenv("PAYTM_DB_URL", "postgresql://paytm_svc:x@127.0.0.1:1/postgres")
    with caplog.at_level(logging.WARNING, logger="paytm_agent.repository"):
        memory_only = client.post("/a2a/dispatch", json=utr_body("fb-down-1"))
    assert memory_only.status_code == 200 and memory_only.json()["status"] == "RESOLVED"
    assert "Supabase unreachable" in caplog.text
    assert repository.enabled() is False            # breaker open: no more waiting on a dead DB

    t0 = time.perf_counter()
    again = client.post("/a2a/dispatch", json=utr_body("fb-down-2"))
    assert again.status_code == 200 and time.perf_counter() - t0 < 0.5

    offer = client.post("/a2a/proactive-alert", json={"mid": MID, "trigger_type": "HIGH_REFUND_CASHFLOW"}).json()
    r = client.post("/a2a/execute-edi-pause", json={"mid": MID, "consent_token": "DPDP_VERIFIED_TS_1763",
                                                    "pause_days": 2,
                                                    "offer_id": offer["data"]["edi_pause_offer"]["offer_id"]})
    assert r.status_code == 200 and r.json()["data"]["loan_edi_status"] == "PAUSED_2_DAYS"
    assert client.post("/ledger/reset").json() == {"ok": True}
