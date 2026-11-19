"""HTTP clients for Sarvam (8001) and Paytm Agent (8002).

Every call has a hard timeout and a deterministic fallback, so the merchant agent works
standalone before 8001/8002 are up and degrades gracefully if they fail mid-demo.
Each helper returns (result, source) where source is "live" or "mock"/"fallback".
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional

import httpx

log = logging.getLogger("merchant_agent.upstream")

try:  # PLAN.md: URLs are configured via .env on the demo laptop
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:  # pragma: no cover
    pass

# 127.0.0.1 rather than localhost: on Windows, "localhost" tries IPv6 first and adds ~2s per refused call.
# PLAN.md names are SARVAM_SERVICE_URL / PAYTM_AGENT_URL; the short names are accepted too.
SARVAM_URL = (os.getenv("SARVAM_SERVICE_URL") or os.getenv("SARVAM_URL") or "http://127.0.0.1:8001").rstrip("/")
PAYTM_URL = (os.getenv("PAYTM_AGENT_URL") or os.getenv("PAYTM_URL") or "http://127.0.0.1:8002").rstrip("/")
TIMEOUT_S = float(os.getenv("UPSTREAM_TIMEOUT_S", "6"))
# After a host refuses a connection, skip it for this long (instant fallback instead of re-waiting).
CIRCUIT_COOLDOWN_S = float(os.getenv("UPSTREAM_CIRCUIT_COOLDOWN_S", "10"))

_client: Optional[httpx.AsyncClient] = None
_down_until: dict[str, float] = {}


class CircuitOpen(Exception):
    pass


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S, connect=min(2.0, TIMEOUT_S)))
    return _client


def upstream_status() -> dict[str, str]:
    now = time.monotonic()
    return {base: ("down (circuit open)" if _down_until.get(base, 0) > now else "unknown/up") for base in (SARVAM_URL, PAYTM_URL)}


async def _post(base: str, path: str, **kwargs: Any) -> httpx.Response:
    if _down_until.get(base, 0) > time.monotonic():
        raise CircuitOpen(f"{base} marked down")
    try:
        r = await client().post(f"{base}{path}", **kwargs)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        _down_until[base] = time.monotonic() + CIRCUIT_COOLDOWN_S
        raise
    _down_until.pop(base, None)
    return r


def reset_circuits() -> None:
    _down_until.clear()


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ----------------------------------------------------------------------------- Sarvam (8001)


async def stt(audio: bytes, filename: str, content_type: str) -> tuple[Optional[str], str]:
    try:
        r = await _post(
            SARVAM_URL, "/stt",
            files={"audio": (filename or "audio.wav", audio, content_type or "audio/wav")},
        )
        r.raise_for_status()
        transcript = (r.json() or {}).get("transcript")
        if transcript:
            return transcript, "live"
    except Exception as exc:  # noqa: BLE001 - any upstream failure falls back
        log.warning("STT failed (%s): %s", type(exc).__name__, exc)
    return None, "fallback"


async def llm(system_prompt: str, user_prompt: str, response_format: str = "text") -> Optional[Any]:
    """Returns parsed JSON (dict) for response_format='json', a string for 'text', or None on failure."""
    try:
        r = await _post(
            SARVAM_URL, "/llm",
            json={
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_format": response_format,
            },
        )
        r.raise_for_status()
        reply = (r.json() or {}).get("reply")
        if reply is None:
            return None
        if response_format == "json":
            return _parse_json(reply)
        return str(reply).strip() or None
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM failed (%s): %s", type(exc).__name__, exc)
        return None


def _parse_json(reply: Any) -> Optional[dict[str, Any]]:
    if isinstance(reply, dict):
        return reply
    text = str(reply).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
    return None


async def tts(text: str, language_code: str = "hi-IN") -> tuple[Optional[str], str]:
    try:
        r = await _post(SARVAM_URL, "/tts", json={"text": text, "language_code": language_code})
        r.raise_for_status()
        audio = (r.json() or {}).get("audio_base64")
        if audio:
            return audio, "live"
    except Exception as exc:  # noqa: BLE001
        log.warning("TTS failed (%s): %s", type(exc).__name__, exc)
    return None, "unavailable"


async def doc_extract(
    file_bytes: bytes, filename: str, content_type: str, doc_type: str
) -> tuple[dict[str, Any], str]:
    try:
        r = await _post(
            SARVAM_URL, "/doc-extract",
            files={"file": (filename or "doc.png", file_bytes, content_type or "application/octet-stream")},
            data={"doc_type": doc_type},
        )
        r.raise_for_status()
        body = r.json() or {}
        if isinstance(body.get("extracted_fields"), dict):
            return body, "live"
    except Exception as exc:  # noqa: BLE001
        log.warning("doc-extract failed (%s): %s", type(exc).__name__, exc)
    return mock_doc_extract(doc_type, filename), "mock"


def mock_doc_extract(doc_type: str, filename: str = "") -> dict[str, Any]:
    if doc_type == "pod":
        fields: dict[str, Any] = {
            "order_id": "9981",
            "txn_id": "9981",
            "delivered_to": "Ramesh Kumar",
            "delivery_date": "2026-11-16",
            "courier": "Delhivery",
            "awb_number": "DLV7712093341",
            "signature_present": True,
        }
    else:
        # Offline demo: a 12-digit UTR in the filename is used as-is; "fake"/"tamper" in the
        # filename (e.g. PLAN.md's fake_upi.png) yields an unknown UTR -> fraud path.
        m = re.search(r"(?<!\d)\d{12}(?!\d)", filename or "")
        if m:
            utr = m.group(0)
        elif re.search(r"fake|tamper|nakli", filename or "", re.I):
            utr = "632184920777"
        else:
            utr = "632184920111"
        known = {"632184920111": (1250, "GPay"), "632184920999": (2400, "PhonePe")}
        amount, app = known.get(utr, (1999, "Unknown"))
        fields = {"utr_number": utr, "amount": amount, "payer_app": app, "payment_status_on_screenshot": "SUCCESS"}
    return {"doc_type": doc_type, "extracted_fields": fields, "confidence": 0.96}


# ----------------------------------------------------------------------------- Paytm agent (8002)


async def dispatch(envelope: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        r = await _post(PAYTM_URL, "/a2a/dispatch", json=envelope)
        r.raise_for_status()
        body = r.json()
        if isinstance(body, dict) and "status" in body:
            return body, "live"
    except Exception as exc:  # noqa: BLE001
        log.warning("A2A dispatch failed (%s): %s", type(exc).__name__, exc)
    return mock_paytm(envelope), "mock"


async def paytm_reset() -> bool:
    try:
        r = await _post(PAYTM_URL, "/ledger/reset")
        return r.is_success
    except Exception:  # noqa: BLE001
        return False


_SETTLEMENT = {
    "settlement_date": "2026-11-18",
    "gross": 100000,
    "net_bank_credit": 95840,
    "variance": 4160,
    "breakdown": [
        {"head": "MDR_FEE", "amount": 1450, "note": "2% Credit Card, 1.1% Wallet-on-UPI >₹2k, 0% Bank UPI"},
        {"head": "GST_ON_MDR", "amount": 261, "rate": "18%", "itc_eligible": True},
        {"head": "CUSTOMER_REFUND", "amount": 1500, "order_id": "4412", "status": "PROCESSED"},
        {"head": "SOUNDBOX_RENTAL", "amount": 149},
        {"head": "CHARGEBACK_HOLD", "amount": 800, "txn_id": "9981", "order_id": "9981", "status": "HELD"},
    ],
}
_GST_ITC = {"amount": 261, "settlement_date": "2026-11-18", "basis": "18% GST on MDR ₹1,450", "itc_eligible": True}
_UTRS = {
    "632184920111": {"amount": 1250, "payer_app": "GPay", "status": "SUCCESS", "settled": True},
    "632184920999": {"amount": 2400, "payer_app": "PhonePe", "status": "PENDING", "note": "NPCI T+1 auto-reversal"},
}


def mock_paytm(envelope: dict[str, Any]) -> dict[str, Any]:
    """Deterministic Paytm-side answers built from CONTRACT.md seed data."""
    intent = envelope.get("intent")
    p = envelope.get("payload") or {}
    base = {"intent": intent, "action_required": None, "escalation_ticket": None}

    if intent == "SETTLEMENT_RECONCILE":
        return {**base, "status": "RECONCILED", "data": {**_SETTLEMENT, "gst_itc": _GST_ITC}}

    if intent == "UTR_VERIFY":
        utr = p.get("utr_number")
        if not utr:
            return {
                **base,
                "status": "NEEDS_INFO",
                "data": {},
                "action_required": {"type": "PROVIDE_UTR", "message": "12-digit UTR number required"},
            }
        hit = _UTRS.get(str(utr))
        if hit:
            return {**base, "status": hit["status"], "data": {"utr_number": utr, **hit}}
        return {
            **base,
            "status": "NOT_FOUND_SUSPECTED_FAKE",
            "data": {"utr_number": utr, "reason": "UTR not present in acquiring settlement ledger / NPCI"},
            "action_required": {"type": "DO_NOT_RELEASE_GOODS", "message": "Payment not received. Possible fake screenshot."},
        }

    if intent == "CHARGEBACK_RESOLVE":
        if p.get("pod_document") or p.get("pod_submitted"):
            return {
                **base,
                "status": "RELEASED",
                "data": {"txn_id": "9981", "order_id": "9981", "amount": 800, "release": "T+1"},
            }
        return {
            **base,
            "status": "HELD",
            "data": {"txn_id": "9981", "order_id": "9981", "amount": 800, "pod_due_in_hours": 48},
            "action_required": {"type": "UPLOAD_POD", "message": "Upload Proof of Delivery within 48h"},
        }

    if intent == "REFUND_MANAGE":
        amount = p.get("amount")
        order_id = p.get("order_id")
        if order_id and str(order_id) != "4412" and amount:
            if float(amount) > 5000:  # PLAN.md: > ₹5,000 needs a human
                return _escalation(base, envelope, "REFUND_MANAGE", f"Refund ₹{amount} on order #{order_id} exceeds ₹5,000 autonomous limit")
            return {**base, "status": "INITIATED", "data": {"order_id": str(order_id), "amount": amount, "eta": "T+1"}}
        return {
            **base,
            "status": "PROCESSED",
            "data": {"order_id": "4412", "amount": 1500, "deducted_in_settlement": "2026-11-18"},
        }

    if intent == "FEE_GST_LOAN":
        return {
            **base,
            "status": "OK",
            "data": {
                "mdr_fee": 1450,
                "mdr_rates": {"credit_card": "2%", "wallet_on_upi_above_2k": "1.1%", "bank_upi": "0%"},
                "gst_on_mdr": 261,
                "gst_itc": _GST_ITC,
                "soundbox_rental": 149,
                "loan": {"edi_per_day": 500, "next_deduction": "tomorrow's settlement", "balance": 42000},
            },
        }

    # ESCALATE_HUMAN (and anything unexpected)
    return _escalation(base, envelope, "ESCALATE_HUMAN", "Merchant requested L2 support")


def _escalation(base: dict[str, Any], envelope: dict[str, Any], intent: str, reason: str) -> dict[str, Any]:
    digits = re.sub(r"\D", "", str(envelope.get("request_id", ""))) or str(int(time.time()))
    return {
        **base,
        "intent": intent,
        "status": "ESCALATED",
        "data": {"reason": reason},
        "escalation_ticket": {
            "ticket_id": f"TKT-PAYTM-{digits[-4:].rjust(4, '0')}",  # PLAN.md format TKT-PAYTM-xxxx
            "queue": "L2",
            "priority": "HIGH",
            "sla": "Callback within 2 hours",
        },
    }
