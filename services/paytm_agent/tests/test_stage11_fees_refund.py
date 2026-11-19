"""Stage 11 — FEE_GST_LOAN and REFUND_MANAGE, contract acceptance cases 11 to 14.

Both are contract v1 intents the scenario table moved past, kept because Person 1 still
routes to them. The tests therefore care most about the two things that would embarrass
the demo: quoting a fee split that disagrees with the dataset, and telling a merchant
they can reclaim tax they cannot.
"""
from __future__ import annotations

import pytest

from app import store
from app.templates import BANNED_WORDS

MID = "PAYTM_MERCH_8821"


def body(intent: str, **over) -> dict:
    base = {
        "request_id": f"r-{intent}", "session_id": "s", "mid": MID, "intent": intent,
        "language_code": "hi-IN", "merchant_said": "", "payload": {}, "consent_token": "ct",
    }
    base.update(over)
    return base


def ops(out):
    return next(e for e in out["agent_trace"] if e["agent"] == "LedgerOpsAgent")


# --- case 13: the fee breakdown ---------------------------------------------------------

def test_case_13_the_fee_breakdown_adds_up(client):
    out = client.post("/a2a/dispatch", json=body("FEE_GST_LOAN", payload={"topic": "FEE"})).json()

    assert out["status"] == "RESOLVED"
    assert out["data"]["mdr_total_inr"] == 1450
    assert sum(b["fee_inr"] for b in out["data"]["breakdown"]) == 1450
    # The rails from the canonical dataset, not a split of our own that merely totals.
    assert [b["fee_inr"] for b in out["data"]["breakdown"]] == [1252, 198, 0]


def test_the_zero_fee_rail_is_pointed_out(client):
    """₹19,400 of UPI cost nothing, which is the good news in an answer about charges."""
    text = client.post("/a2a/dispatch", json=body("FEE_GST_LOAN", payload={"topic": "FEE"})).json()["template_text"]
    assert "no fee at all" in text
    assert "₹19,400" in text


# --- GST, and the claim we will not make --------------------------------------------------

def test_gst_is_explained_with_the_credit(client):
    out = client.post("/a2a/dispatch", json=body("FEE_GST_LOAN", payload={"topic": "GST"})).json()

    assert out["data"]["gst_inr"] == 261
    assert out["data"]["base_inr"] == 1450
    assert out["data"]["itc_eligible"] is True
    assert "input tax credit" in out["template_text"]


def test_an_unregistered_merchant_is_not_told_to_claim_the_credit(client):
    """Telling them otherwise has them file a credit they are not entitled to."""
    store.ledger.gst_registered = False
    out = client.post("/a2a/dispatch", json=body("FEE_GST_LOAN", payload={"topic": "GST"})).json()

    assert out["status"] == "ESCALATED"
    assert "input tax credit" not in out["template_text"]
    assert "depends on your GST registration" in out["template_text"]
    # The amount is still given: they asked what the charge was.
    assert "₹261" in out["template_text"]


# --- case 14: the loan ---------------------------------------------------------------------

def test_case_14_the_loan_instalment(client):
    out = client.post("/a2a/dispatch", json=body("FEE_GST_LOAN", payload={"topic": "LOAN"})).json()

    assert out["data"]["edi_per_day_inr"] == 500
    assert out["data"]["balance_inr"] == 42_000
    assert out["data"]["next_deduction_date"] == "2026-11-19"
    assert "₹500" in out["template_text"]
    assert "19 November" in out["template_text"]


def test_a_paused_loan_says_nothing_is_due(client):
    store.ledger.loan.status = "PAUSED_2_DAYS"
    out = client.post("/a2a/dispatch", json=body("FEE_GST_LOAN", payload={"topic": "LOAN"})).json()
    assert out["data"]["edi_tomorrow_inr"] == 0
    assert "paused" in out["template_text"]


@pytest.mark.parametrize("said, topic", [
    ("mera gst kitna laga", "GST"),
    ("loan ki kisht kab kategi", "LOAN"),
    ("ye fee kya hai", "FEE"),
    ("", "FEE"),
])
def test_the_topic_is_inferred_when_the_caller_omits_it(client, said, topic):
    """The contract makes topic optional, and the merchant agent often omits it."""
    out = client.post("/a2a/dispatch", json=body(
        "FEE_GST_LOAN", request_id=said or "blank", merchant_said=said)).json()
    assert out["data"]["topic"] == topic


def test_a_nonsense_topic_is_rejected(client):
    r = client.post("/a2a/dispatch", json=body("FEE_GST_LOAN", payload={"topic": "WEATHER"}))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_PAYLOAD"


def test_explaining_a_charge_changes_nothing(client):
    out = client.post("/a2a/dispatch", json=body("FEE_GST_LOAN", payload={"topic": "FEE"})).json()
    assert ops(out)["acted"] is False


# --- case 11 and 12: refunds ----------------------------------------------------------------

def test_case_11_refund_status(client):
    out = client.post("/a2a/dispatch", json=body(
        "REFUND_MANAGE", payload={"order_id": "4412", "action": "STATUS"})).json()

    assert out["status"] == "RESOLVED"
    assert out["data"]["refund_status"] == "PROCESSED"
    assert out["data"]["amount_inr"] == 1500
    assert "already been sent back" in out["template_text"]
    assert ops(out)["acted"] is False


def test_case_12_a_refund_over_the_limit_goes_to_a_person(client):
    out = client.post("/a2a/dispatch", json=body(
        "REFUND_MANAGE",
        payload={"order_id": "4490", "action": "INITIATE", "amount_inr": 3500})).json()

    assert out["status"] == "ESCALATED"
    assert out["escalation_ticket"]["reason_code"] == "REFUND_OVER_LIMIT"
    assert ops(out)["acted"] is False


def test_an_unknown_order_goes_to_a_person(client):
    out = client.post("/a2a/dispatch", json=body(
        "REFUND_MANAGE", payload={"order_id": "7777", "action": "STATUS"})).json()

    assert out["status"] == "ESCALATED"
    assert out["escalation_ticket"]["reason_code"] == "ORDER_NOT_FOUND"
    assert "cannot find order 7777" in out["template_text"]


def test_refunding_an_order_twice_is_refused(client):
    out = client.post("/a2a/dispatch", json=body(
        "REFUND_MANAGE",
        payload={"order_id": "4412", "action": "INITIATE", "amount_inr": 1500})).json()

    assert out["status"] == "ESCALATED"
    assert "already been refunded" in out["escalation_ticket"]["reason_text"]


def test_refunding_more_than_was_paid_is_refused(client):
    out = client.post("/a2a/dispatch", json=body(
        "REFUND_MANAGE",
        payload={"order_id": "4489", "action": "INITIATE", "amount_inr": 1800})).json()

    assert out["status"] == "ESCALATED"
    assert "more than the 1180 paid" in out["escalation_ticket"]["reason_text"]


def test_a_refund_within_the_limit_is_started(client):
    out = client.post("/a2a/dispatch", json=body(
        "REFUND_MANAGE",
        payload={"order_id": "4489", "action": "INITIATE", "amount_inr": 1180})).json()

    assert out["status"] == "RESOLVED"
    assert ops(out)["acted"] is True
    assert store.ledger.orders["4489"].refund_status == "PENDING"
    # And it does not rewrite the settlement that already ran.
    assert store.ledger.reconciles is True
    assert store.ledger.variance_inr == 4160


def test_a_missing_order_id_is_a_bad_payload(client):
    r = client.post("/a2a/dispatch", json=body("REFUND_MANAGE", payload={"action": "STATUS"}))
    assert r.status_code == 400


# --- across both -----------------------------------------------------------------------------

@pytest.mark.parametrize("intent, payload", [
    ("FEE_GST_LOAN", {"topic": "FEE"}),
    ("FEE_GST_LOAN", {"topic": "GST"}),
    ("FEE_GST_LOAN", {"topic": "LOAN"}),
    ("REFUND_MANAGE", {"order_id": "4412", "action": "STATUS"}),
    ("REFUND_MANAGE", {"order_id": "7777", "action": "STATUS"}),
])
def test_nothing_accusatory_is_said(client, intent, payload):
    out = client.post("/a2a/dispatch", json=body(
        intent, request_id=f"{intent}{payload}", payload=payload)).json()
    text = out["template_text"].lower()
    assert text
    assert not any(w in text for w in BANNED_WORDS)


def test_all_ten_intents_now_have_a_handler():
    """Nothing is left answering 501 on demo day."""
    from app.intents import MODULES
    from app.models import INTENTS

    assert set(MODULES) == set(INTENTS)
