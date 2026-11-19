"""Pydantic schemas for the Merchant AI Buddy (Port 8003). Mirrors CONTRACT.md + PLAN.md (V3)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# PLAN.md's 8 intents, the original CONTRACT.md 6 (REFUND_MANAGE, FEE_GST_LOAN stay supported),
# and the 4 service-request intents (soundbox return, loan NOC, bank/KYC change, settlement hold).
Intent = Literal[
    "SETTLEMENT_RECONCILE",
    "UTR_VERIFY",
    "CHARGEBACK_RESOLVE",
    "REFUND_MANAGE",
    "FEE_GST_LOAN",
    "ESCALATE_HUMAN",
    "MANDATE_TROUBLESHOOT",
    "DUPLICATE_RECONCILE",
    "GROWTH_ADVISORY",
    "CASHFLOW_EDI_SWITCH",
    "SOUNDBOX_RETURN",
    "LOAN_CLOSURE_NOC",
    "BANK_KYC_UPDATE",
    "SETTLEMENT_HOLD_BANK",
]
INTENTS: tuple[str, ...] = Intent.__args__  # type: ignore[attr-defined]

DEFAULT_MID = "PAYTM_MERCH_8821"


class Slots(BaseModel):
    utr_number: Optional[str] = None
    order_id: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[str] = None


class QueryRequest(BaseModel):
    text: str = Field(..., min_length=1)
    mid: str = DEFAULT_MID
    consent_granted: bool = False
    doc_context: Optional[dict[str, Any]] = None


ProactiveScenario = Literal["CHARGEBACK_INCOMING", "CASHFLOW_EDI_SWITCH", "MANDATE_FAILED"]


class ProactiveRequest(BaseModel):
    mid: str = DEFAULT_MID
    scenario: ProactiveScenario
    consent_granted: bool = False


class ConfirmDisputeRequest(BaseModel):
    mid: str = DEFAULT_MID
    consent_granted: bool = False
    packet_id: str


class ConfirmEdiPauseRequest(BaseModel):
    mid: str = DEFAULT_MID
    consent_granted: bool = False
    offer_id: str
    pause_days: Optional[int] = Field(None, ge=1)


class Classification(BaseModel):
    intent: Intent
    slots: Slots
    source: Literal["llm", "utterance_bank", "keyword_fallback"]


class A2AEvent(BaseModel):
    seq: int
    ts: str
    unix: float
    type: str
    actor: str
    request_id: Optional[str]
    summary: str
    payload: dict[str, Any]


class MerchantResponse(BaseModel):
    """Returned by every /merchant/* action endpoint (query, query-audio, upload-doc, proactive-shield, confirm-*)."""

    request_id: str
    mid: str
    transcript: Optional[str] = None
    transcript_source: Optional[Literal["live", "mock"]] = None
    consent_token: str
    intent: Intent
    intent_source: Literal["llm", "utterance_bank", "keyword_fallback", "document", "proactive"]
    slots: Slots
    doc_extract: Optional[dict[str, Any]] = None
    # Buddy cognition (PLAN.md steps 1, 2, 5)
    historical_insight: dict[str, Any]
    intervention_evaluation: dict[str, Any]
    verified_outcome: dict[str, Any]
    pending_action: Optional[dict[str, Any]] = None
    # Paytm mesh (PLAN.md steps 3, 4)
    paytm_response: dict[str, Any]
    paytm_source: Literal["live", "mock"]
    paytm_agent_trace: list[dict[str, Any]]
    # Voice reply. hindi_reply == reply_text (PLAN.md name; reply_text kept for CONTRACT.md clients)
    hindi_reply: str
    reply_text: str
    reply_source: Literal["llm", "template"]
    audio_base64: Optional[str] = None
    audio_source: Literal["live", "mock", "unavailable"] = "unavailable"
    language_code: str = "hi-IN"
    # Merchant-side side effects
    fraud_alert: Optional[dict[str, Any]] = None
    gst_itc_logged: Optional[dict[str, Any]] = None
    local_gst_itc_log: list[dict[str, Any]]
    proactive: Optional[dict[str, Any]] = None
    a2a_events: list[A2AEvent]


class EventsResponse(BaseModel):
    a2a_events: list[A2AEvent]
    local_gst_itc_log: list[dict[str, Any]]
    gst_itc_total: float
    fraud_alerts: list[dict[str, Any]]
    merchant_order_sheet: dict[str, Any]
    strategy_memory: dict[str, Any]
    pending_actions: dict[str, Any]
