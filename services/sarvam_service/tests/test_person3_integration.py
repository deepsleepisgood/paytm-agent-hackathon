"""How Person 3 (merchant agent, :8003) actually calls us: 6 s timeout, JSON intent+slots,
then a Hindi rephrase of Paytm's answer that gets spoken. These tests pin that behaviour."""
import asyncio
import json
import time

import httpx
import pytest
import respx

from app import main, mock

BASE = "https://api.sarvam.ai"


def _client(monkeypatch, fallback: str):
    from fastapi.testclient import TestClient
    from conftest import _use_settings

    _use_settings(monkeypatch, SARVAM_MODE="live", SARVAM_API_KEY="sk_test",
                  SARVAM_FALLBACK_TO_MOCK=fallback, SARVAM_LATENCY_BUDGET="0.3")
    return TestClient(main.app)


@pytest.mark.parametrize("text,intent", [
    ("Bhaiya kal ka settlement 4160 kam kyun aaya?", "SETTLEMENT_RECONCILE"),
    ("मेरा कल का settlement कम आया है, पैसा कहाँ कटा?", "SETTLEMENT_RECONCILE"),
    ("Mere bank mein credit kam hua", "SETTLEMENT_RECONCILE"),  # 'credit' must not hit 'edi'
    ("Ye UTR 632184920111 check karo, customer bol raha paisa bhej diya", "UTR_VERIFY"),
    ("632184920999 wala payment aaya kya?", "UTR_VERIFY"),
    ("Order 9981 pe chargeback hold kyun laga?", "CHARGEBACK_RESOLVE"),
    ("ORDER #4412 ka refund kab gaya?", "REFUND_MANAGE"),
    ("GST 261 rupaye kyun kata? ITC milega?", "FEE_GST_LOAN"),
    ("Loan ki kisht kitni kategi kal?", "FEE_GST_LOAN"),
    ("Mujhe kisi insaan se baat karni hai", "ESCALATE_HUMAN"),
    ("मुझे किसी इंसान से बात करनी है", "ESCALATE_HUMAN"),
])
def test_mock_intent_routing(mock_client, text, intent):
    r = mock_client.post("/llm", json={"system_prompt": "classify", "user_prompt": text, "response_format": "json"})
    assert r.status_code == 200
    assert r.json()["parsed"]["intent"] == intent


def test_mock_slots_flat_and_nested(mock_client):
    p = mock_client.post("/llm", json={"user_prompt": "UTR 632184920111 ka ₹1,250 payment check karo",
                                       "response_format": "json"}).json()["parsed"]
    assert p["utr_number"] == "632184920111" and p["amount"] == 1250 and p["order_id"] is None
    assert p["slots"] == {"utr_number": "632184920111", "order_id": None, "amount": 1250}

    p = mock_client.post("/llm", json={"user_prompt": "TXNID #9981 pe 800 rupaye hold", "response_format": "json"}).json()["parsed"]
    assert p["order_id"] == "9981" and p["amount"] == 800

    p = mock_client.post("/llm", json={"user_prompt": "#632184920111", "response_format": "json"}).json()["parsed"]
    assert p["utr_number"] == "632184920111" and p["order_id"] is None


@pytest.mark.parametrize("paytm_json,expect", [
    ({"status": "OK", "intent": "SETTLEMENT_RECONCILE", "data": {"variance": 4160}}, "₹95,840"),
    ({"status": "OK", "intent": "UTR_VERIFY", "data": {"utr": "632184920999", "status": "PENDING"}}, "pending"),
    ({"status": "OK", "intent": "UTR_VERIFY", "data": {"utr": "632184920555", "status": "NOT_FOUND_SUSPECTED_FAKE"}}, "नहीं मिला"),
    ({"status": "OK", "intent": "UTR_VERIFY", "data": {"utr": "632184920111", "status": "SUCCESS"}}, "सफल"),
    ({"status": "OK", "intent": "CHARGEBACK_RESOLVE", "data": {"order_id": "9981"}}, "POD"),
    ({"status": "OK", "intent": "REFUND_MANAGE", "data": {"order_id": "4412"}}, "₹1,500"),
    ({"status": "OK", "intent": "FEE_GST_LOAN", "data": {"gst": 261}}, "Input Tax Credit"),
    ({"status": "ESCALATED", "intent": "ESCALATE_HUMAN", "escalation_ticket": {"id": "T1"}}, "सपोर्ट"),
])
def test_mock_spoken_reply_for_each_paytm_answer(mock_client, paytm_json, expect):
    prompt = "Paytm response:\n" + json.dumps(paytm_json)
    reply = mock_client.post("/llm", json={"system_prompt": "Reply in Hindi", "user_prompt": prompt,
                                           "response_format": "text"}).json()["reply"]
    assert expect in reply
    assert "mock" not in reply.lower()  # never speak debug text to the merchant


def test_seed_settlement_reply_adds_up():
    # 1450 + 261 + 1500 + 149 + 800 = 4160 (contract.md)
    assert 1450 + 261 + 1500 + 149 + 800 == 4160 == 100000 - 95840
    for amount in ("₹1,450", "₹261", "₹1,500", "₹149", "₹800", "₹4,160", "₹95,840"):
        assert amount in mock._REPLIES["SETTLEMENT_RECONCILE"]


@respx.mock
def test_slow_sarvam_never_exceeds_callers_6s_timeout(monkeypatch):
    """If Sarvam is slow, we answer from mock inside the budget instead of making Person 3 time out."""
    client = _client(monkeypatch, fallback="true")

    async def slow(_request):
        await asyncio.sleep(2)
        return httpx.Response(200, json={"choices": [{"message": {"content": "late"}}]})

    respx.post(f"{BASE}/v1/chat/completions").mock(side_effect=slow)
    started = time.perf_counter()
    r = client.post("/llm", json={"user_prompt": "refund kab aayega", "response_format": "text"})
    assert time.perf_counter() - started < 1.5
    assert r.status_code == 200 and r.json()["source"] == "mock"


@respx.mock
def test_slow_sarvam_without_fallback_returns_504(monkeypatch):
    client = _client(monkeypatch, fallback="false")

    async def slow(_request):
        await asyncio.sleep(2)
        return httpx.Response(200, json={})

    respx.post(f"{BASE}/text-to-speech").mock(side_effect=slow)
    r = client.post("/tts", json={"text": "नमस्ते", "language_code": "hi-IN"})
    assert r.status_code == 504
