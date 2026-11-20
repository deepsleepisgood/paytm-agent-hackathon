"""A2A orchestration (PLAN.md closed loop): DPDP gate -> intent -> diagnose -> evaluate A/B/C -> Paytm mesh
-> side effects (ITC, fraud, khata) -> verify + learn -> Hinglish voice reply."""
from __future__ import annotations

import contextvars
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

# Reply wording. Default: Sarvam's LLM answers the merchant's actual question from Paytm's answer (numbers checked,
# verified tip appended verbatim); the per-status templates are the fallback. REPLY_LLM=0 = templates only.
# (Templates alone answered the topic, not the question: every settlement question got the same breakdown.)
REPLY_LLM = __import__("os").getenv("REPLY_LLM", "1").strip().lower() in ("1", "true", "yes", "on")

# Reply language for this request (the app's हि / EN tab). Set once per request by the endpoint.
_REPLY_LANG: contextvars.ContextVar[str] = contextvars.ContextVar("reply_lang", default="hi")


def set_lang(code: Optional[str]) -> str:
    value = "en" if str(code or "").lower().startswith("en") else "hi"
    _REPLY_LANG.set(value)
    return value


def lang() -> str:
    return _REPLY_LANG.get()


# The last few turns of this merchant's conversation (conversation.recent), set per request by the endpoint, so the
# reply and info LLMs understand follow-ups ("uska", "kab tak?") and earlier answers count as grounded facts.
_HISTORY: contextvars.ContextVar[list] = contextvars.ContextVar("history", default=[])


def set_history(turns: Optional[list]) -> None:
    _HISTORY.set(list(turns or []))


def history() -> list:
    return _HISTORY.get()


def _history_json() -> str:
    return json.dumps(history(), ensure_ascii=False, default=str) if history() else ""


def tts_code() -> str:
    return "en-IN" if lang() == "en" else "hi-IN"


LANGUAGE_RULE = {
    "hi": "Write in everyday Hinglish in ROMAN (Latin) letters only, the way Indian shopkeepers type on WhatsApp "
          "(e.g. \"Aapka settlement kal subah 8 baje aa jayega.\"). Never use Devanagari script, even if the question "
          "was in Devanagari. Keep UTR, GST, ITC, settlement, chargeback, refund, MDR, EDI, KFS, PoD, Soundbox in English.",
    "en": "Write in simple Indian English (Latin script only, no Hindi words).",
}

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
                "message_hi": "Aage badhne ke liye data share karne ki sahmati dijiye.",
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
You get JSON with the merchant's exact question, Paytm's multi-agent answer (paytm_response) and your diagnosis.
ANSWER THE MERCHANT'S QUESTION directly in 1-2 short sentences (at most 30 words): what Paytm found or did that
answers it, plus the one next step if paytm_response has one (action_required). {language_rule}
Rules: use ONLY numbers present in the JSON (rupees like ₹4,160). Do not invent advice or facts.
NEVER claim an action (ticket, refund, link, call, check with NPCI) unless paytm_response shows it was done.
Never call a payment or screenshot fake or fraud: say it is not in the merchant's account. When intent is UTR_VERIFY
(and only then) say whether to hand over the goods (received) or hold them (not found / PENDING); for every other
intent never mention goods / saman.
If conversation_so_far is present, the question may be a follow-up: use it to understand what "uska", "woh", "it"
refer to, and do not repeat what you already said there. No business tip (one is added separately), no greetings,
no markdown."""

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
        return f"#{oid} ka {amount} chargeback hold" if oid else f"{amount} chargeback hold"
    label = next((lbl for needle, lbl in _DEDUCTION_LABELS if needle in head), head.replace("_", " ").lower())
    return f"{label} {amount}"


_SUCCESS = {"SUCCESS", "SETTLED", "VERIFIED", "CONFIRMED", "CREDITED", "RECEIVED"}
_PENDING = {"PENDING", "IN_PROGRESS", "PROCESSING", "INITIATED"}
_CAUSE_HI = (("closure", "market band"), ("rain", "baarish"), ("flood", "baadh"), ("holiday", "chhutti"),
             ("bandh", "bandh"), ("strike", "hadtaal"))


def _cause_hi(cause: Any) -> str:
    c = str(cause or "").lower()
    return next((hi for en, hi in _CAUSE_HI if en in c), "")


def template_reply(intent: str, resp: dict[str, Any], gst_entry: Optional[dict[str, Any]],
                   ctx: Optional[dict[str, Any]] = None) -> str:
    """Status-aware Roman Hinglish fallback replies (the resolution part; the tip is added by compose())."""
    d, h, ctx = dl.DATA, dl.DATA.history, ctx or {}
    status = str(resp.get("status") or "").upper()
    data = resp.get("data") or {}
    if is_fraud(resp):
        # "Not in your account", never "fake": the payment may still be on its way, and the merchant has to face
        # this customer. The fraud flag is internal (risk count), not something to accuse anyone with.
        return (
            f"Dhyan dijiye: UTR {_utr(data)} aapke Paytm account mein nahi mila. Jab tak paisa account mein na dikhe, "
            "saman mat dijiye. Maine ise risk alert ke roop mein note kar liya hai."
        )
    if intent == "SETTLEMENT_RECONCILE":
        # PLAN.md golden path: itemise briefly, log ITC, and flag the chargeback hold (#9981) with a next step.
        items = dl.normalise_deductions(data.get("breakdown") or data.get("deductions")) or d.settlement["deductions"]
        parts = [_deduction_phrase(i) for i in items]
        listing = f"{', '.join(parts[:-1])} aur {parts[-1]}" if len(parts) > 1 else "".join(parts)
        itc = f" — {_inr(gst_entry['amount'])} ITC maine log kar diya" if gst_entry else ""
        hold = next((i for i in items if "CHARGEBACK" in _head_of(i) or "HOLD" in _head_of(i)), None)
        cta = (f" Delivery proof bhejiye, {_inr(hold['amount'])} chhudwa dunga."
               if hold and str(hold.get("status", "HELD")).upper() != "RELEASED" else "")
        variance = data.get("variance") or order_sheet()["variance"]
        return f"{_inr(variance)} mein {listing} hai{itc}.{cta}"
    if intent == "UTR_VERIFY":
        utr, amount = _utr(data), _amt(data.get("amount"))
        if status == "NEEDS_INFO":
            return ("Payment check karne ke liye mujhe 12 digit ka UTR number chahiye. UTR bataiye ya payment ka "
                    "screenshot upload kijiye.")
        if status in _PENDING:
            return (f"UTR {utr} ka {amount}payment abhi PENDING hai. Agar fail hua toh T+1 mein customer ko "
                    "auto-reverse ho jayega, isliye confirm hone tak saman rok kar rakhiye.")
        if status in _SUCCESS:
            return (f"Achhi khabar! UTR {utr} ka {amount}payment safal hai aur settle ho chuka hai. Aap befikr hokar "
                    "saman de sakte hain.")
        return f"UTR {utr} ka {amount}payment {status} hai. Paisa confirm hone tak saman mat dijiye."
    if intent == "CHARGEBACK_RESOLVE":
        cb = d.chargeback(dl.digits(data.get("order_id"))) or d.chargeback() or {}
        oid, amount = data.get("order_id") or cb.get("order_id", ""), _amt(data.get("amount") or cb.get("amount"))
        if status == "NO_CHARGEBACK_FOUND":
            return f"Order #{oid} par koi chargeback hold nahi mila. Koi aur order dekhna ho toh number bataiye."
        if status in ("RELEASED", "CHARGEBACK_REVERSED", "RESOLVED", "WON", "SUCCESS"):
            return (f"Proof of Delivery Paytm ko bhej diya, #{oid} ka {amount}hold RELEASED ho gaya hai. "
                    "Paisa T+1 settlement mein aa jayega.")
        if status == "ALERT_RAISED" and ctx.get("pod_ready"):
            return (f"Paytm ne #{oid} par {amount}chargeback alert bheja hai. Shiprocket se signed PoD mil gaya, "
                    "1-tap sign-off kijiye, main dispute bhej dunga.")
        hours = data.get("pod_due_in_hours") or data.get("deadline_hours") or cb.get("pod_due_in_hours") or 48
        return (f"Order #{oid} ka {amount}chargeback ki wajah se hold par hai. {hours} ghante ke andar Proof of "
                "Delivery upload kijiye, main turant Paytm se release karwa dunga.")
    if intent == "REFUND_MANAGE" and status != "ESCALATED":
        if status == "INITIATED":
            return (f"#{data.get('order_id')} ka {_amt(data.get('amount'))}refund shuru kar diya hai, customer ko T+1 "
                    "mein mil jayega.")
        if status == "NEEDS_INFO":
            return "Refund shuru karne ke liye order number aur amount bataiye."
        rf = d.refund(dl.digits(data.get("order_id"))) or d.refund() or {}
        return (
            f"Order #{data.get('order_id') or rf.get('order_id', '')} ka {_amt(data.get('amount') or rf.get('amount'))}"
            f"refund customer ko {status or 'PROCESSED'} ho chuka hai. Yahi amount aapke settlement se kata tha, isme "
            "koi gadbad nahi hai."
        )
    if intent == "FEE_GST_LOAN":
        loan = dl.normalise_loan(data.get("loan")) or d.loan
        gst_pct = data.get("gst_rate_pct") or d.fees["gst_rate_pct"]
        return (
            f"MDR {_inr(data.get('mdr_fee') or d.deduction_amount('MDR'))} par {gst_pct}% GST "
            f"{_inr(data.get('gst_on_mdr') or d.deduction_amount('GST'))} laga, "
            f"poora ITC claim hoga{' — maine log kar diya' if gst_entry else ''}. "
            f"Loan EDI {_inr(loan.get('edi_per_day'))} roz hai, baaki balance {_inr(loan.get('balance'))}."
        )
    if intent == "MANDATE_TROUBLESHOOT" and status != "ESCALATED":
        edi = _inr(data.get("missed_edi") or data.get("edi_amount") or d.loan.get("edi_per_day"))
        m = (ctx.get("insight") or {}).get("metrics") or {}
        cause = _cause_hi(((ctx.get("insight") or {}).get("summary")))
        why = (f"{(cause + ' se sale').capitalize() if cause else 'Sale'} {m.get('sales_dip_pct')}% giri, isliye {edi} EDI "
               "fail hui, default nahi."
               if (ctx.get("insight") or {}).get("classification") == "PAYMENT_FRICTION"
               else f"{edi} EDI ka mandate fail hua tha.")
        if status == "REMINDER_SENT":
            return f"{why} Reminder bhej diya hai, kal phir debit hoga."
        if status == "ALERT_RAISED":
            return f"{why} 1-tap UPI link bhejun? 48 ghante ki grace milegi."
        if status == "REMEDIES_OFFERED":  # live 8002: UPI link to pay today, or a KFS 2-day pause
            pause = any(r.get("offer_id") for r in data.get("remedies") or [])
            return (f"{why} 1-tap UPI link se aaj bhariye, penalty nahi"
                    f"{'; chahein toh 2 din ka KFS pause bhi hai' if pause else ''}.")
        if status == "MANDATE_RESOLVED":
            return f"{why} Paytm ne maamla suljha diya hai, penalty nahi lagegi."
        return f"{why} 1-tap UPI link bheja hai, penalty nahi lagegi."
    if intent == "DUPLICATE_RECONCILE" and status != "ESCALATED":
        if status == "NO_DUPLICATE_FOUND":
            return (f"Order #{data.get('order_id') or ''} par koi duplicate payment nahi mila. UTR bataiye toh dobara "
                    "check kar loon.")
        amt = _inr(data.get("amount"))
        return (f"{data.get('customer') or 'Customer'} ne order #{data.get('order_id')} ke {amt} do baar diye the. "
                f"Duplicate {amt} ka refund shuru kar diya, T+1 mein pahunchega.")
    if intent == "GROWTH_ADVISORY" and status == "ADVICE_READY":  # 8002: advice only, no new credit offered
        day = {"Monday": "Somvaar", "Tuesday": "Mangalvaar", "Wednesday": "Budhvaar", "Thursday": "Guruvaar",
               "Friday": "Shukravaar"}.get(str(data.get("restock_by")), data.get("restock_by") or "Guruvaar")
        loan = data.get("existing_loan") or {}
        loan_line = (f" {loan.get('lender')} loan ka {_inr(loan.get('balance'))} baaki hai, "
                     f"{_inr(loan.get('edi_per_day'))} EDI roz ki sale ka sirf {loan.get('edi_share_of_daily_sales_pct')}% hai."
                     if loan.get("balance") and loan.get("edi_share_of_daily_sales_pct") is not None else "")
        return (f"Roz average {_inr(data.get('daily_avg_sales'))}, Fri–Sun {data.get('weekend_multiplier')}x "
                f"(~{_inr(data.get('weekend_daily_sales'))}/din) — {day} tak stock bhar lijiye.{loan_line}")
    if intent == "GROWTH_ADVISORY":
        offer = data.get("offer") or h.get("growth_offer") or {}
        trend = data.get("six_month_trend_pct")
        grew = f"6 mahine mein sale {trend}% badhi hai. " if isinstance(trend, (int, float)) and trend > 0 else ""
        # No rate is quoted: rate and tenure are the NBFC's to disclose in the KFS (same stance as 8002).
        return (f"{grew}{offer.get('lender') or h.get('active_lender')} ka {_inr(offer.get('amount'))} working capital "
                "pre-approved hai; rate aur tenure KFS mein dekhkar hi lijiye.")
    if intent == "CASHFLOW_EDI_SWITCH":
        gap = ctx.get("cashflow") or {}
        offer = data.get("edi_pause_offer") or {}
        edi = _inr(d.loan.get("edi_per_day"))
        if status == "EDI_PAUSED":
            return (f"{data.get('nbfc') or h.get('active_lender')} ka {edi} EDI {data.get('pause_days')} din pause kar "
                    f"diya, {_inr(data.get('edi_saved_inr'))} bache; kal EDI nahi kategi.")
        if status == "ALERT_RAISED":
            refund = gap.get("refund_request") or {}
            if gap.get("shortfall") and offer.get("eligible"):
                return (f"{_inr(refund.get('amount'))} refund ke baad kal payout {_inr(gap.get('projected_net_payout'))} "
                        f"rahega, stock ke {_inr(gap.get('tomorrow_stock_due'))} chahiye. {offer.get('nbfc')} ka {edi} EDI "
                        f"{offer.get('pause_days')} din rok doon?")
            if STATE.loan_edi_status != "ACTIVE":
                return f"Aapki {edi} EDI pehle se pause hai, kal nahi kategi."
            if not gap.get("shortfall"):
                return (f"Kal ka payout {_inr(gap.get('projected_net_payout'))} stock ke liye kaafi hai, EDI pause ki "
                        "zaroorat nahi.")
            return "Is baar EDI pause ki eligibility nahi hai. Supplier se 2 din ki mohlat maangna behtar rahega."
        return ("Is baar EDI pause nahi ho sakta, KFS ki sharten poori nahi hain. Supplier se 2 din ki mohlat maangna "
                "behtar rahega.")
    if intent == "SOUNDBOX_RETURN" and status != "ESCALATED":
        return (f"Soundbox ki pickup {data.get('pickup_within_hours', 48)} ghante mein hogi, ticket "
                f"{data.get('pickup_ticket')}. {_inr(data.get('rental_per_month'))} ka rental agle cycle se band ho jayega.")
    if intent == "LOAN_CLOSURE_NOC" and status != "ESCALATED":
        return (f"{data.get('lender')} loan ka baaki {_inr(data.get('outstanding'))} hai, foreclosure charge "
                f"{_inr(data.get('foreclosure_charge', 0))}. Payment ke {data.get('noc_eta_days', 7)} din mein NOC mil jayega.")
    if intent == "BANK_KYC_UPDATE" and status != "ESCALATED":
        return ("Naya bank account jodne ka secure link bhej diya hai. Penny-drop verify hote hi "
                f"{data.get('eta_hours', '24-48')} ghante mein settlement naye account mein aayega.")
    if intent == "SETTLEMENT_HOLD_BANK" and status != "ESCALATED":
        if status == "NO_BANK_HOLD":
            last = data.get("last_credit") or {}
            holds = data.get("open_holds") or []
            hold = (f" Sirf #{holds[0]['order_id']} ka {_inr(holds[0].get('amount'))} chargeback hold hai." if holds else "")
            return (f"Aapka {data.get('bank') or 'bank'} account ACTIVE hai, koi bank hold nahi; "
                    f"{_inr(last.get('amount'))} credit ho chuka hai.{hold}")
        return (f"Bank account {data.get('bank_status')} hone se settlement ruka hai. "
                "Account update kijiye, agle cycle mein paisa aa jayega.")
    ticket = (resp.get("escalation_ticket") or {}).get("ticket_id", "")
    hardware = (data.get("device") or data.get("issue_type") == "HARDWARE_SOUNDBOX"
                or ctx.get("issue_type") == "HARDWARE_SOUNDBOX")  # live 8002 doesn't echo the device back
    what = "Soundbox ki kharabi ka maamla" if hardware else "aapka maamla"
    return (
        f"Maine {what} Paytm ki L2 team ko bhej diya hai{f', ticket {ticket}' if ticket else ''}. "
        "2 ghante mein aapko callback aayega."
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
            **({"conversation_so_far": history()} if history() else {}),
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
    system_prompt = REPLY_SYSTEM_PROMPT.format(merchant_name=dl.DATA.merchant["name"], language_rule=LANGUAGE_RULE[lang()])
    # Consent moments (EDI pause offer, dispute sign-off) are never paraphrased: live, the LLM turned
    # "EDI 2 दिन रोक दूँ?" into "Paytm ने EDI pause किया है" before the merchant had said yes.
    awaiting = (ctx or {}).get("awaiting_confirmation")
    reply = None if (awaiting or not REPLY_LLM) else await upstream.llm(system_prompt, user_prompt, response_format="text")
    resolution = template_reply(intent, resp, gst_entry, {**(ctx or {}), "insight": insight})
    tip = None if is_fraud(resp) else insight.get("tip_hi")
    # The tip names the duplicate payer from the merchant's books; if Paytm matched a different order, drop it.
    paid_order = dl.digits((resp.get("data") or {}).get("order_id"))
    if intent == "DUPLICATE_RECONCILE" and paid_order and paid_order != (insight.get("metrics") or {}).get("order_id"):
        tip = None
    template = compose(resolution, tip)
    english = lang() == "en"
    if english:
        tip = None  # the verified tips are Hindi; an English reply carries the answer only
        if awaiting and (en := consent_template_en(intent, resp, ctx or {})):
            return en, "template"
    # The LLM answers the question; the verified tip is appended verbatim. (Live, it once rewrote the Soundbox tip
    # "payment notification चालू रखिए" into "PoD लेकर रखें", so it no longer writes tips.)
    if isinstance(reply, str) and len(reply.split()) > 40:
        # Live: 49-53 word answers to "will there be a penalty?" were thrown away for an even longer template.
        # The answer comes first, so keep the leading sentences that fit.
        reply = _first_sentences(reply, 40) or reply
    if isinstance(reply, str) and len(reply.strip()) > 10 and len(reply.split()) <= 40:
        bad = ungrounded_numbers(reply, " ".join([user_prompt, template, merchant_text or ""]))
        # Live, despite the prompt: "screenshot fake ho sakta hai". A missing UTR is "not in your account", never an
        # accusation the merchant then repeats to a customer whose payment may still be on its way.
        if intent != "UTR_VERIFY":
            # Live: settlement answers gained "Saman abhi hold par rakhiye…" (goods advice belongs to payment checks).
            reply = " ".join(s for s in re.split(r"(?<=[.!?।])\s+", reply.strip()) if not _GOODS.search(s)) or reply
        accuses = _ACCUSES.search(reply)
        if not bad and not accuses and not _DEVANAGARI.search(reply):  # both tabs are Latin script
            return compose(human_dates(reply.strip()), tip, max_words=48), "llm"
        # Live: the LLM said "₹4,160 का UTR" when no amount existed. Money talk must come from the facts.
        log.warning("LLM reply dropped (ungrounded numbers %s / accusation / wrong language)", bad)
    elif REPLY_LLM and not awaiting:
        log.warning("LLM reply unusable (%s): using the template",
                    "no answer / timed out" if not isinstance(reply, str) else f"{len(reply.split())} words")
    if english:  # no Hindi template in English mode: Paytm's own English answer, if it gave one
        if isinstance(resp.get("template_text"), str) and resp["template_text"].strip():
            return resp["template_text"].strip(), "template"
        # Neither the LLM nor Paytm's English text: never answer the English tab in Hinglish.
        status = str(resp.get("status") or "").replace("_", " ").lower()
        return (f"Paytm's answer: {status}. I couldn't word the full reply just now; please ask again in a minute."
                if status else "I couldn't get an answer just now; please ask again in a minute."), "template"
    return template, "template"


_DEVANAGARI = re.compile("[\u0900-\u097F]")
def _first_sentences(text: str, max_words: int) -> str:
    """The leading whole sentences of `text` that fit in max_words ('' if even the first doesn't)."""
    out: list[str] = []
    for s in re.split(r"(?<=[.!?।])\s+", text.strip()):
        if len(" ".join(out + [s]).split()) > max_words:
            break
        out.append(s)
    return " ".join(out)


_GOODS = re.compile(r"\bsaa?man\b|\bgoods\b|hand\s*over", re.I)
_ACCUSES = re.compile(r"\bfake\b|\bfraud\w*|\bnakli\b|\bfarzi\b|\bscam\b", re.I)
_ISO_DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]  # Hinglish uses these too


def human_dates(text: str) -> str:
    """'2026-11-20' -> '20 Nov' (reads and sounds natural in English and Hinglish). Runs after the number check."""
    return _ISO_DATE.sub(lambda m: f"{int(m.group(3))} {_MONTHS[int(m.group(2)) - 1]}", text)


def consent_template_en(intent: str, resp: dict[str, Any], ctx: dict[str, Any]) -> Optional[str]:
    """English wording for the two consent prompts (never paraphrased by the LLM)."""
    d, h = dl.DATA, dl.DATA.history
    data = resp.get("data") or {}
    status = str(resp.get("status") or "").upper()
    if intent == "CHARGEBACK_RESOLVE" and status == "ALERT_RAISED" and ctx.get("pod_ready"):
        cb = d.chargeback() or {}
        oid = data.get("order_id") or cb.get("order_id", "")
        return (f"Paytm flagged a chargeback on order #{oid} for {_inr(data.get('amount') or cb.get('amount'))}. "
                "The signed proof of delivery from Shiprocket is ready: tap yes and I will file the dispute.")
    if intent == "CASHFLOW_EDI_SWITCH" and status == "ALERT_RAISED":
        gap, offer = ctx.get("cashflow") or {}, data.get("edi_pause_offer") or {}
        if gap.get("shortfall") and offer.get("eligible"):
            refund = gap.get("refund_request") or {}
            return (f"After the {_inr(refund.get('amount'))} refund, tomorrow's payout will be "
                    f"{_inr(gap.get('projected_net_payout'))} but your stock bill is {_inr(gap.get('tomorrow_stock_due'))}. "
                    f"Shall I pause the {offer.get('nbfc') or h.get('active_lender')} {_inr(d.loan.get('edi_per_day'))} EDI "
                    f"for {offer.get('pause_days') or 2} days?")
    return None


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
    if intent == "FEE_GST_LOAN":  # 8002 answers one topic (FEE | GST | LOAN) and defaults to FEE without one
        t = (merchant_text or "").lower()
        out["topic"] = ("GST" if re.search(r"gst|itc|tax|टैक्स|जीएसटी", t)
                        else "LOAN" if re.search(r"loan|edi|emi|लोन|ईडीआई|interest|byaj|ब्याज", t) else "FEE")
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
            "language_code": tts_code(),
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
    import triage  # local: triage imports this module
    # Paytm didn't answer and the fallback is on: the mock answer may shape the wording, but nothing may be recorded
    # as if Paytm had acted (no khata entry, EDI status, fraud alert or learned strategy). triage.py tells the merchant.
    unconfirmed = paytm_source == "mock" and triage.enabled()
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
    if is_fraud(resp) and not unconfirmed:
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
    if edi_status and not unconfirmed:
        STATE.loan_edi_status = "ACTIVE" if edi_status.upper() == "ACTIVE" else edi_status
    if not unconfirmed and (entry := khata.record(intent, resp, request_id)) is not None:
        STATE.log("KHATA_UPDATED", ACTOR_MERCHANT, f"Khata: {entry['kind']} {_inr(entry['amount'])} ({entry['reference']})",
                  entry, request_id)

    # 5. Verify the outcome and learn
    outcome = advisor.verify_and_learn(intent, evaluation, resp, paytm_source, request_id) if not unconfirmed else {
        "outcome": "NOT_VERIFIED", "paytm_status": "PAYTM_UNREACHABLE", "learned": False, "intent": intent,
        "verified_by": "nobody: Paytm did not answer", "request_id": request_id, "ts": time.time()}
    STATE.log("OUTCOME_VERIFIED", ACTOR_MERCHANT,
              f"{outcome['outcome']}: {sel['action']} → {outcome['paytm_status']}"
              + (f" (strategy now {outcome['strategy_success_rate']:.0%})" if outcome["learned"] else ""),
              outcome, request_id)

    reply_text, reply_source = await vernacular_reply(
        intent, resp, gst_entry, merchant_text, (doc_extract or {}).get("doc_type"), insight, evaluation, ctx
    )

    result = {
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
        "audio_base64": None,
        "audio_source": "unavailable",
        "language_code": tts_code(),
        "fraud_alert": fraud_alert,
        "gst_itc_logged": gst_entry,
        "local_gst_itc_log": STATE.local_gst_itc_log,
        "proactive": None,
        "a2a_events": STATE.a2a_events,
    }
    return await finish(result, merchant_text, "Hinglish voice reply ready", tts_note=True)


async def finish(result: dict[str, Any], merchant_text: Optional[str], ready: str, tts_note: bool = False
                 ) -> dict[str, Any]:
    """Last step of every answer: rate its severity and run the fallback (triage.py), then make the voice from the
    final wording, so a changed reply never needs a second TTS call."""
    import triage  # local: triage imports this module

    import voice

    await triage.apply(result, merchant_text)
    reply = result["reply_text"]
    # The screen shows the full answer; the voice says only what matters now (voice.py). Shorter is also faster:
    # Sarvam TTS takes 4-8 s for 30-35 words.
    said = voice.for_result(result, lang()) or reply
    result.pop("_answer", None)
    result.pop("_voice", None)
    result["spoken_text"] = said
    audio_b64, tts_source = await upstream.tts(said, tts_code())
    result.update(audio_base64=audio_b64, audio_source=tts_source, language_code=tts_code())
    note = {"live": "", "mock": " (TTS mock audio)"}.get(tts_source, " (text only — TTS unavailable)") if tts_note else ""
    STATE.log("VOICE_REPLY_READY", ACTOR_MERCHANT, ready + note,
              {"reply_text": reply, "spoken_text": said, "spoken_words": len(said.split()),
               "reply_source": result.get("reply_source"), "tts": tts_source, "language_code": tts_code()},
              result.get("request_id"))
    return result


# ----------------------------------------------------------------------------- not understood

CLARIFY_HI = {
    # STT ran but heard nothing usable
    "stt": "Maaf kijiye, aapki awaaz saaf nahi aayi. Phone thoda paas rakhkar phir se boliye, ya sawaal type kijiye.",
    # 8001 has no Sarvam key (mock mode) or is down: be honest instead of answering a canned line
    "voice_off": ("Awaaz pehchanne wali service abhi band hai, isliye main sun nahi paaya. Sawaal type kijiye ya neeche "
                  "ka koi button dabaiye."),
    # off-topic or too vague
    "unclear": ("Maaf kijiye, yeh main theek se samajh nahi paaya. Main settlement, UTR ya payment check, chargeback, "
                "refund, loan EDI, Soundbox aur KYC mein madad karta hoon. Inmein se kya jaanna hai?"),
}


CLARIFY_EN = {
    "stt": "Sorry, I couldn't hear that clearly. Please hold the phone a little closer and say it again, or type it.",
    "voice_off": "Voice recognition is off right now, so I couldn't hear you. Please type your question or tap a button below.",
    "unclear": ("Sorry, I didn't quite get that. I can help with settlements, UTR or payment checks, chargebacks, refunds, "
                "loan EDI, your Soundbox and KYC. What would you like to know?"),
}


CLARIFY_SPOKEN = {
    "hi": {"stt": "Awaaz saaf nahi aayi, phir se boliye ya type kijiye.",
           "voice_off": "Abhi main sun nahi pa raha, sawaal type kijiye.",
           "unclear": "Samajh nahi paaya. Settlement, payment, refund ya loan, kis baare mein poochna hai?"},
    "en": {"stt": "I couldn't hear that clearly. Please say it again or type it.",
           "voice_off": "I can't hear right now. Please type your question.",
           "unclear": "I didn't get that. Is it about a settlement, a payment, a refund or your loan?"},
}


def clarify_text(reason: str) -> str:
    table = CLARIFY_EN if lang() == "en" else CLARIFY_HI
    return table.get(reason, table["unclear"])


async def clarify(*, request_id: str, mid: str, consent_token: str, reason: str, merchant_text: Optional[str],
                  transcript: Optional[str] = None, transcript_source: Optional[str] = None,
                  intent_source: str = "none") -> dict[str, Any]:
    """The buddy didn't understand: say so and ask again. Nothing is sent to Paytm, nothing is logged as an
    outcome, and no strategy is learned (the old code guessed SETTLEMENT_RECONCILE and answered that)."""
    reply = clarify_text(reason)
    examples = [u.get("chip_label") or u["text"] for u in dl.DATA.presets()][:4]
    STATE.log("INTENT_UNCLEAR", ACTOR_MERCHANT,
              {"stt": "Voice not clear: asked the merchant to repeat",
               "voice_off": "Voice recognition is off (Sarvam in mock mode): asked the merchant to type",
               }.get(reason, "Not a question the buddy can act on: asked the merchant to rephrase"),
              {"reason": reason, "merchant_text": merchant_text, "transcript_source": transcript_source}, request_id)
    return await finish({
        "request_id": request_id, "mid": mid, "transcript": transcript, "transcript_source": transcript_source,
        "consent_token": consent_token, "intent": "UNCLEAR", "intent_source": intent_source,
        "slots": Slots().model_dump(), "doc_extract": None,
        "historical_insight": {}, "intervention_evaluation": {}, "verified_outcome": {},
        "pending_action": {"type": "REPHRASE", "reason": reason, "message": reply, "examples": examples},
        "_voice": CLARIFY_SPOKEN[lang()].get(reason, CLARIFY_SPOKEN[lang()]["unclear"]),
        "paytm_response": {"status": "NOT_UNDERSTOOD", "reason": reason}, "paytm_source": "none",
        "paytm_agent_trace": [], "hindi_reply": reply, "reply_text": reply, "reply_source": "template",
        "audio_base64": None, "audio_source": "unavailable", "language_code": tts_code(),
        "fraud_alert": None, "gst_itc_logged": None, "local_gst_itc_log": STATE.local_gst_itc_log,
        "proactive": None, "a2a_events": STATE.a2a_events,
    }, merchant_text, "Clarifying question ready")


# ----------------------------------------------------------------------------- questions about the merchant's books

INFO_SYSTEM_PROMPT = """You are the AI business buddy of {merchant_name}, a small Paytm merchant in India.
Answer the merchant's question using ONLY the facts JSON (their own books; "today" is facts.today).
Give the direct answer first, in 1-2 short sentences (at most 35 words). {language_rule}
If conversation_so_far is present, the question may be a follow-up ("kab tak?", "uska kya hua?"): answer it about the
thing discussed there, using the facts and what was already said in those turns.
Only if neither the facts nor the conversation contain ANY of the answer, say you don't have that information and that you can check settlements,
payments, chargebacks, refunds, the loan EDI or the Soundbox. Use ONLY numbers that appear in the facts
(rupees like ₹22,189; dates like 20 Nov). No greetings, no markdown."""


async def answer_info(*, request_id: str, mid: str, consent_token: str, merchant_text: str,
                      transcript: Optional[str] = None, transcript_source: Optional[str] = None,
                      intent_source: str = "llm") -> dict[str, Any]:
    """Read-only answer from the merchant's own books ("agla settlement kab aayega?"). Nothing goes to Paytm."""
    import facts  # local: facts imports state, which imports this module's siblings

    f = facts.merchant_facts()
    facts_json = json.dumps(f, ensure_ascii=False, default=str)
    reply = await upstream.llm(
        INFO_SYSTEM_PROMPT.format(merchant_name=dl.DATA.merchant["name"], language_rule=LANGUAGE_RULE[lang()]),
        json.dumps({"question": merchant_text, **({"conversation_so_far": history()} if history() else {}), "facts": f},
                   ensure_ascii=False, default=str), response_format="text")
    ok = (isinstance(reply, str) and len(reply.strip()) > 5 and len(reply.split()) <= 55
          and not ungrounded_numbers(reply, facts_json + " " + (merchant_text or "") + " " + _history_json())
          and not _DEVANAGARI.search(reply))
    if not ok:
        log.warning("INFO answer unusable (LLM down, ungrounded numbers or wrong language): asking to rephrase")
        return await clarify(request_id=request_id, mid=mid, consent_token=consent_token, reason="unclear",
                             merchant_text=merchant_text, transcript=transcript, transcript_source=transcript_source,
                             intent_source=intent_source)
    reply = human_dates(reply.strip())
    STATE.log("INFO_ANSWERED", ACTOR_MERCHANT, "Answered from the merchant's own books (read-only, nothing sent to Paytm)",
              {"question": merchant_text, "facts_used": sorted(f)}, request_id)
    return await finish({
        "request_id": request_id, "mid": mid, "transcript": transcript, "transcript_source": transcript_source,
        "consent_token": consent_token, "intent": "INFO_QUERY", "intent_source": intent_source,
        "slots": Slots().model_dump(), "doc_extract": None,
        "historical_insight": {}, "intervention_evaluation": {}, "verified_outcome": {}, "pending_action": None,
        "paytm_response": {"status": "ANSWERED_FROM_BOOKS"}, "paytm_source": "none", "paytm_agent_trace": [],
        "hindi_reply": reply, "reply_text": reply, "reply_source": "llm",
        "audio_base64": None, "audio_source": "unavailable", "language_code": tts_code(),
        "fraud_alert": None, "gst_itc_logged": None, "local_gst_itc_log": STATE.local_gst_itc_log,
        "proactive": None, "a2a_events": STATE.a2a_events,
    }, merchant_text, "Answer ready")
