"""A2A orchestration (PLAN.md closed loop): DPDP gate -> intent -> diagnose -> evaluate A/B/C -> Paytm mesh
-> side effects (ITC, fraud, khata) -> verify + learn -> Hinglish voice reply."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException

import advisor
import dataset_loader as dl
import khata
import repository
import upstream
from schemas import Slots
from state import STATE, order_sheet

log = logging.getLogger("merchant_agent.pipeline")

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
    return order_sheet()["settlement_date"]


def is_fraud(resp: dict[str, Any]) -> bool:
    if resp.get("status") == FRAUD_STATUS:
        return True
    return any(FRAUD_STATUS in (v for v in d.values() if isinstance(v, str)) for d in _walk(resp))


# ----------------------------------------------------------------------------- vernacular reply

REPLY_SYSTEM_PROMPT = """You are the warm AI business buddy of {merchant_name}, a small Paytm merchant in India.
You get JSON with the merchant's question, Paytm's multi-agent answer, your own root-cause diagnosis
(historical_insight) and the intervention you chose. Reply in Hinglish written in Devanagari; keep
financial terms like UTR, GST, ITC, settlement, chargeback, refund, MDR, EDI, KFS, PoD in English.
Combine (1) what was resolved or what the merchant must do next with (2) ONE short business tip from
historical_insight.tip_hi. At most 2 sentences and 35 words in total. Use ONLY numbers present in the JSON
(format rupees like ₹4,160). If status is NOT_FOUND_SUSPECTED_FAKE, warn firmly not to hand over goods and
skip the tip. If confirmation is awaited, ask for a 1-tap yes. No greetings, no markdown, no bullet points."""

MAX_REPLY_WORDS = 35


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


def _amt(v: Any) -> str:
    """'₹1,250 ' when v is a number, else '' (keeps templates grammatical when Paytm omits an amount)."""
    return f"{_inr(v)} " if _num(v) is not None else ""


def _utr(data: dict[str, Any]) -> str:
    return str(data.get("utr_number") or data.get("utr") or "")


def _head_of(item: dict[str, Any]) -> str:
    return dl.head_code(dl.pick(item, "head", "code", "type", "name", "component", "label", "category") or "")


# Order matters: GST_ON_MDR contains "MDR", so GST must be checked first.
_DEDUCTION_LABELS = (("GST", "GST"), ("MDR", "MDR"), ("REFUND", "refund"), ("SOUNDBOX", "soundbox"),
                     ("RENTAL", "rental"), ("EDI", "loan EDI"), ("LOAN", "loan EDI"))


def _deduction_phrase(item: dict[str, Any]) -> str:
    head, amount = _head_of(item), _inr(item.get("amount"))
    if "CHARGEBACK" in head or "HOLD" in head:
        oid = item.get("order_id") or (dl.DATA.chargeback() or {}).get("order_id")
        return f"#{oid} का {amount} chargeback hold" if oid else f"{amount} chargeback hold"
    label = next((lbl for needle, lbl in _DEDUCTION_LABELS if needle in head), head.replace("_", " ").lower())
    return f"{label} {amount}"


_SUCCESS = {"SUCCESS", "SETTLED", "VERIFIED", "CONFIRMED", "CREDITED", "RECEIVED"}
_PENDING = {"PENDING", "IN_PROGRESS", "PROCESSING", "INITIATED"}
_CAUSE_HI = (("closure", "बाज़ार बंदी"), ("rain", "बारिश"), ("flood", "बाढ़"), ("holiday", "छुट्टी"),
             ("bandh", "बंद"), ("strike", "हड़ताल"))


def _cause_hi(cause: Any) -> str:
    c = str(cause or "").lower()
    return next((hi for en, hi in _CAUSE_HI if en in c), "")


def template_reply(intent: str, resp: dict[str, Any], gst_entry: Optional[dict[str, Any]],
                   ctx: Optional[dict[str, Any]] = None) -> str:
    """Status-aware Hindi/Hinglish fallback replies (the resolution part; the tip is added by compose())."""
    d, h, ctx = dl.DATA, dl.DATA.history, ctx or {}
    status = str(resp.get("status") or "").upper()
    data = resp.get("data") or {}
    if is_fraud(resp):
        return (
            f"सावधान! UTR {_utr(data)} Paytm के settlement ledger में नहीं मिला, यह payment fake लग रहा है। "
            "कृपया सामान मत दीजिए, मैंने इसे high-priority fraud alert के रूप में flag कर दिया है।"
        )
    if intent == "SETTLEMENT_RECONCILE":
        # PLAN.md golden path: itemise briefly, log ITC, and flag the chargeback hold (#9981) with a next step.
        items = dl.normalise_deductions(data.get("breakdown") or data.get("deductions")) or d.settlement["deductions"]
        parts = [_deduction_phrase(i) for i in items]
        listing = f"{', '.join(parts[:-1])} और {parts[-1]}" if len(parts) > 1 else "".join(parts)
        itc = f" — {_inr(gst_entry['amount'])} ITC मैंने log कर दिया" if gst_entry else ""
        hold = next((i for i in items if "CHARGEBACK" in _head_of(i) or "HOLD" in _head_of(i)), None)
        cta = (f" Delivery proof भेजिए, {_inr(hold['amount'])} छुड़वा दूँगा।"
               if hold and str(hold.get("status", "HELD")).upper() != "RELEASED" else "")
        variance = data.get("variance") or order_sheet()["variance"]
        return f"{_inr(variance)} में {listing} है{itc}।{cta}"
    if intent == "UTR_VERIFY":
        utr, amount = _utr(data), _amt(data.get("amount"))
        if status == "NEEDS_INFO":
            return "Payment check करने के लिए मुझे 12 अंकों का UTR नंबर चाहिए। कृपया UTR बताइए या payment का screenshot upload कीजिए।"
        if status in _PENDING:
            return (f"UTR {utr} का {amount}payment अभी PENDING है। "
                    "NPCI इसे T+1 में auto-reverse कर सकता है, इसलिए confirm होने तक सामान रोक कर रखिए।")
        if status in _SUCCESS:
            return f"अच्छी खबर! UTR {utr} का {amount}payment सफल है और settle हो चुका है। आप बेफिक्र होकर सामान दे सकते हैं।"
        return f"UTR {utr} का {amount}payment {status} है। पैसा confirm होने तक सामान मत दीजिए।"
    if intent == "CHARGEBACK_RESOLVE":
        cb = d.chargeback(dl.digits(data.get("order_id"))) or d.chargeback() or {}
        oid, amount = data.get("order_id") or cb.get("order_id", ""), _amt(data.get("amount") or cb.get("amount"))
        if status == "NO_CHARGEBACK_FOUND":
            return f"Order #{oid} पर कोई chargeback hold नहीं मिला। कोई और order देखना हो तो number बताइए।"
        if status in ("RELEASED", "CHARGEBACK_REVERSED", "RESOLVED", "WON", "SUCCESS"):
            return (f"Proof of Delivery Paytm को भेज दिया, #{oid} का {amount}hold RELEASED हो गया है। "
                    "पैसा T+1 settlement में आ जाएगा।")
        if status == "ALERT_RAISED" and ctx.get("pod_ready"):
            return (f"Paytm ने #{oid} पर {amount}chargeback alert भेजा है। Shiprocket से signed PoD मिल गया, "
                    "1-tap sign-off कीजिए, मैं dispute भेज दूँगा।")
        hours = data.get("pod_due_in_hours") or data.get("deadline_hours") or cb.get("pod_due_in_hours") or 48
        return (f"ORDER #{oid} का {amount}chargeback की वजह से hold पर है। "
                f"{hours} घंटे के अंदर Proof of Delivery upload कीजिए, मैं तुरंत Paytm से release करवा दूँगा।")
    if intent == "REFUND_MANAGE" and status != "ESCALATED":
        if status == "INITIATED":
            return f"#{data.get('order_id')} का {_amt(data.get('amount'))}refund शुरू कर दिया है, customer को T+1 में मिल जाएगा।"
        if status == "NEEDS_INFO":
            return "Refund शुरू करने के लिए order number और amount बताइए।"
        rf = d.refund(dl.digits(data.get("order_id"))) or d.refund() or {}
        return (
            f"ORDER #{data.get('order_id') or rf.get('order_id', '')} का {_amt(data.get('amount') or rf.get('amount'))}"
            f"refund customer को {status or 'PROCESSED'} हो चुका है। यही राशि आपके settlement से काटी गई थी, इसमें कोई गड़बड़ी नहीं है।"
        )
    if intent == "FEE_GST_LOAN":
        loan = dl.normalise_loan(data.get("loan")) or d.loan
        gst_pct = data.get("gst_rate_pct") or d.fees["gst_rate_pct"]
        return (
            f"MDR {_inr(data.get('mdr_fee') or d.deduction_amount('MDR'))} पर {gst_pct}% GST "
            f"{_inr(data.get('gst_on_mdr') or d.deduction_amount('GST'))} लगा, "
            f"पूरा ITC claim होगा{' — मैंने log कर दिया' if gst_entry else ''}। "
            f"Loan EDI {_inr(loan.get('edi_per_day'))} रोज़ है, बाकी balance {_inr(loan.get('balance'))}।"
        )
    if intent == "MANDATE_TROUBLESHOOT" and status != "ESCALATED":
        edi = _inr(data.get("missed_edi") or data.get("edi_amount") or d.loan.get("edi_per_day"))
        m = (ctx.get("insight") or {}).get("metrics") or {}
        cause = _cause_hi(((ctx.get("insight") or {}).get("summary")))
        why = (f"{cause + ' से ' if cause else ''}बिक्री {m.get('sales_dip_pct')}% गिरी, इसलिए {edi} EDI fail हुई, default नहीं।"
               if (ctx.get("insight") or {}).get("classification") == "PAYMENT_FRICTION" else f"{edi} EDI का mandate fail हुआ था।")
        if status == "REMINDER_SENT":
            return f"{why} Reminder भेज दिया है, कल फिर debit होगा।"
        if status == "ALERT_RAISED":
            return f"{why} 1-tap UPI link भेजूँ? 48 घंटे की grace मिलेगी।"
        if status == "REMEDIES_OFFERED":  # live 8002: UPI link to pay today, or a KFS 2-day pause
            pause = any(r.get("offer_id") for r in data.get("remedies") or [])
            return f"{why} 1-tap UPI link से आज भरिए, penalty नहीं{'; चाहें तो 2 दिन का KFS pause भी है' if pause else ''}।"
        if status == "MANDATE_RESOLVED":
            return f"{why} Paytm ने मामला सुलझा दिया है, penalty नहीं लगेगी।"
        return f"{why} 1-tap UPI link भेजा है, penalty नहीं लगेगी।"
    if intent == "DUPLICATE_RECONCILE" and status != "ESCALATED":
        if status == "NO_DUPLICATE_FOUND":
            return f"Order #{data.get('order_id') or ''} पर कोई duplicate payment नहीं मिला। UTR बताइए तो दोबारा जाँच लूँ।"
        amt = _inr(data.get("amount"))
        return (f"{data.get('customer') or 'Customer'} ने order #{data.get('order_id')} के {amt} दो बार दिए थे। "
                f"Duplicate {amt} का refund शुरू कर दिया, T+1 में पहुँचेगा।")
    if intent == "GROWTH_ADVISORY" and status == "ADVICE_READY":  # 8002: advice only, no new credit offered
        day = {"Monday": "सोमवार", "Tuesday": "मंगलवार", "Wednesday": "बुधवार", "Thursday": "गुरुवार",
               "Friday": "शुक्रवार"}.get(str(data.get("restock_by")), data.get("restock_by") or "गुरुवार")
        loan = data.get("existing_loan") or {}
        loan_line = (f" {loan.get('lender')} loan का {_inr(loan.get('balance'))} बाकी है, {_inr(loan.get('edi_per_day'))} EDI "
                     f"रोज़ की बिक्री का सिर्फ़ {loan.get('edi_share_of_daily_sales_pct')}% है।"
                     if loan.get("balance") and loan.get("edi_share_of_daily_sales_pct") is not None else "")
        return (f"रोज़ औसत {_inr(data.get('daily_avg_sales'))}, Fri–Sun {data.get('weekend_multiplier')}x "
                f"(~{_inr(data.get('weekend_daily_sales'))}/दिन) — {day} तक stock भर लीजिए।{loan_line}")
    if intent == "GROWTH_ADVISORY":
        offer = data.get("offer") or h.get("growth_offer") or {}
        trend = data.get("six_month_trend_pct")
        grew = f"6 महीने में बिक्री {trend}% बढ़ी है। " if isinstance(trend, (int, float)) and trend > 0 else ""
        # No rate is quoted: rate and tenure are the NBFC's to disclose in the KFS (same stance as 8002).
        return (f"{grew}{offer.get('lender') or h.get('active_lender')} का {_inr(offer.get('amount'))} working capital "
                "pre-approved है; rate और tenure KFS में देखकर ही लें।")
    if intent == "CASHFLOW_EDI_SWITCH":
        gap = ctx.get("cashflow") or {}
        offer = data.get("edi_pause_offer") or {}
        edi = _inr(d.loan.get("edi_per_day"))
        if status == "EDI_PAUSED":
            return (f"{data.get('nbfc') or h.get('active_lender')} का {edi} EDI {data.get('pause_days')} दिन pause कर दिया, "
                    f"{_inr(data.get('edi_saved_inr'))} बचे; कल EDI नहीं कटेगी।")
        if status == "ALERT_RAISED":
            refund = gap.get("refund_request") or {}
            if gap.get("shortfall") and offer.get("eligible"):
                return (f"{_inr(refund.get('amount'))} refund के बाद कल payout {_inr(gap.get('projected_net_payout'))} रहेगा, "
                        f"stock के {_inr(gap.get('tomorrow_stock_due'))} चाहिए। {offer.get('nbfc')} का {edi} EDI "
                        f"{offer.get('pause_days')} दिन रोक दूँ?")
            if STATE.loan_edi_status != "ACTIVE":
                return f"आपकी {edi} EDI पहले से pause है, कल नहीं कटेगी।"
            if not gap.get("shortfall"):
                return f"कल का payout {_inr(gap.get('projected_net_payout'))} stock के लिए काफी है, EDI pause की ज़रूरत नहीं।"
            return "इस बार EDI pause की पात्रता नहीं है। Supplier से 2 दिन की मोहलत माँगना बेहतर रहेगा।"
        return "इस बार EDI pause नहीं हो सकता, KFS शर्तें पूरी नहीं हैं। Supplier से 2 दिन की मोहलत माँगना बेहतर रहेगा।"
    if intent == "SOUNDBOX_RETURN" and status != "ESCALATED":
        return (f"Soundbox की pickup {data.get('pickup_within_hours', 48)} घंटे में होगी, ticket {data.get('pickup_ticket')}। "
                f"{_inr(data.get('rental_per_month'))} का rental अगले cycle से बंद हो जाएगा।")
    if intent == "LOAN_CLOSURE_NOC" and status != "ESCALATED":
        return (f"{data.get('lender')} loan का बाकी {_inr(data.get('outstanding'))} है, foreclosure charge "
                f"{_inr(data.get('foreclosure_charge', 0))}। भुगतान के {data.get('noc_eta_days', 7)} दिन में NOC मिल जाएगा।")
    if intent == "BANK_KYC_UPDATE" and status != "ESCALATED":
        return ("नया bank account जोड़ने का secure link भेज दिया है। Penny-drop verify होते ही "
                f"{data.get('eta_hours', '24-48')} घंटे में settlement नए account में आएगा।")
    if intent == "SETTLEMENT_HOLD_BANK" and status != "ESCALATED":
        if status == "NO_BANK_HOLD":
            last = data.get("last_credit") or {}
            holds = data.get("open_holds") or []
            hold = (f" सिर्फ #{holds[0]['order_id']} का {_inr(holds[0].get('amount'))} chargeback hold है।" if holds else "")
            return (f"आपका {data.get('bank') or 'bank'} account ACTIVE है, कोई bank hold नहीं; "
                    f"{_inr(last.get('amount'))} credit हो चुका है।{hold}")
        return (f"Bank account {data.get('bank_status')} होने से settlement रुका है। "
                "Account update कीजिए, अगले cycle में पैसा आ जाएगा।")
    ticket = (resp.get("escalation_ticket") or {}).get("ticket_id", "")
    hardware = (data.get("device") or data.get("issue_type") == "HARDWARE_SOUNDBOX"
                or ctx.get("issue_type") == "HARDWARE_SOUNDBOX")  # live 8002 doesn't echo the device back
    what = "Soundbox की खराबी का मामला" if hardware else "आपका मामला"
    return (
        f"मैंने {what} Paytm की L2 team को भेज दिया है{f', ticket {ticket}' if ticket else ''}। "
        "2 घंटे में आपको callback आएगा।"
    )


def compose(resolution: str, tip: Optional[str], max_words: int = MAX_REPLY_WORDS) -> str:
    """Resolution + historical business tip, keeping the voice reply within the PLAN.md word budget."""
    if tip and tip not in resolution and len(resolution.split()) + len(tip.split()) <= max_words:
        return f"{resolution} {tip}"
    return resolution


async def vernacular_reply(
    intent: str,
    resp: dict[str, Any],
    gst_entry: Optional[dict[str, Any]],
    merchant_text: Optional[str],
    document_submitted: Optional[str] = None,
    insight: Optional[dict[str, Any]] = None,
    evaluation: Optional[dict[str, Any]] = None,
    ctx: Optional[dict[str, Any]] = None,
) -> tuple[str, str]:
    insight = insight or {}
    user_prompt = json.dumps(
        {
            "merchant_question": merchant_text,
            "intent": intent,
            "paytm_response": {k: v for k, v in resp.items() if k != "agent_trace"},
            "historical_insight": {k: insight.get(k) for k in ("classification", "summary", "tip_hi")},
            "chosen_intervention": (evaluation or {}).get("selected_intervention"),
            "merchant_side_actions": {
                "gst_itc_auto_logged": gst_entry is not None,
                "fraud_alert_raised": is_fraud(resp),
                "document_submitted": document_submitted,
                "awaiting_confirmation": (ctx or {}).get("awaiting_confirmation"),
            },
        },
        ensure_ascii=False,
        default=str,
    )
    system_prompt = REPLY_SYSTEM_PROMPT.format(merchant_name=dl.DATA.merchant["name"])
    # Consent moments (EDI pause offer, dispute sign-off) are never paraphrased: live, the LLM turned
    # "EDI 2 दिन रोक दूँ?" into "Paytm ने EDI pause किया है" before the merchant had said yes.
    awaiting = (ctx or {}).get("awaiting_confirmation")
    reply = None if awaiting else await upstream.llm(system_prompt, user_prompt, response_format="text")
    resolution = template_reply(intent, resp, gst_entry, {**(ctx or {}), "insight": insight})
    tip = None if is_fraud(resp) else insight.get("tip_hi")
    # The tip names the duplicate payer from the merchant's books; if Paytm matched a different order, drop it.
    paid_order = dl.digits((resp.get("data") or {}).get("order_id"))
    if intent == "DUPLICATE_RECONCILE" and paid_order and paid_order != (insight.get("metrics") or {}).get("order_id"):
        tip = None
    template = compose(resolution, tip)
    # PLAN.md budget is ≤35 words; allow some slack, otherwise use the (short) template.
    if isinstance(reply, str) and len(reply) > 10 and len(reply.split()) <= 45:
        bad = ungrounded_numbers(reply, " ".join([user_prompt, template, merchant_text or ""]))
        if not bad:
            return reply, "llm"
        # Live: the LLM said "₹4,160 का UTR" when no amount existed. Money talk must come from the facts.
        log.warning("LLM reply dropped, numbers not in the facts: %s", bad)
    return template, "template"


_NUM_RE = re.compile(r"(₹\s*)?(\d[\d,]*(?:\.\d+)?)")


def _num_forms(text: str) -> set[str]:
    forms: set[str] = set()
    for _, n in _NUM_RE.findall(text.translate(str.maketrans("०१२३४५६७८९", "0123456789"))):
        n = n.replace(",", "").rstrip(".")
        forms.add(n)
        try:
            f = float(n)
            forms.add(str(int(f)) if f == int(f) else str(f))
        except ValueError:
            pass
    return forms


def ungrounded_numbers(reply: str, facts: str) -> list[str]:
    """Amounts (₹…) and 3+ digit numbers (UTRs, orders, years) in `reply` that appear nowhere in `facts`."""
    known = _num_forms(facts)
    bad = []
    for rupee, n in _NUM_RE.findall(reply.translate(str.maketrans("०१२३४५६७८९", "0123456789"))):
        plain = n.replace(",", "").rstrip(".")
        if not (rupee or len(re.sub(r"\D", "", plain)) >= 3):
            continue
        forms = {plain}
        try:
            f = float(plain)
            forms.add(str(int(f)) if f == int(f) else str(f))
        except ValueError:
            pass
        if not forms & known:
            bad.append((rupee or "") + n)
    return bad


# ----------------------------------------------------------------------------- pending action

# Where the frontend sends the merchant's next step.
_NEXT_STEP = {
    "UPLOAD_POD": {"endpoint": "/merchant/upload-doc", "doc_type": "pod"},
    "SUBMIT_POD": {"endpoint": "/merchant/upload-doc", "doc_type": "pod"},
    "PROVIDE_UTR": {"endpoint": "/merchant/upload-doc", "doc_type": "upi_screenshot"},
    "CONFIRM_DISPUTE": {"endpoint": "/merchant/confirm-dispute"},
    "CONFIRM_EDI_PAUSE": {"endpoint": "/merchant/confirm-edi-pause"},
}


def pending_action(resp: dict[str, Any]) -> Optional[dict[str, Any]]:
    ar = resp.get("action_required")
    if not isinstance(ar, dict) or not ar.get("type"):
        return None
    out = {**ar, **_NEXT_STEP.get(str(ar["type"]).upper(), {})}
    if str(ar["type"]).upper() == "CHOOSE_REMEDY":  # 8002 mandate: UPI link or a KFS pause (confirmable here)
        out["remedies"] = (resp.get("data") or {}).get("remedies") or []
        pause = next((r for r in out["remedies"] if r.get("offer_id")), None)
        if pause:
            out.update(offer_id=pause["offer_id"], pause_endpoint="/merchant/confirm-edi-pause")
    return out


def _register_remedy_offers(resp: dict[str, Any], request_id: str, insight: dict[str, Any],
                            evaluation: dict[str, Any]) -> None:
    """8002 offers a KFS hardship pause as a mandate remedy; keep it so /merchant/confirm-edi-pause can accept it."""
    for r in (resp.get("data") or {}).get("remedies") or []:
        if r.get("offer_id") and r.get("eligible", True) and r["offer_id"] not in STATE.edi_offers:
            STATE.edi_offers[r["offer_id"]] = {
                "offer_id": r["offer_id"], "eligible": True, "nbfc": r.get("nbfc"), "pause_days": r.get("pause_days", 2),
                "edi_saved_inr": r.get("edi_saved_inr"), "kfs_clause": r.get("kfs_clause", "4.2"), "status": "OFFERED",
                "request_id": request_id, "insight": insight, "evaluation": evaluation, "cashflow": None,
                "source": "MANDATE_REMEDY"}


# "wapas karna hai", "refund kar do/karo", "return karo": the merchant wants to send money back (vs. "refund hua?")
_REFUND_ASK_RE = re.compile(r"wapas\s+(karna|kar\s*do|karo|dena|de\s*do)|refund\s+(karna|kar\s*do|karo|dena|de\s*do|initiate|start)|लौटा(ना|\s*दो)|वापस\s+(करना|कर\s*दो|करो)", re.I)


def paytm_payload_aliases(intent: str, payload: dict[str, Any], ctx: dict[str, Any], from_document: bool,
                          merchant_text: Optional[str] = None) -> dict[str, Any]:
    """Field names Person 2's 8002 reads (it answers 400 BAD_PAYLOAD without them); ours stay alongside."""
    out: dict[str, Any] = {}
    if payload.get("utr_number"):
        out["utr"] = payload["utr_number"]
    if intent == "UTR_VERIFY":
        out["source"] = "screenshot" if from_document else "voice"
        if payload.get("amount") is not None:
            out["claimed_amount_inr"] = payload["amount"]
    if intent == "CHARGEBACK_RESOLVE" and payload.get("pod_document") and "doc_confidence" not in payload:
        out["doc_confidence"] = ctx.get("doc_confidence")
    if intent == "REFUND_MANAGE":  # 8002 reads order_id + action (STATUS | INITIATE) + amount_inr
        out["action"] = "INITIATE" if _REFUND_ASK_RE.search(merchant_text or "") else "STATUS"
        if payload.get("amount") is not None:
            out["amount_inr"] = int(payload["amount"])
    if intent == "ESCALATE_HUMAN" and not payload.get("reason_code"):
        out["reason_code"] = "MERCHANT_REQUESTED_HUMAN"  # 8002 has no hardware code; the details go in reason_text
        if payload.get("issue_type") == "HARDWARE_SOUNDBOX":
            diag = payload.get("diagnostics") or {}
            out["reason_text"] = "Soundbox hardware fault: needs a replacement device"
            out["tried"] = [f"Device logs checked: battery health {diag.get('battery_health_pct', diag.get('battery_pct'))}%, "
                            f"network {diag.get('network')}, {diag.get('announce_failures_24h', '?')} payments not announced"
                            f" in 24h, speaker test {diag.get('speaker_test')}"]
    return out


# ----------------------------------------------------------------------------- core

Caller = Callable[[dict[str, Any]], Awaitable[tuple[dict[str, Any], str]]]


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
    call: Optional[Caller] = None,
    preset_response: Optional[tuple[dict[str, Any], str]] = None,
    insight: Optional[dict[str, Any]] = None,
    evaluation: Optional[dict[str, Any]] = None,
    context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """PLAN.md's 5-step loop for one request.

    call            -- 8002 endpoint to use instead of /a2a/dispatch (e.g. /a2a/execute-edi-pause)
    preset_response -- Paytm's answer is already known (a proactive alert): nothing is sent to Paytm
    insight / evaluation -- reuse an earlier diagnosis + choice (confirmations of a proactive offer)
    context         -- merchant-side facts for diagnosis and the reply (alert data, connector results)
    """
    ctx = {**(extra_payload or {}), **(context or {})}
    STATE.log(
        "INTENT_CLASSIFIED",
        ACTOR_MERCHANT,
        f"Intent: {intent} ({intent_source})",
        {"intent": intent, "source": intent_source, "slots": slots.model_dump()},
        request_id,
    )

    # 1. Understand + diagnose against the 6-month history
    insight = insight or advisor.diagnose(intent, slots, merchant_text, ctx)
    STATE.log("ROOT_CAUSE_DIAGNOSED", ACTOR_MERCHANT, f"{insight.get('classification')}: {insight.get('summary')}",
              {k: v for k, v in insight.items() if k != "profile"}, request_id)

    # 2. Evaluate interventions A/B/C
    evaluation = evaluation or advisor.evaluate(intent, insight, slots, ctx)
    sel = evaluation["selected_intervention"]
    STATE.log("INTERVENTIONS_EVALUATED", ACTOR_MERCHANT,
              f"Selected option {sel['option_id']}: {sel['action']} (score {sel['score']:.2f})", evaluation, request_id)

    # 3. A2A dispatch. Data minimisation: Paytm gets structured slots only, never the raw utterance/audio.
    if preset_response is not None:
        resp, paytm_source = preset_response
    else:
        payload: dict[str, Any] = {k: v for k, v in slots.model_dump().items() if v is not None}
        if intent == "SETTLEMENT_RECONCILE":
            sheet = order_sheet()
            payload["merchant_books"] = {
                k: sheet[k] for k in ("settlement_date", "expected_gross", "bank_credit_received", "variance")
            }
        if extra_payload:
            payload.update(extra_payload)
        payload.update(paytm_payload_aliases(intent, payload, ctx, doc_extract is not None, merchant_text))
        envelope = {
            "request_id": request_id,
            "mid": mid,
            "intent": intent,
            "selected_intervention": sel,
            "payload": payload,
            "consent_token": consent_token,
            # Person 2's DispatchRequest: a session lets 8002 apply cross-call rules (repeated unknown UTRs).
            # `merchant_said` is deliberately not sent (DPDP data minimisation, D8): structured slots only.
            "session_id": STATE.session_id,
            "language_code": "hi-IN",
        }
        STATE.log("MERCHANT_TO_PAYTM", ACTOR_MERCHANT, f"A2A request → Paytm: {intent} / {sel['action']}",
                  envelope, request_id)
        resp, paytm_source = await (call or upstream.dispatch)(envelope)
        # 4. Paytm's 4-agent mesh answered (agent_trace)
        STATE.log(
            "PAYTM_TO_MERCHANT",
            ACTOR_PAYTM,
            f"A2A response ← Paytm: {resp.get('status')}" + (" [mock]" if paytm_source == "mock" else ""),
            {**resp, "_source": paytm_source},
            request_id,
        )

    raw_resp = resp
    resp = upstream.interpret(intent, resp, paytm_source)  # 8002's RESOLVED/ACTION_REQUIRED -> specific outcome
    if intent == "MANDATE_TROUBLESHOOT":
        _register_remedy_offers(resp, request_id, insight, evaluation)

    # Local merchant side-effects
    gst_entry: Optional[dict[str, Any]] = None
    itc: Optional[float | int] = find_gst_itc(resp)
    if itc:
        itc = int(itc) if float(itc).is_integer() else itc
        gst_entry = STATE.add_gst_itc(
            {
                "amount": itc,
                "settlement_date": find_settlement_date(resp),
                "gstin": dl.DATA.merchant.get("gstin"),
                "basis": dl.DATA.gst_basis(),
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
            "utr_number": _utr(data) or slots.utr_number,
            "amount": data.get("amount") or slots.amount,
            "recommended_action": "DO_NOT_RELEASE_GOODS",
            "raised_at": time.time(),
        }
        STATE.fraud_alerts.append(fraud_alert)
        repository.add_fraud_alert(fraud_alert)  # no-op unless USE_SUPABASE=true
        STATE.log(
            "FRAUD_ALERT",
            ACTOR_MERCHANT,
            f"HIGH priority: suspected fake payment (UTR {fraud_alert['utr_number']})",
            fraud_alert,
            request_id,
        )

    edi_status = str((resp.get("data") or {}).get("loan_edi_status") or "")
    if edi_status:
        STATE.loan_edi_status = "ACTIVE" if edi_status.upper() == "ACTIVE" else edi_status
    if (entry := khata.record(intent, resp, request_id)) is not None:
        STATE.log("KHATA_UPDATED", ACTOR_MERCHANT, f"Khata: {entry['kind']} {_inr(entry['amount'])} ({entry['reference']})",
                  entry, request_id)

    # 5. Verify the outcome and learn
    outcome = advisor.verify_and_learn(intent, evaluation, resp, paytm_source, request_id)
    STATE.log("OUTCOME_VERIFIED", ACTOR_MERCHANT,
              f"{outcome['outcome']}: {sel['action']} → {outcome['paytm_status']}"
              + (f" (strategy now {outcome['strategy_success_rate']:.0%})" if outcome["learned"] else ""),
              outcome, request_id)

    reply_text, reply_source = await vernacular_reply(
        intent, resp, gst_entry, merchant_text, (doc_extract or {}).get("doc_type"), insight, evaluation, ctx
    )
    audio_b64, tts_source = await upstream.tts(reply_text, "hi-IN")
    tts_note = {"live": "", "mock": " (TTS mock audio)"}.get(tts_source, " (text only — TTS unavailable)")
    STATE.log(
        "VOICE_REPLY_READY",
        ACTOR_MERCHANT,
        "Hinglish voice reply ready" + tts_note,
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
        "historical_insight": insight,
        "intervention_evaluation": evaluation,
        "verified_outcome": outcome,
        "pending_action": pending_action(resp),
        # 8002's body as sent, plus the merchant-side reading of it (e.g. RESOLVED -> RELEASED)
        # D1 shape: `status` is the specific outcome (RELEASED, PENDING, …), as in mock mode, which the frontend
        # keys its ledger effects on. 8002's own RESOLVED/ACTION_REQUIRED/ESCALATED stays in `mesh_status`;
        # `data` stays 8002's raw body (the frontend reads its field names).
        "paytm_response": {**raw_resp, "status": resp.get("status"), "mesh_status": raw_resp.get("status"),
                           "status_detail": resp.get("status")} if raw_resp is not resp else resp,
        "paytm_source": paytm_source,
        "paytm_agent_trace": resp.get("agent_trace") if isinstance(resp.get("agent_trace"), list) else [],
        "hindi_reply": reply_text,
        "reply_text": reply_text,
        "reply_source": reply_source,
        "audio_base64": audio_b64,
        "audio_source": tts_source,
        "language_code": "hi-IN",
        "fraud_alert": fraud_alert,
        "gst_itc_logged": gst_entry,
        "local_gst_itc_log": STATE.local_gst_itc_log,
        "proactive": None,
        "a2a_events": STATE.a2a_events,
    }
