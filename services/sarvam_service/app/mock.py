"""Offline stand-ins for Sarvam, aligned with the seed data in contract.md.

Why this exists:
1. Persons 2-4 can integrate against port 8001 today, before anyone has a Sarvam key.
2. If Sarvam is slow or down during judging, the demo still runs (SARVAM_FALLBACK_TO_MOCK).
Every mock response is labelled source="mock", so nobody mistakes it for real output.
"""
from __future__ import annotations

import json
import re

from .audio import tone_wav_base64

DEFAULT_TRANSCRIPT = "मेरा कल का settlement ₹4,160 कम आया है, पैसा कहाँ कटा?"


_HINGLISH_MARKERS = {"hai", "hain", "kya", "kyun", "kyon", "mera", "mere", "bhaiya", "wala", "wali", "paisa",
                     "karo", "kab", "nahi", "aaya", "kata", "kam", "mujhe", "ka", "ki", "ke", "se", "ko"}


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
    # pod
    return {"order_id": "9981", "awb_or_tracking_id": "DLV7781203345", "courier_name": "Delhivery",
            "delivery_date": "2026-11-16", "recipient_name": "Rohit Verma",
            "delivery_address": "B-14, Lajpat Nagar, New Delhi 110024", "amount": 800, "signature_present": True}


# ---------------------------------------------------------------- mock LLM
# Two jobs Person 3 uses /llm for:
#   1. JSON: classify the merchant's message into an intent + slots (utr_number, order_id, amount)
#   2. text: turn Paytm's JSON answer into a short Hindi reply that gets spoken via TTS
# Offline we can't "understand" text, so: keyword routing + regex slots for (1), and replies
# written from the contract's seed numbers for (2). Good enough to rehearse the whole demo.

INTENTS = ("SETTLEMENT_RECONCILE", "UTR_VERIFY", "CHARGEBACK_RESOLVE", "REFUND_MANAGE", "FEE_GST_LOAN", "ESCALATE_HUMAN")

# Checked in order: the first group with a hit wins (most specific first).
_INTENT_KEYWORDS = [
    ("ESCALATE_HUMAN", ["human", "agent se baat", "manager", "complaint", "insaan", "इंसान", "बात करनी", "बात कराओ"]),
    ("UTR_VERIFY", ["utr", "screenshot", "verify", "fake", "payment aaya", "पेमेंट आया", "स्क्रीनशॉट"]),
    ("CHARGEBACK_RESOLVE", ["chargeback", "charge back", "dispute", "pod", "proof of delivery", "9981", "होल्ड", "hold"]),
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


# Spoken replies, written from the contract's seed data. Devanagari Hindi with common
# English words: this is how Bulbul (hi-IN) pronounces Hinglish most naturally.
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
    "CHARGEBACK_POD_SUBMITTED": "ऑर्डर 9981 का delivery सबूत Paytm को भेज दिया गया है। "
                                "Paytm की टीम इसे जाँचकर ₹800 का hold हटाने का फ़ैसला करेगी, आपको हर अपडेट यहीं मिलेगा।",
    "REFUND_MANAGE": "ऑर्डर 4412 का ₹1,500 का refund ग्राहक को भेजा जा चुका है, इसलिए यह रकम आपके settlement से कटी है। "
                     "आपको इसमें कुछ करने की ज़रूरत नहीं है।",
    "FEE_GST_LOAN": "₹1,450 की MDR फीस पर 18% GST यानी ₹261 लगा है, जिसका Input Tax Credit आप GST रिटर्न में ले सकते हैं। "
                    "आपके लोन की ₹500 की रोज़ की किस्त कल के settlement से कटेगी, बाकी लोन ₹42,000 है।",
    "ESCALATE_HUMAN": "मैंने आपका मामला पूरी जानकारी के साथ Paytm की सपोर्ट टीम को भेज दिया है। "
                      "एक सपोर्ट एजेंट आपसे संपर्क करेगा, आपको दोबारा कुछ समझाना नहीं पड़ेगा।",
}


def _reply_key(prompt: str) -> str:
    """Pick the reply for a 'rephrase Paytm's answer' prompt: explicit statuses first, then intent names."""
    p = prompt.upper()
    if "NOT_FOUND_SUSPECTED_FAKE" in p or "SUSPECTED_FAKE" in p:
        return "UTR_NOT_FOUND"
    if "632184920999" in p:
        return "UTR_PENDING"
    if "632184920111" in p:
        return "UTR_SUCCESS"
    named = [i for i in INTENTS if i in p]
    intent = named[0] if len(named) == 1 else guess_intent(prompt)
    if intent == "UTR_VERIFY":
        return "UTR_PENDING" if "PENDING" in p else "UTR_SUCCESS"
    if intent == "CHARGEBACK_RESOLVE" and any(k in p for k in ("SIGNATURE_PRESENT", "RECIPIENT_NAME", "POD_SUBMITTED", "DOC_CONTEXT")):
        return "CHARGEBACK_POD_SUBMITTED"
    return intent


def llm(user_prompt: str, response_format: str) -> str:
    if response_format == "json":
        slots = extract_slots(user_prompt)
        intent = guess_intent(user_prompt)
        return json.dumps({
            "intent": intent,
            **slots,               # flat: utr_number, order_id, amount
            "slots": slots,        # and nested, whichever shape the caller reads
            "confidence": 0.6,
            "reply_text": _REPLIES[_reply_key(user_prompt)],
            "mock": True,
        }, ensure_ascii=False)
    return _REPLIES[_reply_key(user_prompt)]
