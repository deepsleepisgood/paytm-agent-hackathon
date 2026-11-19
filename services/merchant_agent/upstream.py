"""HTTP clients for Sarvam (8001) and Paytm Agent (8002).

Every call has a hard timeout and a deterministic fallback, so the merchant agent works
standalone before 8001/8002 are up and degrades gracefully if they fail mid-demo.
Each helper returns (result, source) where source is "live", "mock" or "unavailable".

Person 1's service labels every answer with source="sarvam"|"mock". We pass that through,
and we ignore its *mock* LLM: that stand-in keyword-matches canned replies and can't read
Paytm's JSON, so our own routing and status-aware templates are more accurate.

The mock Paytm answers and mock document fields are built from the team dataset
(dataset_loader.DATA), falling back to the CONTRACT.md seed.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional

import httpx

import dataset_loader as dl

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
# Person 1 gives Sarvam Vision up to 25 s (SARVAM_DOC_LATENCY_BUDGET) before its own fallback,
# so a 6 s cut-off here would discard every real extraction. Wait a little longer than that.
DOC_TIMEOUT_S = float(os.getenv("DOC_EXTRACT_TIMEOUT_S", "30"))
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


def _label(body: dict[str, Any]) -> str:
    """Person 1 marks offline answers source="mock"; anything else that answered counts as live."""
    return "mock" if str(body.get("source", "")).lower() == "mock" else "live"


# ----------------------------------------------------------------------------- Sarvam (8001)


async def stt(audio: bytes, filename: str, content_type: str) -> tuple[Optional[str], str]:
    try:
        r = await _post(
            SARVAM_URL, "/stt",
            files={"audio": (filename or "audio.wav", audio, content_type or "audio/wav")},
        )
        r.raise_for_status()
        body = r.json() or {}
        if body.get("transcript"):
            return body["transcript"], _label(body)
    except Exception as exc:  # noqa: BLE001 - any upstream failure falls back
        log.warning("STT failed (%s): %s", type(exc).__name__, exc)
    return None, "unavailable"


async def llm(system_prompt: str, user_prompt: str, response_format: str = "text") -> Optional[Any]:
    """Parsed JSON (dict) for 'json', a string for 'text', or None if no real LLM answered."""
    try:
        r = await _post(
            SARVAM_URL, "/llm",
            json={"system_prompt": system_prompt, "user_prompt": user_prompt, "response_format": response_format},
        )
        r.raise_for_status()
        body = r.json() or {}
        if _label(body) == "mock":
            log.info("8001 /llm answered from its mock; using merchant-side routing/templates instead")
            return None
        if response_format == "json":
            parsed = body.get("parsed")
            return parsed if isinstance(parsed, dict) else _parse_json(body.get("reply"))
        reply = body.get("reply")
        return (str(reply).strip() or None) if reply is not None else None
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM failed (%s): %s", type(exc).__name__, exc)
        return None


def _parse_json(reply: Any) -> Optional[dict[str, Any]]:
    if isinstance(reply, dict):
        return reply
    if reply is None:
        return None
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
        body = r.json() or {}
        if body.get("audio_base64"):
            return body["audio_base64"], _label(body)
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
            timeout=httpx.Timeout(DOC_TIMEOUT_S, connect=min(2.0, DOC_TIMEOUT_S)),
        )
        r.raise_for_status()
        body = r.json() or {}
        if isinstance(body.get("extracted_fields"), dict):
            return body, _label(body)
    except Exception as exc:  # noqa: BLE001
        log.warning("doc-extract failed (%s): %s", type(exc).__name__, exc)
    return mock_doc_extract(doc_type, filename), "mock"


async def doc_extract_sample(doc_type: str) -> tuple[Optional[dict[str, Any]], str]:
    """Ask 8001 to extract its consented sample connector document (Shiprocket PoD for #9981)."""
    try:
        r = await _post(SARVAM_URL, "/doc-extract", data={"doc_type": doc_type, "use_sample_connector": "true"},
                        timeout=httpx.Timeout(DOC_TIMEOUT_S, connect=min(2.0, DOC_TIMEOUT_S)))
        r.raise_for_status()
        body = r.json() or {}
        if isinstance(body.get("extracted_fields"), dict):
            return body, _label(body)
    except Exception as exc:  # noqa: BLE001
        log.warning("doc-extract (sample connector) failed (%s): %s", type(exc).__name__, exc)
    return None, "unavailable"


def mock_doc_extract(doc_type: str, filename: str = "") -> dict[str, Any]:
    """Field names mirror Person 1's /doc-extract (utr, payer_app, order_id, ...)."""
    d = dl.DATA
    name = filename or ""
    if doc_type == "pod":
        ids = re.findall(r"\d{3,10}", name)
        cb = next((d.chargeback(i) for i in ids if d.chargeback(i)), None) or d.chargeback() or {}
        fields: dict[str, Any] = {
            "order_id": cb.get("order_id", "9981"),
            "txn_id": cb.get("txn_id", cb.get("order_id", "9981")),
            "amount": cb.get("amount"),
            "recipient_name": "Rohit Verma",
            "delivery_date": "2026-11-16",
            "courier_name": "Demo Express Logistics",
            "awb_or_tracking_id": "DEX7781203345",
            "otp_verified": True,
            "signature_present": True,
        }
    else:
        # Offline demo: a 12-digit UTR in the filename is used as-is; "fake"/"tamper" (e.g. PLAN.md's
        # fake_upi.png) yields a UTR absent from the ledger -> fraud path; "pending" picks a PENDING one.
        m = re.search(r"(?<!\d)\d{12}(?!\d)", name)
        if m:
            utr = m.group(0)
        elif re.search(r"fake|tamper|nakli", name, re.I):
            utr = next(u for u in (str(632184920777 + i) for i in range(1000)) if u not in d.utrs)
        else:
            want = "PENDING" if re.search(r"pending|phonepe", name, re.I) else "SUCCESS"
            utr = next((u for u, t in d.utrs.items() if t.get("status") == want), next(iter(d.utrs), "632184920111"))
        known = d.utrs.get(utr) or {}
        fields = {
            "utr": utr,
            "amount": known.get("amount") or 1999,
            "payer_app": known.get("payer_app") or "GPay",
            "status": "SUCCESS",  # what the screenshot *claims*
        }
    return {"doc_type": doc_type, "extracted_fields": fields, "confidence": 0.96}



# ----------------------------------------------------------------------------- Paytm agent (8002)

# Statuses a live 8002 might use for an intent it doesn't implement yet: answer from the mock instead.
_UNSUPPORTED = {"UNSUPPORTED_INTENT", "UNKNOWN_INTENT", "INVALID_INTENT", "NOT_IMPLEMENTED"}


class UpstreamRejected(Exception):
    """8002 refused the request on purpose (403 consent / 409 not eligible): passed through to the frontend."""

    def __init__(self, status_code: int, detail: Any):
        super().__init__(f"{status_code}: {detail}")
        self.status_code, self.detail = status_code, detail


async def dispatch(envelope: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        r = await _post(PAYTM_URL, "/a2a/dispatch", json=envelope)
        r.raise_for_status()
        body = r.json()
        if isinstance(body, dict) and "status" in body and str(body["status"]).upper() not in _UNSUPPORTED:
            return body, "live"
    except Exception as exc:  # noqa: BLE001
        log.warning("A2A dispatch failed (%s): %s", type(exc).__name__, exc)
    return mock_paytm(envelope), "mock"


async def proactive_alert(mid: str, trigger_type: str) -> tuple[dict[str, Any], str]:
    """CONTRACT.md V2: 8003 fetches the alert from 8002 (no consent token: it only informs the merchant)."""
    try:
        r = await _post(PAYTM_URL, "/a2a/proactive-alert", json={"mid": mid, "trigger_type": trigger_type})
        r.raise_for_status()
        body = r.json()
        if isinstance(body, dict) and body.get("status"):
            return body, "live"
    except Exception as exc:  # noqa: BLE001
        log.warning("proactive-alert failed (%s): %s", type(exc).__name__, exc)
    return mock_alert(trigger_type), "mock"


async def execute_edi_pause(body: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """CONTRACT.md V2 /a2a/execute-edi-pause. 403/409 from a live 8002 are raised as UpstreamRejected."""
    try:
        r = await _post(PAYTM_URL, "/a2a/execute-edi-pause", json=body)
        if r.status_code in (403, 409):
            try:
                payload = r.json()
                detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
            except Exception:  # noqa: BLE001
                detail = r.text
            raise UpstreamRejected(r.status_code, detail)
        r.raise_for_status()
        resp = r.json()
        if isinstance(resp, dict) and resp.get("status"):
            return resp, "live"
    except UpstreamRejected:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("execute-edi-pause failed (%s): %s", type(exc).__name__, exc)
    return mock_execute_edi_pause(body), "mock"


async def paytm_reset() -> bool:
    try:
        r = await _post(PAYTM_URL, "/ledger/reset")
        return r.is_success
    except Exception:  # noqa: BLE001
        return False


# ----------------------------------------------------------------------------- mock Paytm mesh
# Deterministic stand-in for Person 2's 4-agent mesh, built from the team dataset. Every answer carries
# the PLAN.md `agent_trace` (Intelligence -> Risk & Policy -> Resolution -> Ledger Ops) and, when the
# case is closed, a `verified_outcome`, so the UI's centre column works before 8002 exists.

AGENTS = ("IntelligenceAgent", "RiskPolicyAgent", "ResolutionAgent", "LedgerOpsAgent")
BUILTIN_CB = {"order_id": "9981", "txn_id": "9981", "amount": 800, "pod_due_in_hours": 48}

# Mock ledger state, seeded from dataset initial_state.json / history and restored by /reset.
_ledger: dict[str, str] = {}  # chargeback order_id -> HELD | RELEASED
_loan_state: dict[str, Any] = {}


def reset_mock_ledger() -> None:
    _ledger.clear()
    _ledger.update(dl.DATA.initial_chargeback_status)
    _loan_state.clear()
    _loan_state.update({"loan_edi_status": "ACTIVE", "offers": {}, "artifacts": 0})


def mock_loan_state() -> dict[str, Any]:
    return {"loan_edi_status": _loan_state.get("loan_edi_status", "ACTIVE")}


def remember_offer(offer: dict[str, Any]) -> None:
    """Let the offline mock execute an offer that a live 8002 made (in case 8002 drops mid-demo)."""
    if offer.get("offer_id"):
        _loan_state.setdefault("offers", {})[offer["offer_id"]] = offer


def _cb_status(order_id: str) -> str:
    return _ledger.get(order_id) or (dl.DATA.chargebacks.get(order_id) or {}).get("status") or "HELD"


def _inr(n: Any) -> str:
    v = dl.num(n)
    return f"₹{dl._inr_commas(v)}" if v is not None else "₹?"


def _seq(envelope: dict[str, Any]) -> str:
    digits = re.sub(r"\D", "", str(envelope.get("request_id", ""))) or str(int(time.time()))
    return digits[-4:].rjust(4, "0")


def _answer(base: dict[str, Any], status: str, data: dict[str, Any], steps: list[str], *,
            resolved: Optional[bool] = None, action_required: Optional[dict] = None, **extra: Any) -> dict[str, Any]:
    trace = [{"step": i + 1, "agent": a, "output": s, "status": "DONE"} for i, (a, s) in enumerate(zip(AGENTS, steps))]
    out = {**base, "status": status, "data": data, "agent_trace": trace, "action_required": action_required, **extra}
    if resolved is not None:
        out["verified_outcome"] = {"resolved": resolved, "status": status, "verified_by": "LedgerOpsAgent"}
    return out


def _selected_action(envelope: dict[str, Any]) -> str:
    sel = envelope.get("selected_intervention") or {}
    return str(sel.get("action") or "") if isinstance(sel, dict) else str(sel)


def _days_after_settlement(days: int) -> str:
    from datetime import date, timedelta
    try:
        base = date.fromisoformat(str(dl.DATA.settlement["settlement_date"]))
    except ValueError:
        base = date.today()
    return (base + timedelta(days=days)).isoformat()


def mock_paytm(envelope: dict[str, Any]) -> dict[str, Any]:
    """Deterministic Paytm-side answers built from the team dataset (CONTRACT.md seed as fallback)."""
    d, h = dl.DATA, dl.DATA.history
    intent = envelope.get("intent")
    p = envelope.get("payload") or {}
    base = {"intent": intent, "action_required": None, "escalation_ticket": None}
    consent = "Consent token verified"

    if intent == "SETTLEMENT_RECONCILE":
        s = d.settlement
        breakdown, held = [], None
        for item in s["deductions"]:
            rec = dict(item)
            if "CHARGEBACK" in rec["head"] or "HOLD" in rec["head"]:
                oid = rec.get("order_id") or (d.chargeback() or {}).get("order_id")
                if oid:
                    rec["status"] = _cb_status(oid)
                    held = rec if rec["status"] != "RELEASED" else None
            breakdown.append(rec)
        data = {k: s[k] for k in ("settlement_date", "gross", "net_bank_credit", "variance")}
        data["breakdown"] = breakdown
        if (itc := d.gst_itc()) is not None:
            data["gst_itc"] = itc
        return _answer(base, "RECONCILED", data, [
            f"Itemised {_inr(s['variance'])} variance into {len(breakdown)} deductions for {s['settlement_date']}",
            f"{consent}; MDR/GST charged as per fee rules",
            f"Open hold #{held.get('order_id')} ({_inr(held['amount'])}) can be released with PoD" if held
            else "No open holds",
            f"Reconciled: {_inr(s['gross'])} − {_inr(s['variance'])} = {_inr(s['net_bank_credit'])}",
        ], resolved=True)

    if intent == "UTR_VERIFY":
        utr = p.get("utr_number")
        if not utr:
            return _answer(base, "NEEDS_INFO", {}, [
                "No UTR in request", consent, "Asked merchant for the 12-digit UTR", "No ledger change"],
                action_required={"type": "PROVIDE_UTR", "message": "12-digit UTR number required"})
        hit = d.utrs.get(str(utr)) or d.history_utr(str(utr))
        if hit:
            st = hit["status"]
            ok = st in ("SUCCESS", "SETTLED")
            return _answer(base, st, {**hit, "utr_number": str(utr)}, [
                f"NPCI lookup UTR {utr}: {st} ({_inr(hit.get('amount'))}, {hit.get('payer_app') or 'UPI'})",
                f"{consent}; payment risk {'low' if ok else 'open until NPCI confirms'}",
                "Merchant cleared to hand over goods" if ok else "Advised to hold goods until confirmed",
                "UTR marked verified in acquiring ledger" if ok else "Watching T+1 auto-reversal window",
            ], resolved=True if ok else None)
        return _answer(base, "NOT_FOUND_SUSPECTED_FAKE",
                       {"utr_number": utr, "reason": "UTR not present in acquiring settlement ledger / NPCI"}, [
            f"NPCI + acquiring ledger lookup: UTR {utr} not found",
            "Risk: screenshot likely tampered — HIGH",
            "Goods release blocked, merchant warned",
            "Fraud attempt logged to risk ledger",
        ], resolved=True, action_required={"type": "DO_NOT_RELEASE_GOODS",
                                           "message": "Payment not received. Possible fake screenshot."})

    if intent == "CHARGEBACK_RESOLVE":
        oid = dl.digits(p.get("order_id"))
        cb = d.chargeback(oid) if oid else d.chargeback()
        if cb is None:
            return _answer(base, "NO_CHARGEBACK_FOUND", {"order_id": oid}, [
                f"No dispute on order #{oid}", consent, "Nothing to resolve", "No ledger change"], resolved=True)
        cid = cb["order_id"]
        data = {"txn_id": cb.get("txn_id", cid), "order_id": cid, "amount": cb.get("amount")}
        if p.get("pod_document") or p.get("pod_submitted"):
            _ledger[cid] = "RELEASED"
        if _cb_status(cid) == "RELEASED":
            src = p.get("pod_source") or "merchant upload"
            return _answer(base, "RELEASED", {**data, "release": "T+1"}, [
                f"Dispute #{cid} ({_inr(cb.get('amount'))}): PoD received via {src}",
                f"{consent}; PoD signature + delivery date valid",
                "Representment filed — chargeback won",
                f"#{cid} HELD → RELEASED, credit in T+1 settlement",
            ], resolved=True)
        due = cb.get("pod_due_in_hours", 48)
        return _answer(base, "HELD", {**data, "pod_due_in_hours": due}, [
            f"Dispute #{cid} ({_inr(cb.get('amount'))}): no PoD yet", f"{consent}; PoD due within {due}h",
            "Representment waiting for Proof of Delivery", f"#{cid} stays HELD"],
            action_required={"type": "UPLOAD_POD", "message": f"Upload Proof of Delivery within {due}h"})

    if intent == "REFUND_MANAGE":
        oid = dl.digits(p.get("order_id"))
        amount = p.get("amount")
        known = d.refund(oid) if oid else d.refund()
        if known:
            st = known.get("status") or "PROCESSED"
            return _answer(base, st, {"order_id": known["order_id"], "amount": known.get("amount"),
                                      "deducted_in_settlement": d.settlement["settlement_date"]}, [
                f"Refund #{known['order_id']} found: {st}", consent,
                "Explained deduction to merchant", "No ledger change"], resolved=True)
        if oid and amount:
            if float(amount) > float(d.refund_limit):  # PLAN.md: > ₹5,000 needs a human
                return _escalation(base, envelope, "REFUND_MANAGE",
                                   f"Refund ₹{amount} on order #{oid} exceeds ₹{d.refund_limit} autonomous limit")
            return _answer(base, "INITIATED", {"order_id": oid, "amount": amount, "eta": "T+1"}, [
                f"Order #{oid} eligible for refund",
                f"{_inr(amount)} ≤ {_inr(d.refund_limit)} autonomous limit — approved",
                "Refund initiated", f"Refund {_inr(amount)} posted, customer credit T+1"], resolved=True)
        return _answer(base, "NEEDS_INFO", {"order_id": oid}, [
            "Order / amount missing", consent, "Asked merchant for order number and amount", "No ledger change"],
            action_required={"type": "PROVIDE_ORDER_AND_AMOUNT", "message": "Order number and refund amount required"})

    if intent == "FEE_GST_LOAN":
        return _answer(base, "OK", {
            "mdr_fee": d.deduction_amount("MDR"), "mdr_rates": d.fees["mdr_rates"],
            "gst_rate_pct": d.fees["gst_rate_pct"], "gst_on_mdr": d.deduction_amount("GST"),
            "gst_itc": d.gst_itc(), "soundbox_rental": d.deduction_amount("SOUNDBOX", "RENTAL"),
            "loan": {**d.loan, **mock_loan_state()},
        }, ["Fee, GST and loan schedule pulled", consent, "Explained charges", "No ledger change"], resolved=True)

    if intent == "MANDATE_TROUBLESHOOT":
        m = h.get("mandate") or {}
        edi = m.get("edi_amount") or d.loan.get("edi_per_day")
        info = {"mandate_type": m.get("type", "eNACH"), "bounce_reason": m.get("bounce_reason", "INSUFFICIENT_FUNDS"),
                "bounce_date": m.get("bounce_date"), "missed_edi": edi, "lender": h.get("active_lender")}
        action = _selected_action(envelope)
        intel = (f"eNACH bounce {info['bounce_date']}: {info['bounce_reason']}; "
                 f"{h.get('past_edi_success_rate')}% EDIs on time in 6 months")
        if action == "SEND_REMINDER":
            return _answer(base, "REMINDER_SENT", info, [intel, consent, "Retry reminder sent for next debit",
                                                          "EDI marked overdue"], resolved=False)
        if action == "ESCALATE_SPECIALIST":
            return _escalation(base, envelope, intent, "Mandate failure needs collections specialist")
        link = f"upi://pay?pa=clixcapital@paytm&am={edi}&tn=EDI-{_seq(envelope)}"
        return _answer(base, "UPI_LINK_SENT", {**info, "upi_link": link, "grace_hours": 48, "penalty_waived": True,
                                               "loan_edi_status": mock_loan_state()["loan_edi_status"]}, [
            intel,
            f"{consent}; friction, not default — KFS 48h grace applies, bounce penalty waived",
            f"1-tap UPI link sent for missed {_inr(edi)} EDI",
            "Bounce penalty reversed; repayment schedule unchanged",
        ], resolved=True, action_required={"type": "PAY_VIA_UPI_LINK", "message": "Pay missed EDI via 1-tap UPI link",
                                           "upi_link": link})

    if intent == "DUPLICATE_RECONCILE":
        oid = dl.digits(p.get("order_id"))
        dup = d.duplicate_payment(oid) if oid else d.duplicate_payment()
        if dup is None:
            return _answer(base, "NO_DUPLICATE_FOUND", {"order_id": oid}, [
                f"No second UTR found for order #{oid}", consent, "Nothing to refund", "No ledger change"], resolved=True)
        amt, utrs = dl.num(dup.get("amount")), [str(u) for u in dup.get("utrs") or []]
        data = {"order_id": dl.digits(dup.get("order_id")), "customer": dup.get("customer"), "amount": amt,
                "utrs": utrs, "kept_utr": utrs[0] if utrs else None, "refunded_utr": utrs[-1] if utrs else None}
        if amt is not None and amt > float(d.refund_limit):
            return _escalation(base, envelope, intent, f"Duplicate refund {_inr(amt)} exceeds autonomous limit")
        return _answer(base, "REFUND_INITIATED", {**data, "eta": "T+1"}, [
            f"Matched {len(utrs)} UTRs for order #{data['order_id']} ({_inr(amt)} each)",
            f"{consent}; {_inr(amt)} ≤ {_inr(d.refund_limit)} autonomous limit — approved",
            f"Duplicate {_inr(amt)} refunded to {dup.get('customer') or 'customer'} (UTR {data['refunded_utr']})",
            "Ledger: one payment kept, duplicate reversed",
        ], resolved=True)

    if intent == "GROWTH_ADVISORY":
        offer = dict(h.get("growth_offer") or {})
        offer.setdefault("lender", h.get("active_lender"))
        trend = six_month_trend_pct()
        data = {"weekend_multiplier": h.get("weekend_multiplier"), "six_month_trend_pct": trend,
                "daily_avg_sales": h.get("daily_avg_sales"), "offer": offer}
        return _answer(base, "OFFER_PREAPPROVED", data, [
            f"Weekend sales {h.get('weekend_multiplier')}x weekdays"
            + (f"; 6-month trend {trend:+d}%" if trend is not None else ""),
            f"{consent}; {_inr(offer.get('amount'))} working-capital limit pre-approved by {offer.get('lender')}",
            "Rate and tenure only in the NBFC's KFS, shown before any drawdown",
            "Offer stored — no disbursal without merchant e-sign",
        ], resolved=True)

    if intent == "CASHFLOW_EDI_SWITCH":
        body = {"mid": envelope.get("mid"), "consent_token": envelope.get("consent_token"),
                "pause_days": p.get("pause_days"), "offer_id": p.get("offer_id")}
        try:
            return mock_execute_edi_pause(body)
        except UpstreamRejected as rej:
            return _answer(base, "EDI_PAUSE_NOT_ELIGIBLE", {"reason": rej.detail, **mock_loan_state()}, [
                "Cashflow gap checked", "KFS: EDI holiday not available now", "No pause executed", "No ledger change"],
                resolved=False)

    if intent == "SOUNDBOX_RETURN":
        plan = h.get("soundbox_plan") or {}
        rent = plan.get("rental_per_month") or d.deduction_amount("SOUNDBOX", "RENTAL")
        ticket = f"PICKUP-{_seq(envelope)}"
        return _answer(base, "RETURN_INITIATED", {
            "device": d.merchant.get("soundbox") or "Paytm Soundbox", "pickup_ticket": ticket, "pickup_within_hours": 48,
            "rental_per_month": rent, "rental_stops": "from next billing cycle", "final_charge": "pro-rata",
        }, [f"Soundbox on rental {plan.get('months_active', '?')} months at {_inr(rent)}/month",
            f"{consent}; no dues blocking return", f"Doorstep pickup {ticket} within 48h",
            "Rental billing stops from next cycle; final bill pro-rata"], resolved=True)

    if intent == "LOAN_CLOSURE_NOC":
        bal = d.loan.get("balance")
        lender = d.loan.get("lender") or h.get("active_lender")
        return _answer(base, "FORECLOSURE_QUOTE_READY", {
            "lender": lender, "outstanding": bal, "foreclosure_charge": 0, "payable": bal, "noc_eta_days": 7,
            "payment_link": f"upi://pay?pa=clixcapital@paytm&am={bal}&tn=FORECLOSE",
        }, [f"Outstanding {_inr(bal)} with {lender}", f"{consent}; KFS: foreclosure charge ₹0",
            "Foreclosure quote + NOC request raised", "NOC issued within 7 days of payment; bureau updated"],
            resolved=True, action_required={"type": "PAY_FORECLOSURE", "message": f"Pay {_inr(bal)} to close the loan"})

    if intent == "BANK_KYC_UPDATE":
        bank = h.get("bank_account") or {}
        return _answer(base, "KYC_UPDATE_LINK_SENT", {
            "current_account": bank.get("account_masked"), "bank": bank.get("bank"), "verification": "PENNY_DROP",
            "eta_hours": "24-48", "settlements_to_old_account_until_verified": True,
        }, [f"Current settlement account {bank.get('bank')} {bank.get('account_masked')} ({bank.get('kyc_status')})",
            f"{consent}; change needs re-KYC + penny-drop (RBI)", "Secure update link sent to registered mobile",
            "Settlements continue to the old account until verified"], resolved=True,
            action_required={"type": "COMPLETE_KYC_LINK", "message": "Open the secure link and add the new account"})

    if intent == "SETTLEMENT_HOLD_BANK":
        bank = h.get("bank_account") or {}
        holds = [{"order_id": oid, "amount": (d.chargebacks.get(oid) or {}).get("amount"), "type": "CHARGEBACK_HOLD"}
                 for oid in d.chargebacks if _cb_status(oid) != "RELEASED"]
        data = {"bank": bank.get("bank"), "account_masked": bank.get("account_masked"),
                "bank_status": str(bank.get("status", "ACTIVE")).upper(), "kyc_status": bank.get("kyc_status"),
                "last_credit": bank.get("last_credit"), "open_holds": holds}
        if data["bank_status"] == "ACTIVE":
            last = (bank.get("last_credit") or {}).get("amount")
            return _answer(base, "NO_BANK_HOLD", data, [
                f"Bank {bank.get('account_masked')} status ACTIVE; last credit {_inr(last)}",
                f"{consent}; no bank/KYC hold on this MID",
                f"Only open holds: {', '.join('#' + x['order_id'] for x in holds)}" if holds else "No open holds",
                "No ledger change"], resolved=True)
        return _answer(base, "SETTLEMENT_HELD_BANK_INACTIVE", data, [
            f"Bank account {bank.get('account_masked')} is {data['bank_status']}",
            f"{consent}; settlement paused by policy", "Asked merchant to update bank account",
            "Payouts queued until account is active"], resolved=False,
            action_required={"type": "UPDATE_BANK_ACCOUNT", "message": "Update or reactivate the settlement bank account"})

    # ESCALATE_HUMAN (and anything unexpected)
    hardware = p.get("device") or p.get("issue_type") == "HARDWARE_SOUNDBOX"
    reason = "Soundbox hardware fault" if hardware else "Merchant requested L2 support"
    return _escalation(base, envelope, "ESCALATE_HUMAN", reason)


def six_month_trend_pct() -> Optional[int]:
    """Growth from the first to the last *full* month of history (a month-to-date row is skipped)."""
    months = [m for m in dl.DATA.history.get("monthly_sales") or [] if isinstance(m, dict)]
    full = [m for m in months if not re.search(r"\d\s*[–-]\s*\d|mtd|to date|partial", str(m.get("note", "")), re.I)] or months
    if len(full) < 2 or not full[0].get("sales"):
        return None
    return round((full[-1]["sales"] / full[0]["sales"] - 1) * 100)


def _escalation(base: dict[str, Any], envelope: dict[str, Any], intent: str, reason: str) -> dict[str, Any]:
    p = envelope.get("payload") or {}
    data: dict[str, Any] = {"reason": reason}
    for k in ("issue_type", "device", "diagnostics"):
        if p.get(k):
            data[k] = p[k]
    ticket = f"TKT-PAYTM-{_seq(envelope)}"  # PLAN.md format TKT-PAYTM-xxxx
    diag = p.get("diagnostics") or {}
    hardware = p.get("issue_type") == "HARDWARE_SOUNDBOX"
    return _answer({**base, "intent": intent}, "ESCALATED", data, [
        f"Diagnostics: battery {diag.get('battery_pct')}%, {diag.get('network')}" if diag else f"Case: {reason}",
        "Consent token verified; L2 priority approved",
        f"Priority L2 ticket {ticket}" + (" — replacement device" if hardware else ""),
        "Ticket logged with diagnostics — no repeat questions",
    ], resolved=True, escalation_ticket={"ticket_id": ticket, "queue": "L2", "priority": "HIGH",
                                         "sla": "Callback within 2 hours"})


def mock_alert(trigger_type: str) -> dict[str, Any]:
    """CONTRACT.md V2 /a2a/proactive-alert answers, from the dataset."""
    d, h = dl.DATA, dl.DATA.history
    base = {"status": "ALERT_RAISED", "trigger_type": trigger_type, "escalation_ticket": None}
    if trigger_type == "CHARGEBACK_INCOMING":
        cb = d.chargeback() or BUILTIN_CB
        oid = cb["order_id"]
        due = cb.get("pod_due_in_hours", 48)
        return {**base, "alert_id": f"ALERT-{oid}", "intent": "CHARGEBACK_RESOLVE",
                "data": {"txn_id": cb.get("txn_id", oid), "order_id": oid, "amount": cb.get("amount"),
                         "deadline_hours": due},
                "action_required": {"type": "SUBMIT_POD", "message": f"Submit Proof of Delivery within {due}h"}}
    if trigger_type == "MANDATE_FAILED_ALERT":
        m = h.get("mandate") or {}
        return {**base, "alert_id": f"ALERT-MANDATE-{str(m.get('bounce_date', '')).replace('-', '')}",
                "intent": "MANDATE_TROUBLESHOOT",
                "data": {"mandate_type": m.get("type", "eNACH"),
                         "edi_amount": m.get("edi_amount") or d.loan.get("edi_per_day"),
                         "bounce_reason": m.get("bounce_reason"), "bounce_date": m.get("bounce_date"),
                         "lender": h.get("active_lender")},
                "action_required": {"type": "RESOLVE_MISSED_EDI", "message": "Missed EDI: pay or request grace"}}
    # HIGH_REFUND_CASHFLOW
    kfs = h.get("kfs") or {}
    edi = d.loan.get("edi_per_day") or 500
    days = kfs.get("max_pause_days", 2)
    eligible = bool(kfs.get("edi_holiday_eligible")) and _loan_state.get("loan_edi_status", "ACTIVE") == "ACTIVE"
    offer = {"offer_id": "EDIOFFER-0001", "eligible": eligible, "nbfc": h.get("active_lender"), "pause_days": days,
             "edi_saved_inr": edi * days, "kfs_clause": kfs.get("clause", "4.2")}
    _loan_state.setdefault("offers", {})[offer["offer_id"]] = offer
    return {**base, "alert_id": "ALERT-4490", "intent": "CASHFLOW_EDI_SWITCH",
            "data": {"refund_request": {"order_id": "4490", "amount": 3500}, "projected_net_payout": 1200,
                     "edi_pause_offer": offer},
            "action_required": {"type": "CONFIRM_EDI_PAUSE", "message": "Merchant consent needed to pause EDI"}
            if eligible else None}


def mock_execute_edi_pause(body: dict[str, Any]) -> dict[str, Any]:
    """CONTRACT.md V2 /a2a/execute-edi-pause on the mock loan ledger. Raises UpstreamRejected like 8002 would."""
    h, d = dl.DATA.history, dl.DATA
    kfs = h.get("kfs") or {}
    max_days = int(kfs.get("max_pause_days", 2))
    days = int(body.get("pause_days") or max_days)
    if not str(body.get("consent_token") or "").startswith("DPDP_VERIFIED_TS_"):
        raise UpstreamRejected(403, {"error": "DPDP_CONSENT_REQUIRED"})
    if body.get("offer_id") and body["offer_id"] not in (_loan_state.get("offers") or {}):
        raise UpstreamRejected(409, {"error": "EDI_PAUSE_NOT_ELIGIBLE", "reason": "no matching offer"})
    if not kfs.get("edi_holiday_eligible") or days > max_days or _loan_state.get("loan_edi_status", "ACTIVE") != "ACTIVE":
        raise UpstreamRejected(409, {"error": "EDI_PAUSE_NOT_ELIGIBLE",
                                     "reason": f"needs an eligible loan, ACTIVE EDI and pause_days ≤ {max_days}"})
    edi = d.loan.get("edi_per_day") or 500
    status = f"PAUSED_{days}_DAYS"
    _loan_state["loan_edi_status"] = status
    _loan_state["artifacts"] = _loan_state.get("artifacts", 0) + 1
    lender = h.get("active_lender")
    data = {"loan_edi_status": status, "nbfc": lender, "pause_days": days, "edi_saved_inr": edi * days,
            "edi_tomorrow": 0, "resume_date": _days_after_settlement(1 + days),
            "kfs_consent_artifact": {"artifact_id": f"KFS-ART-{_loan_state['artifacts']:04d}",
                                     "clause": kfs.get("clause", "4.2"), "consent_token": body.get("consent_token"),
                                     "ts": time.time()}}
    return _answer({"intent": "CASHFLOW_EDI_SWITCH", "escalation_ticket": None}, "EDI_PAUSED", data, [
        "Cashflow gap confirmed: payout below tomorrow's stock payable",
        f"KFS clause {kfs.get('clause', '4.2')}: {days}-day EDI holiday eligible; consent artifact recorded",
        f"{lender} EDI paused {days} days ({_inr(edi * days)} liquidity freed)",
        f"loan_edi_status ACTIVE → {status}; resumes {data['resume_date']}",
    ], resolved=True)



# ----------------------------------------------------------------------------- live 8002 -> merchant view
# Person 2's /a2a/dispatch answers every intent with status RESOLVED | ACTION_REQUIRED | ESCALATED and puts
# the specifics in `data` (lookup_status, hold_status, refund_status, *_inr amounts, lines, remedies...).
# The merchant side (replies, ITC log, fraud alert, khata, learning) keys on specific outcomes, so this
# translates one into the other. The raw 8002 body is still returned to the frontend as paytm_response.

_UTR_STATUS = {"SUCCESS_SETTLED": "SUCCESS", "SUCCESS": "SUCCESS", "PENDING": "PENDING", "FAILED": "FAILED",
               "REVERSED": "FAILED"}


def _amt_of(d: dict[str, Any], *keys: str) -> Any:
    return next((d[k] for k in keys if d.get(k) is not None), None)


def interpret(intent: str, resp: dict[str, Any], source: str) -> dict[str, Any]:
    if source != "live" or not isinstance(resp, dict):
        return resp
    mesh = str(resp.get("status") or "").upper()
    if mesh not in ("RESOLVED", "ACTION_REQUIRED", "ESCALATED"):
        return resp  # already specific (or an older 8002 build)
    d = resp.get("data") or {}
    status, data = mesh, dict(d)
    ar = resp.get("action_required")
    # Person 2 renamed two plan intents and accepts both names; read either.
    canon = {"DUPLICATE_RECONCILE": "DUPLICATE_PAYMENT_RECONCILE", "GROWTH_ADVISORY": "WORKING_CAPITAL_ADVISORY"}.get(
        intent, resp.get("intent_canonical") or intent)

    if canon == "SETTLEMENT_RECONCILE" and "lines" in d:
        breakdown = []
        for ln in d.get("lines") or []:
            rec = {"head": ln.get("code") or ln.get("label"), "label": ln.get("label"),
                   "amount": _amt_of(ln, "amount_inr", "amount")}
            if (m := re.search(r"order\s*#?\s*(\d+)", str(ln.get("label") or ""), re.I)):
                rec["order_id"] = m.group(1)
            if "CHARGEBACK" in str(rec["head"]).upper() or "HOLD" in str(rec["head"]).upper():
                rec["status"] = str(ln.get("status") or "HELD").upper()
            breakdown.append(rec)
        data = {"settlement_date": d.get("settlement_date"), "gross": d.get("gross_inr"),
                "net_bank_credit": d.get("net_credit_inr"), "variance": d.get("variance_inr"), "breakdown": breakdown,
                "reconciles": d.get("reconciles")}
        status = "RECONCILED" if mesh == "RESOLVED" else mesh
    elif canon == "UTR_VERIFY" and "lookup_status" in d:
        look = str(d.get("lookup_status") or "").upper()
        fake = look == "NOT_FOUND" or d.get("internal_flag") == "POSSIBLE_FAKE"
        status = "NOT_FOUND_SUSPECTED_FAKE" if fake else _UTR_STATUS.get(look, look or mesh)
        data = {"utr_number": d.get("utr"), "amount": d.get("amount_inr"), "payer_app": d.get("payer_app"),
                "advice": d.get("advice"), "amount_matches_claim": d.get("amount_matches_claim")}
        if fake:
            ar = ar or {"type": "DO_NOT_RELEASE_GOODS", "message": "Payment not found in NPCI log. Possible fake screenshot."}
    elif canon == "CHARGEBACK_RESOLVE" and "hold_status" in d:
        status = "RELEASED" if str(d.get("hold_status")).upper() == "RELEASED" else (
            "HELD" if mesh != "ESCALATED" else mesh)
        data = {"order_id": d.get("order_id"), "txn_id": d.get("txn_id"), "amount": d.get("amount_held_inr"),
                "pod_due_in_hours": round(float(d["hours_left"])) if d.get("hours_left") is not None else None,
                "evidence_status": d.get("evidence_status"), "release": "T+1" if status == "RELEASED" else None}
    elif canon == "MANDATE_TROUBLESHOOT" and ("remedies" in d or "bounce_date" in d):
        status = "REMEDIES_OFFERED" if mesh == "ACTION_REQUIRED" else ("MANDATE_RESOLVED" if mesh == "RESOLVED" else mesh)
        data = {"missed_edi": d.get("amount_inr"), "bounce_date": d.get("bounce_date"), "bounce_reason": d.get("bounce_reason"),
                "lender": d.get("nbfc"), "is_default": d.get("is_default"), "remedies": d.get("remedies") or [],
                "penalty_waived": not d.get("bounce_charge_inr") or None, "bounce_charge_inr": d.get("bounce_charge_inr")}
    elif canon == "DUPLICATE_PAYMENT_RECONCILE" and "duplicates_found" in d:
        refund, keep = d.get("refund") or {}, d.get("keep") or {}
        if not d.get("duplicates_found"):
            status = "NO_DUPLICATE_FOUND"
        elif mesh == "RESOLVED":
            status = "REFUND_INITIATED"
        data = {"order_id": d.get("order_id"), "amount": d.get("order_amount_inr") or refund.get("amount_inr"),
                "utrs": [x.get("utr") for x in d.get("payments") or []], "kept_utr": keep.get("utr"),
                "refunded_utr": refund.get("utr"), "refund_status": d.get("refund_status"), "customer": None}
    elif canon == "WORKING_CAPITAL_ADVISORY" and ("credit_offer" in d or "sales" in d):
        offer, sales = d.get("credit_offer") or {}, d.get("sales") or {}
        status = "OFFER_PREAPPROVED" if offer and mesh == "RESOLVED" else mesh
        data = {"daily_avg_sales": sales.get("avg_daily_sales_inr"), "weekend_multiplier": sales.get("weekend_multiplier"),
                "weekend_daily_sales": d.get("weekend_daily_sales_inr"),
                "offer": {"amount": offer.get("pre_approved_inr"), "lender": offer.get("nbfc"),
                          "kfs_required": offer.get("kfs_required"), "terms": offer.get("terms")}}
    elif mesh == "ESCALATED":
        data = {**d, "reason": (resp.get("escalation_ticket") or {}).get("reason_text")}
    return {**resp, "status": status, "data": data, "action_required": ar, "mesh_status": mesh}


reset_mock_ledger()
