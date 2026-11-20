"""Severity triage (LOW / MEDIUM / SEVERE) and the fallback each level gets (triage.py)."""
from __future__ import annotations

import httpx
import pytest

import triage
import upstream
from conftest import ask
from state import STATE


@pytest.fixture(autouse=True)
def fallback_on(client, monkeypatch):
    monkeypatch.setenv("TRIAGE_FALLBACK", "1")
    monkeypatch.setattr(triage, "MAX_RETRIES", 3)
    client.post("/reset")
    yield
    client.post("/reset")


def _r(intent, status="RESOLVED", data=None, src="live", **kw):
    return {"intent": intent, "paytm_source": src, "paytm_response": {"status": status, "data": data or {}}, **kw}


# ----------------------------------------------------------------------------- the bifurcation
@pytest.mark.parametrize("intent,level", [
    ("INFO_QUERY", "LOW"), ("GROWTH_ADVISORY", "LOW"), ("FEE_GST_LOAN", "LOW"), ("SETTLEMENT_RECONCILE", "LOW"),
    ("LOAN_CLOSURE_NOC", "LOW"), ("UTR_VERIFY", "MEDIUM"), ("DUPLICATE_RECONCILE", "MEDIUM"),
    ("REFUND_MANAGE", "MEDIUM"), ("CHARGEBACK_RESOLVE", "MEDIUM"), ("MANDATE_TROUBLESHOOT", "MEDIUM"),
    ("CASHFLOW_EDI_SWITCH", "MEDIUM"), ("SOUNDBOX_RETURN", "MEDIUM"), ("BANK_KYC_UPDATE", "MEDIUM"),
    ("SETTLEMENT_HOLD_BANK", "SEVERE"), ("ESCALATE_HUMAN", "SEVERE"),
])
def test_every_problem_has_a_level(intent, level):
    assert triage.rate(_r(intent, status="PENDING"), "")["severity"] == level


def test_every_intent_the_router_knows_is_classified():
    import schemas
    assert set(schemas.INTENTS) | {"INFO_QUERY", "UNCLEAR"} <= set(triage.BASE)


@pytest.mark.parametrize("result,text,level,code", [
    (_r("UTR_VERIFY", "NOT_FOUND_SUSPECTED_FAKE", fraud_alert={"utr_number": "1"}), "", "SEVERE", "SUSPECTED_FRAUD"),
    (_r("UTR_VERIFY", "SUCCESS"), "", "LOW", "PAYMENT_OK"),
    (_r("REFUND_MANAGE", "NEEDS_APPROVAL", {"amount_inr": 6500}), "", "SEVERE", "NEEDS_APPROVAL"),
    (_r("REFUND_MANAGE", "PROCESSED", {"amount_inr": 6000}), "", "MEDIUM", "AMOUNT"),
    (_r("DUPLICATE_RECONCILE", "PROCESSED", {"refund": {"amount_inr": 30000}}), "", "SEVERE", "HIGH_AMOUNT"),
    (_r("SETTLEMENT_RECONCILE", "RECONCILED", {"variance": 4160}), "", "LOW", None),
    (_r("SETTLEMENT_RECONCILE", "RECONCILED", {"variance": 7000}), "", "MEDIUM", "AMOUNT"),
    (_r("CHARGEBACK_RESOLVE", "HELD", {"hours_left": 6}), "", "SEVERE", "DEADLINE"),
    (_r("CHARGEBACK_RESOLVE", "RELEASED", {"hours_left": 6}), "", "MEDIUM", None),
    (_r("SETTLEMENT_RECONCILE", "RECONCILED"), "yeh toh fraud hai, police mein jaunga", "SEVERE", "FRAUD_WORDS"),
    (_r("SETTLEMENT_RECONCILE", "RECONCILED"), "bahut pareshan hoon, urgent hai", "MEDIUM", "DISTRESS"),
    (_r("SETTLEMENT_RECONCILE", "RECONCILED"), "fir se check karo, settlement kab tak aayega", "LOW", None),
    (_r("LOAN_CLOSURE_NOC", "FORECLOSURE_QUOTE_READY", {"outstanding": 42000}), "", "LOW", None),
])
def test_rules_raise_the_level_for_a_reason(result, text, level, code):
    out = triage.rate(result, text)
    assert out["severity"] == level
    codes = {r["code"] for r in out["reasons"]}
    assert code in codes if code else not (codes - {"BASE_LOW", "BASE_MEDIUM", "BASE_SEVERE"})


# ----------------------------------------------------------------------------- fallbacks with Paytm offline
def test_low_offline_answers_from_the_books_and_says_so(client):
    r = ask(client, "Kal settlement kam kyun aaya?").json()
    t = r["triage"]
    assert (t["severity"], t["fallback"], t["automated"]) == ("LOW", "AUTO_MESSAGE", False)
    assert r["reply_text"].startswith("Paytm se abhi live confirm nahi ho paya")
    assert not STATE.handoffs and not STATE.retry_queue


def test_medium_offline_changes_nothing_queues_a_retry_then_hands_to_a_person(client):
    r = ask(client, "Customer ne order 4489 ke liye do baar payment kar diya").json()
    t = r["triage"]
    assert (t["severity"], t["fallback"]) == ("MEDIUM", "AUTO_RETRY")
    assert "kuch change nahi kiya" in r["reply_text"] and t["retry_id"] in r["reply_text"]
    assert "refund" not in r["reply_text"].lower().split("queue")[0]  # no claim that a refund happened
    for _ in range(triage.MAX_RETRIES):       # Paytm stays down
        client.post("/merchant/fallback/tick")
    h = client.get("/merchant/handoffs").json()
    assert h["retries"][0]["status"] == "ESCALATED" and h["handoffs"][0]["severity"] == "SEVERE"
    kinds = [f["kind"] for f in client.get("/merchant/followups").json()["followups"]]
    assert kinds == ["ESCALATED_TO_HUMAN"]


def test_severe_offline_opens_a_human_case_and_promises_a_callback(client):
    r = ask(client, "Settlement hold pe hai kya? Bank account inactive dikha raha hai").json()
    t = r["triage"]
    assert (t["severity"], t["fallback"]) == ("SEVERE", "HUMAN_HANDOFF")
    assert t["handoff_id"] in r["reply_text"] and "2 ghante" in r["reply_text"]
    assert "kuch change nahi kiya" in r["reply_text"]
    case = client.get("/merchant/handoffs").json()["handoffs"][0]
    assert case["reason_code"] == "COMPLIANCE_HOLD" and case["paytm_ticket_id"] is None  # synced when Paytm is back
    done = client.post(f"/merchant/handoffs/{case['id']}/resolve", params={"note": "Bank verified"}).json()
    assert done["status"] == "RESOLVED"
    assert client.get("/merchant/followups").json()["followups"][-1]["kind"] == "HUMAN_RESOLVED"


def test_three_misunderstandings_in_a_row_get_a_person(client):
    levels = [ask(client, "Aaj cricket match kaun jeeta?").json()["triage"]["severity"] for _ in range(3)]
    assert levels == ["LOW", "MEDIUM", "SEVERE"]
    assert STATE.handoffs and next(iter(STATE.handoffs.values()))["reason_code"] == "REPEATED_ISSUE"


def test_english_fallback_is_english(client):
    r = client.post("/merchant/query", json={"text": "My settlement is on hold, bank account inactive",
                                             "consent_granted": True, "language": "en"}).json()
    if r["intent"] == "SETTLEMENT_HOLD_BANK":
        assert "Paytm specialist" in r["reply_text"] and "ghante" not in r["reply_text"]


# ----------------------------------------------------------------------------- Paytm comes back
@pytest.fixture()
def paytm_live(monkeypatch):
    """A live 8002: answers dispatches, has an employee ticket queue."""
    state = {"tickets": {}, "sent": []}

    async def fake_post(base, path, **kwargs):
        req = httpx.Request("POST", f"{base}{path}")
        env = kwargs.get("json") or {}
        state["sent"].append(env)
        intent, p = env.get("intent"), env.get("payload") or {}
        if intent == "ESCALATE_HUMAN":
            tid = f"tkt_{len(state['tickets']) + 1:03d}"
            state["tickets"][tid] = {"ticket_id": tid, "status": "OPEN", "claimed_by": None, "resolution_note": None,
                                     "reason_code": p.get("reason_code"), "reason_text": p.get("reason_text")}
            body = {"status": "ESCALATED", "intent": intent, "data": {}, "escalation_ticket": state["tickets"][tid]}
        elif intent == "UTR_VERIFY":
            body = {"status": "RESOLVED", "intent": intent, "data": {"utr": p.get("utr"), "lookup_status": "NOT_FOUND",
                                                                     "internal_flag": "POSSIBLE_FAKE"}}
        else:
            body = {"status": "RESOLVED", "intent": intent, "data": {
                "duplicates_found": 1, "order_id": "4489", "order_amount_inr": 1180,
                "refund": {"utr": "632230725895", "amount_inr": 1180}, "refund_status": "PROCESSED"}}
        body.setdefault("agent_trace", [])
        return httpx.Response(200, request=req, json=body)

    async def up():
        return True

    async def tickets():
        return dict(state["tickets"])

    def go_live():
        monkeypatch.setattr(upstream, "_post", fake_post)
        monkeypatch.setattr(triage, "paytm_up", up)
        monkeypatch.setattr(triage, "fetch_tickets", tickets)

    state["go_live"] = go_live
    return state


def test_medium_retry_goes_through_when_paytm_is_back(client, paytm_live):
    r = ask(client, "Customer ne order 4489 ke liye do baar payment kar diya").json()
    rid = r["triage"]["retry_id"]
    paytm_live["go_live"]()
    client.post("/merchant/fallback/tick")
    retry = client.get("/merchant/handoffs").json()["retries"][0]
    assert (retry["id"], retry["status"]) == (rid, "DONE")
    f = client.get("/merchant/followups").json()["followups"]
    assert f[-1]["kind"] == "AUTO_RETRY_DONE" and f[-1]["text"].startswith(f"Update ({rid})")
    assert not STATE.handoffs


def test_severe_live_case_lands_in_paytms_console_and_the_merchant_hears_back(client, paytm_live):
    paytm_live["go_live"]()
    r = ask(client, "UTR 632184920555 check karo").json()
    t = r["triage"]
    assert (t["severity"], t["fallback"], t["automated"]) == ("SEVERE", "HUMAN_HANDOFF", True)
    assert t["paytm_ticket_id"] == "tkt_001" and "30 minute" in r["reply_text"]
    ticket = paytm_live["tickets"]["tkt_001"]
    assert ticket["reason_code"] == "REPEATED_UNKNOWN_UTR" and t["handoff_id"] in ticket["reason_text"]

    ticket.update(status="CLAIMED", claimed_by="Asha")
    client.post("/merchant/fallback/tick")
    ticket.update(status="RESOLVED", resolution_note="Called the merchant, goods held")
    client.post("/merchant/fallback/tick")
    f = client.get("/merchant/followups").json()["followups"]
    assert [x["kind"] for x in f] == ["HUMAN_CLAIMED", "HUMAN_RESOLVED"]
    assert "Asha" in f[0]["text"] and "goods held" in f[1]["text"]
    assert client.get("/merchant/handoffs").json()["handoffs"][0]["status"] == "RESOLVED"


def test_paytms_own_escalation_is_not_ticketed_twice(client, paytm_live):
    paytm_live["go_live"]()
    r = ask(client, "mera soundbox kharab ho gaya").json()
    if r["intent"] == "ESCALATE_HUMAN":
        assert len(paytm_live["tickets"]) == 1
        assert r["triage"]["paytm_ticket_id"] == next(iter(paytm_live["tickets"]))


def test_switch_off_keeps_the_old_behaviour(client, monkeypatch):
    monkeypatch.setenv("TRIAGE_FALLBACK", "0")
    r = ask(client, "Customer ne order 4489 ke liye do baar payment kar diya").json()
    assert r["triage"]["fallback"] == "DISABLED" and r["triage"]["severity"] == "MEDIUM"
    assert not STATE.retry_queue


def test_nothing_is_recorded_as_done_while_paytm_is_down(client):
    before = (len(STATE.khata_entries), len(STATE.fraud_alerts), len(STATE.strategy_memory), STATE.loan_edi_status)
    ask(client, "Customer ne order 4489 ke liye do baar payment kar diya")
    r = ask(client, "UTR 632184920555 check karo").json()
    assert r["verified_outcome"]["outcome"] == "NOT_VERIFIED" and r["fraud_alert"] is None
    assert r["triage"]["severity"] == "MEDIUM" and "saman mat dijiye" in r["reply_text"]  # fraud needs Paytm's word
    after = (len(STATE.khata_entries), len(STATE.fraud_alerts), len(STATE.strategy_memory), STATE.loan_edi_status)
    assert after == before
