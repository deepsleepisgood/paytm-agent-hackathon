"""Stage 7 — UTR_VERIFY, contract acceptance cases 2 to 5, plus intent-name aliases.

The logic here is small. The wording is the product. A shopkeeper is standing in front
of a customer, and what the agent says decides whether the goods leave the shop and
whether a named person gets called a thief.

So the heart of this file is `test_nothing_accusatory_is_ever_said`, which checks every
merchant-facing string on every branch, not just the happy one.
"""
from __future__ import annotations

import json

import pytest

from app import store
from app.templates import BANNED_WORDS

KNOWN_SETTLED = "632184920111"
KNOWN_PENDING = "632184920999"
UNKNOWN = "111111111111"


def body(**over) -> dict:
    base = {
        "request_id": "req-utr",
        "session_id": "sess-shop",
        "mid": "PAYTM_MERCH_8821",
        "intent": "UTR_VERIFY",
        "language_code": "hi-IN",
        "merchant_said": "payment aaya kya?",
        "payload": {"utr": KNOWN_SETTLED, "claimed_amount_inr": 1250},
        "consent_token": "ct-abc",
    }
    base.update(over)
    return base


# --- acceptance cases 2, 3, 4 ------------------------------------------------------------

def test_case_2_a_settled_payment_releases_the_goods(client):
    out = client.post("/a2a/dispatch", json=body()).json()

    assert out["status"] == "RESOLVED"
    assert out["data"]["lookup_status"] == "SUCCESS_SETTLED"
    assert out["data"]["advice"] == "RELEASE_GOODS"
    assert out["data"]["amount_inr"] == 1250
    assert out["data"]["payer_app"] == "GPay"
    assert out["data"]["amount_matches_claim"] is True
    assert out["data"]["internal_flag"] is None
    assert "hand over the goods" in out["template_text"]


def test_case_3_a_pending_payment_says_wait_not_failed(client):
    out = client.post("/a2a/dispatch", json=body(
        payload={"utr": KNOWN_PENDING, "claimed_amount_inr": 2400},
    )).json()

    assert out["status"] == "RESOLVED"
    assert out["data"]["lookup_status"] == "PENDING"
    assert out["data"]["advice"] == "WAIT"
    text = out["template_text"]
    assert "still being processed" in text
    # A pending payment reverses on its own; saying it failed would be wrong.
    assert "failed" not in text.lower()
    assert "reverses" in text


def test_case_4_an_unknown_reference_is_not_in_your_account(client):
    out = client.post("/a2a/dispatch", json=body(payload={"utr": UNKNOWN})).json()

    assert out["status"] == "RESOLVED"
    data = out["data"]
    assert data["lookup_status"] == "NOT_FOUND"
    assert data["advice"] == "DO_NOT_RELEASE_YET"
    assert data["amount_inr"] is None
    assert data["payer_app"] is None

    text = out["template_text"]
    assert "cannot find" in text
    assert "do not hand over" in text
    # And it offers a way forward rather than leaving the merchant stuck.
    assert "ticket" in text


def test_the_internal_flag_exists_in_data_but_is_never_spoken(client):
    """The contract requires the flag. The merchant must never hear it."""
    out = client.post("/a2a/dispatch", json=body(payload={"utr": UNKNOWN})).json()

    assert out["data"]["internal_flag"] == "POSSIBLE_FAKE"
    assert "POSSIBLE_FAKE" not in out["template_text"]
    assert "possible_fake" not in out["template_text"].lower()

    # Nor does it reach the employee's feed row.
    summary = store.summaries[0]
    assert "POSSIBLE_FAKE" not in json.dumps(summary)


# --- the property this whole module exists for ---------------------------------------------

@pytest.mark.parametrize("payload", [
    {"utr": KNOWN_SETTLED, "claimed_amount_inr": 1250},
    {"utr": KNOWN_SETTLED, "claimed_amount_inr": 9999},   # amount mismatch
    {"utr": KNOWN_PENDING},
    {"utr": UNKNOWN},
    {"utr": UNKNOWN, "source": "screenshot"},
])
def test_nothing_accusatory_is_ever_said(client, payload):
    """Checks every branch, not just the comfortable ones.

    Covers everything a human or the merchant screen might read aloud: the spoken
    sentence, the feed row, and any ticket raised.
    """
    out = client.post("/a2a/dispatch", json=body(payload=payload)).json()

    spoken = [out["template_text"]]
    spoken += [s["found"] for s in store.summaries]
    spoken += [s["action_taken"] for s in store.summaries]
    if out.get("escalation_ticket"):
        spoken += [out["escalation_ticket"]["reason_text"],
                   out["escalation_ticket"]["suggested_next_step"]]

    for text in spoken:
        for word in BANNED_WORDS:
            assert word not in text.lower(), f"{word!r} appears in: {text!r}"


def test_a_screenshot_changes_nothing_about_the_lookup(client):
    """Person 1's reader extracts text from an image. That is a hint, not evidence."""
    by_voice = client.post("/a2a/dispatch", json=body(
        request_id="v", payload={"utr": UNKNOWN, "source": "voice"})).json()
    by_shot = client.post("/a2a/dispatch", json=body(
        request_id="s", payload={"utr": UNKNOWN, "source": "screenshot"})).json()

    assert by_voice["data"]["lookup_status"] == by_shot["data"]["lookup_status"]
    assert by_voice["data"]["advice"] == by_shot["data"]["advice"]


def test_an_amount_that_does_not_match_is_pointed_out(client):
    out = client.post("/a2a/dispatch", json=body(
        payload={"utr": KNOWN_SETTLED, "claimed_amount_inr": 9999})).json()

    assert out["data"]["amount_matches_claim"] is False
    assert "not what you were told" in out["template_text"]
    # Still answerable: the money did arrive.
    assert out["status"] == "RESOLVED"


# --- acceptance case 5: the pattern, not the single lookup ------------------------------------

def test_case_5_three_unknown_references_in_one_session_escalate(client):
    first = client.post("/a2a/dispatch", json=body(
        request_id="u1", payload={"utr": "111111111111"})).json()
    second = client.post("/a2a/dispatch", json=body(
        request_id="u2", payload={"utr": "222222222222"})).json()
    third = client.post("/a2a/dispatch", json=body(
        request_id="u3", payload={"utr": "333333333333"})).json()

    assert first["status"] == "RESOLVED"
    assert second["status"] == "RESOLVED"
    assert third["status"] == "ESCALATED"

    ticket = third["escalation_ticket"]
    assert ticket["reason_code"] == "REPEATED_UNKNOWN_UTR"
    assert "call the merchant" in ticket["suggested_next_step"].lower()
    # The escalation still carries the answer: the merchant is told to hold the goods.
    assert "do not hand over" in third["template_text"]


def test_the_counter_counts_lookups_not_distinct_references(client):
    """The same bogus number three times is the same warning sign."""
    for i in range(3):
        out = client.post("/a2a/dispatch", json=body(
            request_id=f"same{i}", payload={"utr": UNKNOWN})).json()

    assert out["status"] == "ESCALATED"
    assert out["escalation_ticket"]["reason_code"] == "REPEATED_UNKNOWN_UTR"


def test_the_counter_is_per_session_not_global(client):
    """Two different shopkeepers must not add up to one fraud pattern."""
    for i in range(2):
        client.post("/a2a/dispatch", json=body(
            request_id=f"a{i}", session_id="shop-a", payload={"utr": UNKNOWN}))
    out = client.post("/a2a/dispatch", json=body(
        request_id="b1", session_id="shop-b", payload={"utr": UNKNOWN})).json()

    assert out["status"] == "RESOLVED"  # shop-b's first, not shop-a's third


def test_a_replayed_unknown_lookup_does_not_advance_the_counter(client):
    """Otherwise a retry trips the limit one reference early."""
    client.post("/a2a/dispatch", json=body(request_id="r1", payload={"utr": UNKNOWN}))
    for _ in range(4):
        client.post("/a2a/dispatch", json=body(request_id="r1", payload={"utr": UNKNOWN}))

    assert store.sessions["sess-shop"].unknown_utr_count == 1
    out = client.post("/a2a/dispatch", json=body(request_id="r2", payload={"utr": UNKNOWN})).json()
    assert out["status"] == "RESOLVED"  # only the second real lookup


def test_unknown_lookups_are_counted_for_the_risk_dashboard(client):
    client.post("/a2a/dispatch", json=body(request_id="f1", payload={"utr": UNKNOWN}))
    client.post("/a2a/dispatch", json=body(request_id="f2", payload={"utr": KNOWN_SETTLED}))

    assert client.get("/metrics").json()["fraud_flags"] == 1
    assert client.get("/ledger/PAYTM_MERCH_8821").json()["counters"]["fraud_blocked"] == 1


# --- the trace ------------------------------------------------------------------------------

def test_the_trace_shows_the_pattern_being_spotted(client):
    for i in range(2):
        client.post("/a2a/dispatch", json=body(request_id=f"t{i}", payload={"utr": UNKNOWN}))
    out = client.post("/a2a/dispatch", json=body(request_id="t3", payload={"utr": UNKNOWN})).json()

    t = {e["agent"]: e for e in out["agent_trace"]}
    assert "not present in this merchant's account" in t["IntelligenceAgent"]["note"]
    assert "3 unknown references" in t["RiskPolicyAgent"]["note"]
    # Checking a reference never changes the merchant's account.
    assert t["LedgerOpsAgent"]["acted"] is False


def test_a_missing_utr_is_a_bad_payload(client):
    r = client.post("/a2a/dispatch", json=body(payload={}))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_PAYLOAD"


# --- intent names across the team -------------------------------------------------------------

def test_person_1s_alternative_names_are_accepted(client):
    """sarvam_service calls these its canonical names; ours are its alternatives.

    Both spellings reach the same handler, and the response reports which name this
    service actually worked with.
    """
    for alias, canonical in (("DUPLICATE_RECONCILE", "DUPLICATE_PAYMENT_RECONCILE"),
                             ("GROWTH_ADVISORY", "WORKING_CAPITAL_ADVISORY")):
        r = client.post("/a2a/dispatch", json=body(request_id=alias, intent=alias))
        assert r.status_code == 200, alias
        out = r.json()
        assert out["intent"] == alias                 # echoed as they sent it
        assert out["intent_canonical"] == canonical   # and what we worked with
        # The feed groups one scenario under one heading.
        assert store.summaries[-1]["intent"] == canonical


@pytest.mark.parametrize("intent", [
    "MANDATE_TROUBLESHOOT", "SETTLEMENT_RECONCILE", "CHARGEBACK_RESOLVE", "UTR_VERIFY",
    "DUPLICATE_PAYMENT_RECONCILE", "WORKING_CAPITAL_ADVISORY", "CASHFLOW_EDI_SWITCH",
    "ESCALATE_HUMAN",
])
def test_every_scenario_in_the_table_has_a_handler(client, intent):
    """The whole eight, so none can be quietly left as a 501 on demo day."""
    from app.intents import MODULES

    assert intent in MODULES, f"{intent} has no handler"


def test_genuinely_unknown_intents_are_still_rejected_not_guessed(client):
    r = client.post("/a2a/dispatch", json=body(intent="MAKE_ME_A_SANDWICH"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "UNKNOWN_INTENT"


def test_genuinely_unknown_intents_are_still_rejected(client):
    r = client.post("/a2a/dispatch", json=body(intent="MAKE_ME_A_SANDWICH"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "UNKNOWN_INTENT"


def test_the_response_echoes_the_callers_spelling(client):
    """Person 3 may validate the intent it gets back against the one it sent."""
    out = client.post("/a2a/dispatch", json=body(intent="UTR_VERIFY")).json()
    assert out["intent"] == "UTR_VERIFY"
    assert "intent_canonical" not in out  # nothing to disambiguate
