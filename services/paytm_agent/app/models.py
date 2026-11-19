"""Wire shapes and the seam between the envelope and the intent handlers.

Fields marked CONTRACT match contract.md exactly. A few additive fields exist
(`resolved_at`, `claimed_at`, `lines_total_inr`); a client that only reads the contract
fields keeps working, and we need them for honest metrics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# The intents this service answers. Anything else is the UNKNOWN_INTENT error, not an
# OUT_OF_SCOPE escalation: we cannot summarise a case we did not understand.
#
# The first eight are the scenario table. The last two are contract.md v1 intents that
# Person 1 and Person 3 still emit, so rejecting them would break a working integration
# for no gain.
INTENTS = (
    "MANDATE_TROUBLESHOOT",
    "SETTLEMENT_RECONCILE",
    "CHARGEBACK_RESOLVE",
    "UTR_VERIFY",
    "DUPLICATE_PAYMENT_RECONCILE",
    "WORKING_CAPITAL_ADVISORY",
    "CASHFLOW_EDI_SWITCH",
    "ESCALATE_HUMAN",
    "FEE_GST_LOAN",
    "REFUND_MANAGE",
)

# The same scenario goes by two names across the team: Person 1's sarvam_service calls
# these two its canonical names and treats ours as the alternatives, and its mock will
# emit whichever name the caller listed in its own prompt. Rather than make anyone
# rename anything mid-hackathon, both are accepted and normalised here.
INTENT_ALIASES = {
    "DUPLICATE_RECONCILE": "DUPLICATE_PAYMENT_RECONCILE",
    "GROWTH_ADVISORY": "WORKING_CAPITAL_ADVISORY",
}


def canonical_intent(name: str) -> str | None:
    """The name this service works with, or None if we do not recognise it at all."""
    resolved = INTENT_ALIASES.get(name, name)
    return resolved if resolved in INTENTS else None

Status = Literal["RESOLVED", "ACTION_REQUIRED", "ESCALATED", "ERROR"]

# How a dispatch status becomes the word the employee console shows in the feed.
OUTCOME_BY_STATUS: dict[str, str] = {
    "RESOLVED": "RESOLVED_BY_AI",
    "ACTION_REQUIRED": "AWAITING_MERCHANT",
    "ESCALATED": "ESCALATED",
}


class DispatchRequest(BaseModel):
    """What Person 3's merchant agent sends us.

    `consent_token` is deliberately Optional here rather than required: we want to
    answer a missing token with the contract's CONSENT_MISSING error, not with a
    framework validation error that Person 3 would have to special-case.
    """

    request_id: str = Field(..., min_length=1)  # CONTRACT
    mid: str = Field(..., min_length=1)  # CONTRACT
    intent: str = Field(..., min_length=1)  # CONTRACT
    # CONTRACT. Optional in practice: if Person 3 omits it we treat the call as its own
    # session, which only means cross-call rules (repeated unknown UTRs) cannot fire.
    session_id: Optional[str] = None
    language_code: str = "en-IN"  # CONTRACT — echoed and stored, never interpreted
    merchant_said: str = ""  # CONTRACT — kept verbatim for the call summary
    payload: dict[str, Any] = Field(default_factory=dict)  # CONTRACT
    consent_token: Optional[str] = None  # CONTRACT


class ProactiveAlertBody(BaseModel):
    """V2 delta. No consent_token: the alert only informs the merchant about their own
    account and shares nothing onward."""

    mid: str = Field(..., min_length=1)
    trigger_type: str = Field(..., min_length=1)


class ExecuteEdiPauseBody(BaseModel):
    """V2 delta. consent_token is Optional so a missing one becomes the contract's 403
    DPDP_CONSENT_REQUIRED rather than a framework validation error."""

    mid: str = Field(..., min_length=1)
    consent_token: Optional[str] = None
    pause_days: int = 2
    offer_id: Optional[str] = None


class ClaimBody(BaseModel):
    employee: str = Field(..., min_length=1)


class ResolveBody(BaseModel):
    employee: str = Field(..., min_length=1)
    note: str = ""


@dataclass
class IntentResult:
    """What an intent handler returns.

    Handlers are pure: they read the ledger and the session and return this. They never
    touch the stores, create tickets, write summaries or read the system clock directly.
    That is what keeps the side-effect ordering in one place (dispatch.py) and therefore
    what makes the idempotency gate able to protect all of it.
    """

    data: dict[str, Any]
    status: Status
    # One line for the employee's call feed: what the agent found, in plain words.
    found: str
    action_taken: str = "None, explained only"
    # The merchant's sentence, written by ResolutionAgent. Empty means no sub-agent
    # composed one, and dispatch falls back to rendering it from the templates.
    template_text: str = ""

    # Set when status is ACTION_REQUIRED.
    action_required: Optional[dict[str, Any]] = None

    # Set when status is ESCALATED.
    reason_code: Optional[str] = None
    reason_text: str = ""
    tried: list[str] = field(default_factory=list)
    suggested_next_step: str = ""
    urgency: Literal["NORMAL", "URGENT"] = "NORMAL"
    deadline_iso: Optional[str] = None

    # A fraud signal to count on the metrics strip. The frozen summary schema has no
    # field for it, so it is recorded separately and never spoken to the merchant.
    fraud_event: Optional[dict[str, Any]] = None
