"""Smoke tests for the Merchant AI Teammate, run fully offline against the built-in seed.

8001/8002 point at a dead port (see conftest.py), so every upstream call exercises its fallback.
Run:  python -m pytest -q   (from services/merchant_agent)
"""
from datetime import date

import pytest

import router
from conftest import MID, NO_DATASET, ask, use_dataset


@pytest.fixture(scope="module", autouse=True)
def _builtin_seed():
    use_dataset(NO_DATASET)  # deterministic: CONTRACT.md values, whatever is in dataset/


@pytest.fixture(autouse=True)
def _reset(client):
    client.post("/reset")


# ------------------------------------------------------------------ router unit tests


@pytest.mark.parametrize(
    "text,intent",
    [
        ("Mera kal ka settlement 4160 kam kyun aaya?", "SETTLEMENT_RECONCILE"),
        ("मेरे पैसे कम क्यों आए?", "SETTLEMENT_RECONCILE"),
        ("UTR 632184920111 ka payment aaya kya?", "UTR_VERIFY"),
        ("ye screenshot fake to nahi?", "UTR_VERIFY"),
        ("Order 9981 ka chargeback hold kyun hai", "CHARGEBACK_RESOLVE"),
        ("order #4412 ka refund status batao", "REFUND_MANAGE"),
        ("GST ka ITC kitna milega aur loan EDI kitni hai", "FEE_GST_LOAN"),
        ("मेरा लोन कितना बाकी है", "FEE_GST_LOAN"),
        ("mujhe kisi insaan se baat karni hai", "ESCALATE_HUMAN"),
        ("namaste", "SETTLEMENT_RECONCILE"),
        ("Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?", "SETTLEMENT_RECONCILE"),
        ("mera soundbox kharab ho gaya, awaaz nahi aa rahi", "ESCALATE_HUMAN"),
        ("साउंडबॉक्स बंद हो गया है", "ESCALATE_HUMAN"),
        ("soundbox ka rental kitna kata", "FEE_GST_LOAN"),
    ],
)
def test_keyword_intent(text, intent):
    assert router.keyword_intent(text) == intent


def test_extract_slots():
    s = router.extract_slots("UTR 632184920111 ka ₹1,250 order #4412 kal", today=date(2026, 11, 19))
    assert s.utr_number == "632184920111"
    assert s.order_id == "4412"
    assert s.amount == 1250
    assert s.date == "2026-11-18"


# ------------------------------------------------------------------ endpoint smoke tests


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_consent_required(client):
    r = ask(client, "settlement kam aaya", consent=False)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "DPDP_CONSENT_REQUIRED"
    types = [e["type"] for e in client.get("/events").json()["a2a_events"]]
    assert types == ["DPDP_CONSENT_DENIED"]  # nothing sent to Paytm


@pytest.mark.parametrize(
    "text,intent,status",
    [
        ("Mera kal ka settlement 4160 kam kyun aaya?", "SETTLEMENT_RECONCILE", "RECONCILED"),
        ("UTR 632184920111 ka payment aaya kya?", "UTR_VERIFY", "SUCCESS"),
        ("UTR 632184920999 check karo", "UTR_VERIFY", "PENDING"),
        ("Order 9981 ka chargeback hold kyun hai", "CHARGEBACK_RESOLVE", "HELD"),
        ("order #4412 ka refund status batao", "REFUND_MANAGE", "PROCESSED"),
        ("GST ka ITC aur loan EDI batao", "FEE_GST_LOAN", "OK"),
        ("mujhe manager se baat karni hai", "ESCALATE_HUMAN", "ESCALATED"),
    ],
)
def test_all_intents_offline(client, text, intent, status):
    r = ask(client, text)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == intent
    assert body["intent_source"] == "keyword_fallback"
    assert body["paytm_source"] == "mock"
    assert body["paytm_response"]["status"] == status
    assert body["consent_token"].startswith("DPDP_VERIFIED_TS_")
    assert body["reply_source"] == "template" and len(body["reply_text"]) > 20
    types = [e["type"] for e in body["a2a_events"]]
    for t in ("DPDP_CONSENT_VERIFIED", "INTENT_CLASSIFIED", "MERCHANT_TO_PAYTM", "PAYTM_TO_MERCHANT", "VOICE_REPLY_READY"):
        assert t in types
    m2p = next(e for e in body["a2a_events"] if e["type"] == "MERCHANT_TO_PAYTM")["payload"]
    assert set(m2p) == {"request_id", "mid", "intent", "selected_intervention", "payload", "consent_token",
                        "session_id", "language_code"}
    assert "text" not in m2p["payload"]  # data minimisation: raw utterance never leaves merchant side


def test_gst_itc_logged_once(client):
    ask(client, "settlement kam kyun aaya")
    body = ask(client, "GST ITC kitna hai").json()
    assert body["gst_itc_logged"] is None  # same settlement's ITC not double-counted
    ev = client.get("/events").json()
    assert [e["amount"] for e in ev["local_gst_itc_log"]] == [261]
    assert ev["gst_itc_total"] == 261


def test_fake_utr_raises_fraud_alert(client):
    body = ask(client, "UTR 999988887777 ka payment aaya kya").json()
    assert body["paytm_response"]["status"] == "NOT_FOUND_SUSPECTED_FAKE"
    assert body["fraud_alert"]["priority"] == "HIGH"
    assert "FRAUD_ALERT" in [e["type"] for e in body["a2a_events"]]
    assert len(client.get("/events").json()["fraud_alerts"]) == 1


def test_upload_pod_resolves_chargeback(client):
    r = client.post(
        "/merchant/upload-doc",
        files={"file": ("pod.jpg", b"fake-image-bytes", "image/jpeg")},
        data={"doc_type": "pod", "mid": MID, "consent_granted": "true"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "CHARGEBACK_RESOLVE"
    assert body["paytm_response"]["status"] == "RELEASED"
    assert "DOC_EXTRACTED" in [e["type"] for e in body["a2a_events"]]


def test_upload_fake_screenshot(client):
    r = client.post(
        "/merchant/upload-doc",
        files={"file": ("upi_123456789012.png", b"img", "image/png")},
        data={"doc_type": "upi_screenshot", "mid": MID, "consent_granted": "true"},
    )
    body = r.json()
    assert body["intent"] == "UTR_VERIFY"
    assert body["slots"]["utr_number"] == "123456789012"
    assert body["fraud_alert"] is not None


def test_upload_requires_consent(client):
    r = client.post(
        "/merchant/upload-doc",
        files={"file": ("pod.jpg", b"x", "image/jpeg")},
        data={"doc_type": "pod", "mid": MID, "consent_granted": "false"},
    )
    assert r.status_code == 403


def test_query_audio_falls_back_to_mock_transcript(client):
    r = client.post(
        "/merchant/query-audio",
        files={"audio": ("q.wav", b"RIFF....", "audio/wav")},
        data={"mid": MID, "consent_granted": "true"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transcript_source"] == "mock"
    assert body["intent"] == "SETTLEMENT_RECONCILE"
    assert body["a2a_events"][0]["type"] == "DPDP_CONSENT_VERIFIED"  # consent before STT


def test_reset(client):
    ask(client, "settlement kam kyun aaya")
    assert client.post("/reset").json()["status"] == "reset"
    ev = client.get("/events").json()
    assert ev["a2a_events"] == [] and ev["local_gst_itc_log"] == []


# ------------------------------------------------------------------ PLAN.md demo paths


def test_golden_path_settlement(client):
    body = ask(client, "Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?").json()
    assert body["intent"] == "SETTLEMENT_RECONCILE"
    assert body["gst_itc_logged"]["amount"] == 261
    assert "9981" in body["reply_text"] and "₹800" in body["reply_text"]
    # every deduction labelled correctly (GST_ON_MDR once came out as "MDR ₹261")
    for part in ("MDR ₹1,450", "GST ₹261", "refund ₹1,500", "soundbox ₹149", "#9981 का ₹800 chargeback hold"):
        assert part in body["reply_text"], (part, body["reply_text"])


def test_template_replies_within_word_budget(client):
    for text in ["settlement kam kyun aaya", "UTR 632184920111 check", "UTR 999988887777 check",
                 "chargeback 9981 hold", "refund 4412", "GST loan EDI", "manager se baat"]:
        client.post("/reset")
        reply = ask(client, text).json()["reply_text"]
        assert len(reply.split()) <= 35, (text, len(reply.split()), reply)


def test_fake_upi_png_triggers_fraud_offline(client):
    r = client.post(
        "/merchant/upload-doc",
        files={"file": ("fake_upi.png", b"img", "image/png")},
        data={"doc_type": "upi_screenshot", "mid": MID, "consent_granted": "true"},
    )
    assert r.json()["paytm_response"]["status"] == "NOT_FOUND_SUSPECTED_FAKE"
    assert r.json()["fraud_alert"]["priority"] == "HIGH"


def test_escalation_ticket_format(client):
    body = ask(client, "mera soundbox kharab ho gaya").json()
    assert body["intent"] == "ESCALATE_HUMAN"
    assert body["paytm_response"]["escalation_ticket"]["ticket_id"].startswith("TKT-PAYTM-")
    assert "Soundbox" in body["reply_text"]  # even with no device on file in the dataset


def test_refund_above_5000_escalates(client):
    body = ask(client, "order 5521 ka ₹7,500 refund kar do").json()
    assert body["intent"] == "REFUND_MANAGE"
    assert body["paytm_response"]["status"] == "ESCALATED"
    small = ask(client, "order 5522 ka ₹1,200 refund kar do").json()
    assert small["paytm_response"]["status"] == "INITIATED"
