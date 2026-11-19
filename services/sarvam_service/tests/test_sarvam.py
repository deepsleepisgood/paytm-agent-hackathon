"""plan.md V2 smoke test for Person 1 (sarvam_service, :8001).

Covers: all 8 plan scenarios, intent-name aliases used across team docs, Option A/B/C
intervention evaluation, proactive shield / EDI-pause replies, use_sample_connector,
MOCK_MODE, and per-request reasoning_effort.
"""
import json
import re

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import main

BASE = "https://api.sarvam.ai"
PLAN_INTENTS = ("MANDATE_TROUBLESHOOT, SETTLEMENT_RECONCILE, CHARGEBACK_RESOLVE, UTR_VERIFY, "
                "DUPLICATE_RECONCILE, GROWTH_ADVISORY, CASHFLOW_EDI_SWITCH, ESCALATE_HUMAN")


def classify(client, text, system=f"Classify into one of: {PLAN_INTENTS}. Return JSON."):
    r = client.post("/llm", json={"system_prompt": system, "user_prompt": text, "response_format": "json"})
    assert r.status_code == 200
    return r.json()["parsed"]


# ------------------------------------------------------------------ the 8 plan.md scenarios
@pytest.mark.parametrize("text,intent", [
    ("Mera ₹500 ka loan EDI mandate fail ho gaya", "MANDATE_TROUBLESHOOT"),
    ("Bank ne autopay bounce kar diya, kisht nahi gayi", "MANDATE_TROUBLESHOOT"),
    ("₹4,160 kahan kata? settlement kam aaya", "SETTLEMENT_RECONCILE"),
    ("Order 9981 pe chargeback aaya hai", "CHARGEBACK_RESOLVE"),
    ("Customer ka screenshot fake lag raha hai, UTR 632184920555", "UTR_VERIFY"),
    ("Customer ne do baar payment kar diya same order ke liye", "DUPLICATE_RECONCILE"),
    ("Mere pichle 6 mahine ke data se business badhane ka suggestion do", "GROWTH_ADVISORY"),
    ("Refund ke baad payout kam hai, stock ke liye paisa nahi, EDI rok sakte ho?", "CASHFLOW_EDI_SWITCH"),
    ("Mera Soundbox kharab ho gaya, awaaz nahi aa rahi", "ESCALATE_HUMAN"),
    ("Mujhe kisi insaan se baat karni hai", "ESCALATE_HUMAN"),
])
def test_all_8_plan_intents(mock_client, text, intent):
    assert classify(mock_client, text)["intent"] == intent


# ------------------------------------------------------------------ name aliases across team docs
def test_uses_callers_intent_names(mock_client):
    # Person 2's prompt in the team chat uses different names for two intents
    alt = ("Intents: MANDATE_TROUBLESHOOT, SETTLEMENT_RECONCILE, CHARGEBACK_RESOLVE, UTR_VERIFY, "
           "DUPLICATE_PAYMENT_RECONCILE, WORKING_CAPITAL_ADVISORY, CASHFLOW_EDI_SWITCH, ESCALATE_HUMAN")
    assert classify(mock_client, "do baar payment ho gaya", alt)["intent"] == "DUPLICATE_PAYMENT_RECONCILE"
    assert classify(mock_client, "business badhane ka suggestion do", alt)["intent"] == "WORKING_CAPITAL_ADVISORY"

    # contract.md v1 list (6 intents): new scenarios map onto the closest old one
    v1 = "Intents: SETTLEMENT_RECONCILE, UTR_VERIFY, CHARGEBACK_RESOLVE, REFUND_MANAGE, FEE_GST_LOAN, ESCALATE_HUMAN"
    assert classify(mock_client, "EDI mandate fail ho gaya", v1)["intent"] == "FEE_GST_LOAN"
    assert classify(mock_client, "payout kam hai, EDI rok do", v1)["intent"] == "FEE_GST_LOAN"
    assert classify(mock_client, "Order 4412 ka refund", v1)["intent"] == "REFUND_MANAGE"


# ------------------------------------------------------------------ Option A/B/C evaluation
@pytest.mark.parametrize("text,intent,root", [
    ("Mera ₹500 ka loan EDI mandate fail ho gaya", "MANDATE_TROUBLESHOOT", "TEMPORARY_FRICTION"),
    ("Refund ke baad payout kam, EDI rok sakte ho?", "CASHFLOW_EDI_SWITCH", "CASHFLOW_SHORTFALL"),
    ("Order 9981 pe chargeback aaya", "CHARGEBACK_RESOLVE", "DISPUTE_WITH_EVIDENCE_AVAILABLE"),
    ("Pichle 6 mahine ke data se business badhane ka suggestion do", "GROWTH_ADVISORY", "GROWTH_OPPORTUNITY"),
])
def test_intervention_evaluation(mock_client, text, intent, root):
    system = (f"Diagnose the root cause, evaluate interventions Option A, B and C, score them and pick one. "
              f"Intents: {PLAN_INTENTS}. Return JSON.")
    p = classify(mock_client, text, system)
    assert p["intent"] == intent and p["root_cause"] == root
    assert [o["id"] for o in p["options"]] == ["A", "B", "C"]
    best = max(p["options"], key=lambda o: o["score"])
    assert p["selected_option"] == best["id"] == "B"
    assert p["selected_intervention"] and p["reason"] and p["reply_text"]


def test_plain_classification_has_no_evaluation_noise(mock_client):
    p = classify(mock_client, "Order 4412 ka refund kab gaya?", "Classify the merchant message. Return JSON.")
    assert "options" not in p and p["order_id"] == "4412"


# ------------------------------------------------------------------ spoken replies (proactive flows)
@pytest.mark.parametrize("paytm,expect", [
    ({"alert_id": "ALERT-9981", "status": "ALERT_RAISED", "trigger_type": "CHARGEBACK_INCOMING",
      "action_required": {"type": "SUBMIT_POD"}}, "Shiprocket"),
    ({"status": "OK", "intent": "CHARGEBACK_RESOLVE", "data": {"order_id": "9981", "status": "RELEASED"}}, "बधाई"),
    ({"alert_id": "ALERT-4490", "trigger_type": "HIGH_REFUND_CASHFLOW",
      "data": {"projected_net_payout": 1200, "edi_pause_offer": {"pause_days": 2}}}, "2 दिन रोक दूँ"),
    ({"status": "EDI_PAUSED", "data": {"loan_edi_status": "PAUSED_2_DAYS", "resume_date": "2026-11-21"}}, "21 नवंबर"),
    ({"status": "OK", "intent": "MANDATE_TROUBLESHOOT", "data": {"bounce_reason": "INSUFFICIENT_FUNDS"}}, "96%"),
    ({"status": "OK", "intent": "GROWTH_ADVISORY", "data": {}}, "2.3 गुना"),
    ({"status": "OK", "intent": "DUPLICATE_RECONCILE", "data": {}}, "दो बार"),
])
def test_hindi_replies_for_every_flow(mock_client, paytm, expect):
    reply = mock_client.post("/llm", json={"system_prompt": "Reply in warm Hindi, max 35 words",
                                           "user_prompt": json.dumps(paytm), "response_format": "text"}).json()["reply"]
    assert expect in reply
    assert len(reply.split()) <= 45  # plan.md asks for ~35 words; Devanagari tokenises a little long
    assert "mock" not in reply.lower()


# ------------------------------------------------------------------ sample connector
def test_sample_connector_pod_without_upload(mock_client):
    body = mock_client.post("/doc-extract", data={"doc_type": "pod", "use_sample_connector": "true"}).json()
    assert body["extracted_fields"]["order_id"] == "9981"
    assert body["extracted_fields"]["amount"] == 800
    assert body["extracted_fields"]["signature_present"] is True
    assert body["connector"]["name"] == "SHIPROCKET_SYNC" and body["connector"]["sample"] is True
    assert body["confidence"] == 1.0


def test_sample_connector_upi(mock_client):
    body = mock_client.post("/doc-extract", data={"doc_type": "upi_screenshot", "use_sample_connector": "true"}).json()
    assert body["extracted_fields"]["utr"] == "632184920111"


def test_doc_extract_needs_file_or_sample(mock_client):
    assert mock_client.post("/doc-extract", data={"doc_type": "pod"}).status_code == 422


def test_sample_images_ship_with_service():
    for meta in main.SAMPLE_DOCS.values():
        data = (main.SAMPLES_DIR / meta["file"]).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"


@respx.mock
def test_live_prewarm_makes_sample_instant(monkeypatch):
    from conftest import _use_settings

    _use_settings(monkeypatch, SARVAM_MODE="live", SARVAM_API_KEY="sk_test",
                  SARVAM_FALLBACK_TO_MOCK="false", SARVAM_DOC_POLL_INTERVAL="0")
    jobs = iter(range(100))

    def submit(_req):
        return httpx.Response(200, json={"job_id": f"j{next(jobs)}"})

    submit_route = respx.post(f"{BASE}/doc-ai/v1/job/extract").mock(side_effect=submit)
    respx.get(url__regex=rf"{BASE}/doc-ai/v1/job/j\d+/status").mock(return_value=httpx.Response(200, json={"status": "completed"}))
    respx.get(url__regex=rf"{BASE}/doc-ai/v1/job/j\d+/results").mock(return_value=httpx.Response(200, json={
        "result": {"order_id": "9981", "delivery_date": "2026-11-16", "recipient_name": "Rohit Verma",
                   "amount": 800, "signature_present": True}}))

    with TestClient(main.app) as client:  # `with` runs the startup warm-up
        body = client.post("/doc-extract", data={"doc_type": "pod", "use_sample_connector": "true"}).json()
        assert body["source"] == "sarvam" and body["connector"]["name"] == "SHIPROCKET_SYNC"
        jobs_after_first = submit_route.call_count
        client.post("/doc-extract", data={"doc_type": "pod", "use_sample_connector": "true"})
        assert submit_route.call_count == jobs_after_first == 2  # one warm-up job per sample type, then cache
        assert client.get("/health").json()["models"]["samples_ready"]["pod"] is True


# ------------------------------------------------------------------ config + LLM knobs
def test_mock_mode_env_alias(monkeypatch):
    from conftest import _use_settings

    s = _use_settings(monkeypatch, MOCK_MODE="true", SARVAM_API_KEY="sk_test")
    assert s.use_live is False


@respx.mock
def test_reasoning_effort_override(live_client):
    route = respx.post(f"{BASE}/v1/chat/completions").mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": "{\"selected_option\": \"B\"}"}}]}))
    r = live_client.post("/llm", json={"user_prompt": "evaluate", "response_format": "json", "reasoning_effort": "low"})
    assert r.json()["parsed"] == {"selected_option": "B"}
    assert json.loads(route.calls.last.request.content)["reasoning_effort"] == "low"


def test_health_reports_v2_models(mock_client):
    models = mock_client.get("/health").json()["models"]
    assert models["stt_mode"] == "codemix"
    assert models["tts"].startswith("bulbul:v4-flash")
