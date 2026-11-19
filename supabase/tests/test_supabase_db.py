"""Database-level tests for the Supabase schema (run after supabase/seed/load_seed.py).

    SUPABASE_DB_URL=<owner connection string> python -m pytest supabase/tests -q

Every agent call runs under the role the service uses in production (`paytm_svc` / `merchant_svc`),
so these tests also prove the merchant <-> Paytm boundary. Skipped when SUPABASE_DB_URL is unset.
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.types.json import Jsonb  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "seed"))
from load_seed import verify  # noqa: E402

DB_URL = os.getenv("SUPABASE_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="SUPABASE_DB_URL not set")

MID = "PAYTM_MERCH_8821"
VALID = "DPDP_VERIFIED_TS_1795058100"
EXPIRED = "DPDP_VERIFIED_TS_1794313800"

# Rows whose content must be byte-identical after /reset (volatile columns excluded).
FINGERPRINT_TABLES = {
    "paytm.refunds": "", "paytm.chargebacks": "- 'paytm_evidence_due'", "paytm.loan_book": "",
    "paytm.enach_mandates": "", "paytm.tickets": "", "paytm.fraud_signals": "", "paytm.edi_collections": "",
    "paytm.dpdp_consents": "", "paytm.shiprocket_pods": "", "paytm.chargeback_status_history": "- 'id'",
    "paytm.demo_counters": "", "merchant.khata": "", "merchant.strategy_memory": "",
    "merchant.agent_state": "",
}


@pytest.fixture()
def conn():
    with psycopg.connect(DB_URL, autocommit=True) as c:
        c.execute("select paytm.reset_demo(); select merchant.reset_demo();")
        yield c
        c.execute("select paytm.reset_demo(); select merchant.reset_demo();")


@contextmanager
def as_role(conn, role):
    with conn.transaction():
        conn.execute(f"set local role {role}")
        yield conn


def call(conn, role, sql, *args):
    with as_role(conn, role) as c:
        return c.execute(sql, args).fetchone()[0]


def fingerprint(conn) -> dict:
    out = {}
    for t, minus in FINGERPRINT_TABLES.items():
        out[t] = conn.execute(
            f"select md5(coalesce(string_agg(j, '|' order by j), '')) from "
            f"(select (to_jsonb(x) {minus})::text j from {t} x) s").fetchone()[0]
    return out


# ----------------------------------------------------------------------------- boundary + RLS
def test_schema_boundary_and_anon_read_only(conn):
    for role, other in (("paytm_svc", "merchant.a2a_events"), ("merchant_svc", "paytm.chargebacks")):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with as_role(conn, role) as c:
                c.execute(f"select 1 from {other} limit 1")
    with as_role(conn, "anon") as c:
        assert c.execute("select count(*) from paytm.chargebacks").fetchone()[0] >= 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with as_role(conn, "anon") as c:
            c.execute("update paytm.chargebacks set status = 'HELD'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with as_role(conn, "anon") as c:
            c.execute("select 1 from paytm.refunds")


def test_consent_checked_and_logged(conn):
    sql = "select paytm.check_consent(%s, %s, 'A2A dispatch', %s)"
    assert call(conn, "paytm_svc", sql, MID, VALID, "T1")["http_status"] == 200
    for token, reason in ((EXPIRED, "EXPIRED"), (None, "MISSING"), ("nope", "MALFORMED")):
        r = call(conn, "paytm_svc", sql, MID, token, "T2")
        assert (r["valid"], r["reason"], r["http_status"]) == (False, reason, 403)
    reasons = [r[0] for r in conn.execute("select reason::text from paytm.consent_checks order by id")]
    assert reasons == ["OK", "EXPIRED", "MISSING", "MALFORMED"]


# ----------------------------------------------------------------------------- all 8 intents, then reset
def run_all_intents(conn):
    P = lambda sql, *a: call(conn, "paytm_svc", sql, *a)      # noqa: E731
    M = lambda sql, *a: call(conn, "merchant_svc", sql, *a)   # noqa: E731

    # MANDATE_TROUBLESHOOT: UPI link for the bounced EDI, then paid
    link = P("select paytm.send_upi_collect_link('CLX-ML-26-008821', '2026-11-17'::date, 'I1')")
    assert link["mandate_status"] == "UPI_LINK_SENT" and link["amount"] == 500
    paid = P("select paytm.mark_upi_link_paid(%s)", link["link_id"])
    assert (paid["mandate_status"], paid["overdue_amount"], paid["outstanding"]) == ("ACTIVE", 0, 41500)

    # SETTLEMENT_RECONCILE: read-only; lines must explain the ₹4,160 variance
    lines = P("select sum(amount_signed) from paytm.settlement_lines where batch_id = 'STL-20261118' "
              "and line_type <> 'TXN'")
    net = P("select net_credit from paytm.settlement_batches where batch_id = 'STL-20261118'")
    assert net == 95840 and lines is not None
    M("select merchant.add_gst_itc('2026-11-18'::date, 261, 'GST on MDR', 'I2')")
    assert M("select merchant.add_gst_itc('2026-11-18'::date, 261, 'GST on MDR', 'I2b')")["logged"] is False

    # CHARGEBACK_RESOLVE
    r = P("select paytm.release_chargeback('CB-9981', 'DEX7781203345', 'I3')")
    assert (r["status"], r["released_amount"]) == ("RELEASED", 800)
    with pytest.raises(psycopg.errors.RaiseException, match="CHARGEBACK_NOT_HELD"):
        P("select paytm.release_chargeback('CB-9981', 'DEX7781203345', 'I3b')")

    # UTR_VERIFY
    assert P("select paytm.verify_utr(%s, '632184920111', 'I4')", MID)["status"] == "SUCCESS"
    assert P("select paytm.verify_utr(%s, '632184920999', 'I4')", MID)["status"] == "PENDING"
    assert P("select paytm.verify_utr(%s, '632184920555', 'I4')", MID)["status"] == "NOT_FOUND_SUSPECTED_FAKE"

    # DUPLICATE_RECONCILE (idempotent)
    r = P("select paytm.execute_refund('PTM26111800021', 1180, 'duplicate', 'AUTO', 'RFD-DUP-4489', 'I5')")
    assert r["status"] == "PROCESSED"
    assert P("select paytm.execute_refund('PTM26111800021', 1180, 'duplicate', 'AUTO', 'RFD-DUP-4489', 'I5')"
             )["idempotent_replay"] is True

    # GROWTH_ADVISORY: read-only, learned strategy written on the merchant side
    M("select merchant.record_strategy('GROWTH_ADVISORY', 'weekend stock-outs', array['A','B'], 'A', "
      "'stocked up', true, '7d')")

    # CASHFLOW_EDI_SWITCH
    with pytest.raises(psycopg.errors.RaiseException, match="EDI_PAUSE_NOT_ELIGIBLE"):
        P("select paytm.pause_edi('CLX-ML-26-008821', 3, '4.2', null, %s, 'I7')", VALID)
    r = P("select paytm.pause_edi('CLX-ML-26-008821', 2, '4.2', 'OFF-1', %s, 'I7')", VALID)
    assert r["loan_edi_status"] == "PAUSED_2_DAYS" and r["kfs_consent_artifact"]["clause"] == "4.2"

    # ESCALATE_HUMAN
    t = P("select paytm.create_l2_ticket(%s, 'ESCALATE_HUMAN', 'Soundbox silent', %s)", MID, Jsonb({"dev": 1}))
    assert t["ticket_id"] == "TKT-PAYTM-1291" and t["assignee_team"] == "Device Ops"

    # Refund guardrails
    big = P("select txn_id from paytm.acquiring_ledger a where mid = %s and status = 'SUCCESS' and amount > 6000 "
            "and not exists (select 1 from paytm.refunds r where r.txn_id = a.txn_id) limit 1", MID)
    r = P("select paytm.execute_refund(%s, 5500, 'return', 'AUTO', null, 'I9')", big)
    assert (r["status"], r["needs_human_approval"]) == ("NEEDS_APPROVAL", True)
    with pytest.raises(psycopg.errors.CheckViolation):
        with as_role(conn, "paytm_svc") as c:
            c.execute("update paytm.refunds set status = 'PROCESSED', approver = 'AUTO' where refund_id = %s",
                      (r["refund_id"],))
    with pytest.raises(psycopg.errors.RaiseException, match="REFUND_EXCEEDS_PAYMENT"):
        P("select paytm.execute_refund('PTM26111800023', 99999, 'over', 'AUTO', null, 'I9')")

    # Outcomes + trace + merchant event log
    P("select paytm.record_outcome(%s, 'CHARGEBACK_RESOLVE', 'I3', 'pod', 'RELEASED', true, 800)", MID)
    P("select paytm.log_agent_trace(%s, 'I3', 'CHARGEBACK_RESOLVE', %s)", MID,
      Jsonb([{"agent": "paytm_agent", "reads": ["chargebacks"], "decision": "release"}]))
    M("select merchant.log_event('A2A_REQUEST', 'merchant_agent', 'chargeback', '{}'::jsonb, 'I3', 'S1', null)")


def test_eight_intents_then_reset_restores_exact_state(conn):
    before = fingerprint(conn)
    assert verify(conn) == []
    run_all_intents(conn)

    after = fingerprint(conn)
    changed = {t for t in before if before[t] != after[t]}
    assert {"paytm.refunds", "paytm.chargebacks", "paytm.loan_book", "paytm.enach_mandates",
            "paytm.tickets", "paytm.fraud_signals", "paytm.demo_counters"} <= changed
    assert verify(conn) != []

    t0 = time.perf_counter()
    conn.execute("select paytm.reset_demo(); select merchant.reset_demo();")
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"reset took {elapsed:.2f}s"
    assert fingerprint(conn) == before
    assert verify(conn) == []
