"""Compatibility with Person 2's real 8002 (services/paytm_agent), using response bodies recorded from it.

8002 answers every intent with status RESOLVED | ACTION_REQUIRED | ESCALATED and the specifics in `data`;
it rejects payloads missing its field names with 400 BAD_PAYLOAD. These tests pin what 8003 sends and how it
reads the answers (upstream.interpret), so the merchant-side ITC log, fraud alert, replies and khata work live.
"""
import httpx
import pytest

import upstream
from conftest import MID, NO_DATASET, ask, use_dataset

TRACE = [{"step": i + 1, "agent": a, "acted": True, "note": "live"} for i, a in enumerate(upstream.AGENTS)]

RECORDED = {  # trimmed bodies from 8002 at commit 70d0f8a
    "SETTLEMENT_RECONCILE": ("RESOLVED", {
        "settlement_date": "2026-11-18", "gross_inr": 100000, "net_credit_inr": 95840, "variance_inr": 4160,
        "lines": [{"code": "MDR_FEE", "label": "Payment fees", "amount_inr": 1450},
                  {"code": "GST_ON_MDR", "label": "GST on fees", "amount_inr": 261},
                  {"code": "CUSTOMER_REFUND", "label": "Refund for order 4412", "amount_inr": 1500},
                  {"code": "SOUNDBOX_RENTAL", "label": "Soundbox rental", "amount_inr": 149},
                  {"code": "CHARGEBACK_HOLD", "label": "Held for dispute on order 9981", "amount_inr": 800}],
        "lines_total_inr": 4160, "reconciles": True}, None),
    "UTR_VERIFY": ("RESOLVED", {"utr": "632184920555", "lookup_status": "NOT_FOUND", "amount_inr": None,
                                "advice": "DO_NOT_RELEASE_YET", "internal_flag": "POSSIBLE_FAKE"}, None),
    "CHARGEBACK_RESOLVE": ("RESOLVED", {"txn_id": "9981", "order_id": "9981", "amount_held_inr": 800, "hours_left": 48.0,
                                        "evidence_status": "SUBMITTED", "hold_status": "RELEASED"}, None),
    "DUPLICATE_RECONCILE": ("RESOLVED", {
        "duplicates_found": 1, "order_id": "4455", "order_amount_inr": 3200,
        "payments": [{"utr": "632184925001"}, {"utr": "632184925002"}], "keep": {"utr": "632184925001"},
        "refund": {"utr": "632184925002", "amount_inr": 3200}, "refund_status": "PROCESSED"}, None),
    "MANDATE_TROUBLESHOOT": ("ACTION_REQUIRED", {
        "mandate_id": "ENACH_8821_01", "status": "BOUNCED", "amount_inr": 500, "bounce_date": "2026-11-19",
        "bounce_reason": "INSUFFICIENT_FUNDS", "is_default": False, "nbfc": "Clix Capital",
        "remedies": [{"type": "PAY_NOW_UPI_LINK", "amount_inr": 500, "valid_hours": 24},
                     {"type": "KFS_HARDSHIP_PAUSE", "offer_id": "EDIOFFER-0001", "eligible": True, "nbfc": "Clix Capital",
                      "pause_days": 2, "edi_saved_inr": 1000, "kfs_clause": "4.2"}]},
        {"type": "CHOOSE_REMEDY", "options": ["PAY_NOW_UPI_LINK", "KFS_HARDSHIP_PAUSE"], "amount_inr": 500}),
    "GROWTH_ADVISORY": ("RESOLVED", {"sales": {"avg_daily_sales_inr": 32000, "weekend_multiplier": 2.3},
                                     "credit_offer": {"pre_approved_inr": 150000, "nbfc": "Clix Capital",
                                                      "kfs_required": True}}, None),
}
REQUIRED = {"UTR_VERIFY": "utr", "ESCALATE_HUMAN": "reason_code"}  # 8002 answers 400 BAD_PAYLOAD without these


@pytest.fixture(autouse=True)
def live_8002(client, monkeypatch):
    sent: list[dict] = []

    async def fake(base, path, **kwargs):
        req = httpx.Request("POST", f"{base}{path}")
        if path == "/a2a/dispatch":
            env = kwargs["json"]
            sent.append(env)
            intent, p = env["intent"], env["payload"]
            if intent in REQUIRED and not p.get(REQUIRED[intent]):
                return httpx.Response(400, request=req, json={"error": {"code": "BAD_PAYLOAD", "message": "missing"}})
            if intent == "ESCALATE_HUMAN":
                ticket = {"ticket_id": "tkt_001", "reason_code": p["reason_code"], "reason_text": p.get("reason_text")}
                return httpx.Response(200, request=req, json={"status": "ESCALATED", "intent": intent, "data": {"ticket_id": "tkt_001"},
                                                              "agent_trace": TRACE, "escalation_ticket": ticket})
            if intent not in RECORDED:
                return httpx.Response(400, request=req, json={"error": {"code": "UNKNOWN_INTENT", "message": intent}})
            status, data, ar = RECORDED[intent]
            return httpx.Response(200, request=req, json={"status": status, "intent": intent, "data": data,
                                                          "agent_trace": TRACE, "action_required": ar,
                                                          "template_text": "English text", "escalation_ticket": None})
        raise httpx.ConnectError("8001 down", request=req)

    monkeypatch.setattr(upstream, "_post", fake)
    use_dataset(NO_DATASET)
    client.post("/reset")
    yield sent
    client.post("/reset")


def test_envelope_has_person2_fields(client, live_8002):
    ask(client, "UTR 632184920555 check karo")
    env = live_8002[-1]
    assert env["session_id"].startswith("SESS_") and env["language_code"] == "hi-IN"
    assert env["payload"]["utr"] == "632184920555" and env["payload"]["source"] == "voice"
    assert "merchant_said" not in env  # DPDP data minimisation


def test_settlement_lines_log_itc(client):
    body = ask(client, "Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?").json()
    # D1 shape: `status` is the specific outcome (the frontend keys on it); 8002's own status is `mesh_status`
    assert body["paytm_source"] == "live" and body["paytm_response"]["status"] == "RECONCILED"
    assert body["paytm_response"]["mesh_status"] == "RESOLVED" and body["paytm_response"]["status_detail"] == "RECONCILED"
    assert body["paytm_response"]["data"]["lines_total_inr"] == 4160  # data stays 8002's raw body
    assert body["gst_itc_logged"]["amount"] == 261
    assert "GST ₹261" in body["reply_text"] and "#9981 ka ₹800 chargeback hold" in body["reply_text"]
    assert len(body["paytm_agent_trace"]) == 4


def test_not_found_utr_raises_fraud_alert(client):
    body = ask(client, "UTR 632184920555 check karo").json()
    assert body["paytm_source"] == "live" and body["fraud_alert"]["priority"] == "HIGH"
    assert "saman mat dijiye" in body["reply_text"] and "fake" not in body["reply_text"].lower()


def test_chargeback_release_is_read_from_hold_status(client):
    body = client.post("/merchant/upload-doc", files={"file": ("pod_9981.png", b"img", "image/png")},
                       data={"doc_type": "pod", "mid": MID, "consent_granted": "true"}).json()
    assert body["paytm_response"]["status_detail"] == "RELEASED" and "RELEASED" in body["reply_text"]
    k = client.get("/merchant/khata-export").json()
    assert any(v["status"] == "CHARGEBACK_RELEASED" for v in k["vouchers"])


def test_duplicate_uses_paytm_amounts_and_drops_mismatched_tip(client):
    body = ask(client, "customer ne do baar payment kar diya").json()
    assert "₹3,200" in body["reply_text"] and "None" not in body["reply_text"]
    assert "Sunita" not in body["reply_text"]  # our books name order 4489's payer; Paytm matched 4455


def test_mandate_remedies_and_pause_offer(client):
    body = ask(client, "Mera ₹500 ka loan EDI mandate fail ho gaya").json()
    assert body["paytm_response"]["status_detail"] == "REMEDIES_OFFERED"
    assert body["verified_outcome"]["outcome"] == "PENDING"  # nothing resolved yet: not learned
    pa = body["pending_action"]
    assert pa["type"] == "CHOOSE_REMEDY" and pa["offer_id"] == "EDIOFFER-0001"
    assert "UPI link" in body["reply_text"] and "bheja hai" not in body["reply_text"]  # 8002 offered, didn't send
    assert "EDIOFFER-0001" in [o["offer_id"] for o in client.get("/events").json()["pending_actions"]["edi_pause_offers"]]


def test_growth_quotes_no_invented_rate(client):
    body = ask(client, "Mere pichle 6 mahine ke data se business badhane ka suggestion do").json()
    assert body["paytm_response"]["status_detail"] == "OFFER_PREAPPROVED"
    assert "₹1,50,000" in body["reply_text"] and "APR" not in body["reply_text"]


def test_escalation_sends_reason_code_and_diagnostics(client, live_8002):
    body = ask(client, "mera soundbox kharab ho gaya").json()
    p = live_8002[-1]["payload"]
    assert p["reason_code"] == "MERCHANT_REQUESTED_HUMAN" and "Soundbox" in p["reason_text"] and p["tried"]
    assert body["paytm_source"] == "live" and "tkt_001" in body["reply_text"] and "Soundbox" in body["reply_text"]


def test_unknown_intents_fall_back_to_mock(client):
    body = ask(client, "soundbox wapas karna hai").json()
    assert body["paytm_source"] == "mock" and body["paytm_response"]["status"] == "RETURN_INITIATED"


# ----------------------------------------------------------------------------- found in the full-stack check

GROWTH_V2 = {"sales": {"avg_daily_sales_inr": 32000, "weekend_multiplier": 2.3, "restock_by": "Thursday", "months": 6},
             "weekend_daily_sales_inr": 73600,
             "existing_loan": {"nbfc": "Clix Capital", "balance_inr": 42000, "edi_per_day_inr": 500},
             "share_of_daily_takings_repaid_percent": 1.56, "new_facility_offered": False}


def test_frontend_effects_get_the_specific_status(client):
    body = client.post("/merchant/upload-doc", files={"file": ("pod_9981.png", b"img", "image/png")},
                       data={"doc_type": "pod", "mid": MID, "consent_granted": "true"}).json()
    pr = body["paytm_response"]
    assert pr["status"] == "RELEASED" and pr["mesh_status"] == "RESOLVED"  # live.js: status === 'RELEASED'
    assert pr["data"]["hold_status"] == "RELEASED"


def test_growth_advice_without_credit_offer(client, monkeypatch):
    monkeypatch.setitem(RECORDED, "GROWTH_ADVISORY", ("RESOLVED", GROWTH_V2, None))
    body = ask(client, "Mere pichle 6 mahine ke data se business badhane ka suggestion do").json()
    assert body["paytm_response"]["status"] == "ADVICE_READY"
    assert "Guruvaar" in body["reply_text"] and "pre-approved" not in body["reply_text"]


def test_refund_over_limit_without_order_goes_to_a_person(client, live_8002):
    body = ask(client, "Customer ko ₹6,500 wapas karna hai").json()
    p = live_8002[-1]["payload"]
    assert p["action"] == "INITIATE" and p["amount_inr"] == 6500
    assert body["paytm_response"]["status"] == "ESCALATED"
    assert "4412" not in body["reply_text"] and "PROCESSED" not in body["reply_text"]


def test_refund_status_question_is_not_an_initiate(client, live_8002):
    ask(client, "order 4412 ka refund hua kya?")
    assert live_8002[-1]["payload"]["action"] == "STATUS"
