"""V3 Merchant AI Buddy tests (PLAN.md closed loop + the 4 service-request intents + khata export).

Offline by default: every upstream call fails instantly, so the merchant-side mocks of 8001/8002 answer.
"""
import json
import re

import httpx
import pytest

import advisor
import router
import upstream
from conftest import MID, NO_DATASET, REAL_DATASET, ask, use_dataset
from schemas import Slots
from state import STATE


@pytest.fixture(autouse=True)
def offline(client, monkeypatch):
    async def down(base, path, **kwargs):
        raise httpx.ConnectError("offline", request=httpx.Request("POST", f"{base}{path}"))

    monkeypatch.setattr(upstream, "_post", down)
    use_dataset(NO_DATASET)
    client.post("/reset")
    yield
    use_dataset(NO_DATASET)
    client.post("/reset")


def shield(client, scenario, consent=True):
    return client.post("/merchant/proactive-shield", json={"mid": MID, "scenario": scenario, "consent_granted": consent})


def events(client, request_id=None):
    evs = client.get("/events").json()["a2a_events"]
    return [e for e in evs if request_id is None or e["request_id"] == request_id]


# ----------------------------------------------------------------------------- routing


@pytest.mark.parametrize(
    "text,intent",
    [
        ("Mera ₹500 ka loan EDI mandate fail ho gaya", "MANDATE_TROUBLESHOOT"),
        ("meri kist bounce ho gayi", "MANDATE_TROUBLESHOOT"),
        ("Mere pichle 6 mahine ke data se business badhane ka suggestion do", "GROWTH_ADVISORY"),
        ("customer ne do baar payment kar diya", "DUPLICATE_RECONCILE"),
        ("kal supplier ko dene ke liye paise kam pad rahe hain", "CASHFLOW_EDI_SWITCH"),
        ("soundbox wapas karna hai", "SOUNDBOX_RETURN"),
        ("soundbox ka bill abhi bhi kat raha hai", "SOUNDBOX_RETURN"),
        ("loan settle karna hai, NOC chahiye", "LOAN_CLOSURE_NOC"),
        ("bank account change karna hai", "BANK_KYC_UPDATE"),
        ("KYC update karna hai", "BANK_KYC_UPDATE"),
        ("settlement hold pe hai, bank inactive dikha raha", "SETTLEMENT_HOLD_BANK"),
        # old meanings must survive the new rules
        ("soundbox ka rental kitna kata", "FEE_GST_LOAN"),
        ("mera soundbox kharab ho gaya", "ESCALATE_HUMAN"),
        ("settlement kam kyun aaya", "SETTLEMENT_RECONCILE"),
        ("order 5521 ka ₹7,500 refund kar do", "REFUND_MANAGE"),
    ],
)
def test_new_intent_keywords(text, intent):
    assert router.keyword_intent(text) == intent


def test_plan_demo_chips_hit_the_fast_path(client):
    body = ask(client, "Mere pichle 6 mahine ke data se business badhane ka suggestion do").json()
    assert (body["intent"], body["intent_source"]) == ("GROWTH_ADVISORY", "utterance_bank")


# ----------------------------------------------------------------------------- closed loop on every query


def test_response_carries_the_full_loop(client):
    body = ask(client, "Mera ₹500 ka loan EDI mandate fail ho gaya").json()
    assert body["hindi_reply"] == body["reply_text"]
    ins = body["historical_insight"]
    assert ins["classification"] == "PAYMENT_FRICTION" and ins["metrics"]["sales_dip_pct"] == 37
    assert ins["profile"]["daily_avg_sales"] == 32000 and ins["profile"]["weekend_multiplier"] == 2.3
    ev = body["intervention_evaluation"]
    assert [o["id"] for o in ev["options"]] == ["A", "B", "C"] and ev["selected"] == "B"
    assert ev["selected_intervention"]["action"] == "UPI_LINK_48H_GRACE"
    assert [t["agent"] for t in body["paytm_agent_trace"]] == list(upstream.AGENTS)
    assert body["verified_outcome"]["outcome"] == "SUCCESS" and body["verified_outcome"]["learned"]
    assert body["pending_action"]["type"] == "PAY_VIA_UPI_LINK"
    # Act 1: friction-not-default + a historical tip, within the voice budget
    assert "default नहीं" in body["reply_text"] and "2.3x" in body["reply_text"]
    assert len(body["reply_text"].split()) <= 35
    m2p = next(e for e in events(client, body["request_id"]) if e["type"] == "MERCHANT_TO_PAYTM")["payload"]
    assert m2p["selected_intervention"]["option_id"] == "B"
    order = [e["type"] for e in events(client, body["request_id"])]
    assert order.index("ROOT_CAUSE_DIAGNOSED") < order.index("INTERVENTIONS_EVALUATED") < order.index("MERCHANT_TO_PAYTM")
    assert order.index("PAYTM_TO_MERCHANT") < order.index("OUTCOME_VERIFIED") < order.index("VOICE_REPLY_READY")


def test_willful_default_history_escalates_instead(client, tmp_path):
    (tmp_path / "seed").mkdir()
    (tmp_path / "seed/merchant_history.json").write_text(json.dumps({
        "daily_avg_sales": 32000, "past_edi_success_rate": "70%",
        "recent_daily_sales": [{"date": "2026-11-17", "sales": 21000}, {"date": "2026-11-18", "sales": 20500}],  # normal weekdays
    }), encoding="utf-8")
    use_dataset(tmp_path)
    body = ask(client, "mera EDI mandate fail ho gaya").json()
    assert body["historical_insight"]["classification"] == "WILLFUL_DEFAULT_RISK"
    assert body["intervention_evaluation"]["selected_intervention"]["action"] == "ESCALATE_SPECIALIST"
    assert body["paytm_response"]["status"] == "ESCALATED"


def test_strategy_memory_changes_future_choices(client):
    insight = advisor.diagnose("MANDATE_TROUBLESHOOT", Slots())
    assert advisor.evaluate("MANDATE_TROUBLESHOOT", insight, Slots())["selected"] == "B"
    for i in range(20):  # the UPI-link strategy keeps failing for this merchant
        STATE.strategy_memory.append({"intent": "MANDATE_TROUBLESHOOT", "action": "UPI_LINK_48H_GRACE",
                                      "outcome": "FAILED", "request_id": f"R{i}"})
    after = advisor.evaluate("MANDATE_TROUBLESHOOT", insight, Slots())
    assert after["selected"] != "B"
    b = next(o for o in after["options"] if o["id"] == "B")
    assert b["history"]["learned_trials"] == 20 and b["history"]["success_rate"] < 0.4


def test_outcomes_are_learned_and_reset(client):
    ask(client, "settlement kam kyun aaya")
    ask(client, "chargeback 9981 hold")  # HELD: not an outcome yet
    mem = client.get("/merchant/strategy-memory").json()
    assert mem["verified_outcomes_learned"] == 1 and mem["successes"] == 1
    assert "SETTLEMENT_RECONCILE" in mem["by_intent"]
    assert client.get("/events").json()["strategy_memory"]["verified_outcomes_learned"] == 1
    client.post("/reset")
    assert client.get("/merchant/strategy-memory").json()["verified_outcomes_learned"] == 0


def test_policy_blocks_are_respected(client):
    body = ask(client, "UTR 632184920111 check").json()
    c = next(o for o in body["intervention_evaluation"]["options"] if o["action"] == "RELEASE_ON_SCREENSHOT")
    assert c["blocked_by_policy"] and c["total"] == 0 and not c["selected"]
    big = ask(client, "order 5521 ka ₹7,500 refund kar do").json()
    assert big["intervention_evaluation"]["selected_intervention"]["action"] == "ESCALATE_HUMAN"


@pytest.mark.parametrize(
    "text,status,needle",
    [
        ("Customer ne order 4489 ke liye do baar payment kar diya", "REFUND_INITIATED", "Sunita Yadav"),
        ("Mere pichle 6 mahine ke data se business badhane ka suggestion do", "OFFER_PREAPPROVED", "₹1,50,000"),
        ("Soundbox wapas karna hai, uska bill abhi bhi kat raha hai", "RETURN_INITIATED", "PICKUP-"),
        ("Loan poora settle karna hai, NOC kab milega?", "FORECLOSURE_QUOTE_READY", "NOC"),
        ("Mujhe settlement ka bank account aur KYC change karna hai", "KYC_UPDATE_LINK_SENT", "Penny-drop"),
        ("Settlement hold pe hai kya? Bank account inactive dikha raha hai", "NO_BANK_HOLD", "ACTIVE"),
        ("mera soundbox kharab ho gaya", "ESCALATED", "TKT-PAYTM-"),
    ],
)
def test_new_intents_offline(client, text, status, needle):
    body = ask(client, text).json()
    assert body["paytm_response"]["status"] == status
    assert needle in body["reply_text"] and len(body["reply_text"].split()) <= 35, body["reply_text"]
    assert len(body["paytm_agent_trace"]) == 4


def test_hardware_escalation_packages_diagnostics(client):
    body = ask(client, "mera soundbox kharab ho gaya").json()
    m2p = next(e for e in events(client, body["request_id"]) if e["type"] == "MERCHANT_TO_PAYTM")["payload"]
    assert m2p["payload"]["diagnostics"]["speaker_test"] == "FAILED"
    assert body["intervention_evaluation"]["selected_intervention"]["action"] == "L2_PRIORITY_REPLACEMENT"


# ----------------------------------------------------------------------------- proactive flows


def test_proactive_chargeback_waits_for_signoff(client):
    body = shield(client, "CHARGEBACK_INCOMING").json()
    p = body["proactive"]
    assert (body["intent"], body["intent_source"]) == ("CHARGEBACK_RESOLVE", "proactive")
    assert p["dispute_packet"]["status"] == "READY_FOR_SIGNOFF" and p["awaiting_confirmation"] == "CONFIRM_DISPUTE"
    assert body["pending_action"] == {"type": "CONFIRM_DISPUTE", "packet_id": "DISPUTE-9981",
                                      "endpoint": "/merchant/confirm-dispute",
                                      "message": "Merchant 1-tap sign-off to submit the dispute with PoD"}
    types = [e["type"] for e in events(client, body["request_id"])]
    assert {"PROACTIVE_ALERT_RECEIVED", "CONNECTOR_PULL", "DISPUTE_PACKET_READY"} <= set(types)
    assert "MERCHANT_TO_PAYTM" not in types  # nothing goes to Paytm before the merchant signs off
    assert "Shiprocket" in body["reply_text"]

    done = client.post("/merchant/confirm-dispute", json={"mid": MID, "consent_granted": True, "packet_id": "DISPUTE-9981"}).json()
    assert done["paytm_response"]["status"] == "RELEASED"
    assert done["proactive"]["dispute_packet"]["status"] == "SUBMITTED"
    m2p = next(e for e in events(client, done["request_id"]) if e["type"] == "MERCHANT_TO_PAYTM")["payload"]
    assert m2p["intent"] == "CHARGEBACK_RESOLVE" and m2p["payload"]["pod_source"] == "SHIPROCKET_SYNC"
    assert "MERCHANT_SIGNOFF" in [e["type"] for e in events(client, done["request_id"])]


def test_proactive_cashflow_offer_then_pause(client):
    body = shield(client, "CASHFLOW_EDI_SWITCH").json()
    p = body["proactive"]
    assert p["cashflow"] == {**p["cashflow"], "projected_net_payout": 1200, "tomorrow_stock_due": 4500, "shortfall": 3300}
    assert p["awaiting_confirmation"] == "CONFIRM_EDI_PAUSE" and p["edi_pause_offer"]["offer_id"] == "EDIOFFER-0001"
    assert client.get("/merchant/profile").json()["loan_edi_status"] == "ACTIVE"  # not paused yet

    too_long = client.post("/merchant/confirm-edi-pause", json={"consent_granted": True, "offer_id": "EDIOFFER-0001", "pause_days": 3})
    assert too_long.status_code == 409 and too_long.json()["detail"]["error"] == "EDI_PAUSE_NOT_ELIGIBLE"
    ok = client.post("/merchant/confirm-edi-pause", json={"consent_granted": True, "offer_id": "EDIOFFER-0001"}).json()
    d = ok["paytm_response"]["data"]
    assert (ok["paytm_response"]["status"], d["loan_edi_status"], d["edi_saved_inr"], d["resume_date"]) == (
        "EDI_PAUSED", "PAUSED_2_DAYS", 1000, "2026-11-21")
    assert d["kfs_consent_artifact"]["consent_token"] == ok["consent_token"]
    assert "EDI_PAUSED" in [e["type"] for e in events(client, ok["request_id"])]
    again = client.post("/merchant/confirm-edi-pause", json={"consent_granted": True, "offer_id": "EDIOFFER-0001"})
    assert again.status_code == 409  # already paused (passed through from the Paytm side)


def test_asking_to_pause_edi_makes_an_offer_not_a_pause(client):
    body = ask(client, "Refund ke baad kal stock ke liye paise kam pad rahe hain, EDI ruk sakti hai?").json()
    assert body["intent"] == "CASHFLOW_EDI_SWITCH" and body["intent_source"] == "utterance_bank"
    assert body["pending_action"]["type"] == "CONFIRM_EDI_PAUSE"
    assert client.get("/merchant/profile").json()["loan_edi_status"] == "ACTIVE"


def test_proactive_mandate_alert(client):
    body = shield(client, "MANDATE_FAILED").json()
    assert body["intent"] == "MANDATE_TROUBLESHOOT" and body["paytm_response"]["status"] == "UPI_LINK_SENT"
    assert body["proactive"]["alert"]["trigger_type"] == "MANDATE_FAILED_ALERT"


def test_proactive_needs_consent_and_known_ids(client):
    r = shield(client, "CHARGEBACK_INCOMING", consent=False)
    assert r.status_code == 403
    assert "PROACTIVE_ALERT_RECEIVED" not in [e["type"] for e in events(client)]
    r = client.post("/merchant/confirm-dispute", json={"consent_granted": True, "packet_id": "DISPUTE-1"})
    assert r.status_code == 404 and r.json()["detail"]["error"] == "PACKET_NOT_FOUND"
    r = client.post("/merchant/confirm-edi-pause", json={"consent_granted": True, "offer_id": "NOPE"})
    assert r.status_code == 404 and r.json()["detail"]["error"] == "OFFER_NOT_FOUND"
    shield(client, "CHARGEBACK_INCOMING")
    assert client.get("/events").json()["pending_actions"]["dispute_packets"][0]["packet_id"] == "DISPUTE-9981"
    client.post("/reset")
    assert client.get("/events").json()["pending_actions"] == {"dispute_packets": [], "edi_pause_offers": []}


def test_live_8002_answers_are_passed_through(client, monkeypatch):
    trace = [{"step": 1, "agent": "IntelligenceAgent", "output": "live"}]

    async def live_8002(base, path, **kwargs):
        req = httpx.Request("POST", f"{base}{path}")
        if path == "/a2a/dispatch":
            intent = kwargs["json"]["intent"]
            status = "UNSUPPORTED_INTENT" if intent == "SOUNDBOX_RETURN" else "UPI_LINK_SENT"
            return httpx.Response(200, request=req, json={"status": status, "intent": intent, "data": {"missed_edi": 500},
                                                          "agent_trace": trace, "verified_outcome": {"resolved": True}})
        raise httpx.ConnectError("8001 down", request=req)

    monkeypatch.setattr(upstream, "_post", live_8002)
    body = ask(client, "mera EDI mandate fail ho gaya").json()
    assert body["paytm_source"] == "live" and body["paytm_agent_trace"] == trace
    assert body["verified_outcome"]["basis"] == "paytm_verified_outcome"
    fallback = ask(client, "soundbox wapas karna hai").json()  # 8002 doesn't know this intent yet -> mock
    assert fallback["paytm_source"] == "mock" and fallback["paytm_response"]["status"] == "RETURN_INITIATED"


# ----------------------------------------------------------------------------- khata export


def test_khata_json_reconciles_and_tracks_actions(client):
    k = client.get("/merchant/khata-export").json()
    s = k["summary"]
    assert (s["gross_sales"], s["mdr_fees"], s["gst_on_mdr"], s["customer_refunds"], s["bank_credit"]) == (
        100000, 1450, 261, 1500, 95840)
    assert s["reconciled"] and s["gst_itc_logged"] == 0 and s["gst_itc_claimable"] == 261
    ask(client, "settlement kam kyun aaya")  # logs the ITC
    ask(client, "Customer ne order 4489 ke liye do baar payment kar diya")
    k = client.get("/merchant/khata-export").json()
    assert k["summary"]["gst_itc_logged"] == 261
    gst = next(v for v in k["vouchers"] if v["debit_ledger"] == "Input GST on MDR (ITC)")
    assert gst["status"] == "ITC LOGGED" and gst["gst_itc_eligible"]
    dup = next(v for v in k["vouchers"] if v["status"] == "DUPLICATE_REFUND")
    assert dup["amount"] == 1180 and "4489" in dup["reference"]
    assert "KHATA_UPDATED" in [e["type"] for e in events(client)]


def test_khata_csv_is_tally_ready(client):
    r = client.get("/merchant/khata-export", params={"format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="khata_PAYTM_MERCH_8821_2026-11-18.csv"' in r.headers["content-disposition"]
    lines = r.text.lstrip("﻿").splitlines()
    assert lines[0] == "Date,Voucher Type,Voucher No,Debit Ledger,Credit Ledger,Amount,GST ITC Eligible,Reference,Status,Narration"
    assert lines[1].startswith("18-11-2026,Sales,") and ",100000.00," in lines[1]
    assert len(lines) == 1 + 7  # sales, 5 deductions, bank receipt


# ----------------------------------------------------------------------------- voice digits + reply grounding

def test_spoken_digits_become_a_utr_but_everyday_words_do_not():
    import router
    assert router.extract_slots("UTR छह तीन दो एक आठ चार नौ दो शून्य एक एक एक check karo").utr_number == "632184920111"
    assert router.spoken_digits("PhonePe se ₹1,180 do baar kat gaya") == "PhonePe se ₹1,180 do baar kat gaya"
    assert router.extract_slots("order ९९८१ ka kya hua").order_id == "9981"


def test_llm_utr_not_in_the_words_is_dropped(client, monkeypatch):
    """Live: 11 spoken digits + a mis-heard word came back from the LLM as a made-up 12-digit UTR -> false fraud."""
    import router

    async def fake_llm(system, user, response_format="json"):
        if response_format == "json":
            return {"intent": "UTR_VERIFY", "slots": {"utr_number": "632184920110"}}
        return None
    monkeypatch.setattr(router.upstream, "llm", fake_llm)
    body = ask(client, "यूटीआर छह तीन दो एक आठ चार नौ दो शून्य एक एक कैप का पेमेंट चेक करो").json()
    assert body["intent"] == "UTR_VERIFY" and body["slots"]["utr_number"] is None
    assert not body.get("fraud_alert")


def test_llm_reply_with_invented_amount_falls_back_to_template(client, monkeypatch):
    import pipeline
    monkeypatch.setattr(pipeline, "REPLY_LLM", True)

    async def fake_llm(system, user, response_format="json"):
        if response_format == "json":
            return None
        return "₹9,999 का settlement आज आपके bank में आ जाएगा, चिंता मत कीजिए।"
    monkeypatch.setattr(pipeline.upstream, "llm", fake_llm)
    body = ask(client, "Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?").json()
    assert body["reply_source"] == "template" and "9,999" not in body["reply_text"]
    assert pipeline.ungrounded_numbers("₹4,160 कटे, UTR 632184920111", '{"variance": 4160.0, "utr": "632184920111"}') == []
    assert pipeline.ungrounded_numbers("₹4,160 का UTR", '{"utr": null}') == ["₹4,160"]


def test_consent_offer_is_never_paraphrased_by_the_llm(client, monkeypatch):
    """Live: the LLM said the EDI 'was paused' while the 1-tap consent was still pending."""
    import pipeline
    calls = []

    async def fake_llm(system, user, response_format="json"):
        calls.append(response_format)
        return "Paytm ने EDI 2 दिन के लिए pause किया है।" if response_format == "text" else None
    monkeypatch.setattr(pipeline.upstream, "llm", fake_llm)
    body = client.post("/merchant/proactive-shield", json={"mid": MID, "scenario": "CASHFLOW_EDI_SWITCH",
                                                            "consent_granted": True}).json()
    assert body["proactive"]["awaiting_confirmation"] == "CONFIRM_EDI_PAUSE"
    assert body["reply_source"] == "template" and "रोक दूँ?" in body["reply_text"] and "text" not in calls


# ----------------------------------------------------------------------------- not understood -> ask, never guess

@pytest.mark.parametrize("text", ["aaj cricket match kaun jeeta?", "mujhe ek pizza order karna hai", "haan theek hai", "hello"])
def test_off_topic_or_vague_is_not_answered_as_business(client, text):
    """LLM down (8001 unreachable in tests): keywords only. No match used to mean 'settlement'."""
    body = ask(client, text).json()
    assert body["intent"] == "UNCLEAR" and body["paytm_source"] == "none"
    assert "समझ नहीं पाया" in body["reply_text"] and body["pending_action"]["type"] == "REPHRASE"
    assert "MERCHANT_TO_PAYTM" not in [e["type"] for e in body["a2a_events"]]
    assert body["verified_outcome"] == {}  # nothing learned from a non-answer


def test_llm_unclear_is_respected(client, monkeypatch):
    import router

    async def fake_llm(system, user, response_format="json"):
        return {"intent": "UNCLEAR", "slots": {}} if response_format == "json" else None
    monkeypatch.setattr(router.upstream, "llm", fake_llm)
    body = ask(client, "settlement wala game kab aayega bhai").json()  # has a keyword, but the LLM knows better
    assert body["intent"] == "UNCLEAR" and body["intent_source"] == "llm"


def test_business_questions_still_route_without_llm(client):
    assert ask(client, "Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?").json()["intent"] == "SETTLEMENT_RECONCILE"


def test_transcribe_returns_only_real_speech(client, monkeypatch):
    async def fake_stt(audio, filename, content_type, language_code="hi-IN"):
        return "UTR 632184920111 check karo", "live"
    monkeypatch.setattr(upstream, "stt", fake_stt)
    r = client.post("/merchant/transcribe", files={"audio": ("v.webm", b"x" * 2000, "audio/webm;codecs=opus")},
                    data={"mid": MID, "consent_granted": "true"}).json()
    assert r["transcript"] == "UTR 632184920111 check karo" and r["source"] == "live"

    async def mock_stt(audio, filename, content_type, language_code="hi-IN"):
        return None, "mock"
    monkeypatch.setattr(upstream, "stt", mock_stt)
    r = client.post("/merchant/transcribe", files={"audio": ("v.webm", b"x" * 2000, "audio/webm")},
                    data={"mid": MID, "consent_granted": "true"}).json()
    assert r["transcript"] is None and r["reason"] == "voice_off" and "टाइप" in r["message_hi"]


def test_transcribe_needs_consent(client):
    r = client.post("/merchant/transcribe", files={"audio": ("v.webm", b"x" * 2000, "audio/webm")},
                    data={"mid": MID, "consent_granted": "false"})
    assert r.status_code == 403


# ----------------------------------------------------------------------------- language + questions about the books

def _q(client, text, language="hi"):
    return client.post("/merchant/query", json={"text": text, "mid": MID, "consent_granted": True,
                                                "language": language}).json()


def test_english_tab_gets_english_clarification(client):
    body = _q(client, "who won the cricket match today?", "en")
    assert body["intent"] == "UNCLEAR" and body["language_code"] == "en-IN"
    assert body["reply_text"].startswith("Sorry") and not re.search("[ऀ-ॿ]", body["reply_text"])


def test_english_consent_prompt_is_english(client):
    body = client.post("/merchant/proactive-shield", json={"mid": MID, "scenario": "CASHFLOW_EDI_SWITCH",
                                                            "consent_granted": True, "language": "en"}).json()
    assert body["proactive"]["awaiting_confirmation"] == "CONFIRM_EDI_PAUSE"
    assert "Shall I pause" in body["reply_text"] and not re.search("[ऀ-ॿ]", body["reply_text"])


def _fake_llm(monkeypatch, intent, answer):
    import router

    async def fake(system, user, response_format="json"):
        return {"intent": intent, "slots": {}} if response_format == "json" else answer
    monkeypatch.setattr(router.upstream, "llm", fake)


def test_next_settlement_question_is_answered_from_the_books(client, monkeypatch):
    use_dataset(REAL_DATASET)
    client.post("/reset")
    _fake_llm(monkeypatch, "INFO_QUERY", "आपका अगला settlement 2026-11-20 को सुबह 08:00 के आसपास आएगा, आज की बिक्री के लिए।")
    body = _q(client, "मेरा अगला settlement कब आएगा?")
    assert body["intent"] == "INFO_QUERY" and body["paytm_source"] == "none" and body["reply_source"] == "llm"
    assert "20 नवंबर" in body["reply_text"]  # ISO dates are humanised for reading and TTS
    assert "MERCHANT_TO_PAYTM" not in [e["type"] for e in body["a2a_events"]]  # read-only


def test_info_answer_with_invented_number_is_rejected(client, monkeypatch):
    _fake_llm(monkeypatch, "INFO_QUERY", "आपका अगला settlement ₹77,777 का होगा।")
    body = _q(client, "agla settlement kitna aayega?")
    assert body["intent"] == "UNCLEAR" and "77,777" not in body["reply_text"]


def test_llm_answers_the_actual_question_by_default(client, monkeypatch):
    import pipeline
    monkeypatch.setattr(pipeline, "REPLY_LLM", True)  # the default; don't depend on the developer's .env
    _fake_llm(monkeypatch, "SETTLEMENT_RECONCILE", "₹4,160 MDR, GST, refund, rental और hold में कटे।")
    body = _q(client, "Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?")
    assert body["reply_source"] == "llm" and body["reply_text"].startswith("₹4,160 MDR")
