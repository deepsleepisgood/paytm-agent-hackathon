"""Short-term memory of the conversation, so follow-up questions work.

    Merchant: "Order 9981 ka chargeback wala paisa kab milega?"   -> CHARGEBACK_RESOLVE, order 9981
    Merchant: "Aur uske liye kya bhejna hai?"                     -> still CHARGEBACK_RESOLVE, order 9981

Each answered turn is kept per merchant (MID): the question, the intent, the slots, the reply, and the few facts that
later questions refer to (order ids, UTRs, ticket ids, the payment the buddy found). The last few turns are used:

  1. by the router: the LLM sees the earlier turns and classifies the NEW message; ids it reuses must appear in the
     conversation; a short referential message the LLM can't place ("uska kya hua?") continues the previous intent;
  2. to carry slots: a follow-up on the same intent with no order id / UTR / amount reuses the previous one;
  3. by the reply and info LLMs: they see the conversation, so "woh" and "kab tak" are answered about the right thing,
     and numbers from earlier answers count as grounded.

Memory is in-process, per MID, forgotten after IDLE_S without a question and on /reset. The raw audio is never kept,
and nothing here is sent to Paytm (8002 still gets structured slots only).
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Optional

from schemas import Slots
from state import STATE

MAX_TURNS = 6  # kept
USE_TURNS = 3  # shown to the LLMs
IDLE_S = float(os.getenv("CONVERSATION_IDLE_S", str(15 * 60)))

# Words that point back at something already said ("uska", "woh", "it", "kab tak", "aur").
_FOLLOW_UP = re.compile(
    r"\b(us|uska|uski|uske|usko|iska|iski|iske|isko|woh?|vo|ye|yeh|wahi|aur|phir|fir|toh|tab|kab\s*tak|kitne\s*din|"
    r"kitna\s*time|kyun|kyon|kaise|kya\s*hua|that|those|then|why|how\s*long|what\s*about)\b"
    r"|उस|इस|वो|वह|ये|यह|और|फिर|क्यों|कब\s*तक|कैसे",
    re.I,
)
_NON_BUSINESS = {"UNCLEAR"}


def _turns(mid: str) -> list[dict[str, Any]]:
    turns = STATE.conversations.setdefault(mid, [])
    if turns and time.time() - turns[-1]["ts"] > IDLE_S:
        turns.clear()  # a new visit starts a new conversation
    return turns


def recent(mid: str, n: int = USE_TURNS) -> list[dict[str, Any]]:
    """The last n answered turns, oldest first, without internals (what the LLMs see)."""
    return [{k: v for k, v in t.items() if k not in ("ts", "request_id")} for t in _turns(mid)[-n:]]


def last_business_turn(mid: str) -> Optional[dict[str, Any]]:
    return next((t for t in reversed(_turns(mid)) if t["intent"] not in _NON_BUSINESS), None)


def is_follow_up(text: str) -> bool:
    """A short message that points back at something ("uska kya hua?", "kab tak?", "and the refund?")."""
    t = (text or "").strip()
    return 0 < len(t.split()) <= 10 and bool(_FOLLOW_UP.search(t))


def text_of(mid: str) -> str:
    """Everything said in the remembered turns, for id checks and number grounding."""
    import json

    return json.dumps(recent(mid, MAX_TURNS), ensure_ascii=False, default=str)


def carry_slots(mid: str, intent: str, slots: Slots) -> tuple[Slots, bool]:
    """Fill a follow-up's missing order id / UTR / amount from the previous turn about the same intent."""
    prev = next((t for t in reversed(_turns(mid)) if t["intent"] == intent), None)
    if not prev:
        return slots, False
    have = slots.model_dump()
    fill = {k: v for k, v in (prev.get("slots") or {}).items() if v is not None and have.get(k) is None}
    return (slots.model_copy(update=fill), True) if fill else (slots, False)


def _facts(body: dict[str, Any]) -> dict[str, Any]:
    """The few things a later question can point at."""
    pr = body.get("paytm_response") or {}
    d = pr.get("data") if isinstance(pr.get("data"), dict) else {}
    out: dict[str, Any] = {"status": pr.get("status")}
    for k in ("order_id", "utr", "utr_number", "amount", "amount_inr", "amount_held_inr", "hold_status", "refund_status",
              "pod_due_in_hours", "hours_left", "loan_edi_status", "resume_date"):
        if d.get(k) is not None:
            out[k] = d[k]
    ticket = (pr.get("escalation_ticket") or {}).get("ticket_id")
    if ticket:
        out["ticket_id"] = ticket
    pc = body.get("payment_check") or {}
    if pc.get("findings"):
        out["payments_found"] = [{k: f.get(k) for k in ("kind", "customer", "amount_inr", "utr", "order_id", "at",
                                                        "reverses_by", "ticket_id", "refunded") if f.get(k) is not None}
                                 for f in pc["findings"]]
    if (pa := body.get("pending_action")) and pa.get("type") not in (None, "REPHRASE"):
        out["waiting_for"] = pa.get("type")
    return {k: v for k, v in out.items() if v is not None}


def record(mid: str, question: Optional[str], body: dict[str, Any]) -> dict[str, Any]:
    """Remember one answered turn (call with the response body); returns the body unchanged."""
    if not question or not isinstance(body, dict) or not body.get("reply_text"):
        return body
    turns = _turns(mid)
    turns.append({"ts": time.time(), "request_id": body.get("request_id"), "merchant": question,
                  "intent": body.get("intent"),
                  "slots": {k: v for k, v in (body.get("slots") or {}).items() if v is not None},
                  "buddy": str(body.get("reply_text"))[:320], "facts": _facts(body)})
    del turns[:-MAX_TURNS]
    return body
