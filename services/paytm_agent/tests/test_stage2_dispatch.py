"""Stage 2 — the envelope, tickets, escalation and the idempotency gate.

The headline test here is `test_replay_changes_nothing`. Everything the product claims
rests on the record being true: if one call can write two summaries or raise two
tickets, the metrics on the pitch slide are fiction.
"""
from __future__ import annotations

import pytest

from app import store
from app.escalation import NEXT_STEP, REASON_CODES
from app.templates import BANNED_WORDS


def body(**over) -> dict:
    base = {
        "request_id": "req-1",
        "session_id": "sess-1",
        "mid": "PAYTM_MERCH_8821",
        "intent": "ESCALATE_HUMAN",
        "language_code": "hi-IN",
        "merchant_said": "mujhe kisi insaan se baat karni hai",
        "payload": {
            "reason_code": "MERCHANT_REQUESTED_HUMAN",
            "reason_text": "Merchant asked for a person",
            "tried": ["Explained settlement"],
            "urgency": "NORMAL",
        },
        "consent_token": "ct-abc",
    }
    base.update(over)
    return base


# --- the happy path ---------------------------------------------------------------------

def test_escalation_writes_one_summary_and_one_ticket(client):
    r = client.post("/a2a/dispatch", json=body())
    assert r.status_code == 200
    out = r.json()

    assert out["status"] == "ESCALATED"
    assert out["intent"] == "ESCALATE_HUMAN"
    assert out["request_id"] == "req-1"
    assert out["action_required"] is None

    assert len(store.summaries) == 1
    assert len(store.tickets) == 1
    summary, ticket = store.summaries[0], list(store.tickets.values())[0]

    # The two records point at each other, so the console can navigate either way.
    assert summary["ticket_id"] == ticket["ticket_id"] == out["escalation_ticket"]["ticket_id"]
    assert ticket["summary_id"] == summary["summary_id"] == out["summary_id"]

    # The contract's ESCALATE_HUMAN data is {"ticket_id": ...}.
    assert out["data"]["ticket_id"] == ticket["ticket_id"]


def test_summary_carries_every_contract_field(client):
    client.post("/a2a/dispatch", json=body())
    s = store.summaries[0]

    assert set(s) == {
        "summary_id", "request_id", "session_id", "created_at", "duration_ms", "mid",
        "merchant_name", "language_code", "merchant_said", "intent", "found",
        "action_taken", "outcome", "ticket_id",
    }
    assert s["merchant_name"] == "Sharma Electronics"
    assert s["language_code"] == "hi-IN"
    assert s["merchant_said"] == "mujhe kisi insaan se baat karni hai"
    assert s["outcome"] == "ESCALATED"
    assert s["duration_ms"] >= 0


def test_ticket_hands_the_employee_a_prepared_case(client):
    client.post("/a2a/dispatch", json=body())
    t = list(store.tickets.values())[0]

    assert t["status"] == "OPEN"
    assert t["claimed_by"] is None
    assert t["resolution_note"] is None
    assert t["reason_code"] == "MERCHANT_REQUESTED_HUMAN"
    assert t["reason_text"] == "Merchant asked for a person"
    assert t["tried"] == ["Explained settlement"]
    # The employee is told what to do, without having to work it out.
    assert t["suggested_next_step"] == NEXT_STEP["MERCHANT_REQUESTED_HUMAN"]
    # And the merchant's own words are there, so nobody re-asks.
    assert t["merchant_said"] == "mujhe kisi insaan se baat karni hai"


def test_bank_account_change_routes_through_escalate_human(client):
    """Not an intent of its own: an account-takeover risk Person 3 sends here."""
    r = client.post("/a2a/dispatch", json=body(
        request_id="req-bank",
        merchant_said="mera settlement account change kar do",
        payload={"reason_code": "BANK_ACCOUNT_CHANGE", "tried": []},
    ))
    out = r.json()
    assert out["status"] == "ESCALATED"
    assert out["escalation_ticket"]["reason_code"] == "BANK_ACCOUNT_CHANGE"
    assert out["escalation_ticket"]["reason_text"] == REASON_CODES["BANK_ACCOUNT_CHANGE"]


def test_template_text_is_safe_to_say_out_loud(client):
    out = client.post("/a2a/dispatch", json=body()).json()
    text = out["template_text"].lower()
    assert text
    assert not any(w in text for w in BANNED_WORDS)


# --- the headline: replay changes nothing -------------------------------------------------

def test_replay_changes_nothing(client):
    first = client.post("/a2a/dispatch", json=body()).json()
    second = client.post("/a2a/dispatch", json=body()).json()

    assert first == second                      # byte-for-byte the same answer
    assert len(store.summaries) == 1            # not two feed rows
    assert len(store.tickets) == 1              # not two tickets for one case


def test_replay_does_not_re_render_or_recompute(client):
    first = client.post("/a2a/dispatch", json=body()).json()
    # Even the original duration and ids come back unchanged.
    second = client.post("/a2a/dispatch", json=body()).json()
    assert first["summary_id"] == second["summary_id"]
    assert first["escalation_ticket"]["created_at"] == second["escalation_ticket"]["created_at"]


def test_replay_with_a_different_payload_still_returns_the_original(client):
    first = client.post("/a2a/dispatch", json=body()).json()
    second = client.post("/a2a/dispatch", json=body(
        payload={"reason_code": "BANK_ACCOUNT_CHANGE"},
    )).json()

    assert second == first
    assert second["escalation_ticket"]["reason_code"] == "MERCHANT_REQUESTED_HUMAN"
    assert len(store.tickets) == 1


def test_private_bookkeeping_never_leaves_the_service(client):
    out = client.post("/a2a/dispatch", json=body()).json()
    assert not [k for k in out if k.startswith("_")]


# --- errors -------------------------------------------------------------------------------

@pytest.mark.parametrize("over, code", [
    ({"consent_token": ""}, "CONSENT_MISSING"),
    ({"consent_token": "   "}, "CONSENT_MISSING"),
    ({"consent_token": None}, "CONSENT_MISSING"),
    ({"mid": "PAYTM_MERCH_0000"}, "UNKNOWN_MID"),
    ({"intent": "MAKE_ME_A_SANDWICH"}, "UNKNOWN_INTENT"),
    ({"payload": {"reason_code": "NOT_A_REAL_CODE"}}, "BAD_PAYLOAD"),
    ({"payload": {"reason_code": "MERCHANT_REQUESTED_HUMAN", "urgency": "SOON"}}, "BAD_PAYLOAD"),
])
def test_error_codes(client, over, code):
    r = client.post("/a2a/dispatch", json=body(**over))
    assert r.status_code >= 400
    err = r.json()["error"]
    assert err["code"] == code
    assert err["retryable"] is False


def test_a_handover_with_no_reason_still_gets_handled(client):
    """The merchant agent routes here having already decided a person is needed, often
    with nothing more specific to say. Refusing would drop the case at the worst moment.
    """
    out = client.post("/a2a/dispatch", json=body(payload={})).json()

    assert out["status"] == "ESCALATED"
    assert out["escalation_ticket"]["reason_code"] == "MERCHANT_REQUESTED_HUMAN"
    assert len(store.tickets) == 1


@pytest.mark.parametrize("sent, expected", [
    ("MERCHANT_REQUESTED", "MERCHANT_REQUESTED_HUMAN"),
    ("NEEDS_HUMAN", "MERCHANT_REQUESTED_HUMAN"),
    ("MERCHANT_REQUESTED_HUMAN", "MERCHANT_REQUESTED_HUMAN"),
])
def test_the_teams_shorter_reason_names_are_accepted(client, sent, expected):
    out = client.post("/a2a/dispatch", json=body(
        request_id=sent, payload={"reason_code": sent})).json()
    assert out["escalation_ticket"]["reason_code"] == expected


def test_a_reason_we_do_not_recognise_is_still_rejected(client):
    """Defaulting a missing reason is a kindness; silently accepting a wrong one is not,
    because the queue's reason codes are what the employee triages on."""
    r = client.post("/a2a/dispatch", json=body(payload={"reason_code": "BECAUSE_I_SAID"}))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_PAYLOAD"


def test_malformed_body_uses_the_contract_error_shape(client):
    """FastAPI's own 422 has a different envelope; Person 3 should only ever see ours."""
    r = client.post("/a2a/dispatch", json={"intent": "ESCALATE_HUMAN"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_PAYLOAD"


def test_errors_write_nothing(client):
    client.post("/a2a/dispatch", json=body(consent_token=""))
    client.post("/a2a/dispatch", json=body(request_id="req-2", mid="NOPE"))
    assert store.summaries == []
    assert store.tickets == {}


def test_a_rejected_request_can_be_retried_with_the_same_id(client):
    """Errors are not cached on purpose.

    Person 3 fixing a missing consent token and retrying must succeed, not be stuck
    with the original rejection for the life of the process.
    """
    first = client.post("/a2a/dispatch", json=body(consent_token=""))
    assert first.json()["error"]["code"] == "CONSENT_MISSING"

    second = client.post("/a2a/dispatch", json=body())
    assert second.status_code == 200
    assert second.json()["status"] == "ESCALATED"
    assert len(store.summaries) == 1


def test_consent_is_checked_before_the_merchant_is_looked_up(client):
    """No consent, no look at anyone's money - even to say the merchant is unknown."""
    r = client.post("/a2a/dispatch", json=body(consent_token="", mid="PAYTM_MERCH_0000"))
    assert r.json()["error"]["code"] == "CONSENT_MISSING"


# --- the queue the employee works ----------------------------------------------------------

def test_claim_then_resolve(client):
    client.post("/a2a/dispatch", json=body())
    tid = list(store.tickets)[0]

    claimed = client.post(f"/tickets/{tid}/claim", json={"employee": "Asha"}).json()
    assert claimed["status"] == "CLAIMED"
    assert claimed["claimed_by"] == "Asha"
    assert claimed["claimed_at"] is not None

    resolved = client.post(f"/tickets/{tid}/resolve",
                           json={"employee": "Asha", "note": "Called the merchant"}).json()
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_note"] == "Called the merchant"
    assert resolved["resolved_at"] is not None


def test_a_claimed_ticket_cannot_be_claimed_again(client):
    """Otherwise two employees work the same case, which is the thing Claim prevents."""
    client.post("/a2a/dispatch", json=body())
    tid = list(store.tickets)[0]

    client.post(f"/tickets/{tid}/claim", json={"employee": "Asha"})
    second = client.post(f"/tickets/{tid}/claim", json={"employee": "Bhavna"})

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "BAD_PAYLOAD"
    assert "Asha" in second.json()["error"]["message"]
    assert store.tickets[tid]["claimed_by"] == "Asha"


def test_unknown_ticket_is_not_found(client):
    r = client.post("/tickets/tkt_999/claim", json={"employee": "Asha"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_feed_is_newest_first(client):
    client.post("/a2a/dispatch", json=body(request_id="r1"))
    client.post("/a2a/dispatch", json=body(request_id="r2"))
    client.post("/a2a/dispatch", json=body(request_id="r3"))

    feed = client.get("/summaries").json()["summaries"]
    assert [s["request_id"] for s in feed] == ["r3", "r2", "r1"]


def test_one_summary_can_be_fetched(client):
    out = client.post("/a2a/dispatch", json=body()).json()
    got = client.get(f"/summaries/{out['summary_id']}").json()
    assert got["summary_id"] == out["summary_id"]

    missing = client.get("/summaries/sum_999")
    assert missing.status_code == 404


def test_queue_filters_by_status(client):
    client.post("/a2a/dispatch", json=body(request_id="r1"))
    client.post("/a2a/dispatch", json=body(request_id="r2"))
    tid = list(store.tickets)[0]
    client.post(f"/tickets/{tid}/claim", json={"employee": "Asha"})

    assert len(client.get("/tickets").json()["tickets"]) == 2
    assert len(client.get("/tickets?status=OPEN").json()["tickets"]) == 1
    assert len(client.get("/tickets?status=CLAIMED").json()["tickets"]) == 1
    assert client.get("/tickets?status=NONSENSE").status_code == 400


def test_urgent_tickets_sort_to_the_top(client):
    client.post("/a2a/dispatch", json=body(request_id="r1"))
    client.post("/a2a/dispatch", json=body(
        request_id="r2", payload={"reason_code": "DEADLINE_URGENT", "urgency": "URGENT"},
    ))

    queue = client.get("/tickets").json()["tickets"]
    assert queue[0]["urgency"] == "URGENT"


def test_ledger_counters_follow_the_record(client):
    client.post("/a2a/dispatch", json=body())
    counters = client.get("/ledger/PAYTM_MERCH_8821").json()["counters"]
    # An escalated case was not deflected: a human still has to do it.
    assert counters == {"tickets_deflected": 0, "fraud_blocked": 0}
