"""Stage 9 — the four scenarios added to the table.

MANDATE_TROUBLESHOOT, DUPLICATE_PAYMENT_RECONCILE, WORKING_CAPITAL_ADVISORY and
CASHFLOW_EDI_SWITCH. Figures are matched to sarvam_service's own Hindi replies so the
two services cannot tell the merchant different stories.

Three properties get the most attention, because each is a way the product could be
quietly wrong rather than broken:

  the duplicate refund must not disturb a settlement that has already closed;
  the advisory must never recommend borrowing;
  neither the mandate nor the cashflow intent may pause credit on its own.
"""
from __future__ import annotations

import pytest

from app import store
from app.config import DUPLICATE_AUTO_LIMIT_INR
from app.templates import BANNED_WORDS

MID = "PAYTM_MERCH_8821"


def body(intent: str, **over) -> dict:
    base = {
        "request_id": f"req-{intent}",
        "session_id": "sess-1",
        "mid": MID,
        "intent": intent,
        "language_code": "hi-IN",
        "merchant_said": "",
        "payload": {},
        "consent_token": "ct-abc",
    }
    base.update(over)
    return base


def trace_of(out: dict) -> dict[str, dict]:
    return {e["agent"]: e for e in out["agent_trace"]}


# ============ MANDATE_TROUBLESHOOT ============================================

def test_a_bounced_mandate_is_not_a_default(client):
    out = client.post("/a2a/dispatch", json=body(
        "MANDATE_TROUBLESHOOT", merchant_said="meri kisht fail ho gayi")).json()

    assert out["status"] == "ACTION_REQUIRED"
    data = out["data"]
    assert data["is_default"] is False
    assert data["amount_inr"] == 500
    # The canonical ledger's representation: the mandate stays ACTIVE and it is the
    # presentment that was returned, which is what makes "not a default" true rather
    # than just reassuring.
    assert data["status"] == "ACTIVE"
    assert data["last_return_reason"] == "Balance insufficient"
    assert data["last_return_date"] == "2026-11-17"
    assert data["days_past_due"] == 0
    # The figures sarvam_service's Hindi reply already quotes.
    assert data["repayment_history"] == {"on_time_rate_percent": 96.0, "months": 6}

    # And the merchant is told so first, before any remedy.
    text = out["template_text"]
    assert "not a default" in text
    assert "96.0%" in text or "96%" in text


def test_both_remedies_are_offered(client):
    out = client.post("/a2a/dispatch", json=body("MANDATE_TROUBLESHOOT")).json()
    kinds = {r["type"] for r in out["data"]["remedies"]}

    assert kinds == {"PAY_NOW_UPI_LINK", "KFS_HARDSHIP_PAUSE"}
    assert out["action_required"]["type"] == "CHOOSE_REMEDY"
    assert "UPI link" in out["template_text"]


def test_the_pause_it_offers_can_actually_be_redeemed(client):
    """An offer with no matching record would be a dead button on the merchant's screen."""
    out = client.post("/a2a/dispatch", json=body("MANDATE_TROUBLESHOOT")).json()
    pause = next(r for r in out["data"]["remedies"] if r["type"] == "KFS_HARDSHIP_PAUSE")

    assert pause["offer_id"] in store.edi_offers
    assert pause["kfs_clause"] == "4.2"
    assert pause["edi_saved_inr"] == 1000

    redeemed = client.post("/a2a/execute-edi-pause", json={
        "mid": MID, "consent_token": "DPDP_VERIFIED_TS_1", "offer_id": pause["offer_id"],
    })
    assert redeemed.status_code == 200
    assert redeemed.json()["data"]["loan_edi_status"] == "PAUSED_2_DAYS"


def test_the_mandate_intent_pauses_nothing_by_itself(client):
    """Offering relief and granting it are different acts; only one needs consent."""
    out = client.post("/a2a/dispatch", json=body("MANDATE_TROUBLESHOOT")).json()

    assert trace_of(out)["LedgerOpsAgent"]["acted"] is False
    assert store.ledger.loan.status == "ACTIVE"


def test_no_pause_left_goes_to_a_person(client):
    store.ledger.mandate.hardship_pauses_used_in_window = 1
    out = client.post("/a2a/dispatch", json=body("MANDATE_TROUBLESHOOT")).json()

    assert out["status"] == "ESCALATED"
    # The merchant is still given the way to pay, not just refused.
    assert "UPI link" in out["template_text"]
    assert {r["type"] for r in out["data"]["remedies"]} == {"PAY_NOW_UPI_LINK"}


# ============ DUPLICATE_PAYMENT_RECONCILE =====================================

def test_a_double_charge_is_found_and_the_later_one_returned(client):
    out = client.post("/a2a/dispatch", json=body(
        "DUPLICATE_PAYMENT_RECONCILE", merchant_said="customer ne do baar pay kiya")).json()

    assert out["status"] == "RESOLVED"
    data = out["data"]
    assert data["order_id"] == "4489"
    assert len(data["payments"]) == 2
    # The first payment keeps its place; the later one goes back.
    assert data["keep"]["utr"] == "632299206882"
    assert data["refund"]["utr"] == "632230725895"
    assert data["refund"]["amount_inr"] == 1180
    assert data["refund_status"] == "PROCESSED"

    assert store.ledger.utrs["632230725895"].refunded is True
    assert store.ledger.utrs["632299206882"].refunded is False


def test_the_closed_settlement_is_not_disturbed(client):
    """The regression that would quietly break the centrepiece demo.

    A refund issued today is real, but it was not one of yesterday's deductions. If it
    were counted there, the five lines would stop adding up to 4,160.
    """
    client.post("/a2a/dispatch", json=body("DUPLICATE_PAYMENT_RECONCILE"))

    led = client.get(f"/ledger/{MID}").json()
    assert led["settlement"]["variance_inr"] == 4160
    assert sum(l["amount_inr"] for l in led["settlement"]["lines"]) == 4160
    assert led["settlement"]["reconciles"] is True
    refund_line = next(l for l in led["settlement"]["lines"] if l["code"] == "CUSTOMER_REFUND")
    assert refund_line["amount_inr"] == 1500  # still only order 4412


def test_the_merchant_is_no_worse_off(client):
    """They were credited twice. Taking one back leaves them where they should have been."""
    before = client.get(f"/ledger/{MID}").json()["projected_net_payout_inr"]
    out = client.post("/a2a/dispatch", json=body("DUPLICATE_PAYMENT_RECONCILE")).json()
    after = client.get(f"/ledger/{MID}").json()["projected_net_payout_inr"]

    assert after == before
    assert out["data"]["merchant_position_changed"] is False
    assert "square" in out["template_text"]


def test_ledger_ops_is_the_one_that_moves_the_money(client):
    out = client.post("/a2a/dispatch", json=body("DUPLICATE_PAYMENT_RECONCILE")).json()
    ops = trace_of(out)["LedgerOpsAgent"]

    assert ops["acted"] is True
    assert "632230725895" in ops["note"]


def test_a_duplicate_over_the_limit_goes_to_a_person(client):
    store.ledger.utrs["632299206882"].amount_inr = DUPLICATE_AUTO_LIMIT_INR + 1
    store.ledger.utrs["632230725895"].amount_inr = DUPLICATE_AUTO_LIMIT_INR + 1

    out = client.post("/a2a/dispatch", json=body("DUPLICATE_PAYMENT_RECONCILE")).json()

    assert out["status"] == "ESCALATED"
    assert out["escalation_ticket"]["reason_code"] == "REFUND_OVER_LIMIT"
    assert store.ledger.utrs["632230725895"].refunded is False
    assert trace_of(out)["LedgerOpsAgent"]["acted"] is False


def test_replaying_does_not_refund_twice(client):
    first = client.post("/a2a/dispatch", json=body("DUPLICATE_PAYMENT_RECONCILE")).json()
    second = client.post("/a2a/dispatch", json=body("DUPLICATE_PAYMENT_RECONCILE")).json()

    assert second == first
    assert len(store.summaries) == 1


def test_asking_again_after_it_is_fixed_says_so(client):
    client.post("/a2a/dispatch", json=body("DUPLICATE_PAYMENT_RECONCILE"))
    again = client.post("/a2a/dispatch", json=body(
        "DUPLICATE_PAYMENT_RECONCILE", request_id="again")).json()

    assert again["status"] == "RESOLVED"
    assert again["data"]["already_refunded"] is True
    assert "already gone back" in again["template_text"]
    assert trace_of(again)["LedgerOpsAgent"]["acted"] is False


def test_an_order_with_one_payment_is_not_a_duplicate(client):
    out = client.post("/a2a/dispatch", json=body(
        "DUPLICATE_PAYMENT_RECONCILE", payload={"order_id": "4412"})).json()

    assert out["status"] == "RESOLVED"
    assert out["data"]["duplicates_found"] == 0
    assert "nothing to put right" in out["template_text"]


# ============ WORKING_CAPITAL_ADVISORY ========================================

def test_the_sales_pattern_is_read_back_from_their_own_data(client):
    out = client.post("/a2a/dispatch", json=body(
        "WORKING_CAPITAL_ADVISORY", merchant_said="business kaise badhaye")).json()

    assert out["status"] == "RESOLVED"
    sales = out["data"]["sales"]
    # Matched to sarvam_service's Hindi reply.
    assert sales["avg_daily_sales_inr"] == 32_000
    assert sales["weekend_multiplier"] == 2.3
    assert sales["restock_by"] == "Thursday"
    assert out["data"]["weekend_daily_sales_inr"] == 73_600

    text = out["template_text"]
    assert "₹32,000" in text
    assert "Thursday" in text


@pytest.mark.parametrize("asked", [
    "should i take the loan?",
    "loan lena chahiye kya?",
    "is it worth taking the working capital?",
    "do you recommend it?",
])
def test_asking_whether_to_borrow_goes_to_a_human(client, asked):
    """The one refusal in this service, and it is deliberate.

    Telling a shopkeeper to take on debt is a recommendation made by software to someone
    whose livelihood depends on it, with no view of their other obligations.
    """
    out = client.post("/a2a/dispatch", json=body(
        "WORKING_CAPITAL_ADVISORY", request_id=asked, merchant_said=asked)).json()

    assert out["status"] == "ESCALATED"
    assert out["escalation_ticket"]["reason_code"] == "OUT_OF_SCOPE"
    assert "recommendation" in out["escalation_ticket"]["reason_text"]
    # It still leaves the merchant with their own numbers rather than nothing.
    assert "₹32,000" in out["template_text"]
    assert "not the right one to answer that" in out["template_text"]


def test_no_credit_pricing_is_ever_invented(client):
    """Rate and tenure belong in the NBFC's Key Fact Statement, not in a demo fixture."""
    out = client.post("/a2a/dispatch", json=body("WORKING_CAPITAL_ADVISORY")).json()

    # No new facility is offered at all: the canonical dataset has no pre-approved
    # limit, so an earlier invented one was removed rather than kept as a placeholder.
    assert out["data"]["new_facility_offered"] is False
    assert "credit_offer" not in out["data"]

    # The loan they already have is quoted on its real terms from the dataset.
    loan = out["data"]["existing_loan"]
    assert loan["apr_percent"] == 31.89
    assert loan["balance_inr"] == 42_000
    assert loan["loan_id"] == "CLX-ML-26-008821"

    # And the merchant is told where the terms of anything further would come from.
    assert "Key Fact Statement" in out["template_text"]


def test_it_never_tells_the_merchant_what_to_do_about_borrowing(client):
    for said in ("business kaise badhaye", "should i take the loan?"):
        out = client.post("/a2a/dispatch", json=body(
            "WORKING_CAPITAL_ADVISORY", request_id=said, merchant_said=said)).json()
        text = out["template_text"].lower()

        for nudge in ("you should take", "i recommend", "we recommend",
                      "it is a good idea", "you ought to"):
            assert nudge not in text, f"{nudge!r} in: {text}"


def test_the_true_cost_is_shown_as_a_share_of_daily_takings(client):
    """500 a day against 32,000 of takings is the number a glossy offer leaves out."""
    out = client.post("/a2a/dispatch", json=body("WORKING_CAPITAL_ADVISORY")).json()
    assert out["data"]["share_of_daily_takings_repaid_percent"] == 1.56


# ============ CASHFLOW_EDI_SWITCH =============================================

def test_the_reactive_twin_gives_the_same_facts_as_the_proactive_alert(client):
    """Same numbers whether Paytm spoke first or the merchant asked."""
    alert = client.post("/a2a/proactive-alert", json={
        "mid": MID, "trigger_type": "HIGH_REFUND_CASHFLOW"}).json()
    asked = client.post("/a2a/dispatch", json=body(
        "CASHFLOW_EDI_SWITCH", merchant_said="kal payout kam hai, kisht rok do")).json()

    assert alert["data"]["projected_net_payout"] == 1200
    assert asked["data"]["projected_net_payout"] == 1200
    assert asked["data"]["edi_pause_offer"]["pause_days"] == 2
    assert asked["data"]["edi_pause_offer"]["edi_saved_inr"] == 1000


def test_the_projection_is_broken_down_so_it_can_be_checked(client):
    out = client.post("/a2a/dispatch", json=body("CASHFLOW_EDI_SWITCH")).json()
    b = out["data"]["breakdown"]

    assert b["expected_gross_inr"] - b["pending_refunds_inr"] - b["edi_due_inr"] \
        + b["released_hold_inr"] == out["data"]["projected_net_payout"]


def test_it_asks_for_consent_rather_than_pausing(client):
    out = client.post("/a2a/dispatch", json=body("CASHFLOW_EDI_SWITCH")).json()

    assert out["status"] == "ACTION_REQUIRED"
    assert out["action_required"]["type"] == "CONFIRM_EDI_PAUSE"
    assert trace_of(out)["LedgerOpsAgent"]["acted"] is False
    assert store.ledger.loan.status == "ACTIVE"


def test_the_offer_it_makes_is_redeemable(client):
    out = client.post("/a2a/dispatch", json=body("CASHFLOW_EDI_SWITCH")).json()
    offer_id = out["action_required"]["offer_id"]

    assert offer_id in store.edi_offers
    done = client.post("/a2a/execute-edi-pause", json={
        "mid": MID, "consent_token": "DPDP_VERIFIED_TS_1", "offer_id": offer_id})
    assert done.status_code == 200
    assert store.ledger.loan.status == "PAUSED_2_DAYS"


def test_asking_again_once_paused_says_it_is_already_done(client):
    first = client.post("/a2a/dispatch", json=body("CASHFLOW_EDI_SWITCH")).json()
    client.post("/a2a/execute-edi-pause", json={
        "mid": MID, "consent_token": "ct", "offer_id": first["action_required"]["offer_id"]})

    again = client.post("/a2a/dispatch", json=body(
        "CASHFLOW_EDI_SWITCH", request_id="again")).json()

    assert again["status"] == "RESOLVED"
    assert again["data"]["edi_pause_offer"]["eligible"] is False
    assert "already paused" in again["template_text"]
    # And the payout reflects the pause.
    assert again["data"]["projected_net_payout"] == 1700


def test_paytm_does_not_claim_to_know_the_suppliers_bill(client):
    """Payables live in the merchant's Vyapar connector, which the contract says Paytm
    never reads. Person 3 holds that figure and works out the shortfall."""
    out = client.post("/a2a/dispatch", json=body("CASHFLOW_EDI_SWITCH")).json()

    assert out["data"]["payables_known_to_paytm"] is False
    assert "tomorrow_stock_due" not in out["data"]
    assert "4,500" not in out["template_text"]


# ============ across all eight ================================================

ALL_EIGHT = [
    ("MANDATE_TROUBLESHOOT", {}),
    ("SETTLEMENT_RECONCILE", {}),
    ("CHARGEBACK_RESOLVE", {"txn_id": "9981"}),
    ("UTR_VERIFY", {"utr": "111111111111"}),
    ("DUPLICATE_PAYMENT_RECONCILE", {}),
    ("WORKING_CAPITAL_ADVISORY", {}),
    ("CASHFLOW_EDI_SWITCH", {}),
    ("ESCALATE_HUMAN", {"reason_code": "MERCHANT_REQUESTED_HUMAN"}),
]


@pytest.mark.parametrize("intent, payload", ALL_EIGHT)
def test_every_scenario_answers_and_says_nothing_accusatory(client, intent, payload):
    out = client.post("/a2a/dispatch", json=body(intent, payload=payload)).json()

    assert out["status"] in {"RESOLVED", "ACTION_REQUIRED", "ESCALATED"}
    assert out["template_text"], f"{intent} said nothing"
    assert len(out["agent_trace"]) == 4
    for word in BANNED_WORDS:
        assert word not in out["template_text"].lower(), f"{word!r} in {intent}"


@pytest.mark.parametrize("intent, payload", ALL_EIGHT)
def test_every_scenario_writes_exactly_one_feed_row(client, intent, payload):
    client.post("/a2a/dispatch", json=body(intent, payload=payload))
    assert len(store.summaries) == 1
    assert store.summaries[0]["intent"] == intent
    assert store.summaries[0]["found"], f"{intent} left the feed row empty"
