"""ESCALATE_HUMAN — hand the case to a person, with the case already prepared.

The only intent with no ledger arithmetic, which is why it was built first: it exercises
the whole envelope before any domain logic exists to confuse a failure.

It is also where two scenarios land that are not intents of their own: a request to
change the settlement bank account, and a merchant asking for a person. Person 3 routes
both here with the matching reason_code.
"""
from __future__ import annotations

from .. import templates
from ..errors import PayloadError
from ..escalation import REASON_CODES
from ..mesh import Case

# Used when the merchant agent routes here without saying why.
DEFAULT_REASON_CODE = "MERCHANT_REQUESTED_HUMAN"

# Shorter names the rest of the team uses for the same reasons.
REASON_ALIASES = {
    "MERCHANT_REQUESTED": "MERCHANT_REQUESTED_HUMAN",
    "NEEDS_HUMAN": "MERCHANT_REQUESTED_HUMAN",
    "BANK_ACCOUNT_CHANGE_REQUEST": "BANK_ACCOUNT_CHANGE",
}


def gather(case: Case) -> str:
    """IntelligenceAgent: parse what we are being asked to hand over, and why."""
    payload = case.req.payload or {}

    # A missing reason is not a reason to refuse. The merchant agent routes here when
    # it has decided a person is needed and often has nothing more specific to say, and
    # the overwhelmingly likely reason is that the merchant asked for one. Rejecting the
    # request would drop a case the agent had already given up on, which is the worst
    # possible moment to be pedantic about a field name.
    reason_code = REASON_ALIASES.get(
        payload.get("reason_code") or "", payload.get("reason_code")
    ) or DEFAULT_REASON_CODE

    if reason_code not in REASON_CODES:
        raise PayloadError(
            f"reason_code {reason_code!r} is not one of {sorted(REASON_CODES)}"
        )

    urgency = (payload.get("urgency") or "NORMAL").upper()
    if urgency not in {"NORMAL", "URGENT"}:
        raise PayloadError("urgency must be NORMAL or URGENT")

    case.data = {}
    case.tried = list(payload.get("tried") or [])
    # Stashed for the next two stages rather than re-parsed by them.
    case.reason_code = reason_code
    case.reason_text = payload.get("reason_text") or REASON_CODES[reason_code]
    case.urgency = urgency

    return f"Parsed a handover request: {reason_code}"


def assess(case: Case) -> str:
    """RiskPolicyAgent: nothing here is ever for the agent to decide."""
    case.escalate(case.reason_code, case.reason_text, urgency=case.urgency)
    return f"Policy: {case.reason_code} is never closed by the agent, routing to a human"


def resolve(case: Case) -> str:
    """ResolutionAgent: prepare the ticket content and reassure the merchant."""
    case.found = case.reason_text
    case.action_taken = "Passed to a human with a prepared ticket"
    case.template_text = templates.render("ESCALATE_HUMAN", case.data, "ESCALATED")
    return "Prepared the ticket and told the merchant a colleague will follow up"
