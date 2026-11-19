"""Stage 1 — the seed ledger adds up, and there is exactly one source of rupee truth.

The contract quotes 1,450 twice (as the MDR_FEE settlement line and as the FEE topic
total) and 500 twice (as the settlement's upcoming line and as the loan EDI). If those
were typed as separate literals they would agree today and silently disagree the moment
someone edits the seed. These tests prove they are derived from one place.
"""
from __future__ import annotations

import pytest

from app import clock, seed, store


# --- the headline numbers from the contract -------------------------------------------

def test_settlement_matches_the_contract():
    led = store.ledger
    assert led.gross_inr == 100_000
    assert led.net_credit_inr == 95_840
    assert led.variance_inr == 4_160


def test_the_five_lines_explain_the_whole_gap():
    led = store.ledger
    assert [l["code"] for l in led.lines] == [
        "MDR_FEE", "GST_ON_MDR", "CUSTOMER_REFUND", "SOUNDBOX_RENTAL", "CHARGEBACK_HOLD",
    ]
    assert [l["amount_inr"] for l in led.lines] == [1_450, 261, 1_500, 149, 800]
    assert led.lines_total_inr == led.variance_inr == 4_160
    assert led.reconciles is True


def test_mdr_bands_add_up_to_the_fee_line():
    led = store.ledger
    assert [b.fee_inr for b in led.mdr_bands] == [900, 550, 0]
    assert led.mdr_total_inr == 1_450


def test_gst_is_eighteen_percent_of_the_fee():
    led = store.ledger
    assert led.gst_on_mdr_inr == 261
    assert led.gst_on_mdr_inr == round(led.mdr_total_inr * 18 / 100)


# --- the point of the stage: one source of truth, proven by moving it ------------------

def test_fee_line_is_derived_from_the_bands_not_typed_twice():
    """Change a band and the settlement line must follow.

    This is what separates 'the numbers agree' from 'the numbers are the same number'.
    """
    led = seed.fresh()
    led.mdr_bands = (seed.MdrBand("Credit card", 10_000, 2.0),)  # fee = 200

    assert led.mdr_total_inr == 200
    mdr_line = next(l for l in led.lines if l["code"] == "MDR_FEE")
    assert mdr_line["amount_inr"] == 200
    # And GST follows the fee, rather than staying at its seeded 261.
    assert led.gst_on_mdr_inr == 36


def test_refund_line_is_derived_from_the_order():
    led = store.ledger
    refund_line = next(l for l in led.lines if l["code"] == "CUSTOMER_REFUND")
    assert refund_line["amount_inr"] == led.orders["4412"].refund_amount_inr == 1_500
    # The label names the order it came from, so the merchant can check it.
    assert "4412" in refund_line["label"]


def test_chargeback_hold_line_is_derived_from_the_dispute():
    led = store.ledger
    hold_line = next(l for l in led.lines if l["code"] == "CHARGEBACK_HOLD")
    assert hold_line["amount_inr"] == led.chargeback.amount_held_inr == 800


# --- the demo levers --------------------------------------------------------------------

def test_break_settlement_makes_the_lines_stop_adding_up():
    """Without this lever the SETTLEMENT_UNRECONCILED path could never be demonstrated."""
    assert store.ledger.reconciles is True

    store.reset(break_settlement=True)

    assert store.ledger.reconciles is False
    assert store.ledger.lines_total_inr != store.ledger.variance_inr
    # The variance itself is untouched: it is a bank fact, not our arithmetic.
    assert store.ledger.variance_inr == 4_160


def test_chargeback_deadline_lever_is_exact():
    store.reset(chargeback_hours_left=6)
    assert clock.hours_until(store.ledger.chargeback.deadline_iso) == 6.0
    assert store.ledger.chargeback.as_dict()["hours_left"] == 6.0


def test_default_deadline_is_comfortably_past_the_urgent_bar():
    # Otherwise chargeback step 1 would escalate as urgent instead of asking for a doc.
    from app.config import URGENT_HOURS

    assert clock.hours_until(store.ledger.chargeback.deadline_iso) == 48.0 > URGENT_HOURS


def test_hours_left_is_computed_on_read_never_stored():
    """A stored hours_left goes stale between chargeback step 1 and step 2."""
    store.reset(chargeback_hours_left=10)
    assert store.ledger.chargeback.as_dict()["hours_left"] == 10.0

    clock.freeze(clock.now().replace(hour=14))  # four hours later
    assert store.ledger.chargeback.as_dict()["hours_left"] == 6.0


# --- the endpoints -----------------------------------------------------------------------

def test_get_ledger_returns_the_live_state(client):
    r = client.get(f"/ledger/{seed.MID}")
    assert r.status_code == 200
    body = r.json()

    assert body["merchant_name"] == "Sharma Electronics"
    assert sum(l["amount_inr"] for l in body["settlement"]["lines"]) == 4_160
    assert body["settlement"]["reconciles"] is True
    assert sum(b["fee_inr"] for b in body["mdr_breakdown"]) == 1_450
    assert body["loan"]["edi_per_day_inr"] == 500
    assert body["loan"]["next_deduction_date"] == "2026-11-19"
    assert body["chargeback"]["hold_status"] == "HELD"
    assert {t["utr"] for t in body["transactions"]} == {
        "632184920111", "632184920999",
        # The duplicate pair: one order, two settled payments.
        "632184925001", "632184925002",
    }
    assert body["counters"] == {"tickets_deflected": 0, "fraud_blocked": 0}


def test_unknown_merchant_returns_the_contract_error_shape(client):
    r = client.get("/ledger/PAYTM_MERCH_0000")
    assert r.status_code == 404
    assert r.json() == {
        "error": {
            "code": "UNKNOWN_MID",
            "message": "No merchant 'PAYTM_MERCH_0000' in this service",
            "retryable": False,
        }
    }


def test_reset_endpoint_accepts_both_levers(client):
    assert client.post("/ledger/reset?chargeback_hours_left=6").json() == {"ok": True}
    assert clock.hours_until(store.ledger.chargeback.deadline_iso) == 6.0

    client.post("/ledger/reset?break_settlement=true")
    assert store.ledger.reconciles is False

    client.post("/ledger/reset")
    assert store.ledger.reconciles is True
    assert clock.hours_until(store.ledger.chargeback.deadline_iso) == 48.0
