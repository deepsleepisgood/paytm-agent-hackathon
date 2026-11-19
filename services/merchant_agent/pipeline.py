"""A2A orchestration: DPDP gate -> intent -> Paytm dispatch -> local side-effects -> voice reply."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from fastapi import HTTPException

import upstream
from schemas import Slots
from state import MERCHANT_ORDER_SHEET, STATE

FRAUD_STATUS = "NOT_FOUND_SUSPECTED_FAKE"
ACTOR_MERCHANT = "MERCHANT_AGENT"
ACTOR_PAYTM = "PAYTM_AGENT"
ACTOR_DPDP = "DPDP_GATE"


def new_request_id() -> str:
    return f"REQ_{uuid.uuid4().hex[:10].upper()}"


# ----------------------------------------------------------------------------- DPDP consent


def require_consent(consent_granted: bool, mid: str, request_id: str, channel: str) -> str:
    if not consent_granted:
        STATE.log(
            "DPDP_CONSENT_DENIED",
            ACTOR_DPDP,
            "Consent nahi mila — Paytm ko koi data share nahi kiya gaya",
            {"mid": mid, "channel": channel, "consent_status": "CONSENT_DENIED"},
            request_id,
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "DPDP_CONSENT_REQUIRED",
                "message": "consent_granted must be true before any data is shared with Paytm.",
                "message_hi": "आगे बढ़ने के लिए कृपया डेटा शेयर करने की सहमति दें।",
                "request_id": request_id,
            },
        )
    token = f"DPDP_VERIFIED_TS_{int(time.time())}"
    STATE.log(
        "DPDP_CONSENT_VERIFIED",
        ACTOR_DPDP,
        "Merchant consent verified (DPDP Act 2023) — token minted",
        {
            "mid": mid,
            "channel": channel,
            "consent_status": "CONSENT_GRANTED",
            "consent_token": token,
            "purpose": "Settlement & payment dispute resolution with Paytm",
            "data_minimised": True,
        },
        request_id,
    )
    return token


# ----------------------------------------------------------------------------- side-effect detectors


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").replace("₹", "").strip())
        except ValueError:
            return None
    return None


def find_gst_itc(resp: dict[str, Any]) -> Optional[float]:
    """Find an ITC-eligible GST amount anywhere in Paytm's response (tolerant to schema drift)."""
    itc_hits: list[float] = []  # explicit ITC keys (strongest signal)
    label_hits: list[float] = []  # {"head": "GST_ON_MDR", "amount": 261}
    gst_hits: list[float] = []  # generic gst_* numeric keys
    for d in _walk(resp):
        for k, v in d.items():
            kl = str(k).lower()
            if not ("itc" in kl or "gst" in kl) or any(x in kl for x in ("rate", "pct", "percent", "eligible")):
                continue
            n = _num(v)
            if n is None and isinstance(v, dict):
                n = _num(v.get("amount"))
            if n:
                (itc_hits if "itc" in kl else gst_hits).append(n)
        label = " ".join(str(d.get(x, "")) for x in ("head", "type", "name", "component", "label")).lower()
        amt = _num(d.get("amount"))
        if "gst" in label and amt:
            label_hits.append(amt)
    for hits in (itc_hits, label_hits, gst_hits):
        if hits:
            return hits[0]
    return None


def find_settlement_date(resp: dict[str, Any]) -> str:
    for d in _walk(resp):
        if isinstance(d.get("settlement_date"), str):
            return d["settlement_date"]
    return MERCHANT_ORDER_SHEET["settlement_date"]


def is_fraud(resp: dict[str, Any]) -> bool:
    if resp.get("status") == FRAUD_STATUS:
        return True
    return any(FRAUD_STATUS in (v for v in d.values() if isinstance(v, str)) for d in _walk(resp))


# ----------------------------------------------------------------------------- vernacular reply

REPLY_SYSTEM_PROMPT = """You are the AI teammate of Sharma Electronics, a small Paytm merchant in India.
You just received a structured JSON answer from Paytm's AI agent about the merchant's question.
Write a crisp, warm, empathetic reply in Hindi (Devanagari script); keep financial terms like
UTR, GST, ITC, settlement, chargeback, refund, MDR, EDI in English. At most 2 sentences and
35 words in total. Use ONLY numbers present in the JSON (format rupees like ₹4,160).
If an action is required (e.g. a chargeback HELD awaiting Proof of Delivery), say clearly what the
merchant should do next. If status is NOT_FOUND_SUSPECTED_FAKE, warn firmly not to hand over goods.
No greetings, no markdown, no bullet points."""


def _inr(n: Any) -> str:
    v = _num(n)
    if v is None:
        return str(n)
    i = int(round(v))
    s = str(abs(i))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"₹{'-' if i < 0 else ''}{s}"


def template_reply(intent: str, resp: dict[str, Any], gst_logged: bool) -> str:
    status = resp.get("status")
    data = resp.get("data") or {}
    if is_fraud(resp):
        utr = data.get("utr_number", "")
        return (
            f"सावधान! UTR {utr} Paytm के settlement ledger में नहीं मिला, यह payment fake लग रहा है। "
            "कृपया सामान मत दीजिए, मैंने इसे high-priority fraud alert के रूप में flag कर दिया है।"
        )
    if intent == "SETTLEMENT_RECONCILE":
        # PLAN.md golden path: itemise briefly, log ITC, and flag the ₹800 hold on #9981.
        return (
            f"{_inr(MERCHANT_ORDER_SHEET['variance'])} में MDR ₹1,450, GST ₹261, refund ₹1,500, soundbox ₹149 और "
            f"#9981 का ₹800 chargeback hold है{' — ₹261 ITC मैंने log कर दिया' if gst_logged else ''}। "
            "Delivery proof भेजिए, ₹800 छुड़वा दूँगा।"
        )
    if intent == "UTR_VERIFY":
        if status == "NEEDS_INFO":
            return "Payment check करने के लिए मुझे 12 अंकों का UTR नंबर चाहिए। कृपया UTR बताइए या payment का screenshot upload कीजिए।"
        if status == "PENDING":
            return (
                f"UTR {data.get('utr_number', '')} का {_inr(data.get('amount'))} अभी PENDING है। "
                "NPCI इसे T+1 में auto-reverse कर देगा, इसलिए payment confirm होने तक सामान रोक कर रखिए।"
            )
        return (
            f"अच्छी खबर! UTR {data.get('utr_number', '')} का {_inr(data.get('amount'))} सफल है और settle हो चुका है। "
            "आप बेफिक्र होकर सामान दे सकते हैं।"
        )
    if intent == "CHARGEBACK_RESOLVE":
        if str(status).upper() in ("RELEASED", "CHARGEBACK_REVERSED", "RESOLVED", "WON", "SUCCESS"):
            return (
                f"Proof of Delivery Paytm को भेज दिया, #{data.get('order_id', '9981')} का "
                f"{_inr(data.get('amount', 800))} hold RELEASED हो गया है। पैसा T+1 settlement में आ जाएगा।"
            )
        return (
            f"ORDER #{data.get('order_id', '9981')} का {_inr(data.get('amount', 800))} chargeback की वजह से hold पर है। "
            "48 घंटे के अंदर Proof of Delivery upload कीजिए, मैं तुरंत Paytm से release करवा दूँगा।"
        )
    if intent == "REFUND_MANAGE" and status == "INITIATED":
        return f"#{data.get('order_id')} का {_inr(data.get('amount'))} refund शुरू कर दिया है, customer को T+1 में मिल जाएगा।"
    if intent == "REFUND_MANAGE" and status != "ESCALATED":
        return (
            f"ORDER #{data.get('order_id', '4412')} का {_inr(data.get('amount', 1500))} refund customer को PROCESSED हो चुका है। "
            "यही राशि आपके कल के settlement से काटी गई थी, इसमें कोई गड़बड़ी नहीं है।"
        )
    if intent == "FEE_GST_LOAN":
        loan = data.get("loan") or {}
        return (
            f"MDR {_inr(data.get('mdr_fee', 1450))} पर 18% GST {_inr(data.get('gst_on_mdr', 261))} लगा, "
            f"पूरा ITC claim होगा{' — मैंने log कर दिया' if gst_logged else ''}। "
            f"Loan EDI {_inr(loan.get('edi_per_day', 500))} रोज़ है, बाकी balance {_inr(loan.get('balance', 42000))}।"
        )
    ticket = (resp.get("escalation_ticket") or {}).get("ticket_id", "")
    return (
        f"मैंने आपका मामला Paytm की L2 team को भेज दिया है{f', ticket {ticket}' if ticket else ''}। "
        "2 घंटे में आपको callback आएगा।"
    )


async def vernacular_reply(intent: str, resp: dict[str, Any], gst_logged: bool, merchant_text: Optional[str]) -> tuple[str, str]:
    user_prompt = json.dumps(
        {
            "merchant_question": merchant_text,
            "intent": intent,
            "paytm_response": resp,
            "merchant_side_actions": {"gst_itc_auto_logged": gst_logged, "fraud_alert_raised": is_fraud(resp)},
        },
        ensure_ascii=False,
    )
    reply = await upstream.llm(REPLY_SYSTEM_PROMPT, user_prompt, response_format="text")
    # PLAN.md budget is ≤35 words; allow some slack, otherwise use the (short) template.
    if isinstance(reply, str) and len(reply) > 10 and len(reply.split()) <= 45:
        return reply, "llm"
    return template_reply(intent, resp, gst_logged), "template"


# ----------------------------------------------------------------------------- core


async def run(
    *,
    request_id: str,
    mid: str,
    consent_token: str,
    intent: str,
    intent_source: str,
    slots: Slots,
    merchant_text: Optional[str],
    extra_payload: Optional[dict[str, Any]] = None,
    transcript: Optional[str] = None,
    transcript_source: Optional[str] = None,
    doc_extract: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    STATE.log(
        "INTENT_CLASSIFIED",
        ACTOR_MERCHANT,
        f"Intent: {intent} ({intent_source})",
        {"intent": intent, "source": intent_source, "slots": slots.model_dump()},
        request_id,
    )

    # Data minimisation: Paytm gets structured slots only, never the raw utterance/audio.
    payload: dict[str, Any] = {k: v for k, v in slots.model_dump().items() if v is not None}
    if intent == "SETTLEMENT_RECONCILE":
        payload["merchant_books"] = {
            k: MERCHANT_ORDER_SHEET[k] for k in ("settlement_date", "expected_gross", "bank_credit_received", "variance")
        }
    if extra_payload:
        payload.update(extra_payload)

    envelope = {
        "request_id": request_id,
        "mid": mid,
        "intent": intent,
        "payload": payload,
        "consent_token": consent_token,
    }
    STATE.log("MERCHANT_TO_PAYTM", ACTOR_MERCHANT, f"A2A request → Paytm: {intent}", envelope, request_id)

    resp, paytm_source = await upstream.dispatch(envelope)
    STATE.log(
        "PAYTM_TO_MERCHANT",
        ACTOR_PAYTM,
        f"A2A response ← Paytm: {resp.get('status')}" + (" [mock]" if paytm_source == "mock" else ""),
        {**resp, "_source": paytm_source},
        request_id,
    )

    # Local merchant side-effects
    gst_entry: Optional[dict[str, Any]] = None
    itc: Optional[float | int] = find_gst_itc(resp)
    if itc:
        itc = int(itc) if float(itc).is_integer() else itc
        gst_entry = STATE.add_gst_itc(
            {
                "amount": itc,
                "settlement_date": find_settlement_date(resp),
                "basis": "18% GST on MDR (ITC eligible)",
                "source_request_id": request_id,
                "logged_at": time.time(),
            }
        )
        if gst_entry:
            STATE.log(
                "GST_ITC_LOGGED",
                ACTOR_MERCHANT,
                f"{_inr(itc)} GST ITC auto-logged to merchant's GST register",
                {**gst_entry, "itc_total": STATE.gst_itc_total},
                request_id,
            )

    fraud_alert: Optional[dict[str, Any]] = None
    if is_fraud(resp):
        data = resp.get("data") or {}
        fraud_alert = {
            "alert_id": f"FRAUD_{request_id}",
            "priority": "HIGH",
            "status": FRAUD_STATUS,
            "utr_number": data.get("utr_number") or slots.utr_number,
            "amount": data.get("amount") or slots.amount,
            "recommended_action": "DO_NOT_RELEASE_GOODS",
            "raised_at": time.time(),
        }
        STATE.fraud_alerts.append(fraud_alert)
        STATE.log(
            "FRAUD_ALERT",
            ACTOR_MERCHANT,
            f"HIGH priority: suspected fake payment (UTR {fraud_alert['utr_number']})",
            fraud_alert,
            request_id,
        )

    reply_text, reply_source = await vernacular_reply(intent, resp, gst_entry is not None, merchant_text)
    audio_b64, tts_source = await upstream.tts(reply_text, "hi-IN")
    STATE.log(
        "VOICE_REPLY_READY",
        ACTOR_MERCHANT,
        "Hindi voice reply ready" + ("" if audio_b64 else " (text only — TTS unavailable)"),
        {"reply_text": reply_text, "reply_source": reply_source, "tts": tts_source, "language_code": "hi-IN"},
        request_id,
    )

    return {
        "request_id": request_id,
        "mid": mid,
        "transcript": transcript,
        "transcript_source": transcript_source,
        "consent_token": consent_token,
        "intent": intent,
        "intent_source": intent_source,
        "slots": slots.model_dump(),
        "doc_extract": doc_extract,
        "paytm_response": resp,
        "paytm_source": paytm_source,
        "reply_text": reply_text,
        "reply_source": reply_source,
        "audio_base64": audio_b64,
        "language_code": "hi-IN",
        "fraud_alert": fraud_alert,
        "gst_itc_logged": gst_entry,
        "local_gst_itc_log": STATE.local_gst_itc_log,
        "a2a_events": STATE.a2a_events,
    }
