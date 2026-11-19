"""Intent + slot router for Hindi / Hinglish merchant queries.

Strategy: ask the Sarvam LLM (8001) first; if it is slow, offline, or returns junk,
fall back to deterministic keyword rules. Slots are always extracted by regex too, and
regex wins for exact-format fields (12-digit UTR) because LLMs mangle long digit strings.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

import upstream
from schemas import INTENTS, Classification, Slots

# Ordered: first match wins. Escalation and hard identifiers (UTR) beat generic money words.
_DEVICE = r"(?:sound\s*box|machine|device|speaker|qr|साउंडबॉक्स|मशीन)"
_FAULT = (
    r"(?:kharab|kharaab|band\s*(?:ho|hai|pada)|kaam\s*nahi|nahi\s*chal|chal\s*nahi|bol\s*nahi|"
    r"awaaz\s*nahi|aawaz\s*nahi|not\s*working|broken|dead|toot|खराब|बंद|नहीं\s*चल|आवाज़?\s*नहीं)"
)
_HARDWARE_FAULT = rf"{_DEVICE}.{{0,40}}{_FAULT}|{_FAULT}.{{0,40}}{_DEVICE}"

KEYWORD_RULES: list[tuple[str, list[str]]] = [
    (
        "ESCALATE_HUMAN",
        [
            r"\bhuman\b", r"\binsaan\b", r"\bmanager\b", r"\bexecutive\b", r"customer\s*care",
            r"agent\s*se\s*baat", r"kisi\s*se\s*baat", r"\bcall\s*(karo|back|me)\b", r"\bcomplaint\b",
            r"\bescalat", r"शिकायत", r"इंसान", r"मैनेजर", r"बात\s*करा",
            # PLAN.md: Soundbox *hardware* faults escalate to L2 (the rental fee stays FEE_GST_LOAN)
            _HARDWARE_FAULT,
        ],
    ),
    (
        "UTR_VERIFY",
        [
            r"(?<!\d)\d{12}(?!\d)", r"\butr\b", r"\bscreenshot\b", r"\bfake\b", r"\bnakli\b",
            r"payment\s*(aaya|aayi|hua|hui|mila|check|verify)", r"paisa\s*(aaya|mila)\s*(kya|ki)",
            r"\bverify\b", r"यूटीआर", r"नकली", r"स्क्रीनशॉट",
        ],
    ),
    (
        "CHARGEBACK_RESOLVE",
        [
            r"charge\s*back", r"\bdispute\b", r"\bpod\b", r"proof\s*of\s*delivery", r"\b9981\b",
            r"\bhold\b", r"\bheld\b", r"\brok\b", r"ruk(a|e)\s*hu(a|e)", r"चार्जबैक", r"होल्ड", r"रोक",
        ],
    ),
    (
        "REFUND_MANAGE",
        [r"\brefund", r"\b4412\b", r"\bwapas\b", r"\bwaapas\b", r"\breturn", r"रिफंड", r"वापस"],
    ),
    (
        "FEE_GST_LOAN",
        [
            r"\bgst\b", r"\bitc\b", r"input\s*tax", r"\bmdr\b", r"\bfees?\b", r"\bcommission\b",
            r"\bloan\b", r"\bedi\b", r"\bemi\b", r"\bkist\b", r"soundbox", r"sound\s*box", r"\brental\b",
            r"जीएसटी", r"लोन", r"फीस", r"किस्त", r"साउंडबॉक्स",
        ],
    ),
    (
        "SETTLEMENT_RECONCILE",
        [
            r"settle", r"\bkam\b", r"\bkaat", r"\bkata\b", r"\bkate\b", r"\bkatt", r"\bvariance\b",
            r"\bdifference\b", r"\bfark\b", r"\bfarak\b", r"\bhisab\b", r"\bhisaab\b", r"bank\s*credit",
            r"\b4160\b", r"\b4,160\b", r"सेटलमेंट", r"कम", r"कटे", r"हिसाब", r"फर्क",
        ],
    ),
]

CLASSIFIER_SYSTEM_PROMPT = """You are the intent router for a Paytm merchant's AI teammate.
The merchant (Sharma Electronics, MID PAYTM_MERCH_8821) speaks Hindi, Hinglish or English.
Classify the message into EXACTLY ONE intent:
- SETTLEMENT_RECONCILE: settlement amount lower than expected, bank credit mismatch, "paise kam aaye", deductions overall
- UTR_VERIFY: check whether a UPI payment / UTR / screenshot is genuine or received
- CHARGEBACK_RESOLVE: chargeback, disputed or held transaction, proof of delivery (PoD)
- REFUND_MANAGE: customer refund status or a refund deducted from settlement
- FEE_GST_LOAN: MDR fees, GST / input tax credit (ITC), soundbox rental, merchant loan EDI
- ESCALATE_HUMAN: wants a human, Soundbox/QR hardware fault (not working, no sound), angry complaint, or anything unsupported
(A Soundbox *rental fee* question is FEE_GST_LOAN, not ESCALATE_HUMAN.)
Extract slots when present (else null): utr_number (exactly 12 digits, as a string),
order_id (digits only, as a string), amount (number in rupees), date (YYYY-MM-DD).
Respond with ONLY JSON: {"intent": "...", "slots": {"utr_number": null, "order_id": null, "amount": null, "date": null}}"""


def keyword_intent(text: str) -> str:
    t = text.lower()
    for intent, patterns in KEYWORD_RULES:
        if any(re.search(p, t) for p in patterns):
            return intent
    return "SETTLEMENT_RECONCILE"  # most common merchant pain point; safest default


_UTR_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
_ORDER_RE = re.compile(r"(?:order|ordr|txn|transaction|ऑर्डर)\s*(?:id|no\.?|number|#)?\s*#?\s*(\d{3,10})", re.I)
_HASH_RE = re.compile(r"#\s*(\d{3,10})")
_AMOUNT_RES = [
    re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)", re.I),
    re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:rupaye|rupaiye|rupees?|rs\.?|रुपये|रुपए)", re.I),
]
_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_DMY_RE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\b")


def extract_slots(text: str, today: Optional[date] = None) -> Slots:
    today = today or date.today()
    utr = _UTR_RE.search(text)
    m = _ORDER_RE.search(text) or _HASH_RE.search(text)
    order_id = m.group(1) if m else None
    if order_id is None:
        known = re.search(r"\b(4412|9981)\b", text)
        order_id = known.group(1) if known else None

    amount: Optional[float] = None
    for rx in _AMOUNT_RES:
        am = rx.search(text)
        if am:
            try:
                amount = float(am.group(1).replace(",", ""))
                break
            except ValueError:
                pass

    d: Optional[str] = None
    if (iso := _ISO_DATE_RE.search(text)):
        d = iso.group(0)
    elif (dmy := _DMY_RE.search(text)):
        try:
            d = date(int(dmy.group(3)), int(dmy.group(2)), int(dmy.group(1))).isoformat()
        except ValueError:
            d = None
    elif re.search(r"\b(kal|yesterday)\b|कल", text, re.I):
        d = (today - timedelta(days=1)).isoformat()
    elif re.search(r"\b(aaj|today)\b|आज", text, re.I):
        d = today.isoformat()

    return Slots(utr_number=utr.group(0) if utr else None, order_id=order_id, amount=amount, date=d)


def slots_from_dict(raw: Any) -> Slots:
    if not isinstance(raw, dict):
        return Slots()
    utr = re.sub(r"\D", "", str(raw.get("utr_number") or ""))
    order = re.sub(r"\D", "", str(raw.get("order_id") or ""))
    amount: Optional[float] = None
    try:
        if raw.get("amount") not in (None, ""):
            amount = float(str(raw["amount"]).replace(",", "").replace("₹", ""))
    except ValueError:
        amount = None
    d = raw.get("date")
    d = d if isinstance(d, str) and _ISO_DATE_RE.fullmatch(d) else None
    return Slots(utr_number=utr if len(utr) == 12 else None, order_id=order or None, amount=amount, date=d)


def merge_slots(primary: Slots, secondary: Slots) -> Slots:
    """Fill gaps in `primary` from `secondary`."""
    a, b = primary.model_dump(), secondary.model_dump()
    return Slots(**{k: a[k] if a[k] is not None else b[k] for k in a})


async def classify(text: str) -> Classification:
    regex_slots = extract_slots(text)
    result = await upstream.llm(CLASSIFIER_SYSTEM_PROMPT, text, response_format="json")
    if isinstance(result, dict):
        intent = str(result.get("intent", "")).strip().upper()
        if intent in INTENTS:
            llm_slots = slots_from_dict(result.get("slots"))
            # Regex wins: it is exact for UTRs/order ids; LLM fills what regex missed.
            return Classification(intent=intent, slots=merge_slots(regex_slots, llm_slots), source="llm")
    return Classification(intent=keyword_intent(text), slots=regex_slots, source="keyword_fallback")
