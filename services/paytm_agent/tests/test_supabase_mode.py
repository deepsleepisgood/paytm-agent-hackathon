"""Supabase mode: the same HTTP API, with every state change mirrored into the `paytm` schema.

    USE_SUPABASE is switched on by this module itself; it only needs the paytm_svc connection:
    PAYTM_DB_URL=postgresql://paytm_svc.<ref>:<pw>@<pooler-host>:6543/postgres python -m pytest tests/test_supabase_mode.py

Skipped when PAYTM_DB_URL is not set. Run supabase/seed/load_seed.py once before.
"""
from __future__ import annotations

import os
import time

import pytest

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.skipif(not os.getenv("PAYTM_DB_URL"), reason="PAYTM_DB_URL not set")

from app import repository, store  # noqa: E402

MID = "PAYTM_MERCH_8821"
EXPIRED = "DPDP_VERIFIED_TS_1794313800"


def fresh_token() -> str:
    return f"DPDP_VERIFIED_TS_{int(time.time())}"


@pytest.fixture(scope="module", autouse=True)
def supabase_on():
    old = os.environ.get("USE_SUPABASE")
    os.environ["USE_SUPABASE"] = "true"
    repository._repo._down_until = 0.0
    yield
    store.reset()
    repository._repo.close()
    if old is None:
        os.environ.pop("USE_SUPABASE", None)
    else:
        os.environ["USE_SUPABASE"] = old


@pytest.fixture()
def db(clean_state):  # clean_state (conftest) has already reset memory *and* the database
    with psycopg.connect(os.environ["PAYTM_DB_URL"], autocommit=True, prepare_threshold=None) as c:
        yield lambda sql, *a: c.execute(sql, a).fetchall()


def body(intent: str, payload: dict | None = None, **over) -> dict:
    return {"request_id": f"sb-{intent}-{time.time_ns()}", "session_id": "sb-sess", "mid": MID,
            "intent": intent, "language_code": "hi-IN", "merchant_said": "", "payload": payload or {},
            "consent_token": fresh_token(), **over}


EIGHT = [
    ("MANDATE_TROUBLESHOOT", {}),
    ("SETTLEMENT_RECONCILE", {}),
    ("CHARGEBACK_RESOLVE", {"txn_id": "9981", "doc": {"doc_type": "pod", "confidence": 0.96,
                                                      "extracted_fields": {"order_id": "9981", "amount_inr": 800}}}),
    ("UTR_VERIFY", {"utr": "632184920111", "claimed_amount_inr": 1250}),
    ("DUPLICATE_RECONCILE", {}),
    ("GROWTH_ADVISORY", {}),
    ("CASHFLOW_EDI_SWITCH", {}),
    ("ESCALATE_HUMAN", {"reason_code": "MERCHANT_REQUESTED_HUMAN", "reason_text": "Merchant asked for a person"}),
]


def test_all_eight_intents_are_mirrored(client, db):
    ids = []
    for intent, payload in EIGHT:
        req = body(intent, payload)
        r = client.post("/a2a/dispatch", json=req)
        assert r.status_code == 200, (intent, r.text)
        ids.append(req["request_id"])

    assert db("select count(*) from paytm.consent_checks where valid and request_id = any(%s)", ids)[0][0] == 8
    assert db("select count(distinct request_id) from paytm.agent_trace where request_id = any(%s)", ids)[0][0] == 8
    assert db("select count(*) from paytm.verified_outcomes where request_id = any(%s)", ids)[0][0] == 8
    assert db("select result::text from paytm.utr_checks where utr = '632184920111'") == [("SUCCESS",)]
    assert db("select status::text from paytm.chargebacks where chargeback_id = 'CB-9981'") == [("RELEASED",)]
    assert db("select amount from paytm.pending_credits") == [(800,)]
    assert db("select value from paytm.demo_counters where name = 'money_recovered_inr'") == [(800,)]
    tickets = db("select ticket_id, diagnostics ->> 'service_ticket_id' from paytm.tickets where not seeded")
    assert len(tickets) == 1 and tickets[0][0] == "TKT-PAYTM-1291" and tickets[0][1]


@pytest.mark.xfail(strict=False, reason="paytm_agent's in-memory seed still uses duplicate order 4455 "
                                        "(UTRs ...5001/...5002); data/paytm uses order 4489. Align app/seed.py.")
def test_duplicate_refund_is_written(client, db):
    r = client.post("/a2a/dispatch", json=body("DUPLICATE_RECONCILE"))
    assert r.json()["data"].get("refund_status") == "PROCESSED"
    assert db("select status::text from paytm.refunds where refund_id = 'RFD-DUP-4489'") == [("PROCESSED",)]


def offer_id(client) -> str:
    out = client.post("/a2a/proactive-alert", json={"mid": MID, "trigger_type": "HIGH_REFUND_CASHFLOW"}).json()
    return out["data"]["edi_pause_offer"]["offer_id"]


def test_edi_pause_is_atomic_in_the_database(client, db):
    r = client.post("/a2a/execute-edi-pause", json={"mid": MID, "consent_token": fresh_token(),
                                                    "pause_days": 2, "offer_id": offer_id(client)})
    assert r.status_code == 200 and r.json()["data"]["loan_edi_status"] == "PAUSED_2_DAYS"
    assert db("select edi_status::text from paytm.loan_book") == [("PAUSED_2_DAYS",)]
    assert db("select count(*) from paytm.lender_approvals")[0][0] == 1
    assert db("select clause from paytm.kfs_consent_artifacts") == [("4.2",)]


def test_expired_consent_is_403_logged_and_changes_nothing(client, db):
    r = client.post("/a2a/execute-edi-pause", json={"mid": MID, "consent_token": EXPIRED,
                                                    "pause_days": 2, "offer_id": offer_id(client)})
    assert r.status_code == 403 and r.json()["error"]["code"] == "DPDP_CONSENT_REQUIRED"
    assert store.ledger.loan.status == "ACTIVE"            # the DB ran first, so memory was not touched
    assert db("select edi_status::text from paytm.loan_book") == [("ACTIVE",)]

    r = client.post("/a2a/dispatch", json=body("UTR_VERIFY", {"utr": "632184920111"}, consent_token=EXPIRED))
    assert r.status_code == 403 and r.json()["error"]["code"] == "DPDP_CONSENT_REQUIRED"
    assert db("select reason::text from paytm.consent_checks order by id") == [("EXPIRED",), ("EXPIRED",)]


def test_ledger_reset_restores_the_database(client, db):
    for intent, payload in EIGHT:
        client.post("/a2a/dispatch", json=body(intent, payload))
    client.post("/a2a/execute-edi-pause", json={"mid": MID, "consent_token": fresh_token(),
                                                "pause_days": 2, "offer_id": offer_id(client)})
    t0 = time.perf_counter()
    assert client.post("/ledger/reset").json() == {"ok": True}
    assert time.perf_counter() - t0 < 2.0

    assert db("select status::text from paytm.chargebacks where chargeback_id = 'CB-9981'") == [("HELD",)]
    assert db("select edi_status::text, outstanding from paytm.loan_book") == [("ACTIVE", 42000)]
    assert db("select sum(value) from paytm.demo_counters")[0][0] == 0
    assert db("""select (select count(*) from paytm.consent_checks) + (select count(*) from paytm.agent_trace)
                 + (select count(*) from paytm.verified_outcomes) + (select count(*) from paytm.lender_approvals)
                 + (select count(*) from paytm.tickets where not seeded)""")[0][0] == 0
