"""Stage 5 — the V2 delta: Paytm speaks first, and pauses the loan when told to.

These are the two endpoints Person 3's proactive demo calls. If their shapes drift, the
teammates' flow breaks, so the assertions here are deliberately literal about field
names and values taken from the contract.
"""
from __future__ import annotations

import pytest

from app import seed, store

MID = "PAYTM_MERCH_8821"


# --- the alert ------------------------------------------------------------------------

def test_chargeback_alert_matches_the_contract(client):
    r = client.post("/a2a/proactive-alert",
                    json={"mid": MID, "trigger_type": "CHARGEBACK_INCOMING"})
    assert r.status_code == 200
    out = r.json()

    assert out["alert_id"] == "ALERT-9981"
    assert out["status"] == "ALERT_RAISED"
    assert out["intent"] == "CHARGEBACK_RESOLVE"
    assert out["trigger_type"] == "CHARGEBACK_INCOMING"
    assert out["data"] == {
        "txn_id": "9981", "order_id": "9981", "amount": 800, "deadline_hours": 48,
    }
    assert out["action_required"]["type"] == "SUBMIT_POD"
    assert out["escalation_ticket"] is None


def test_cashflow_alert_matches_the_contract(client):
    out = client.post("/a2a/proactive-alert",
                      json={"mid": MID, "trigger_type": "HIGH_REFUND_CASHFLOW"}).json()

    assert out["alert_id"] == "ALERT-4490"
    assert out["intent"] == "FEE_GST_LOAN"
    assert out["data"]["refund_request"] == {"order_id": "4490", "amount": 3500}
    assert out["data"]["projected_net_payout"] == 1200

    offer = out["data"]["edi_pause_offer"]
    assert offer["offer_id"] == "EDIOFFER-0001"
    assert offer["eligible"] is True
    assert offer["nbfc"] == "Clix Capital"
    assert offer["pause_days"] == 2
    assert offer["edi_saved_inr"] == 1000
    assert offer["kfs_clause"] == "4.2"

    assert out["action_required"]["type"] == "CONFIRM_EDI_PAUSE"


def test_the_projected_payout_is_calculated_not_hardcoded():
    """5,200 expected tomorrow, minus the 3,500 refund, minus the 500 EDI = 1,200."""
    led = store.ledger
    assert led.projected_gross_tomorrow_inr == 5_200
    assert led.pending_refund_inr == 3_500
    assert led.loan.edi_due_tomorrow_inr == 500
    assert led.projected_net_payout_inr() == 1_200


def test_pausing_the_edi_visibly_improves_the_projection(client):
    """The number the merchant is shown has to move, or the offer means nothing."""
    before = client.post("/a2a/proactive-alert",
                         json={"mid": MID, "trigger_type": "HIGH_REFUND_CASHFLOW"}).json()
    offer_id = before["data"]["edi_pause_offer"]["offer_id"]
    assert before["data"]["projected_net_payout"] == 1200

    client.post("/a2a/execute-edi-pause",
                json={"mid": MID, "consent_token": "DPDP_VERIFIED_TS_1763", "offer_id": offer_id})

    assert store.ledger.projected_net_payout_inr() == 1700  # the 500 stays with the merchant


def test_an_alert_needs_no_consent_token(client):
    """It only tells the merchant about their own account; nothing is shared onward."""
    r = client.post("/a2a/proactive-alert",
                    json={"mid": MID, "trigger_type": "CHARGEBACK_INCOMING"})
    assert r.status_code == 200


def test_raising_the_same_alert_twice_does_not_duplicate_it(client):
    """The frontend simulates the webhook, and a rehearsed demo clicks it twice."""
    first = client.post("/a2a/proactive-alert",
                        json={"mid": MID, "trigger_type": "HIGH_REFUND_CASHFLOW"}).json()
    second = client.post("/a2a/proactive-alert",
                         json={"mid": MID, "trigger_type": "HIGH_REFUND_CASHFLOW"}).json()

    assert first == second
    assert len(store.alerts) == 1
    assert len(store.edi_offers) == 1  # not a second offer id


def test_alerts_stay_out_of_the_merchant_call_feed(client):
    """Paytm raised these. Counting them as merchant calls would flatter the metrics."""
    client.post("/a2a/proactive-alert", json={"mid": MID, "trigger_type": "CHARGEBACK_INCOMING"})
    client.post("/a2a/proactive-alert", json={"mid": MID, "trigger_type": "HIGH_REFUND_CASHFLOW"})

    assert client.get("/summaries").json()["summaries"] == []
    m = client.get("/metrics").json()
    assert m["calls_total"] == 0
    assert m["proactive_alerts"] == 2


@pytest.mark.parametrize("trigger, code, status", [
    ("NONSENSE", "BAD_PAYLOAD", 400),
])
def test_bad_trigger_is_rejected(client, trigger, code, status):
    r = client.post("/a2a/proactive-alert", json={"mid": MID, "trigger_type": trigger})
    assert r.status_code == status
    assert r.json()["error"]["code"] == code


def test_alert_for_an_unknown_merchant(client):
    r = client.post("/a2a/proactive-alert",
                    json={"mid": "NOPE", "trigger_type": "CHARGEBACK_INCOMING"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "UNKNOWN_MID"


# --- the pause ------------------------------------------------------------------------

def offer_id(client) -> str:
    out = client.post("/a2a/proactive-alert",
                      json={"mid": MID, "trigger_type": "HIGH_REFUND_CASHFLOW"}).json()
    return out["data"]["edi_pause_offer"]["offer_id"]


def test_pause_matches_the_contract(client):
    oid = offer_id(client)
    r = client.post("/a2a/execute-edi-pause", json={
        "mid": MID, "consent_token": "DPDP_VERIFIED_TS_1763", "pause_days": 2, "offer_id": oid,
    })
    assert r.status_code == 200
    out = r.json()

    assert out["status"] == "EDI_PAUSED"
    assert out["intent"] == "FEE_GST_LOAN"
    data = out["data"]
    assert data["loan_edi_status"] == "PAUSED_2_DAYS"
    assert data["nbfc"] == "Clix Capital"
    assert data["pause_days"] == 2
    assert data["edi_saved_inr"] == 1000
    assert data["edi_tomorrow"] == 0
    assert data["resume_date"] == "2026-11-21"
    assert out["action_required"] is None


def test_the_consent_artifact_records_why_this_was_allowed(client):
    oid = offer_id(client)
    out = client.post("/a2a/execute-edi-pause", json={
        "mid": MID, "consent_token": "DPDP_VERIFIED_TS_1763", "offer_id": oid,
    }).json()

    artifact = out["data"]["kfs_consent_artifact"]
    assert artifact["artifact_id"] == "KFS-ART-0001"
    assert artifact["clause"] == "4.2"
    assert artifact["consent_token"] == "DPDP_VERIFIED_TS_1763"
    assert isinstance(artifact["ts"], int)


def test_no_consent_token_is_403_not_400(client):
    """The contract's DPDP guardrail. /a2a/dispatch answers 400 for a missing token;
    this endpoint must answer 403, because Person 3 branches on it."""
    oid = offer_id(client)
    for token in (None, "", "   "):
        r = client.post("/a2a/execute-edi-pause",
                        json={"mid": MID, "consent_token": token, "offer_id": oid})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "DPDP_CONSENT_REQUIRED"

    # And nothing was changed.
    assert store.ledger.loan.status == "ACTIVE"


def test_more_than_two_days_is_refused_by_the_kfs_clause(client):
    oid = offer_id(client)
    r = client.post("/a2a/execute-edi-pause", json={
        "mid": MID, "consent_token": "ct", "pause_days": 3, "offer_id": oid,
    })
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EDI_PAUSE_NOT_ELIGIBLE"
    assert "4.2" in r.json()["error"]["message"]
    assert store.ledger.loan.status == "ACTIVE"


def test_pausing_twice_is_refused(client):
    oid = offer_id(client)
    first = client.post("/a2a/execute-edi-pause",
                        json={"mid": MID, "consent_token": "ct", "offer_id": oid})
    assert first.status_code == 200

    second = client.post("/a2a/execute-edi-pause",
                         json={"mid": MID, "consent_token": "ct", "offer_id": oid})
    assert second.status_code == 409
    assert "already" in second.json()["error"]["message"].lower()


def test_a_pause_with_no_offer_is_refused(client):
    """Nobody pauses a loan without an offer having been made and seen."""
    r = client.post("/a2a/execute-edi-pause",
                    json={"mid": MID, "consent_token": "ct", "offer_id": "EDIOFFER-9999"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EDI_PAUSE_NOT_ELIGIBLE"

    missing = client.post("/a2a/execute-edi-pause",
                          json={"mid": MID, "consent_token": "ct"})
    assert missing.status_code == 409


# --- the ledger and the reset ----------------------------------------------------------

def test_ledger_reports_the_edi_status_and_connector_consent(client):
    led = client.get(f"/ledger/{MID}").json()

    assert led["loan_edi_status"] == "ACTIVE"
    assert led["projected_net_payout_inr"] == 1200

    keys = {c["key"]: c for c in led["connectors"]}
    assert set(keys) == {"SHIPROCKET_SYNC", "VYAPAR_POS_SYNC", "ACTIVE_LOAN_KFS"}
    assert all(c["consent"] == "GRANTED" for c in keys.values())
    # Consent state only: we never hold what is inside the merchant's connectors.
    assert all(set(c) == {"key", "state", "consent"} for c in keys.values())

    assert led["loan"]["nbfc"] == "Clix Capital"
    assert led["loan"]["kfs_clause"] == "4.2"
    assert led["loan"]["max_pause_days"] == 2


def test_the_ledger_shows_the_pause_after_it_happens(client):
    oid = offer_id(client)
    client.post("/a2a/execute-edi-pause",
                json={"mid": MID, "consent_token": "ct", "offer_id": oid})

    led = client.get(f"/ledger/{MID}").json()
    assert led["loan_edi_status"] == "PAUSED_2_DAYS"
    assert led["loan"]["edi_tomorrow"] == 0
    assert led["loan"]["resume_date"] == "2026-11-21"
    assert led["projected_net_payout_inr"] == 1700


def test_reset_puts_the_edi_back_so_the_demo_can_run_again(client):
    oid = offer_id(client)
    client.post("/a2a/execute-edi-pause",
                json={"mid": MID, "consent_token": "ct", "offer_id": oid})
    assert store.ledger.loan.status == "PAUSED_2_DAYS"

    client.post("/ledger/reset")

    assert store.ledger.loan.status == "ACTIVE"
    assert store.ledger.loan.resume_date is None
    assert store.alerts == {}
    assert store.edi_offers == {}


# --- nothing from stages 1 to 4 moved --------------------------------------------------

def test_the_new_pending_refund_did_not_disturb_yesterdays_settlement(client):
    """Order 4490 is PENDING, so it must not appear in the settlement that already ran."""
    led = client.get(f"/ledger/{MID}").json()
    assert led["settlement"]["variance_inr"] == 4160
    assert sum(l["amount_inr"] for l in led["settlement"]["lines"]) == 4160
    assert led["settlement"]["reconciles"] is True

    refund_line = next(l for l in led["settlement"]["lines"] if l["code"] == "CUSTOMER_REFUND")
    assert refund_line["amount_inr"] == 1500
    assert "4412" in refund_line["label"]
