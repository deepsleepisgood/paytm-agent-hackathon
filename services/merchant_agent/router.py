"""Intent + slot router for Hindi / Hinglish merchant queries.

Order of attempts:
  1. Utterance bank, exact match: the team dataset (intents/utterances.json) labels known
     phrases, including the demo's preset chips. An exact match is answered instantly and
     deterministically (no LLM round-trip). Disable with UTTERANCE_FAST_PATH=0.
  2. Sarvam LLM (8001, JSON mode), with few-shot examples taken from the same utterance bank.
  3. Utterance bank, close match (token overlap), if the LLM is slow, offline or returns junk.
  4. Deterministic keyword rules (Hinglish + Devanagari). Order/txn ids come from the dataset.
Slots are always extracted by regex too, and regex wins for exact-format fields (12-digit UTR)
because LLMs mangle long digit strings.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from typing import Any, Optional

import dataset_loader as dl
import upstream
from schemas import INFO_QUERY, INTENTS, UNCLEAR, Classification, Slots

FAST_PATH = os.getenv("UTTERANCE_FAST_PATH", "1").strip().lower() not in ("0", "false", "no")
FUZZY_MIN = 0.7  # token-set Jaccard needed to trust a near-match from the utterance bank

_DEVICE = r"(?:sound\s*box|machine|device|speaker|qr|साउंडबॉक्स|मशीन)"
_FAULT = (
    r"(?:kharab|kharaab|band\s*(?:ho|hai|pada)|kaam\s*nahi|nahi\s*chal|chal\s*nahi|bol\s*nahi|"
    r"awaaz\s*nahi|aawaz\s*nahi|not\s*working|broken|dead|toot|खराब|बंद|नहीं\s*चल|आवाज़?\s*नहीं)"
)
_HARDWARE_FAULT = rf"{_DEVICE}.{{0,40}}{_FAULT}|{_FAULT}.{{0,40}}{_DEVICE}"

# Ordered: first match wins. Specific service requests and identifiers beat generic money words
# (e.g. "soundbox wapas" is a return, not a refund; "loan settle" is a NOC, not a settlement).
# Dataset ids (chargeback/refund order ids, the variance) are appended at call time: see _rules().
_SOUNDBOX = r"(?:sound\s*box|साउंडबॉक्स|साउंड\s*बॉक्स)"
KEYWORD_RULES: list[tuple[str, list[str]]] = [
    (
        "SOUNDBOX_RETURN",
        [
            rf"{_SOUNDBOX}.{{0,40}}(?:wapas|waapas|vapas|return|lauta|band\s*kar|cancel|surrender|nahi\s*chahiye|"
            # "bill abhi bhi kat raha hai" = still being charged (a return), unlike "rental kitna kata" (a fee question)
            rf"(?:bill|rent\w*|charge|बिल).{{0,25}}(?:kat\s*rah|cut\s*ho\s*rah|कट\s*रह|abhi\s*bhi|ab\s*bhi|still)|वापस|लौटा)",
            rf"(?:wapas|waapas|vapas|return|lauta|वापस).{{0,20}}{_SOUNDBOX}",
        ],
    ),
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
        "LOAN_CLOSURE_NOC",
        [
            r"\bnoc\b", r"no\s*objection", r"foreclos", r"pre\s*-?\s*close", r"एनओसी",
            r"loan.{0,25}(?:settle|close|band\s*kar|khatam|poora|pura|chuka|clear)",
            r"(?:settle|close|khatam|chuka).{0,15}loan", r"लोन.{0,20}(?:बंद|खत्म|चुका|पूरा)",
        ],
    ),
    (
        "MANDATE_TROUBLESHOOT",
        [
            r"mandate", r"e\s*-?\s*nach", r"\bnach\b", r"auto\s*-?\s*debit", r"\bbounce", r"मैंडेट",
            r"(?:edi|emi|kist|kisht|किस्त).{0,30}(?:fail|bounce|miss|nahi\s*kat|chhut|chut|nahi\s*gay|फेल|नहीं\s*कट)",
        ],
    ),
    (
        "CASHFLOW_EDI_SWITCH",
        [
            r"cash\s*-?\s*flow", r"\bsupplier\b", r"\bstock\b.{0,40}(?:paise|paisa|payment|kam|nahi)",
            r"(?:paise|paisa).{0,30}(?:kam\s*pad|nahi\s*bach|short)", r"\bliquidity\b",
            r"(?:edi|emi|kist).{0,25}(?:pause|ruk|rok|holiday|skip|aage|baad\s*me)",
            r"सप्लायर", r"स्टॉक",
        ],
    ),
    (
        "SETTLEMENT_HOLD_BANK",
        [
            r"settlement.{0,25}(?:hold|ruk|rok|band|nahi\s*aa|freeze|atak)",
            r"(?:bank|account|khata).{0,25}(?:inactive|dormant|frozen|freeze|band\s*ho|block)",
            r"सेटलमेंट.{0,20}(?:रुक|रोक|होल्ड|अटक)", r"(?:बैंक|अकाउंट).{0,20}(?:बंद|इनएक्टिव|फ्रीज)",
        ],
    ),
    (
        "BANK_KYC_UPDATE",
        [
            r"\bkyc\b", r"\bifsc\b", r"केवाईसी",
            r"(?:bank|account)\s*(?:account|number|details?)?.{0,25}(?:change|badal|update|naya|new|बदल)",
            r"(?:change|badal|update|naya|new).{0,20}bank\s*account", r"बैंक.{0,20}बदल",
        ],
    ),
    (
        "DUPLICATE_RECONCILE",
        [
            r"do\s*baar", r"\b2\s*baar\b", r"double\s*(?:payment|pay|debit|charge)", r"duplicate", r"twice",
            r"dobara\s*pay", r"दो\s*बार", r"डुप्लिकेट",
        ],
    ),
    (
        "GROWTH_ADVISORY",
        [
            r"business\s*(?:badh|grow|bada)", r"\bgrowth\b", r"\bgrow\b", r"suggestion", r"\bsalah\b", r"\badvice\b",
            r"\b6\s*mahine", r"pichle\s*\w*\s*mahin", r"working\s*capital", r"\btrend\b", r"kaise\s*badh",
            r"बिज़नेस\s*बढ़", r"बिजनेस\s*बढ़", r"सुझाव", r"सलाह",
        ],
    ),
    (
        "UTR_VERIFY",
        [
            r"(?<!\d)\d{12}(?!\d)", r"\butr\b", r"\bscreenshot\b", r"\bfake\b", r"\bnakli\b",
            # No UTR: customer debited but nothing reached the merchant, or the customer's payment screen is stuck
            r"(?:paisa|paise|payment|amount|money|rupay\w*).{0,30}(?:kat\s*gay|kat\s*chuk|cut\s*gay|debit|deduct)",
            r"(?:kat\s*gay|debit\w*).{0,40}(?:nahi\s*aa|nahi\s*mil|not\s*(?:received|come|reach))",
            r"screen.{0,30}(?:ghoom|ghum|rotat|spin|load|atak|atka|stuck|processing|pending|chakkar)",
            r"(?:ghoom|ghum|spinning|loading|processing).{0,25}(?:screen|raha|rahi|rhi|rha)",
            r"payment.{0,20}(?:atak|atka|stuck|pending|processing)",
            r"कट\s*गय", r"स्क्रीन", r"घूम", r"अटक",
            r"payment\s*(aaya|aayi|hua|hui|mila|check|verify)", r"paisa\s*(aaya|mila)\s*(kya|ki)",
            r"\bverify\b", r"यूटीआर", r"नकली", r"स्क्रीनशॉट",
        ],
    ),
    (
        "CHARGEBACK_RESOLVE",
        [
            r"charge\s*back", r"\bdispute\b", r"\bpod\b", r"proof\s*of\s*delivery",
            r"\bhold\b", r"\bheld\b", r"\brok\b", r"ruk(a|e)\s*hu(a|e)", r"चार्जबैक", r"होल्ड", r"रोक",
        ],
    ),
    (
        "REFUND_MANAGE",
        [r"\brefund", r"\bwapas\b", r"\bwaapas\b", r"\breturn", r"रिफंड", r"वापस"],
    ),
    (
        "FEE_GST_LOAN",
        [
            r"\bgst\b", r"\bitc\b", r"input\s*tax", r"\bmdr\b", r"\bfees?\b", r"\bcommission\b",
            r"\bloan\b", r"\bedi\b", r"\bemi\b", r"\bkist\b", r"\bkisht\b", r"soundbox", r"sound\s*box",
            r"\brental\b", r"जीएसटी", r"लोन", r"फीस", r"किस्त", r"साउंडबॉक्स",
        ],
    ),
    (
        "SETTLEMENT_RECONCILE",
        [
            r"settle", r"\bkam\b", r"\bkaat", r"\bkata\b", r"\bkate\b", r"\bkatt", r"\bvariance\b",
            r"\bdifference\b", r"\bfark\b", r"\bfarak\b", r"\bhisab\b", r"\bhisaab\b", r"bank\s*credit",
            r"सेटलमेंट", r"कम", r"कटे", r"हिसाब", r"फर्क",
        ],
    ),
]

CLASSIFIER_SYSTEM_PROMPT = """You are the intent router for a Paytm merchant's AI business buddy.
The merchant ({merchant_name}, MID {mid}) speaks Hindi, Hinglish or English.
Classify the message into EXACTLY ONE intent:
- SETTLEMENT_RECONCILE: settlement amount lower than expected, bank credit mismatch, "paise kam aaye", why money was deducted
- UTR_VERIFY: did a customer's UPI payment arrive / is a UTR or screenshot genuine. ALSO (no UTR needed): the
  customer says money was debited / "kat gaya" but the merchant didn't get it, or the customer's payment screen is
  stuck / loading / spinning ("screen ghoom rahi hai"), or "check karo payment aaya kya"
- CHARGEBACK_RESOLVE: chargeback, disputed or held transaction, proof of delivery (PoD)
- REFUND_MANAGE: customer refund status or a refund deducted from settlement
- FEE_GST_LOAN: why / how much MDR (payment) fees or GST / input tax credit (ITC) were charged, or the loan's
  interest rate / terms
- MANDATE_TROUBLESHOOT: loan EDI / eNACH / auto-debit mandate failed or bounced, missed EDI
- DUPLICATE_RECONCILE: a customer paid twice for the same order, double payment
- GROWTH_ADVISORY: business growth advice, sales trends, past months' data, stocking up, working capital
- CASHFLOW_EDI_SWITCH: not enough money for stock / supplier tomorrow, wants to pause or delay the EDI
- SOUNDBOX_RETURN: wants to return the Soundbox or stop its rental bill that is still being charged
- LOAN_CLOSURE_NOC: wants to close / settle / foreclose the loan, or asks for the NOC
- BANK_KYC_UPDATE: change the settlement bank account, IFSC or KYC details
- SETTLEMENT_HOLD_BANK: settlement held or not arriving because the bank account is inactive / frozen / on hold
- ESCALATE_HUMAN: explicitly wants a human / call / complaint, or a Soundbox/QR hardware fault (not working, no sound)
- INFO_QUERY: any OTHER question about this merchant's own account or business numbers that needs no action:
  WHEN the next settlement comes ("agla settlement kab aayega", "paisa kab aayega"), how much they sold today /
  this week / yesterday, transaction counts, how much of the loan is left, next EDI date, Soundbox rent amount,
  store details
- UNCLEAR: NOT about this merchant's Paytm business (cricket, weather, food orders, jokes, general knowledge),
  OR too vague to act on ("haan", "theek hai", "hello", "kuch gadbad hai" with no detail), OR garbled/incomplete
  speech. Never guess a business intent for these: the buddy will ask the merchant to rephrase.
(A Soundbox *rent amount* question is INFO_QUERY; returning it is SOUNDBOX_RETURN; a faulty one is ESCALATE_HUMAN.
"Loan settle" means LOAN_CLOSURE_NOC, not SETTLEMENT_RECONCILE.)
Extract slots when present (else null): utr_number (exactly 12 digits, as a string),
order_id (digits only, as a string), amount (number in rupees), date (YYYY-MM-DD).
If the message is about money, payments, settlement, loan, Soundbox, KYC or refunds but you are unsure which,
pick the closest intent above (not UNCLEAR).
Respond with ONLY JSON: {{"intent": "...", "slots": {{"utr_number": null, "order_id": null, "amount": null, "date": null}}}}"""


def classifier_prompt(examples_per_intent: int = 2) -> str:
    """System prompt with the dataset merchant and few-shot examples (preset chips first)."""
    d = dl.DATA
    prompt = CLASSIFIER_SYSTEM_PROMPT.format(merchant_name=d.merchant["name"], mid=d.merchant["mid"])
    lines = []
    for intent in INTENTS:
        bank = sorted((u for u in d.routing_utterances() if u["intent"] == intent), key=lambda u: not u.get("preset"))
        lines += [f'"{u["text"]}" -> {intent}' for u in bank[:examples_per_intent]]
    lines += ['"मेरा अगला settlement कब आएगा?" -> INFO_QUERY', '"aaj kitni sale hui?" -> INFO_QUERY',
              '"When will I get my next payout?" -> INFO_QUERY',
              '"customer ka paisa kat gaya par mere paas nahi aaya" -> UTR_VERIFY',
              '"customer ki screen ghoom rahi hai, payment hua ya nahi?" -> UTR_VERIFY',
              '"aaj cricket match kaun jeeta?" -> UNCLEAR', '"haan theek hai" -> UNCLEAR']
    return prompt + ("\nExamples:\n" + "\n".join(lines) if lines else "")


def _id_pattern(value: Any) -> Optional[str]:
    return rf"(?<!\d){re.escape(str(value))}(?!\d)" if value not in (None, "") else None


def _rules() -> list[tuple[str, list[str]]]:
    """KEYWORD_RULES plus dataset ids: chargeback order/txn ids, refund order ids, the variance."""
    d = dl.DATA
    extra: dict[str, list[str]] = {
        "CHARGEBACK_RESOLVE": [_id_pattern(c.get(k)) for c in d.chargebacks.values() for k in ("order_id", "txn_id")],
        "REFUND_MANAGE": [_id_pattern(oid) for oid in d.refunds],
        "SETTLEMENT_RECONCILE": [],
    }
    variance = dl.num(d.settlement.get("variance"))
    if variance:
        extra["SETTLEMENT_RECONCILE"] += [_id_pattern(int(variance)), _id_pattern(dl._inr_commas(variance))]
    return [(intent, patterns + [p for p in extra.get(intent, []) if p]) for intent, patterns in KEYWORD_RULES]


def keyword_intent(text: str) -> Optional[str]:
    """First keyword rule that matches, else None. (It used to default to SETTLEMENT_RECONCILE, so any question
    the buddy didn't understand, even "cricket match kaun jeeta", got a settlement answer.)"""
    t = spoken_digits(text).lower()
    for intent, patterns in _rules():
        if any(re.search(p, t) for p in patterns):
            return intent
    return None


def is_hardware_fault(text: str) -> bool:
    return re.search(_HARDWARE_FAULT, text.lower()) is not None


# ----------------------------------------------------------------------------- utterance bank


def _norm_text(text: str) -> str:
    # Devanagari vowel signs aren't \w in Python's re, so the block is listed explicitly.
    t = text.lower().replace(",", "")
    t = re.sub(r"[^\wऀ-ॿ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def utterance_match(text: str) -> tuple[Optional[str], float]:
    """(intent, score) of the closest dataset utterance; score 1.0 means an exact (normalised) match."""
    n = _norm_text(text)
    if not n:
        return None, 0.0
    tokens = set(n.split())
    best: tuple[Optional[str], float] = (None, 0.0)
    for u in dl.DATA.routing_utterances():
        un = _norm_text(u["text"])
        if un == n:
            return u["intent"], 1.0
        ut = set(un.split())
        score = len(tokens & ut) / len(tokens | ut) if ut else 0.0
        if score > best[1]:
            best = (u["intent"], score)
    return best


# ----------------------------------------------------------------------------- slots

_UTR_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
_ORDER_RE = re.compile(r"(?:order|ordr|txn|transaction|ऑर्डर)\s*(?:id|no\.?|number|#)?\s*#?\s*(\d{3,10})", re.I)
_HASH_RE = re.compile(r"#\s*(\d{3,10})")
_AMOUNT_RES = [
    re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)", re.I),
    re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:rupaye|rupaiye|rupees?|rs\.?|रुपये|रुपए)", re.I),
]
_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_DMY_RE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\b")


# Sarvam STT writes spoken numbers as words ("छह तीन दो …"). Only runs of 4+ digit tokens are joined, so
# everyday words like "do baar" (twice) are left alone.
_DIGIT_WORDS = {
    "0": ("शून्य", "शुन्य", "ज़ीरो", "जीरो", "zero", "shunya", "shoonya"),
    "1": ("एक", "ek", "one"), "2": ("दो", "do", "two"), "3": ("तीन", "teen", "three"),
    "4": ("चार", "char", "chaar", "four"), "5": ("पांच", "पाँच", "paanch", "panch", "five"),
    "6": ("छह", "छः", "छे", "छै", "chhe", "chhah", "che", "six"), "7": ("सात", "saat", "seven"),
    "8": ("आठ", "aath", "eight"), "9": ("नौ", "nau", "nine"),
}
_WORD_TO_DIGIT = {w: d for d, ws in _DIGIT_WORDS.items() for w in ws}
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_TOKEN_RE = re.compile(r"[^\s,।.?!-]+|[\s,।.?!-]+")


def spoken_digits(text: str) -> str:
    """'UTR छह तीन दो एक …' -> 'UTR 6321…'. Devanagari digits become ASCII. A run of 4+ single digits / digit
    words is joined; shorter runs and multi-digit numbers ("₹1,180") are left exactly as written."""
    out: list[str] = []
    digits: list[str] = []
    raw: list[str] = []
    last = 0

    def flush() -> None:
        nonlocal last
        if len(digits) >= 4:
            out.append("".join(digits))
            out.extend(raw[last:])  # separators after the last digit
        else:
            out.extend(raw)
        digits.clear()
        raw.clear()
        last = 0

    for t in _TOKEN_RE.findall(text.translate(_DEVANAGARI_DIGITS)):
        d = _WORD_TO_DIGIT.get(t.lower()) or (t if len(t) == 1 and t.isdigit() else None)
        if d is not None:
            digits.append(d)
            raw.append(t)
            last = len(raw)
        elif digits and (t.isspace() or t.strip() in {",", "-"}):
            raw.append(t)
        else:
            flush()
            out.append(t)
    flush()
    return "".join(out)


def _seen_digits(value: Optional[str], text: str) -> bool:
    """True when an id the LLM returned is literally in what the merchant said (after spoken-digit normalising)."""
    return bool(value) and value in re.sub(r"[\s,-]", "", spoken_digits(text))


def extract_slots(text: str, today: Optional[date] = None) -> Slots:
    today = today or date.today()
    text = spoken_digits(text)
    utr = _UTR_RE.search(text)
    m = _ORDER_RE.search(text) or _HASH_RE.search(text)
    order_id = m.group(1) if m else None
    if order_id is None:  # a bare known id from the dataset, e.g. "9981 ka kya hua"
        ids = sorted(dl.DATA.order_ids(), key=len, reverse=True)
        known = re.search(rf"(?<!\d)({'|'.join(map(re.escape, ids))})(?!\d)", text) if ids else None
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
    """Slots from LLM JSON or /doc-extract fields. Accepts Person 1's names too (`utr`, not `utr_number`)."""
    if not isinstance(raw, dict):
        return Slots()
    utr = re.sub(r"\D", "", str(dl.pick(raw, "utr_number", "utr", "utr_no", "upi_ref", "upi_ref_no", "rrn") or ""))
    order = re.sub(r"\D", "", str(dl.pick(raw, "order_id", "order_no", "order_number", "order") or ""))
    amount = dl.num(dl.pick(raw, "amount", "amount_paid"))
    d = raw.get("date")
    d = d if isinstance(d, str) and _ISO_DATE_RE.fullmatch(d) else None
    return Slots(utr_number=utr if len(utr) == 12 else None, order_id=order or None,
                 amount=float(amount) if amount is not None else None, date=d)


def merge_slots(primary: Slots, secondary: Slots) -> Slots:
    """Fill gaps in `primary` from `secondary`."""
    a, b = primary.model_dump(), secondary.model_dump()
    return Slots(**{k: a[k] if a[k] is not None else b[k] for k in a})


FOLLOW_UP_RULE = """
FOLLOW-UPS: the input may be JSON with "conversation_so_far" (earlier turns: what the merchant asked, the intent,
the slots and what you answered) and "new_message". Classify ONLY new_message, but use the earlier turns to resolve
what it refers to ("uska", "woh", "kab tak?", "aur refund?", "why?"): a follow-up about the same case keeps that
intent, and reuses its order_id / utr_number / amount. A question answered by what you already said (e.g. "kab tak
aayega?" after you gave the date) is INFO_QUERY. A follow-up is never UNCLEAR just because it is short."""


def _continue(history: Optional[list[dict[str, Any]]], text: str, slots: Slots) -> Optional[Classification]:
    """A short message pointing back ("uska kya hua?") that nothing else placed: continue the last business turn."""
    import conversation

    prev = next((t for t in reversed(history or []) if t.get("intent") not in (UNCLEAR, None)), None)
    if not prev or not conversation.is_follow_up(text):
        return None
    return Classification(intent=prev["intent"], slots=slots, source="context")


async def classify(text: str, history: Optional[list[dict[str, Any]]] = None) -> Classification:
    """history: the last few turns (conversation.recent), so follow-up questions keep their context."""
    regex_slots = extract_slots(text)
    bank_intent, bank_score = utterance_match(text)
    if FAST_PATH and bank_intent and bank_score >= 1.0:
        return Classification(intent=bank_intent, slots=regex_slots, source="utterance_bank")

    import conversation

    # Ids the LLM returns must be in what the merchant said. For a follow-up ("uska status?") the earlier turns count
    # too; a fresh question must not pick up an old UTR (live: "money debited but I didn't get it" re-checked the
    # previous question's UTR instead of finding the stuck payment).
    follow_up = bool(history) and conversation.is_follow_up(text)
    seen = text + " " + (json.dumps(history, ensure_ascii=False, default=str) if follow_up else "")
    prompt, user = classifier_prompt(), text
    if history:
        prompt += FOLLOW_UP_RULE
        user = json.dumps({"conversation_so_far": [{k: t.get(k) for k in ("merchant", "intent", "slots", "buddy")}
                                                   for t in history], "new_message": text},
                          ensure_ascii=False, default=str)
    result = await upstream.llm(prompt, user, response_format="json")
    if isinstance(result, dict):
        intent = str(result.get("intent", "")).strip().upper()
        if intent in (UNCLEAR, "OUT_OF_SCOPE", "UNKNOWN", "NONE"):
            # The LLM says this isn't an actionable business question. A preset/near-exact match still wins.
            if bank_intent and bank_score >= FUZZY_MIN:
                return Classification(intent=bank_intent, slots=regex_slots, source="utterance_bank")
            return _continue(history, text, regex_slots) or Classification(intent=UNCLEAR, slots=regex_slots,
                                                                           source="llm")
        if intent == INFO_QUERY:
            return Classification(intent=INFO_QUERY, slots=regex_slots, source="llm")
        if intent in INTENTS:
            raw_slots = result.get("slots") if isinstance(result.get("slots"), dict) else result  # nested or flat
            llm_slots = slots_from_dict(raw_slots)
            # The LLM can invent a digit (live: 11 spoken digits came back as a 12-digit UTR, which then
            # looked fake). Keep its UTR / order id only if those digits are really in the merchant's words.
            llm_slots = llm_slots.model_copy(update={
                "utr_number": llm_slots.utr_number if _seen_digits(llm_slots.utr_number, seen) else None,
                "order_id": llm_slots.order_id if _seen_digits(llm_slots.order_id, seen) else None,
            })
            # Regex wins: it is exact for UTRs/order ids; LLM fills what regex missed.
            return Classification(intent=intent, slots=merge_slots(regex_slots, llm_slots), source="llm")

    if bank_intent and bank_score >= FUZZY_MIN:
        return Classification(intent=bank_intent, slots=regex_slots, source="utterance_bank")
    # No LLM: keywords only. No match means we don't know (unless it continues the last question), so ask.
    kw = keyword_intent(text)
    if kw:
        return Classification(intent=kw, slots=regex_slots, source="keyword_fallback")
    return _continue(history, text, regex_slots) or Classification(intent=UNCLEAR, slots=regex_slots,
                                                                   source="keyword_fallback")
