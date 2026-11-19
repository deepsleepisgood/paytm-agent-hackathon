"""Offline stand-ins for Sarvam, aligned with the seed data in contract.md and plan.md.

Why this exists:
1. Persons 2-4 can integrate against port 8001 before anyone has a Sarvam key.
2. If Sarvam is slow or down during judging, the demo still runs (SARVAM_FALLBACK_TO_MOCK).
Every mock response is labelled source="mock", so nobody mistakes it for real output.
"""
from __future__ import annotations

import json
import re

from .audio import tone_wav_base64

DEFAULT_TRANSCRIPT = "मेरा कल का settlement ₹4,160 कम आया है, पैसा कहाँ कटा?"

_HINGLISH_MARKERS = {"hai", "hain", "kya", "kyun", "kyon", "mera", "mere", "bhaiya", "wala", "wali", "paisa",
                     "karo", "kab", "nahi", "aaya", "kata", "kam", "mujhe", "ka", "ki", "ke", "se", "ko", "ho", "gaya"}


def stt(mock_transcript: str | None = None) -> dict:
    text = (mock_transcript or DEFAULT_TRANSCRIPT).strip()
    has_devanagari = bool(re.search(r"[ऀ-ॿ]", text))
    # Romanised Hinglish ("payment aaya kya?") is Hindi speech: Saaras labels it hi-IN too.
    words = set(re.findall(r"[a-z]+", text.lower()))
    is_hinglish = len(words & _HINGLISH_MARKERS) >= 2
    return {"transcript": text, "language_code": "hi-IN" if has_devanagari or is_hinglish else "en-IN",
            "language_probability": None}


def tts() -> str:
    return tone_wav_base64()


# Filename hints let the demo pick a scenario: e.g. upload "upi_fake.png" to show fraud detection.
def doc_extract(doc_type: str, filename: str) -> dict:
    name = (filename or "").lower()
    if doc_type == "upi_screenshot":
        if "fake" in name or "tamper" in name:
            return {"utr": "632184920555", "amount": 1250, "payer_app": "GPay", "status": "SUCCESS",
                    "transaction_datetime": "18 Nov 2026, 7:42 pm", "payee_name": "Sharma Electronics"}
        if "pending" in name or "phonepe" in name:
            return {"utr": "632184920999", "amount": 2400, "payer_app": "PhonePe", "status": "PENDING",
                    "transaction_datetime": "18 Nov 2026, 6:15 pm", "payee_name": "Sharma Electronics"}
        return {"utr": "632184920111", "amount": 1250, "payer_app": "GPay", "status": "SUCCESS",
                "transaction_datetime": "18 Nov 2026, 11:03 am", "payee_name": "Sharma Electronics"}
    # pod: same values as the bundled sample app/samples/pod_9981.png
    return {"order_id": "9981", "delivery_status": "Delivered", "awb_or_tracking_id": "DEX7781203345",
            "courier_name": "Demo Express Logistics", "delivery_date": "2026-11-16", "recipient_name": "Rohit Verma",
            "delivery_address": "B-14, Lajpat Nagar, New Delhi 110024", "amount": 800, "signature_present": True}


# ====================================================================== mock LLM
# What callers use /llm for (plan.md):
#   1. JSON  - classify a merchant message into an intent + slots (utr_number, order_id, amount)
#   2. JSON  - evaluate interventions: diagnose root cause, score Option A/B/C, pick one
#   3. text  - turn Paytm's JSON answer into a short, warm Hindi reply (spoken via TTS)
# Offline we can't "understand" text, so: keyword routing + regex slots, and replies written
# from the seed numbers. Good enough to rehearse the whole demo end-to-end.

# Canonical names = plan.md. Older/alternative names used elsewhere in the team docs are aliases.
INTENTS = ("MANDATE_TROUBLESHOOT", "SETTLEMENT_RECONCILE", "CHARGEBACK_RESOLVE", "UTR_VERIFY",
           "DUPLICATE_RECONCILE", "GROWTH_ADVISORY", "CASHFLOW_EDI_SWITCH", "ESCALATE_HUMAN",
           "REFUND_MANAGE", "FEE_GST_LOAN")  # last two: contract.md v1 intents, still used by some code

# If the caller's prompt doesn't allow our canonical name, try these in order.
_ALTERNATIVES = {
    "DUPLICATE_RECONCILE": ["DUPLICATE_PAYMENT_RECONCILE", "REFUND_MANAGE", "SETTLEMENT_RECONCILE"],
    "GROWTH_ADVISORY": ["WORKING_CAPITAL_ADVISORY", "FEE_GST_LOAN"],
    "CASHFLOW_EDI_SWITCH": ["FEE_GST_LOAN"],
    "MANDATE_TROUBLESHOOT": ["FEE_GST_LOAN"],
    "REFUND_MANAGE": ["DUPLICATE_RECONCILE", "DUPLICATE_PAYMENT_RECONCILE", "SETTLEMENT_RECONCILE"],
    "FEE_GST_LOAN": ["SETTLEMENT_RECONCILE"],
}
_ALL_NAMES = set(INTENTS) | {n for alts in _ALTERNATIVES.values() for n in alts}

# Checked in order: the first group with a hit wins (most specific first).
_INTENT_KEYWORDS = [
    ("ESCALATE_HUMAN", ["human", "agent se baat", "manager", "complaint", "insaan", "इंसान", "बात करनी", "बात कराओ",
                        "soundbox kharab", "soundbox band", "soundbox not working", "device kharab", "बंद हो गया",
                        "खराब", "kharab", "replacement", "awaaz nahi"]),
    ("MANDATE_TROUBLESHOOT", ["mandate", "enach", "e-nach", "autopay", "auto pay", "bounce", "bounced",
                              "edi fail", "emi fail", "kisht fail", "किस्त फेल", "मैंडेट"]),
    ("DUPLICATE_RECONCILE", ["duplicate", "do baar", "dobara pay", "twice", "double payment", "दो बार", "डबल"]),
    ("CASHFLOW_EDI_SWITCH", ["edi pause", "edi rok", "kisht rok", "cashflow", "cash flow", "payout kam",
                             "stock ke liye", "stock ka paisa", "supplier", "किस्त रोक", "nakdi"]),
    ("UTR_VERIFY", ["utr", "screenshot", "verify", "fake", "payment aaya", "पेमेंट आया", "स्क्रीनशॉट"]),
    ("CHARGEBACK_RESOLVE", ["chargeback", "charge back", "dispute", "pod", "proof of delivery", "9981", "होल्ड", "hold"]),
    ("GROWTH_ADVISORY", ["business badhane", "business badhana", "grow", "growth", "suggestion", "advice", "salah",
                         "सलाह", "सुझाव", "6 mahine", "pichle", "working capital", "बढ़ाने", "badhaye"]),
    ("REFUND_MANAGE", ["refund", "4412", "wapas", "रिफंड", "वापस"]),
    ("FEE_GST_LOAN", ["gst", "mdr", "fee", "loan", "edi", "emi", "rental", "soundbox", "किराया", "लोन", "किस्त", "kisht"]),
    ("SETTLEMENT_RECONCILE", ["settlement", "kam aaya", "kam", "कम", "कटा", "kata", "deduct", "paisa", "पैसा", "credit"]),
]

_UTR_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")
_ORDER_RE = re.compile(r"(?:order|ऑर्डर|txn\s*id|#)\s*(?:no\.?|number|id)?\s*#?\s*(\d{3,10})(?!\d)", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:rupaye|rupees|rupay|रुपये|रुपए)", re.IGNORECASE)


def _has(text: str, word: str) -> bool:
    # Latin keywords match whole words only ("edi" must not match "credit");
    # Devanagari has no \b semantics in Python's re, so substring match there.
    if word.isascii():
        return re.search(rf"\b{re.escape(word)}\b", text) is not None
    return word in text


def guess_intent(text: str) -> str:
    t = text.lower()
    for intent, words in _INTENT_KEYWORDS:
        if intent == "UTR_VERIFY" and _UTR_RE.search(t):  # a 12-digit number is a UTR question
            return intent
        if any(_has(t, w) for w in words):
            return intent
    return "SETTLEMENT_RECONCILE"


def allowed_intents(system_prompt: str) -> set[str]:
    """Intent names the caller listed in its own prompt (empty = caller didn't say)."""
    return {n for n in _ALL_NAMES if re.search(rf"\b{n}\b", system_prompt or "")}


def resolve_name(intent: str, allowed: set[str]) -> str:
    """Return the caller's name for this intent, so mock output always passes their validation."""
    if not allowed or intent in allowed:
        return intent
    for alt in _ALTERNATIVES.get(intent, []):
        if alt in allowed:
            return alt
    return intent


def extract_slots(text: str) -> dict:
    utr = _UTR_RE.search(text)
    order = _ORDER_RE.search(text)
    amount = _AMOUNT_RE.search(text)
    amount_value = None
    if amount:
        raw = (amount.group(1) or amount.group(2)).replace(",", "")
        try:
            num = float(raw)
            amount_value = int(num) if num.is_integer() else num
        except ValueError:
            pass
    return {
        "utr_number": utr.group(1) if utr else None,
        "order_id": order.group(1) if order and (not utr or order.group(1) != utr.group(1)) else None,
        "amount": amount_value,
    }


# ---------------------------------------------------------------- spoken replies
# Devanagari Hindi with common English words: how Bulbul (hi-IN) pronounces Hinglish best.
# plan.md: <= 35 words, immediate resolution + a historical business tip where it fits.
_REPLIES = {
    "SETTLEMENT_RECONCILE": "आपके ₹1,00,000 के कलेक्शन में से ₹4,160 कटे हैं: MDR ₹1,450, उस पर GST ₹261, "
                            "ऑर्डर 4412 का refund ₹1,500, Soundbox किराया ₹149 और chargeback hold ₹800। "
                            "बाकी ₹95,840 आपके बैंक खाते में आ चुके हैं।",
    "UTR_SUCCESS": "UTR 632184920111 वाला ₹1,250 का GPay पेमेंट सफल है और आपके settlement में जुड़ चुका है। "
                   "आप निश्चिंत होकर सामान दे सकते हैं।",
    "UTR_PENDING": "UTR 632184920999 वाला ₹2,400 का PhonePe पेमेंट अभी pending है। अगर यह कल तक पूरा नहीं हुआ, "
                   "तो पैसा ग्राहक को अपने-आप वापस चला जाएगा, इसलिए सामान देने से पहले पेमेंट पक्का कर लें।",
    "UTR_NOT_FOUND": "इस UTR का कोई पेमेंट Paytm के रिकॉर्ड में नहीं मिला। "
                     "कृपया सामान देने से पहले ग्राहक से दोबारा पेमेंट करवाएँ और Soundbox पर पुष्टि सुनें।",
    "CHARGEBACK_RESOLVE": "ऑर्डर 9981 पर ₹800 का chargeback hold लगा है। "
                          "48 घंटे के अंदर delivery का सबूत यानी POD अपलोड करें, ताकि यह पैसा आपको वापस मिल सके।",
    "CHARGEBACK_SIGNOFF": "ऑर्डर 9981 पर ₹800 का chargeback आया है। मैंने Shiprocket से delivery का सबूत निकाल लिया है, "
                          "ग्राहक ने OTP से सामान लिया था। क्या मैं इसे Paytm को भेज दूँ?",
    "CHARGEBACK_POD_SUBMITTED": "ऑर्डर 9981 का delivery सबूत Paytm को भेज दिया गया है। "
                                "Paytm की टीम इसे जाँचकर ₹800 का hold हटाने का फ़ैसला करेगी, आपको हर अपडेट यहीं मिलेगा।",
    "CHARGEBACK_RELEASED": "बधाई हो! ऑर्डर 9981 का ₹800 का hold हट गया है और यह पैसा आपके अगले settlement में जुड़ जाएगा। "
                           "आगे भी हर delivery का OTP सबूत अपने-आप संभाल कर रखूँगा।",
    "REFUND_MANAGE": "ऑर्डर 4412 का ₹1,500 का refund ग्राहक को भेजा जा चुका है, इसलिए यह रकम आपके settlement से कटी है। "
                     "आपको इसमें कुछ करने की ज़रूरत नहीं है।",
    "FEE_GST_LOAN": "₹1,450 की MDR फीस पर 18% GST यानी ₹261 लगा है, जिसका Input Tax Credit आप GST रिटर्न में ले सकते हैं। "
                    "आपके लोन की ₹500 की रोज़ की किस्त कल के settlement से कटेगी, बाकी लोन ₹42,000 है।",
    "MANDATE_TROUBLESHOOT": "घबराइए मत, आपका ₹500 का EDI mandate बैंक में bounce हुआ है, यह default नहीं है। "
                            "पिछले 6 महीनों में आपकी 96% किस्तें समय पर गई हैं, इसलिए 1-tap UPI link से आज की किस्त भर दीजिए।",
    "DUPLICATE_RECONCILE": "ग्राहक ने एक ही ऑर्डर के लिए दो बार पेमेंट किया था। दूसरा पेमेंट ₹5,000 की सीमा के अंदर है, "
                           "इसलिए उसका refund सीधे ग्राहक को भेज दिया गया है, आपका हिसाब बराबर है।",
    "GROWTH_ADVISORY": "पिछले 6 महीनों में आपकी औसत बिक्री ₹32,000 रोज़ है और शुक्रवार से रविवार 2.3 गुना हो जाती है। "
                       "गुरुवार तक स्टॉक भर लें; ज़रूरत हो तो साफ़ KFS वाला working capital भी मिल सकता है।",
    "CASHFLOW_OFFER": "₹3,500 के refund से कल आपका payout सिर्फ़ ₹1,200 रहेगा, जबकि ₹4,500 का स्टॉक भुगतान बाकी है। "
                      "क्या Clix Capital की ₹500 की किस्त 2 दिन रोक दूँ? इससे ₹1,000 बचेंगे।",
    "EDI_PAUSED": "हो गया! Clix Capital की ₹500 की रोज़ की किस्त 2 दिन के लिए रुक गई है, कल कुछ नहीं कटेगा। "
                  "किस्तें 21 नवंबर से फिर शुरू होंगी, और आपका स्टॉक भुगतान समय पर हो जाएगा।",
    "ESCALATE_HUMAN": "मैंने आपका मामला पूरी जानकारी के साथ Paytm की सपोर्ट टीम को भेज दिया है। "
                      "एक सपोर्ट एजेंट आपसे संपर्क करेगा, आपको दोबारा कुछ समझाना नहीं पड़ेगा।",
}
_REPLIES["CASHFLOW_EDI_SWITCH"] = _REPLIES["CASHFLOW_OFFER"]


def _reply_key(prompt: str) -> str:
    """Pick the reply for a 'rephrase Paytm's answer' prompt: explicit statuses first, then intent names."""
    p = prompt.upper()
    checks = [
        (("EDI_PAUSED", "PAUSED_2_DAYS"), "EDI_PAUSED"),
        (("EDI_PAUSE_OFFER", "CONFIRM_EDI_PAUSE", "HIGH_REFUND_CASHFLOW", "PROJECTED_NET_PAYOUT"), "CASHFLOW_OFFER"),
        (("NOT_FOUND_SUSPECTED_FAKE", "SUSPECTED_FAKE"), "UTR_NOT_FOUND"),
        (("632184920999",), "UTR_PENDING"),
        (("632184920111",), "UTR_SUCCESS"),
        (("\"RELEASED\"", "'RELEASED'", ": RELEASED", "STATUS=RELEASED", "HELD → RELEASED", "HELD -> RELEASED"),
         "CHARGEBACK_RELEASED"),
        (("READY_FOR_SIGNOFF", "CONFIRM_DISPUTE", "CHARGEBACK_INCOMING", "SUBMIT_POD"), "CHARGEBACK_SIGNOFF"),
    ]
    for needles, key in checks:
        if any(n in p for n in needles):
            return key
    named = [i for i in INTENTS if re.search(rf"\b{i}\b", p)]
    intent = named[0] if len(named) == 1 else guess_intent(prompt)
    if intent == "UTR_VERIFY":
        return "UTR_PENDING" if "PENDING" in p else "UTR_SUCCESS"
    if intent == "CHARGEBACK_RESOLVE" and any(k in p for k in ("SIGNATURE_PRESENT", "RECIPIENT_NAME", "POD_SUBMITTED", "DOC_CONTEXT")):
        return "CHARGEBACK_POD_SUBMITTED"
    return intent if intent in _REPLIES else "SETTLEMENT_RECONCILE"


# ---------------------------------------------------------------- intervention evaluation
def _opt(oid: str, action: str, score: float, why: str) -> dict:
    return {"id": oid, "label": f"Option {oid}", "action": action, "score": score, "rationale": why}


_EVALUATIONS = {
    "MANDATE_TROUBLESHOOT": {
        "root_cause": "TEMPORARY_FRICTION",
        "diagnosis": "eNACH mandate bounced after a ~40% rain-related sales dip; 96% past EDI success means "
                     "payment friction, not unwillingness to pay.",
        "evidence": ["past_edi_success_rate: 96%", "daily_avg_sales: ₹32,000", "recent sales dip ~40%", "daily_edi: ₹500"],
        "options": [_opt("A", "Send a payment reminder", 0.35, "Cheap, but ignores the real cause and risks a second bounce"),
                    _opt("B", "Switch to 1-tap UPI link / 48h KFS EDI pause", 0.88, "Fixes the friction, no penalty, KFS-compliant"),
                    _opt("C", "Escalate to collections specialist", 0.30, "Costly and damages trust for a reliable payer")],
        "selected": "B",
    },
    "CASHFLOW_EDI_SWITCH": {
        "root_cause": "CASHFLOW_SHORTFALL",
        "diagnosis": "₹3,500 refund drops tomorrow's payout to ₹1,200, below the ₹4,500 stock payable.",
        "evidence": ["projected_net_payout: ₹1,200", "tomorrow_stock_payable: ₹4,500", "kfs_edi_holiday_eligible: true"],
        "options": [_opt("A", "Do nothing; pay supplier late", 0.20, "Supplier penalty and lost weekend stock"),
                    _opt("B", "Pause Clix Capital EDI for 2 days (KFS clause 4.2)", 0.90, "Frees ₹1,000, allowed by KFS, no penalty"),
                    _opt("C", "Take a short-term credit line", 0.50, "Solves the gap but adds interest cost")],
        "selected": "B",
    },
    "CHARGEBACK_RESOLVE": {
        "root_cause": "DISPUTE_WITH_EVIDENCE_AVAILABLE",
        "diagnosis": "₹800 chargeback on order 9981; consented Shiprocket connector holds an OTP-verified PoD.",
        "evidence": ["order_id: 9981", "amount: ₹800", "pod_source: SHIPROCKET_SYNC", "signature_present: true"],
        "options": [_opt("A", "Accept the chargeback", 0.10, "Merchant loses ₹800 for a delivered order"),
                    _opt("B", "Submit Shiprocket PoD after 1-tap merchant sign-off", 0.93, "Strong evidence, inside 48h deadline"),
                    _opt("C", "Escalate to a human dispute agent", 0.40, "Slower; evidence is already sufficient")],
        "selected": "B",
    },
    "GROWTH_ADVISORY": {
        "root_cause": "GROWTH_OPPORTUNITY",
        "diagnosis": "Sales average ₹32,000/day with a 2.3x Friday–Sunday peak; weekend stock-outs limit revenue.",
        "evidence": ["daily_avg_sales: ₹32,000", "weekend_multiplier: 2.3x", "past_edi_success_rate: 96%"],
        "options": [_opt("A", "No change", 0.20, "Leaves weekend demand unmet"),
                    _opt("B", "Stock up by Thursday + KFS-transparent working capital", 0.84, "Matches cash to the weekend peak"),
                    _opt("C", "Run a discount campaign", 0.45, "Raises volume but cuts margin")],
        "selected": "B",
    },
}


def _evaluation(intent: str) -> dict:
    if intent in _EVALUATIONS:
        return _EVALUATIONS[intent]
    return {
        "root_cause": "INFORMATION_REQUEST" if intent != "ESCALATE_HUMAN" else "NEEDS_HUMAN",
        "diagnosis": "Merchant needs a clear explanation backed by ledger data.",
        "evidence": [],
        "options": [_opt("A", "Explain with itemised ledger data", 0.85, "Resolves it immediately"),
                    _opt("B", "Proactively fix any wrong deduction", 0.60, "Only if Paytm finds an error"),
                    _opt("C", "Escalate to a human agent", 0.90 if intent == "ESCALATE_HUMAN" else 0.30,
                         "Right when the merchant asks for a person or hardware needs replacing")],
        "selected": "C" if intent == "ESCALATE_HUMAN" else "A",
    }


def _is_evaluation_prompt(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ("intervention", "option a", "options", "evaluate", "root cause", "root_cause"))


def llm(user_prompt: str, response_format: str, system_prompt: str = "") -> str:
    allowed = allowed_intents(system_prompt)
    both = f"{system_prompt}\n{user_prompt}"
    if response_format != "json":
        return _REPLIES[_reply_key(user_prompt)]

    intent = guess_intent(user_prompt)
    name = resolve_name(intent, allowed)
    slots = extract_slots(user_prompt)
    out: dict = {"intent": name, **slots, "slots": slots, "confidence": 0.6}
    if _is_evaluation_prompt(both):
        ev = _evaluation(intent)
        chosen = next(o for o in ev["options"] if o["id"] == ev["selected"])
        out.update({
            "root_cause": ev["root_cause"], "diagnosis": ev["diagnosis"], "evidence": ev["evidence"],
            "options": ev["options"], "selected_option": ev["selected"], "selected": ev["selected"],
            "selected_intervention": chosen["action"], "reason": chosen["rationale"],
        })
    reply_key = _reply_key(user_prompt) if intent not in _REPLIES else intent
    out["reply_text"] = _REPLIES.get(reply_key, _REPLIES["SETTLEMENT_RECONCILE"])
    out["mock"] = True
    return json.dumps(out, ensure_ascii=False)
