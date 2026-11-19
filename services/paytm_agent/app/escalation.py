"""When a human must take over, and what they are handed.

The product's claim is not "the AI escalates". It is that the human receives the case
already prepared: the reason, what was tried, and what to do next. That is what this
module builds, so a support employee never has to re-ask the merchant anything.
"""
from __future__ import annotations

from . import clock, store
from .config import URGENT_HOURS
from .models import IntentResult

# Contract section 2.2. Every escalation carries exactly one of these.
REASON_CODES = {
    "LOW_DOC_CONFIDENCE": "Document confidence below the bar to act on",
    "DOC_MISMATCH": "Order id or amount on the proof does not match the dispute",
    "REFUND_OVER_LIMIT": "Refund above the amount the agent may approve alone",
    "ORDER_NOT_FOUND": "Order is not in the merchant's ledger",
    "SETTLEMENT_UNRECONCILED": "Deductions do not add up to the settlement variance",
    "COMPLIANCE_HOLD": "Settlement is on a risk or compliance hold",
    "BANK_ACCOUNT_CHANGE": "Request to change the settlement bank account",
    "OUT_OF_SCOPE": "Outside the six intents this agent handles",
    "REPEATED_ISSUE": "Same issue raised twice in a session without being solved",
    "MERCHANT_REQUESTED_HUMAN": "The merchant asked to speak to a person",
    "REPEATED_UNKNOWN_UTR": "Several unknown payment references in one session",
    "DEADLINE_URGENT": "Deadline too close to resolve without a person",
    "IDENTITY_NOT_VERIFIED": "Identity check required but not passed",
}

# Four of these have no producer among the six intents today:
#   COMPLIANCE_HOLD, OUT_OF_SCOPE, REPEATED_ISSUE, IDENTITY_NOT_VERIFIED
# They are part of the frozen vocabulary so Person 3 and the console can display them,
# but nothing in this service raises them yet. Noted so nobody writes a test demanding
# one and then "fixes" the agent to satisfy it.
UNUSED_REASON_CODES = {
    "COMPLIANCE_HOLD", "OUT_OF_SCOPE", "REPEATED_ISSUE", "IDENTITY_NOT_VERIFIED",
}

# What the employee should actually do, per reason. Written for someone picking the
# ticket up cold, with no memory of the call.
NEXT_STEP = {
    "LOW_DOC_CONFIDENCE": "Call the merchant and ask for a clearer photo before the deadline",
    "DOC_MISMATCH": "Check which order the proof belongs to, then ask for the right document",
    "REFUND_OVER_LIMIT": "Confirm the refund with the merchant, then approve it manually",
    "ORDER_NOT_FOUND": "Ask the merchant for the correct order id and check the full ledger",
    "SETTLEMENT_UNRECONCILED": "Pull the full settlement report; a deduction is missing from our breakdown",
    "COMPLIANCE_HOLD": "Route to the risk team; the hold cannot be lifted from support",
    "BANK_ACCOUNT_CHANGE": "Run the identity check before touching the bank account",
    "OUT_OF_SCOPE": "Handle directly; this is outside what the agent covers",
    "REPEATED_ISSUE": "Call the merchant; the earlier answer did not land",
    "MERCHANT_REQUESTED_HUMAN": "Call the merchant back",
    "REPEATED_UNKNOWN_UTR": "Call the merchant and warn them before they hand over goods",
    "DEADLINE_URGENT": "Chase the merchant by phone now; the deadline is close",
    "IDENTITY_NOT_VERIFIED": "Verify identity before answering anything about this account",
}


def urgency_for(deadline_iso: str | None, default: str = "NORMAL") -> str:
    """A deadline inside URGENT_HOURS makes a ticket urgent.

    Computed from the deadline rather than taken on trust, so the queue's urgency is
    always consistent with the clock a judge can see.
    """
    if not deadline_iso:
        return default
    return "URGENT" if clock.hours_until(deadline_iso) < URGENT_HOURS else default


def create_ticket(result: IntentResult, req, merchant_name: str, summary_id: str) -> dict:
    """Build and store the ticket a human picks up."""
    reason_code = result.reason_code or "OUT_OF_SCOPE"
    ticket_id = store.next_id("tkt")

    ticket = {
        "ticket_id": ticket_id,  # CONTRACT
        "created_at": clock.iso(),  # CONTRACT
        "mid": req.mid,  # CONTRACT
        "merchant_name": merchant_name,  # CONTRACT
        "reason_code": reason_code,  # CONTRACT
        "reason_text": result.reason_text or REASON_CODES.get(reason_code, reason_code),  # CONTRACT
        "merchant_said": req.merchant_said,  # CONTRACT
        "tried": list(result.tried),  # CONTRACT
        "suggested_next_step": result.suggested_next_step or NEXT_STEP.get(reason_code, ""),  # CONTRACT
        "deadline_iso": result.deadline_iso,  # CONTRACT
        "urgency": urgency_for(result.deadline_iso, result.urgency),  # CONTRACT
        "status": "OPEN",  # CONTRACT
        "claimed_by": None,  # CONTRACT
        "resolution_note": None,  # CONTRACT
        "summary_id": summary_id,  # CONTRACT
        # Additive, for avg_resolution_ms_human on the metrics strip.
        "claimed_at": None,
        "resolved_at": None,
    }
    store.tickets[ticket_id] = ticket
    return ticket
