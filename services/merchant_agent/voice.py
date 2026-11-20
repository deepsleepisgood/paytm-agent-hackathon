"""What the buddy SAYS, as opposed to what it SHOWS.

The screen keeps the full answer (every deduction, the business tip, the case number). The voice says only what a
shopkeeper at a busy counter needs to hear right now:

  1. the direct answer (first sentence; a list of amounts is cut to the two biggest) and, if it fits, the next
     sentence, which is usually what was done about it ("refund shuru kar diya")
  2. any question waiting for a yes / no      ("EDI 2 din rok doon?") - never dropped: it is a consent moment
  3. any safety warning                       ("saman mat dijiye", "hold the goods")
  4. anything the merchant must do            ("delivery proof bhejiye")
  5. one short severity line, if a person or a retry is involved ("Specialist 30 minute mein call karenge.")

No business tip, no ITC bookkeeping notes, no case ids, no repeated numbers. Deterministic (no extra LLM call), so it
also makes the voice faster: Sarvam TTS takes 4-8 s for 30-35 words, about half that for 15.
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional

MAX_WORDS = int(os.getenv("VOICE_MAX_WORDS", "24"))   # cap for optional sentences (answer, questions, warnings
                                                      # and things the merchant must do are always said)
FIRST_MAX = int(os.getenv("VOICE_FIRST_MAX", "18"))   # the answer sentence itself

_SENT = re.compile(r"(?<=[.!?।])\s+")
_AMOUNT = re.compile(r"₹\s?\d+(?:,\d+)*(?:\.\d+)?")
# Hinglish imperatives (bhejiye, dijiye, rakhiye, kijiye, kahiye...) and their English counterparts.
_ACTION = re.compile(r"\b\w+(?:iye|ijiye)\b|\b(send|hold|keep|ask|tell|tap|approve|share|upload|don'?t|do not)\b", re.I)
_SAFETY = re.compile(r"\bsaa?man\b.*\b(mat|rok)|hold the goods|don'?t hand over|do not hand over", re.I)
# Bookkeeping asides that belong on screen only.
_ASIDE = re.compile(r"\bITC\b|\blog kar\b|\blogged\b|\bkhata\b|\bTally\b", re.I)
MORE = {"hi": "Baaki details screen par hain.", "en": "The details are on your screen."}
_LONG_REF = re.compile(r"\b(UTR|UMRN|RRN|txn|ref)(\s*(?:no\.?|number|#)?\s*:?\s*)\d{4,}(\d{4})\b", re.I)


# "ticket tkt_002", "(case HND-0001)", "request RTY-0001": ids are for the screen, not the ear.
_IDS = re.compile(r",?\s*\(?\b(?:ticket|case|request)\s+(?:no\.?\s*)?[A-Za-z]+(?:[-_][A-Za-z0-9]+)+\)?", re.I)


def _short_refs(text: str) -> str:
    """'UTR 632184920555' is spoken as 'UTR 0555' (the full number is on screen, the last four identify it), and
    ticket / case ids are left out."""
    text = _LONG_REF.sub(lambda m: f"{m.group(1)} {m.group(3)}", text)
    return re.sub(r"\s+([.,!?])", r"\1", _IDS.sub("", text))


def _words(s: str) -> int:
    return len(s.split())


def _amount(s: str) -> float:
    m = _AMOUNT.search(s)
    return float(re.sub(r"[^\d.]", "", m.group())) if m else 0.0


def compress_amounts(sentence: str, keep: int = 2) -> tuple[str, bool]:
    """'₹4,160 mein MDR ₹1,450, GST ₹261, refund ₹1,500, soundbox ₹149 aur ₹800 hold hai' ->
    '₹4,160 mein MDR ₹1,450, refund ₹1,500' (the total, then the two biggest items in their original order)."""
    if len(_AMOUNT.findall(sentence)) <= keep + 1:
        return sentence, False
    body = re.sub(r"\s+[—–-]\s.*$", "", sentence.strip()).rstrip(" .!।")    # drop an aside after a dash
    parts = [p.strip() for p in re.split(r",\s+|\s+aur\s+|\s+and\s+", body) if p.strip()]
    head = ""
    first = list(_AMOUNT.finditer(parts[0]))
    if len(first) >= 2:   # "₹4,160 mein MDR ₹1,450": the total and its connective word, then the first item
        m = re.match(r"(.*?" + re.escape(first[0].group()) + r"\s*\S*)\s+(.*)$", parts[0])
        if m:
            head, parts[0] = m.group(1), m.group(2)
    items = [p for p in parts if _AMOUNT.search(p)]
    top = sorted(sorted(items, key=_amount, reverse=True)[:keep], key=items.index)
    tail = ", ".join(re.sub(r"\s+(hai|hain|is|are)$", "", t) for t in top)
    return (f"{head} {tail}" if head else tail).strip(), True


def spoken(answer: str, *, lang: str = "hi", tip: Optional[str] = None, voice_line: Optional[str] = None,
           replace: Optional[str] = None, prefix: Optional[str] = None) -> str:
    """The spoken form of one reply.

    answer      the reply as shown on screen, before any severity line was added
    tip         the business tip appended to it (not spoken)
    voice_line  the short spoken severity line from triage.py (e.g. "Specialist 30 minute mein call karenge.")
    replace     triage replaced the whole answer (Paytm down): speak this short form instead
    prefix      a short spoken lead-in from triage.py ("Khate ke hisaab se:")
    """
    if replace:
        return _short_refs(replace)
    text = (answer or "").strip()
    if tip and tip.strip() and tip.strip() in text:
        text = text.replace(tip.strip(), "").strip()
    sents = [s.strip() for s in _SENT.split(text) if s.strip()]
    if not sents:
        return voice_line or ""
    first, cut = compress_amounts(sents[0])
    first = re.sub(r"\s*[—–]\s*[^—–]*\b(ITC|log kar|logged)\b[^.!?।]*", "", first).strip()   # "— ₹261 ITC log kiya"
    if _words(first) > FIRST_MAX:                                       # cut at a clause boundary, never mid-number
        clauses = re.split(r"(?<=[,;:—–])\s+", first)
        kept = []
        for c in clauses:
            if kept and _words(" ".join(kept + [c])) > FIRST_MAX:
                break
            kept.append(c)
        first, cut = " ".join(kept).rstrip(",;:—– "), True
    if first and first[-1] not in ".!?।":
        first += "."
    out = [first]
    for i, s in enumerate(sents[1:], start=1):
        if _ASIDE.search(s) and not s.endswith("?"):
            continue
        # the second sentence is usually what was done about it ("refund shuru kar diya"); keep it if it fits
        if i == 1 or s.endswith("?") or _SAFETY.search(s) or _ACTION.search(s):
            out.append(s)
    if cut:
        out.append(MORE["en" if lang == "en" else "hi"])
    if voice_line:
        out.append(voice_line)
    # Cap: drop optional sentences until it fits. Never dropped: the answer, a question, a warning, something the
    # merchant must do, and the severity line.
    must = {0, len(out) - 1} if voice_line else {0}
    must |= {i for i, s in enumerate(out) if s.endswith("?") or _SAFETY.search(s) or _ACTION.search(s)}
    i = len(out) - 1
    while _words(" ".join(out)) > MAX_WORDS and i > 0:
        if i not in must:
            out.pop(i)
            must = {m - 1 if m > i else m for m in must}
        i -= 1
    said = " ".join(out)
    return _short_refs(f"{prefix} {said}" if prefix else said)


def for_result(result: dict[str, Any], lang: str) -> str:
    """Spoken form of a finished /merchant/* response (see pipeline.finish)."""
    tri = result.get("triage") or {}
    if result.get("_voice"):   # the reply came with its own spoken form (e.g. a clarifying question)
        return _short_refs(" ".join(x for x in (result["_voice"], tri.get("voice_line")) if x))
    return spoken(result.get("_answer") or result.get("reply_text") or "", lang=lang,
                  tip=(result.get("historical_insight") or {}).get("tip_hi"),
                  voice_line=tri.get("voice_line"), replace=tri.get("voice_replace"), prefix=tri.get("voice_prefix"))
