"""Stage 4 — SETTLEMENT_RECONCILE, contract acceptance case 1.

"Why did I get 95,840 and not 1,00,000?" is the call this product exists to answer, and
the one the 60-second demo opens with.
"""
from __future__ import annotations

from app import store
from app.templates import BANNED_WORDS, rupees


def body(**over) -> dict:
    base = {
        "request_id": "req-settle",
        "session_id": "sess-1",
        "mid": "PAYTM_MERCH_8821",
        "intent": "SETTLEMENT_RECONCILE",
        "language_code": "hi-IN",
        "merchant_said": "mujhe 95,840 hi kyun mile?",
        "payload": {},
        "consent_token": "ct-abc",
    }
    base.update(over)
    return base


# --- acceptance case 1 -------------------------------------------------------------------

def test_case_1_the_five_lines_explain_the_gap(client):
    out = client.post("/a2a/dispatch", json=body()).json()

    assert out["status"] == "RESOLVED"
    data = out["data"]
    assert data["gross_inr"] == 100_000
    assert data["net_credit_inr"] == 95_840
    assert data["variance_inr"] == 4_160
    assert len(data["lines"]) == 5
    assert sum(l["amount_inr"] for l in data["lines"]) == data["variance_inr"]
    assert data["reconciles"] is True

    # Closed with no human: no ticket, no action needed from the merchant.
    assert out["escalation_ticket"] is None
    assert out["action_required"] is None
    assert store.tickets == {}


def test_tomorrows_loan_deduction_is_flagged_before_it_surprises_them(client):
    out = client.post("/a2a/dispatch", json=body()).json()
    upcoming = out["data"]["upcoming"]

    assert upcoming == [{"label": "Loan instalment", "amount_inr": 500, "date": "2026-11-19"}]


def test_the_feed_row_shows_the_arithmetic(client):
    client.post("/a2a/dispatch", json=body())
    summary = store.summaries[0]

    assert summary["outcome"] == "RESOLVED_BY_AI"
    assert summary["action_taken"] == "None, explained only"
    assert summary["found"].startswith("Gap 4160 =")
    assert "MDR_FEE 1450" in summary["found"]
    assert "CHARGEBACK_HOLD 800" in summary["found"]
    assert summary["ticket_id"] is None


# --- what the merchant actually hears ------------------------------------------------------

def test_the_spoken_answer_carries_every_number(client):
    out = client.post("/a2a/dispatch", json=body()).json()
    text = out["template_text"]

    # Grouped the Indian way, which is also how Person 1's text-to-speech reads them
    # correctly: "95,840" is spoken as an amount, "95840" as a string of digits.
    for amount in ("1,00,000", "95,840", "4,160", "1,450", "1,500", "800"):
        assert amount in text, f"{amount} missing from: {text}"

    assert "18 November" in text
    assert not any(w in text.lower() for w in BANNED_WORDS)


def test_rupee_grouping_is_indian_not_western():
    # Person 1's text-to-speech reads "₹95,840" as an amount and "95840" as digits.
    assert rupees(100_000) == "₹1,00,000"
    assert rupees(95_840) == "₹95,840"
    assert rupees(4_160) == "₹4,160"
    assert rupees(800) == "₹800"
    assert rupees(0) == "₹0"


# --- the honest failure --------------------------------------------------------------------

def test_an_unexplained_gap_goes_to_a_human(client):
    """If our lines do not add up, we do not recite them as if they did."""
    client.post("/ledger/reset?break_settlement=true")
    out = client.post("/a2a/dispatch", json=body()).json()

    assert out["status"] == "ESCALATED"
    ticket = out["escalation_ticket"]
    assert ticket["reason_code"] == "SETTLEMENT_UNRECONCILED"
    assert ticket["suggested_next_step"].startswith("Pull the full settlement report")

    # The partial breakdown still travels with the ticket, so the employee starts
    # from what we found rather than from nothing.
    assert len(out["data"]["lines"]) == 5
    assert out["data"]["reconciles"] is False


def test_the_unexplained_answer_does_not_pretend_to_be_complete(client):
    client.post("/ledger/reset?break_settlement=true")
    text = client.post("/a2a/dispatch", json=body()).json()["template_text"]

    assert "not all of it" in text
    # It must not read out a list that does not add up.
    assert "soundbox rental" not in text.lower()


def test_a_date_we_have_no_settlement_for_is_a_bad_payload(client):
    r = client.post("/a2a/dispatch", json=body(payload={"settlement_date": "2026-01-01"}))
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "BAD_PAYLOAD"
    assert "2026-11-18" in err["message"]  # tells the caller what we do have


def test_asking_for_the_date_we_have_is_fine(client):
    out = client.post("/a2a/dispatch", json=body(payload={"settlement_date": "2026-11-18"})).json()
    assert out["status"] == "RESOLVED"


# --- it plays well with everything from stages 2 and 3 --------------------------------------

def test_a_resolved_call_counts_as_deflected(client):
    client.post("/a2a/dispatch", json=body())

    m = client.get("/metrics").json()
    assert m["calls_total"] == 1
    assert m["resolved_by_ai"] == 1
    assert m["escalated"] == 0
    assert m["auto_resolution_rate"] == 1.0

    counters = client.get("/ledger/PAYTM_MERCH_8821").json()["counters"]
    assert counters["tickets_deflected"] == 1


def test_replaying_a_settlement_call_writes_one_row(client):
    first = client.post("/a2a/dispatch", json=body()).json()
    second = client.post("/a2a/dispatch", json=body()).json()

    assert first == second
    assert len(store.summaries) == 1
