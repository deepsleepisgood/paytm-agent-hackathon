"""Stage 8 — CHARGEBACK_RESOLVE, contract acceptance cases 6 to 10.

The first intent that moves money, so the tests do two extra things: they check the
ledger itself rather than trusting the response, and they check that nothing moved on
every path that did not succeed.

They also send the payload in all three shapes the team currently uses, because the two
specs disagree and Person 1's document reader uses a third field name again.
"""
from __future__ import annotations

import pytest

from app import clock, store
from app.templates import BANNED_WORDS

MID = "PAYTM_MERCH_8821"


def body(**over) -> dict:
    base = {
        "request_id": "req-cb",
        "session_id": "sess-1",
        "mid": MID,
        "intent": "CHARGEBACK_RESOLVE",
        "language_code": "hi-IN",
        "merchant_said": "ye 800 ka hold kya hai?",
        "payload": {"txn_id": "9981"},
        "consent_token": "ct-abc",
    }
    base.update(over)
    return base


def clean_doc(order_id: str = "9981", amount: int = 800, confidence: float = 0.96) -> dict:
    return {"txn_id": "9981", "doc": {
        "doc_type": "pod",
        "extracted_fields": {"order_id": order_id, "amount_inr": amount},
        "confidence": confidence,
    }}


# --- case 6: step one, ask for the document ------------------------------------------------

def test_case_6_step_one_asks_for_the_proof(client):
    out = client.post("/a2a/dispatch", json=body()).json()

    assert out["status"] == "ACTION_REQUIRED"
    assert out["data"]["amount_held_inr"] == 800
    assert out["data"]["hours_left"] == 48.0
    assert out["action_required"]["type"] == "UPLOAD_DOC"
    assert out["action_required"]["doc_type"] == "pod"
    assert out["action_required"]["hours_left"] == 48.0

    # Nothing released, and no ticket: the merchant has to act, not a colleague.
    assert out["escalation_ticket"] is None
    assert store.ledger.chargeback.hold_status == "HELD"


def test_step_one_counts_as_awaiting_the_merchant(client):
    client.post("/a2a/dispatch", json=body())

    assert store.summaries[0]["outcome"] == "AWAITING_MERCHANT"
    m = client.get("/metrics").json()
    assert m["calls_total"] == 1
    assert m["awaiting_merchant"] == 1
    assert m["resolved_by_ai"] == 0
    assert m["escalated"] == 0
    # The invariant that keeps auto_resolution_rate meaningful.
    assert m["resolved_by_ai"] + m["escalated"] + m["awaiting_merchant"] == m["calls_total"]


# --- case 7: a clean proof is submitted and the hold released --------------------------------

def test_case_7_a_clean_proof_releases_the_hold(client):
    out = client.post("/a2a/dispatch", json=body(payload=clean_doc())).json()

    assert out["status"] == "RESOLVED"
    assert out["data"]["evidence_status"] == "SUBMITTED"
    assert out["data"]["hold_status"] == "RELEASED"
    assert out["data"]["simulated"] is True

    # Confirmed against the ledger, not just the response.
    cb = store.ledger.chargeback
    assert cb.hold_status == "RELEASED"
    assert cb.evidence_status == "SUBMITTED"


def test_the_released_hold_comes_back_in_the_next_payout(client):
    before = client.get(f"/ledger/{MID}").json()["projected_net_payout_inr"]
    client.post("/a2a/dispatch", json=body(payload=clean_doc()))
    after = client.get(f"/ledger/{MID}").json()["projected_net_payout_inr"]

    assert after - before == 800


def test_yesterdays_settlement_is_history_and_does_not_change(client):
    """The hold was already deducted. Winning the dispute returns it later, it does not
    rewrite a settlement that has already run."""
    client.post("/a2a/dispatch", json=body(payload=clean_doc()))

    led = client.get(f"/ledger/{MID}").json()
    assert led["settlement"]["variance_inr"] == 4160
    assert led["settlement"]["reconciles"] is True
    hold_line = next(l for l in led["settlement"]["lines"] if l["code"] == "CHARGEBACK_HOLD")
    assert hold_line["amount_inr"] == 800


def test_the_simulation_is_labelled_and_said_out_loud(client):
    out = client.post("/a2a/dispatch", json=body(payload=clean_doc())).json()

    assert out["data"]["simulated"] is True
    # And the merchant is told the bank still decides.
    assert "bank still makes the final decision" in out["template_text"]
    ops = next(e for e in out["agent_trace"] if e["agent"] == "LedgerOpsAgent")
    assert "simulated" in ops["note"]


def test_the_confidence_bar_is_inclusive(client):
    """Exactly at the bar passes; a hair under does not."""
    at_bar = client.post("/a2a/dispatch", json=body(
        request_id="at", payload=clean_doc(confidence=0.90))).json()
    assert at_bar["status"] == "RESOLVED"

    client.post("/ledger/reset")
    under = client.post("/a2a/dispatch", json=body(
        request_id="under", payload=clean_doc(confidence=0.89))).json()
    assert under["status"] == "ESCALATED"
    assert under["escalation_ticket"]["reason_code"] == "LOW_DOC_CONFIDENCE"


# --- cases 8, 9, 10: the refusals -------------------------------------------------------------

def test_case_8_an_unreadable_proof_escalates(client):
    out = client.post("/a2a/dispatch", json=body(payload=clean_doc(confidence=0.62))).json()

    assert out["status"] == "ESCALATED"
    t = out["escalation_ticket"]
    assert t["reason_code"] == "LOW_DOC_CONFIDENCE"
    assert "0.62" in t["reason_text"]
    assert "clearer photo" in t["suggested_next_step"]
    assert store.ledger.chargeback.hold_status == "HELD"


def test_case_9_a_proof_for_the_wrong_order_escalates(client):
    out = client.post("/a2a/dispatch", json=body(payload=clean_doc(order_id="7777"))).json()

    assert out["status"] == "ESCALATED"
    assert out["escalation_ticket"]["reason_code"] == "DOC_MISMATCH"
    assert "7777" in out["escalation_ticket"]["reason_text"]
    assert store.ledger.chargeback.hold_status == "HELD"


def test_a_readable_proof_for_the_wrong_amount_escalates(client):
    out = client.post("/a2a/dispatch", json=body(payload=clean_doc(amount=500))).json()

    assert out["status"] == "ESCALATED"
    assert out["escalation_ticket"]["reason_code"] == "DOC_MISMATCH"
    assert store.ledger.chargeback.hold_status == "HELD"


def test_case_10_a_close_deadline_escalates_as_urgent(client):
    client.post("/ledger/reset?chargeback_hours_left=6")
    out = client.post("/a2a/dispatch", json=body()).json()

    assert out["status"] == "ESCALATED"
    t = out["escalation_ticket"]
    assert t["reason_code"] == "DEADLINE_URGENT"
    assert t["urgency"] == "URGENT"
    assert t["deadline_iso"] is not None


def test_the_deadline_is_checked_before_the_document(client):
    """With six hours left AND a perfect document, both rules are true at once.

    The deadline wins, because it is the only one a person can still fix by picking up
    the phone. Whichever fires is what the employee reads on the ticket, so the order
    is pinned here rather than left to chance.
    """
    client.post("/ledger/reset?chargeback_hours_left=6")
    out = client.post("/a2a/dispatch", json=body(payload=clean_doc())).json()

    assert out["escalation_ticket"]["reason_code"] == "DEADLINE_URGENT"
    assert store.ledger.chargeback.hold_status == "HELD"


def test_a_passed_deadline_escalates_and_says_so(client):
    client.post("/ledger/reset?chargeback_hours_left=1")
    clock.freeze(clock.now().replace(hour=13))  # three hours later
    out = client.post("/a2a/dispatch", json=body(payload=clean_doc())).json()

    assert out["escalation_ticket"]["reason_code"] == "DEADLINE_URGENT"
    assert "passed" in out["escalation_ticket"]["reason_text"]


def test_an_urgent_chargeback_sorts_to_the_top_of_the_queue(client):
    from .test_stage2_dispatch import body as escalate_body
    client.post("/a2a/dispatch", json=escalate_body(request_id="normal"))

    client.post("/ledger/reset?chargeback_hours_left=6")
    client.post("/a2a/dispatch", json=escalate_body(request_id="normal2"))
    client.post("/a2a/dispatch", json=body(request_id="urgent"))

    queue = client.get("/tickets").json()["tickets"]
    assert queue[0]["reason_code"] == "DEADLINE_URGENT"
    assert queue[0]["urgency"] == "URGENT"


# --- the audit property --------------------------------------------------------------------

@pytest.mark.parametrize("payload, expected", [
    ({"txn_id": "9981"}, "ACTION_REQUIRED"),
    (clean_doc(confidence=0.62), "ESCALATED"),
    (clean_doc(order_id="7777"), "ESCALATED"),
    (clean_doc(amount=500), "ESCALATED"),
])
def test_ledger_ops_stays_idle_on_every_path_that_releases_nothing(client, payload, expected):
    out = client.post("/a2a/dispatch", json=body(payload=payload)).json()
    ops = next(e for e in out["agent_trace"] if e["agent"] == "LedgerOpsAgent")

    assert out["status"] == expected
    assert ops["acted"] is False
    assert ops["note"] == "No ledger change required"
    assert store.ledger.chargeback.hold_status == "HELD"


def test_ledger_ops_acts_exactly_once_on_the_path_that_does(client):
    out = client.post("/a2a/dispatch", json=body(payload=clean_doc())).json()
    ops = next(e for e in out["agent_trace"] if e["agent"] == "LedgerOpsAgent")

    assert ops["acted"] is True
    assert "released the 800 hold" in ops["note"]


def test_replaying_an_accepted_proof_does_not_release_twice(client):
    """The gate exists for exactly this: a second release would be real money."""
    first = client.post("/a2a/dispatch", json=body(payload=clean_doc())).json()
    before = client.get(f"/ledger/{MID}").json()["projected_net_payout_inr"]

    second = client.post("/a2a/dispatch", json=body(payload=clean_doc())).json()

    assert second == first
    assert client.get(f"/ledger/{MID}").json()["projected_net_payout_inr"] == before
    assert len(store.summaries) == 1


# --- the three payload shapes the team actually sends -----------------------------------------

def test_the_contract_delta_shape_is_accepted(client):
    """{order_id, txn_id, pod_submitted, pod_document, pod_source} per the V2 delta."""
    out = client.post("/a2a/dispatch", json=body(payload={
        "order_id": "9981", "txn_id": "9981", "pod_submitted": True,
        "pod_source": "SHIPROCKET_SYNC",
        "pod_document": {"order_id": "9981", "amount_inr": 800},
        "doc_confidence": 0.96,
    })).json()

    assert out["status"] == "RESOLVED"
    assert out["data"]["hold_status"] == "RELEASED"
    assert out["data"]["document"]["source"] == "SHIPROCKET_SYNC"


def test_person_1s_field_name_for_the_amount_is_accepted(client):
    """sarvam /doc-extract returns `amount`, where both specs say `amount_inr`."""
    out = client.post("/a2a/dispatch", json=body(payload={"txn_id": "9981", "doc": {
        "doc_type": "pod",
        "extracted_fields": {"order_id": "9981", "amount": 800, "signature_present": True},
        "confidence": 1.0,
    }})).json()

    assert out["status"] == "RESOLVED"
    assert out["data"]["document"]["amount_inr"] == 800


def test_a_claim_of_submission_with_no_document_is_a_bad_payload(client):
    r = client.post("/a2a/dispatch", json=body(payload={
        "txn_id": "9981", "pod_submitted": True,
    }))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_PAYLOAD"
    assert "no document fields or confidence" in r.json()["error"]["message"]


def test_a_dispute_we_do_not_have_is_a_bad_payload(client):
    r = client.post("/a2a/dispatch", json=body(payload={"txn_id": "1234"}))
    assert r.status_code == 400
    assert "9981" in r.json()["error"]["message"]


# --- wording ----------------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {"txn_id": "9981"},
    clean_doc(),
    clean_doc(confidence=0.62),
    clean_doc(order_id="7777"),
])
def test_nothing_accusatory_or_blaming_is_said(client, payload):
    out = client.post("/a2a/dispatch", json=body(payload=payload)).json()
    text = out["template_text"].lower()

    assert not any(w in text for w in BANNED_WORDS)
    # A blurry photo is not the merchant's fault, and the reply should not imply it.
    assert "your fault" not in text
    assert "you failed" not in text
