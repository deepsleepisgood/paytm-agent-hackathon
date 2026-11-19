"""Merchant AI Teammate & A2A Orchestrator — Port 8003.

Run:  uvicorn main:app --port 8003 --reload   (from services/merchant_agent)
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import pipeline
import router
import upstream
from schemas import DEFAULT_MID, EventsResponse, MerchantResponse, QueryRequest
from state import MERCHANT_ORDER_SHEET, STATE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("merchant_agent")

MOCK_TRANSCRIPT = "मेरा कल का settlement ₹4,160 कम क्यों आया?"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# PLAN.md: frontend may also be served via ngrok/Vercel for field testing -> add origins via CORS_EXTRA_ORIGINS (comma-separated).
CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"] + [
    o.strip().rstrip("/") for o in os.getenv("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await upstream.aclose()


app = FastAPI(title="Merchant AI Teammate (A2A Orchestrator)", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content={"detail": {"error": "INTERNAL_ERROR", "message": str(exc), "message_hi": "कुछ गड़बड़ हो गई, कृपया दोबारा कोशिश करें।"}},
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "merchant_agent", "port": 8003, "sarvam_url": upstream.SARVAM_URL, "paytm_url": upstream.PAYTM_URL,
            "upstreams": upstream.upstream_status()}


async def _query(text: str, mid: str, request_id: str, consent_token: str, doc_context: dict[str, Any] | None,
                 transcript: str | None = None, transcript_source: str | None = None) -> dict[str, Any]:
    cls = await router.classify(text)
    slots = cls.slots
    extra: dict[str, Any] = {}
    if doc_context:
        fields = doc_context.get("extracted_fields", doc_context)
        if isinstance(fields, dict):
            slots = router.merge_slots(slots, router.slots_from_dict(fields))
            extra["doc_context"] = fields
    return await pipeline.run(
        request_id=request_id, mid=mid, consent_token=consent_token, intent=cls.intent,
        intent_source=cls.source, slots=slots, merchant_text=text, extra_payload=extra or None,
        transcript=transcript, transcript_source=transcript_source,
    )


@app.post("/merchant/query", response_model=MerchantResponse)
async def merchant_query(req: QueryRequest) -> dict[str, Any]:
    request_id = pipeline.new_request_id()
    consent_token = pipeline.require_consent(req.consent_granted, req.mid, request_id, channel="text")
    return await _query(req.text, req.mid, request_id, consent_token, req.doc_context)


@app.post("/merchant/query-audio", response_model=MerchantResponse)
async def merchant_query_audio(
    audio: UploadFile = File(...),
    mid: str = Form(DEFAULT_MID),
    consent_granted: bool = Form(False),
) -> dict[str, Any]:
    # Consent is checked before the audio is even transcribed.
    request_id = pipeline.new_request_id()
    consent_token = pipeline.require_consent(consent_granted, mid, request_id, channel="voice")
    data = await audio.read()
    if not data:
        raise HTTPException(400, detail={"error": "EMPTY_AUDIO", "message_hi": "आवाज़ रिकॉर्ड नहीं हुई, कृपया फिर से बोलिए।"})
    transcript, src = await upstream.stt(data, audio.filename or "audio.wav", audio.content_type or "audio/wav")
    if not transcript:
        transcript, src = MOCK_TRANSCRIPT, "mock"
    STATE.log(
        "AUDIO_TRANSCRIBED",
        pipeline.ACTOR_MERCHANT,
        f"STT: “{transcript}”" + (" [mock]" if src == "mock" else ""),
        {"transcript": transcript, "source": src, "language_code": "hi-IN"},
        request_id,
    )
    return await _query(transcript, mid, request_id, consent_token, None, transcript=transcript, transcript_source=src)


@app.post("/merchant/upload-doc", response_model=MerchantResponse)
async def merchant_upload_doc(
    file: UploadFile = File(...),
    doc_type: Literal["pod", "upi_screenshot"] = Form(...),
    mid: str = Form(DEFAULT_MID),
    consent_granted: bool = Form(False),
) -> dict[str, Any]:
    request_id = pipeline.new_request_id()
    consent_token = pipeline.require_consent(consent_granted, mid, request_id, channel=f"document:{doc_type}")

    data = await file.read()
    if not data:
        raise HTTPException(400, detail={"error": "EMPTY_FILE", "message_hi": "फ़ाइल खाली है, कृपया दोबारा upload कीजिए।"})
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail={"error": "FILE_TOO_LARGE", "message_hi": "फ़ाइल 10MB से छोटी होनी चाहिए।"})

    extract, src = await upstream.doc_extract(data, file.filename or "doc", file.content_type or "", doc_type)
    fields: dict[str, Any] = extract.get("extracted_fields") or {}
    pipeline.STATE.log(
        "DOC_EXTRACTED",
        pipeline.ACTOR_MERCHANT,
        f"{'Proof of Delivery' if doc_type == 'pod' else 'UPI screenshot'} read"
        f" (confidence {extract.get('confidence', 'n/a')})" + (" [mock]" if src == "mock" else ""),
        {**extract, "_source": src},
        request_id,
    )

    slots = router.slots_from_dict(fields)
    if doc_type == "pod":
        intent = "CHARGEBACK_RESOLVE"
        if not slots.order_id:
            slots = slots.model_copy(update={"order_id": str(fields.get("txn_id") or "") or None})
        extra = {"pod_submitted": True, "pod_document": fields, "doc_confidence": extract.get("confidence")}
    else:
        intent = "UTR_VERIFY"
        extra = {"screenshot_fields": fields, "doc_confidence": extract.get("confidence")}

    return await pipeline.run(
        request_id=request_id, mid=mid, consent_token=consent_token, intent=intent,
        intent_source="document", slots=slots, merchant_text=None, extra_payload=extra,
        doc_extract={**extract, "_source": src},
    )


@app.get("/events", response_model=EventsResponse)
async def events() -> dict[str, Any]:
    return {
        "a2a_events": STATE.a2a_events,
        "local_gst_itc_log": STATE.local_gst_itc_log,
        "gst_itc_total": STATE.gst_itc_total,
        "fraud_alerts": STATE.fraud_alerts,
        "merchant_order_sheet": MERCHANT_ORDER_SHEET,
    }


@app.post("/reset")
async def reset(cascade: bool = False) -> dict[str, Any]:
    """Clear merchant-side state. `?cascade=true` also resets Paytm's ledger on 8002."""
    STATE.reset()
    upstream.reset_circuits()  # re-probe 8001/8002 on next call
    paytm_reset = await upstream.paytm_reset() if cascade else None
    return {"status": "reset", "a2a_events": [], "local_gst_itc_log": [], "paytm_ledger_reset": paytm_reset}
