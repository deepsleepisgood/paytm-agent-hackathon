"""Read-only views of state, plus the demo's reset lever.

These are what the employee console polls. They never make decisions; they report.
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from . import clock, metrics, proactive, store
from .dispatch import dispatch
from .errors import error_response
from .models import (
    ClaimBody,
    DispatchRequest,
    ExecuteEdiPauseBody,
    ProactiveAlertBody,
    ResolveBody,
)

router = APIRouter()


@router.post("/a2a/dispatch")
def a2a_dispatch(req: DispatchRequest):
    """The one entry point Person 3's merchant agent calls when the merchant asks."""
    body, status = dispatch(req)
    return JSONResponse(status_code=status, content=body)


@router.post("/a2a/proactive-alert")
def a2a_proactive_alert(req: ProactiveAlertBody):
    """Paytm speaking first: a dispute landed, or tomorrow's payout will be short."""
    body, status = proactive.raise_alert(req.mid, req.trigger_type)
    return JSONResponse(status_code=status, content=body)


@router.post("/a2a/execute-edi-pause")
def a2a_execute_edi_pause(req: ExecuteEdiPauseBody):
    """The merchant consented, so pause the NBFC's daily loan deduction."""
    body, status = proactive.execute_edi_pause(
        req.mid, req.consent_token, req.pause_days, req.offer_id
    )
    return JSONResponse(status_code=status, content=body)


@router.get("/ledger/{mid}")
def get_ledger(mid: str):
    """Full live state for a merchant."""
    if mid != store.ledger.mid:
        return error_response("UNKNOWN_MID", f"No merchant {mid!r} in this service", status=404)

    body = store.ledger.as_dict()
    body["counters"] = {
        "tickets_deflected": store.tickets_deflected(),
        "fraud_blocked": store.fraud_blocked(),
    }
    return body


@router.post("/ledger/reset")
def reset_ledger(
    chargeback_hours_left: float = Query(
        default=48.0,
        description="Hours until the chargeback evidence deadline. Set it below "
                    "URGENT_HOURS to demonstrate the urgent escalation path.",
    ),
    break_settlement: bool = Query(
        default=False,
        description="Perturb a deduction so the lines no longer explain the variance, "
                    "which triggers SETTLEMENT_UNRECONCILED.",
    ),
):
    store.reset(chargeback_hours_left=chargeback_hours_left,
                break_settlement=break_settlement)
    return {"ok": True}


# --- what the employee console reads ------------------------------------------------

@router.get("/metrics")
def get_metrics():
    """The numbers strip. Computed from real runs only."""
    return metrics.compute()


@router.get("/summaries")
def list_summaries(limit: int = Query(default=50, ge=1, le=500)):
    """The call feed: every dispatch, newest first."""
    return {"summaries": list(reversed(store.summaries))[:limit]}


@router.get("/summaries/{summary_id}")
def get_summary(summary_id: str):
    found = next((s for s in store.summaries if s["summary_id"] == summary_id), None)
    if found is None:
        return error_response("NOT_FOUND", f"No summary {summary_id!r}", status=404)
    # The feed stays lean; opening one row shows the reasoning behind it.
    return {**found, "agent_trace": store.traces.get(summary_id, [])}


@router.get("/tickets")
def list_tickets(status: str | None = Query(default=None)):
    """The escalation queue. Urgent first, then newest first."""
    items = list(store.tickets.values())
    if status:
        wanted = status.upper()
        if wanted not in {"OPEN", "CLAIMED", "RESOLVED"}:
            return error_response("BAD_PAYLOAD", f"status {status!r} is not OPEN, CLAIMED or RESOLVED")
        items = [t for t in items if t["status"] == wanted]
    items.sort(key=lambda t: (t["urgency"] != "URGENT", t["created_at"]), reverse=False)
    urgent = [t for t in items if t["urgency"] == "URGENT"]
    normal = [t for t in items if t["urgency"] != "URGENT"]
    return {"tickets": urgent[::-1] + normal[::-1]}


@router.post("/tickets/{ticket_id}/claim")
def claim_ticket(ticket_id: str, body: ClaimBody):
    ticket = store.tickets.get(ticket_id)
    if ticket is None:
        return error_response("NOT_FOUND", f"No ticket {ticket_id!r}", status=404)
    if ticket["status"] != "OPEN":
        # Refused rather than silently reassigned: the whole point of Claim is that two
        # people do not work the same case.
        return error_response(
            "BAD_PAYLOAD",
            f"Ticket {ticket_id} is already {ticket['status'].lower()}"
            + (f" by {ticket['claimed_by']}" if ticket["claimed_by"] else ""),
            status=409,
        )
    ticket["status"] = "CLAIMED"
    ticket["claimed_by"] = body.employee
    ticket["claimed_at"] = clock.iso()
    return ticket


@router.post("/tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: str, body: ResolveBody):
    ticket = store.tickets.get(ticket_id)
    if ticket is None:
        return error_response("NOT_FOUND", f"No ticket {ticket_id!r}", status=404)
    if ticket["status"] == "RESOLVED":
        return error_response("BAD_PAYLOAD", f"Ticket {ticket_id} is already resolved", status=409)
    ticket["status"] = "RESOLVED"
    ticket["claimed_by"] = ticket["claimed_by"] or body.employee
    ticket["resolution_note"] = body.note
    ticket["resolved_at"] = clock.iso()
    return ticket
