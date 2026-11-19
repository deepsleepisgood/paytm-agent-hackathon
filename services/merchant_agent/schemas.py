"""Pydantic schemas for the Merchant AI Teammate (Port 8003). Mirrors CONTRACT.md."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Intent = Literal[
    "SETTLEMENT_RECONCILE",
    "UTR_VERIFY",
    "CHARGEBACK_RESOLVE",
    "REFUND_MANAGE",
    "FEE_GST_LOAN",
    "ESCALATE_HUMAN",
]
INTENTS: tuple[str, ...] = (
    "SETTLEMENT_RECONCILE",
    "UTR_VERIFY",
    "CHARGEBACK_RESOLVE",
    "REFUND_MANAGE",
    "FEE_GST_LOAN",
    "ESCALATE_HUMAN",
)

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


class Classification(BaseModel):
    intent: Intent
    slots: Slots
    source: Literal["llm", "keyword_fallback"]


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
    """Returned by /merchant/query, /merchant/query-audio and /merchant/upload-doc."""

    request_id: str
    mid: str
    transcript: Optional[str] = None
    transcript_source: Optional[Literal["live", "mock"]] = None
    consent_token: str
    intent: Intent
    intent_source: Literal["llm", "keyword_fallback", "document"]
    slots: Slots
    doc_extract: Optional[dict[str, Any]] = None
    paytm_response: dict[str, Any]
    paytm_source: Literal["live", "mock"]
    reply_text: str
    reply_source: Literal["llm", "template"]
    audio_base64: Optional[str] = None
    language_code: str = "hi-IN"
    fraud_alert: Optional[dict[str, Any]] = None
    gst_itc_logged: Optional[dict[str, Any]] = None
    local_gst_itc_log: list[dict[str, Any]]
    a2a_events: list[A2AEvent]


class EventsResponse(BaseModel):
    a2a_events: list[A2AEvent]
    local_gst_itc_log: list[dict[str, Any]]
    gst_itc_total: float
    fraud_alerts: list[dict[str, Any]]
    merchant_order_sheet: dict[str, Any]
