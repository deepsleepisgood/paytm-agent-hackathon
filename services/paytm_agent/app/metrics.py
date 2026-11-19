"""The numbers strip, computed from the records rather than kept as counters.

Why derived and not counted: a counter is a second side effect. The dispatch idempotency
gate protects the summary and the ticket, so if metrics were incremented separately a
replayed request could inflate them even though no new record was written. Reading the
stores means a replay that writes nothing counts nothing, with no extra guard.

These are the numbers that go on the pitch slide, so each one is defined here in terms a
judge could check against the call feed on screen.
"""
from __future__ import annotations

from datetime import datetime

from . import store


def _ms_between(start_iso: str | None, end_iso: str | None) -> float | None:
    if not start_iso or not end_iso:
        return None
    return (datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)).total_seconds() * 1000


def _mean(values: list[float]) -> float | None:
    """None, never 0, when there is nothing to average.

    Zero would read on the console as "humans resolve instantly", which looks like a
    bug. An empty average is an absence, and the console shows it as a dash.
    """
    return round(sum(values) / len(values), 1) if values else None


def compute() -> dict:
    summaries = store.summaries
    calls_total = len(summaries)

    resolved = [s for s in summaries if s["outcome"] == "RESOLVED_BY_AI"]
    escalated = [s for s in summaries if s["outcome"] == "ESCALATED"]
    # Chargeback step 1 lands here: the agent asked the merchant to upload a document,
    # so the case is neither closed nor handed over. It counts in calls_total, which is
    # why resolved + escalated does not always equal calls_total.
    awaiting = [s for s in summaries if s["outcome"] == "AWAITING_MERCHANT"]

    human_times = [
        ms for t in store.tickets.values()
        if t["status"] == "RESOLVED"
        and (ms := _ms_between(t["created_at"], t["resolved_at"])) is not None
    ]

    by_status: dict[str, int] = {"OPEN": 0, "CLAIMED": 0, "RESOLVED": 0}
    for t in store.tickets.values():
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1

    return {
        "calls_total": calls_total,  # CONTRACT
        "resolved_by_ai": len(resolved),  # CONTRACT
        "escalated": len(escalated),  # CONTRACT
        # CONTRACT. Share of all calls the agent closed with no human. 0.0 on a cold
        # start rather than a division by zero.
        "auto_resolution_rate": round(len(resolved) / calls_total, 3) if calls_total else 0.0,
        "avg_resolution_ms_ai": _mean([float(s["duration_ms"]) for s in resolved]),  # CONTRACT
        # CONTRACT. Ticket creation to an employee closing it.
        "avg_resolution_ms_human": _mean(human_times),
        "fraud_flags": len(store.fraud_events),  # CONTRACT
        "tickets_open": by_status["OPEN"],  # CONTRACT
        "tickets_claimed": by_status["CLAIMED"],  # CONTRACT
        "tickets_resolved": by_status["RESOLVED"],  # CONTRACT
        # Additive: the console shows it so the three outcome counts visibly account for
        # every call, instead of appearing not to add up.
        "awaiting_merchant": len(awaiting),
        # V2 delta. Deliberately outside calls_total: Paytm raised these, the merchant
        # did not call about them, and the whole point of the feature is that the
        # merchant never had to.
        "proactive_alerts": len(store.alerts),
        "edi_status": store.ledger.loan.status,
    }
