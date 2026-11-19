"""Stage 3 — the numbers strip, derived from the records.

Two things are being proven: the edge cases render as something a human can read rather
than NaN or a crash, and a replayed request cannot inflate the figures.
"""
from __future__ import annotations

from datetime import timedelta

from app import clock, store

from .test_stage2_dispatch import body


def test_cold_start_is_all_zeros_and_no_crash(client):
    """The console loads before anyone has called. It must not divide by zero."""
    m = client.get("/metrics").json()

    assert m["calls_total"] == 0
    assert m["resolved_by_ai"] == 0
    assert m["escalated"] == 0
    assert m["auto_resolution_rate"] == 0.0  # not a ZeroDivisionError
    assert m["tickets_open"] == m["tickets_claimed"] == m["tickets_resolved"] == 0
    assert m["fraud_flags"] == 0


def test_averages_are_null_not_zero_when_nothing_has_resolved(client):
    """Zero would read on screen as 'humans resolve instantly', which looks like a bug."""
    m = client.get("/metrics").json()
    assert m["avg_resolution_ms_ai"] is None
    assert m["avg_resolution_ms_human"] is None


def test_every_field_the_contract_names_is_present(client):
    m = client.get("/metrics").json()
    for key in (
        "calls_total", "resolved_by_ai", "escalated", "auto_resolution_rate",
        "avg_resolution_ms_ai", "avg_resolution_ms_human", "fraud_flags",
        "tickets_open", "tickets_claimed", "tickets_resolved",
    ):
        assert key in m, key


def test_an_escalation_moves_the_right_numbers(client):
    client.post("/a2a/dispatch", json=body())
    m = client.get("/metrics").json()

    assert m["calls_total"] == 1
    assert m["escalated"] == 1
    assert m["resolved_by_ai"] == 0
    assert m["auto_resolution_rate"] == 0.0
    assert m["tickets_open"] == 1
    # Still null: a ticket was raised but no human has closed it yet.
    assert m["avg_resolution_ms_human"] is None


def test_human_resolution_time_is_creation_to_close(client):
    """The contract's own example is 420000 ms. That is seven minutes."""
    client.post("/a2a/dispatch", json=body())
    tid = list(store.tickets)[0]

    # The employee picks it up and closes it seven minutes later.
    clock.freeze(clock.now() + timedelta(minutes=7))
    client.post(f"/tickets/{tid}/claim", json={"employee": "Asha"})
    client.post(f"/tickets/{tid}/resolve", json={"employee": "Asha", "note": "Called back"})

    m = client.get("/metrics").json()
    assert m["avg_resolution_ms_human"] == 420_000.0
    assert m["tickets_resolved"] == 1
    assert m["tickets_open"] == 0


def test_ticket_states_always_account_for_every_ticket(client):
    client.post("/a2a/dispatch", json=body(request_id="r1"))
    client.post("/a2a/dispatch", json=body(request_id="r2"))
    client.post("/a2a/dispatch", json=body(request_id="r3"))

    tids = list(store.tickets)
    client.post(f"/tickets/{tids[0]}/claim", json={"employee": "Asha"})
    client.post(f"/tickets/{tids[1]}/resolve", json={"employee": "Bhavna", "note": "done"})

    m = client.get("/metrics").json()
    assert m["tickets_open"] == 1
    assert m["tickets_claimed"] == 1
    assert m["tickets_resolved"] == 1
    assert m["tickets_open"] + m["tickets_claimed"] + m["tickets_resolved"] == len(store.tickets)


def test_a_replay_cannot_inflate_the_numbers(client):
    """The reason metrics are derived rather than counted."""
    client.post("/a2a/dispatch", json=body())
    before = client.get("/metrics").json()

    for _ in range(5):
        client.post("/a2a/dispatch", json=body())

    assert client.get("/metrics").json() == before


def test_rejected_calls_are_not_counted_as_calls(client):
    """A call we refused to answer is not a call the agent handled."""
    client.post("/a2a/dispatch", json=body(consent_token=""))
    client.post("/a2a/dispatch", json=body(request_id="r2", mid="NOPE"))

    m = client.get("/metrics").json()
    assert m["calls_total"] == 0


def test_the_outcome_counts_add_up_to_calls_total(client):
    """Guards the auto_resolution_rate denominator.

    Chargeback step 1 is AWAITING_MERCHANT, so resolved + escalated alone will not equal
    calls_total once stage 6 lands. The console shows awaiting_merchant for that reason.
    """
    client.post("/a2a/dispatch", json=body(request_id="r1"))
    client.post("/a2a/dispatch", json=body(request_id="r2"))

    m = client.get("/metrics").json()
    assert m["resolved_by_ai"] + m["escalated"] + m["awaiting_merchant"] == m["calls_total"]
