"""Stage 6 — the four sub-agents, and the trace that shows what each one did.

The trace has to be worth trusting, or it is decoration. Two properties matter:

  it is complete  — all four sub-agents report on every request, including the ones
                    with nothing to do;
  it is honest    — what a sub-agent says it did is what the response actually shows.

The second is what the cross-check tests below are for: RiskPolicyAgent's line and the
escalation it caused must agree, and LedgerOpsAgent must be idle on every request that
did not change the merchant's account.
"""
from __future__ import annotations

from app import store
from app.mesh import AGENT_SEQUENCE

from .test_stage2_dispatch import body as escalate_body
from .test_stage4_settlement import body as settlement_body

AGENT_NAMES = [name for name, _ in AGENT_SEQUENCE]


def trace_of(out: dict) -> dict[str, dict]:
    return {entry["agent"]: entry for entry in out["agent_trace"]}


# --- completeness -----------------------------------------------------------------------

def test_all_four_sub_agents_report_in_order(client):
    out = client.post("/a2a/dispatch", json=settlement_body()).json()

    assert [e["agent"] for e in out["agent_trace"]] == AGENT_NAMES
    assert [e["step"] for e in out["agent_trace"]] == [1, 2, 3, 4]
    assert AGENT_NAMES == [
        "IntelligenceAgent", "RiskPolicyAgent", "ResolutionAgent", "LedgerOpsAgent",
    ]


def test_every_entry_says_what_it_did_and_how_long_it_took(client):
    out = client.post("/a2a/dispatch", json=settlement_body()).json()

    for entry in out["agent_trace"]:
        assert entry["note"], f"{entry['agent']} said nothing"
        assert isinstance(entry["acted"], bool)
        assert isinstance(entry["ms"], (int, float))
        assert entry["ms"] >= 0


def test_a_sub_agent_with_nothing_to_do_says_so(client):
    """Explaining a settlement changes nothing, and the trace proves it."""
    out = client.post("/a2a/dispatch", json=settlement_body()).json()
    ops = trace_of(out)["LedgerOpsAgent"]

    assert ops["acted"] is False
    assert ops["note"] == "No ledger change required"


# --- honesty: the trace agrees with the answer --------------------------------------------

def test_the_trace_explains_a_resolved_settlement(client):
    out = client.post("/a2a/dispatch", json=settlement_body()).json()
    t = trace_of(out)

    # IntelligenceAgent read, and reported the numbers it found.
    assert "1000" in t["IntelligenceAgent"]["note"] or "100000" in t["IntelligenceAgent"]["note"]
    assert "5 deductions" in t["IntelligenceAgent"]["note"]

    # RiskPolicyAgent judged, and said why it was safe.
    assert "4160" in t["RiskPolicyAgent"]["note"]
    assert "without a human" in t["RiskPolicyAgent"]["note"]

    # ResolutionAgent composed.
    assert "Explained all 5 deductions" in t["ResolutionAgent"]["note"]

    assert out["status"] == "RESOLVED"


def test_the_trace_explains_an_escalated_settlement(client):
    client.post("/ledger/reset?break_settlement=true")
    out = client.post("/a2a/dispatch", json=settlement_body()).json()
    t = trace_of(out)

    # The sub-agent that made the call is the one that explains it.
    assert "a human must look" in t["RiskPolicyAgent"]["note"]
    assert "unaccounted for" in t["RiskPolicyAgent"]["note"]
    assert "handed it over" in t["ResolutionAgent"]["note"]

    assert out["status"] == "ESCALATED"
    assert out["escalation_ticket"]["reason_code"] == "SETTLEMENT_UNRECONCILED"
    # And nothing was changed on the way to escalating.
    assert trace_of(out)["LedgerOpsAgent"]["acted"] is False


def test_the_same_request_resolved_and_escalated_differ_only_at_risk_policy(client):
    """The decision lives in exactly one sub-agent, which is the point of the split."""
    ok = trace_of(client.post("/a2a/dispatch", json=settlement_body(request_id="a")).json())

    client.post("/ledger/reset?break_settlement=true")
    bad = trace_of(client.post("/a2a/dispatch", json=settlement_body(request_id="b")).json())

    # Both read the same thing.
    assert ok["IntelligenceAgent"]["note"] == bad["IntelligenceAgent"]["note"]
    # They disagree about whether it may be answered.
    assert ok["RiskPolicyAgent"]["note"] != bad["RiskPolicyAgent"]["note"]


def test_the_trace_explains_a_handover(client):
    out = client.post("/a2a/dispatch", json=escalate_body()).json()
    t = trace_of(out)

    assert "MERCHANT_REQUESTED_HUMAN" in t["IntelligenceAgent"]["note"]
    assert "never closed by the agent" in t["RiskPolicyAgent"]["note"]
    assert "Prepared the ticket" in t["ResolutionAgent"]["note"]
    assert t["LedgerOpsAgent"]["acted"] is False


def test_ledger_ops_is_idle_on_every_read_only_request(client):
    """The audit property: if LedgerOpsAgent did not act, nothing moved."""
    for req in (settlement_body(request_id="s"), escalate_body(request_id="e")):
        out = client.post("/a2a/dispatch", json=req).json()
        assert trace_of(out)["LedgerOpsAgent"]["acted"] is False

    # Corroborated independently of the trace.
    led = client.get("/ledger/PAYTM_MERCH_8821").json()
    assert led["settlement"]["net_credit_inr"] == 95_840
    assert led["loan_edi_status"] == "ACTIVE"
    assert led["chargeback"]["hold_status"] == "HELD"


# --- where the trace is kept ---------------------------------------------------------------

def test_the_feed_stays_lean_but_one_row_opens_to_its_reasoning(client):
    out = client.post("/a2a/dispatch", json=settlement_body()).json()
    sid = out["summary_id"]

    feed = client.get("/summaries").json()["summaries"]
    assert "agent_trace" not in feed[0]

    one = client.get(f"/summaries/{sid}").json()
    assert [e["agent"] for e in one["agent_trace"]] == AGENT_NAMES


def test_the_call_summary_keeps_exactly_the_shape_the_contract_froze(client):
    """The trace is stored beside the summary, not inside it, so Person 4 is unaffected."""
    client.post("/a2a/dispatch", json=settlement_body())
    assert "agent_trace" not in store.summaries[0]
    assert set(store.summaries[0]) == {
        "summary_id", "request_id", "session_id", "created_at", "duration_ms", "mid",
        "merchant_name", "language_code", "merchant_said", "intent", "found",
        "action_taken", "outcome", "ticket_id",
    }


def test_a_replay_returns_the_same_trace_and_stores_one(client):
    first = client.post("/a2a/dispatch", json=settlement_body()).json()
    second = client.post("/a2a/dispatch", json=settlement_body()).json()

    assert first["agent_trace"] == second["agent_trace"]
    assert len(store.traces) == 1


def test_a_request_we_could_not_read_has_no_trace(client):
    r = client.post("/a2a/dispatch", json=escalate_body(payload={}))
    assert r.status_code == 400
    assert "agent_trace" not in r.json()
    assert store.traces == {}
