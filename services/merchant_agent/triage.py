"""Severity triage and fallback: every answer is rated LOW, MEDIUM or SEVERE, and that rating decides what
happens when the automated fix cannot finish.

    LOW     information only, no money at risk      -> automated message (answer from the merchant's own books,
                                                       labelled as not confirmed live)
    MEDIUM  money delayed but recoverable           -> automated message ("nothing changed yet"), automatic retry
                                                       as soon as Paytm answers again, then an update in the app.
                                                       Still failing after FALLBACK_MAX_RETRIES -> SEVERE.
    SEVERE  money at risk, fraud, business blocked  -> human in the loop, always: a ticket in Paytm's employee
                                                       console (8002 /tickets) with the full context and a callback
                                                       promise. The buddy follows the ticket and tells the merchant
                                                       when a person picks it up and when it is resolved.

Two things decide whether a fallback is needed at all: did Paytm itself answer (paytm_source == "live"), and was the
question understood. A LOW/MEDIUM case that Paytm handled live gets no fallback; a SEVERE case always gets a human,
even when the automated part worked (a person double-checks fraud, big amounts and blocked settlements).

The rating is never shown as a guess: `triage.reasons` lists every rule that fired, so the console and the
decision trace can show *why* a case is SEVERE.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import re
import time
from typing import Any, Awaitable, Callable, Optional

import pipeline
import upstream
from state import STATE

log = logging.getLogger("merchant_agent.triage")

LOW, MEDIUM, SEVERE = "LOW", "MEDIUM", "SEVERE"
_RANK = {LOW: 0, MEDIUM: 1, SEVERE: 2}
_BY_RANK = {v: k for k, v in _RANK.items()}

# ----------------------------------------------------------------------------- configuration
MEDIUM_INR = int(os.getenv("TRIAGE_MEDIUM_INR", "5000"))      # at least MEDIUM from this amount at risk
SEVERE_INR = int(os.getenv("TRIAGE_SEVERE_INR", "25000"))     # SEVERE from this amount at risk
DEADLINE_HOURS = float(os.getenv("TRIAGE_DEADLINE_HOURS", "24"))  # chargeback evidence due sooner -> SEVERE
RETRY_EVERY_S = float(os.getenv("FALLBACK_RETRY_EVERY_S", "15"))
MAX_RETRIES = int(os.getenv("FALLBACK_MAX_RETRIES", "6"))     # ~90 s of Paytm being down, then a human takes over
SLA_FRAUD_MIN = int(os.getenv("HANDOFF_SLA_FRAUD_MIN", "30"))
SLA_DEFAULT_MIN = int(os.getenv("HANDOFF_SLA_MIN", "120"))


def enabled() -> bool:
    """TRIAGE_FALLBACK=0 turns the fallback policies off (the rating is still computed and returned)."""
    return os.getenv("TRIAGE_FALLBACK", "1").strip().lower() not in ("0", "false", "no", "off")


# ----------------------------------------------------------------------------- the bifurcation
# Base level per problem. Rules below can only raise it (or lower a payment check that found nothing wrong).
BASE: dict[str, tuple[str, str]] = {
    # LOW: information only, nothing moves
    "INFO_QUERY": (LOW, "Question about the merchant's own books"),
    "UNCLEAR": (LOW, "Not understood: the merchant is asked to rephrase"),
    "GROWTH_ADVISORY": (LOW, "Business advice, no money moves"),
    "FEE_GST_LOAN": (LOW, "Explains fees, GST or loan terms"),
    "SETTLEMENT_RECONCILE": (LOW, "Explains deductions on money already credited"),
    "LOAN_CLOSURE_NOC": (LOW, "Loan closure quote and NOC timeline"),
    # MEDIUM: money delayed or an action is needed, but it is recoverable
    "UTR_VERIFY": (MEDIUM, "A customer payment is in question"),
    "DUPLICATE_RECONCILE": (MEDIUM, "Customer charged twice, refund needed"),
    "REFUND_MANAGE": (MEDIUM, "Refund to a customer"),
    "CHARGEBACK_RESOLVE": (MEDIUM, "Money held by a chargeback"),
    "MANDATE_TROUBLESHOOT": (MEDIUM, "Loan EDI bounced"),
    "CASHFLOW_EDI_SWITCH": (MEDIUM, "Cash crunch, EDI change"),
    "SOUNDBOX_RETURN": (MEDIUM, "Device rent still being charged"),
    "BANK_KYC_UPDATE": (MEDIUM, "Settlement bank or KYC change"),
    # SEVERE: business blocked, or a person was asked for
    "SETTLEMENT_HOLD_BANK": (SEVERE, "Settlements are on hold"),
    "ESCALATE_HUMAN": (SEVERE, "The merchant asked for a person, or a device stopped taking payments"),
}
# Amount-at-risk rules only apply where money actually moves (a loan balance is not "at risk").
MONEY_INTENTS = {"UTR_VERIFY", "DUPLICATE_RECONCILE", "REFUND_MANAGE", "CHARGEBACK_RESOLVE", "SETTLEMENT_RECONCILE",
                 "SETTLEMENT_HOLD_BANK"}

# Not "fir": in Hinglish it is usually "again" (fir se). Not "kab tak" / "phir se": ordinary questions.
_FRAUD_WORDS = re.compile(r"\b(fraud\w*|scam\w*|dhokh?a\w*|police|court|legal|cyber\s*cell|chori|thag\w*)\b", re.I)
_DISTRESS_WORDS = re.compile(r"\b(urgent|turant|abhi\s+ke\s+abhi|pareshan|gussa|angry|worst|bekaar|bakwas|"
                             r"third\s+time|teesri\s+baar|bahut\s+der)\b", re.I)
_CLEAN_UTR = {"SUCCESS", "SUCCESS_SETTLED", "RECEIVED", "ALL_CLEAR", "FAILED"}


def _bump(level: str, to: str) -> str:
    return to if _RANK[to] > _RANK[level] else level


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", "").replace("₹", "")) if v not in (None, "") else None
    except ValueError:
        return None


def amount_at_risk(result: dict[str, Any]) -> Optional[int]:
    """The rupees this case puts at risk, from what Paytm said (falling back to what the merchant said)."""
    intent = result.get("intent")
    if intent not in MONEY_INTENTS:
        return None
    pr = result.get("paytm_response") or {}
    d = pr.get("data") or {}
    if intent == "SETTLEMENT_RECONCILE":
        return int(v) if (v := _num(d.get("variance"))) is not None else None
    found: list[float] = []
    for k in ("amount_at_risk", "amount_held_inr", "hold_amount", "amount_held", "held_amount_inr", "refund_amount_inr",
              "amount_inr", "amount", "order_amount_inr"):
        if (v := _num(d.get(k))) is not None:
            found.append(v)
            break
    if isinstance(d.get("refund"), dict) and (v := _num(d["refund"].get("amount_inr"))) is not None:
        found.append(v)
    for f in (result.get("payment_check") or {}).get("findings") or []:
        if f.get("kind") in ("STUCK", "PAID_TWICE") and (v := _num(f.get("amount_inr"))) is not None:
            found.append(v)
    if not found and (v := _num((result.get("slots") or {}).get("amount"))) is not None:
        found.append(v)
    return int(max(found)) if found else None


def _deadline_hours(d: dict[str, Any]) -> Optional[float]:
    for k in ("hours_left", "deadline_hours", "pod_due_in_hours", "evidence_due_in_hours"):
        if (v := _num(d.get(k))) is not None:
            return v
    return None


def rate(result: dict[str, Any], merchant_text: Optional[str]) -> dict[str, Any]:
    """LOW / MEDIUM / SEVERE for one answer, with every rule that fired. Pure: no side effects."""
    intent = str(result.get("intent") or "UNCLEAR")
    level, why = BASE.get(intent, (MEDIUM, "Unlisted problem: treated as medium"))
    reasons = [{"code": f"BASE_{level}", "why": why}]
    pr = result.get("paytm_response") or {}
    d = pr.get("data") or {}
    status = str(pr.get("status") or "").upper()
    mesh = str(pr.get("mesh_status") or pr.get("status") or "").upper()

    def raise_to(to: str, code: str, text: str) -> None:
        nonlocal level
        if _RANK[to] > _RANK[level] or code not in {r["code"] for r in reasons}:
            reasons.append({"code": code, "why": text})
        level = _bump(level, to)

    # A payment check that found the money (or nothing wrong) is not an incident.
    if intent == "UTR_VERIFY" and status in _CLEAN_UTR and not result.get("fraud_alert"):
        level = LOW
        reasons.append({"code": "PAYMENT_OK", "why": "Paytm confirmed the payment status, nothing is at risk"})
    pc = result.get("payment_check") or {}
    if intent == "UTR_VERIFY" and pc.get("amount") is not None and not pc.get("findings"):
        raise_to(MEDIUM, "NOT_FOUND_FOR_AMOUNT", f"No ₹{int(pc['amount']):,} payment found: possibly not paid")
    # Only Paytm's real ledger can say a payment is missing: a mock "not found" is not evidence of fraud.
    if result.get("fraud_alert") or (status == pipeline.FRAUD_STATUS and result.get("paytm_source") == "live"):
        raise_to(SEVERE, "SUSPECTED_FRAUD", "Payment reference not in Paytm's ledger: possible fake payment")
    if "APPROVAL" in status or "APPROVAL" in str(d.get("refund_status") or "").upper():
        raise_to(SEVERE, "NEEDS_APPROVAL", "A refund above the agent's limit needs a person to approve it")
    if pr.get("escalation_ticket") or mesh == "ESCALATED":
        raise_to(SEVERE, "PAYTM_ESCALATED", "Paytm's agents routed this case to a person")
    amt = amount_at_risk(result)
    if amt is not None and amt >= SEVERE_INR:
        raise_to(SEVERE, "HIGH_AMOUNT", f"₹{amt:,} at risk (≥ ₹{SEVERE_INR:,})")
    elif amt is not None and amt >= MEDIUM_INR:
        raise_to(MEDIUM, "AMOUNT", f"₹{amt:,} at risk (≥ ₹{MEDIUM_INR:,})")
    if intent == "CHARGEBACK_RESOLVE" and (h := _deadline_hours(d)) is not None and h < DEADLINE_HOURS \
            and status not in ("RELEASED", "WON"):
        raise_to(SEVERE, "DEADLINE", f"Chargeback evidence due in {h:.0f} h")
    text = merchant_text or ""
    if _FRAUD_WORDS.search(text):
        raise_to(SEVERE, "FRAUD_WORDS", "The merchant mentioned fraud, police or legal action")
    elif _DISTRESS_WORDS.search(text):
        raise_to(_BY_RANK[min(_RANK[level] + 1, 2)], "DISTRESS", "The merchant sounds urgent or upset")
    if intent == "UNCLEAR":
        streak = STATE.unclear_streak
        if streak >= 3:
            raise_to(SEVERE, "NOT_UNDERSTOOD_3X", f"Not understood {streak} times in a row: a person should call")
        elif streak == 2:
            raise_to(MEDIUM, "NOT_UNDERSTOOD_2X", "Not understood twice in a row")
    elif STATE.intent_counts.get(intent, 0) >= 3:
        raise_to(_BY_RANK[min(_RANK[level] + 1, 2)], "REPEATED",
                 f"Same problem raised {STATE.intent_counts[intent]} times this session")
    return {"severity": level, "reasons": reasons, "amount_at_risk": amt}


def automated_ok(result: dict[str, Any]) -> bool:
    """Did the automated path finish? Paytm answered live, or nothing needed Paytm (books / clarification)."""
    src = result.get("paytm_source")
    pc = result.get("payment_check")
    if pc is not None:   # payments.py: the feed itself came from Paytm, and no A2A call fell back to a mock
        return pc.get("feed") == "live" and src != "mock"
    if src == "live":
        return True
    return src == "none" and result.get("intent") in ("INFO_QUERY", "UNCLEAR")


# ----------------------------------------------------------------------------- merchant-facing wording
def _en() -> bool:
    return pipeline.lang() == "en"


def _sla_pair(minutes: int) -> tuple[str, str]:
    """(Hinglish, English) wording of a callback window."""
    if minutes < 60:
        return f"{minutes} minute", f"{minutes} minutes"
    h = minutes // 60
    return f"{h} ghante", f"{h} hour" + ("s" if h > 1 else "")


def _sla_words(minutes: int) -> str:
    hi, en = _sla_pair(minutes)
    return en if _en() else hi


SAFETY = {
    "UTR_VERIFY": ("Tab tak saman mat dijiye.", "Hold the goods until then."),
    "DUPLICATE_RECONCILE": ("Customer se kahiye ki aap refund karwa rahe hain.",
                            "Tell the customer you're arranging the refund."),
    "REFUND_MANAGE": ("Customer se kahiye ki aap refund karwa rahe hain.",
                      "Tell the customer you're arranging the refund."),
    "CHARGEBACK_RESOLVE": ("Delivery ka proof sambhal kar rakhiye.", "Keep the delivery proof safe."),
    "MANDATE_TROUBLESHOOT": ("Tab tak EDI apne schedule par chalega.", "Until then the EDI stays on its schedule."),
    "CASHFLOW_EDI_SWITCH": ("Tab tak EDI apne schedule par chalega.", "Until then the EDI stays on its schedule."),
    "SETTLEMENT_HOLD_BANK": ("Bank details abhi mat badliye.", "Don't change your bank details meanwhile."),
}


def _safety(intent: str) -> str:
    hi, en = SAFETY.get(intent, ("", ""))
    return " " + (en if _en() else hi) if (en if _en() else hi) else ""


def low_text(original: str) -> str:
    return (("I couldn't confirm this live with Paytm, so this is from your own books: " if _en() else
             "Paytm se abhi live confirm nahi ho paya, yeh aapke khate ke hisaab se hai: ") + original)


def medium_text(intent: str, retry_id: str) -> str:
    if _en():
        return ("Paytm isn't responding right now, so I haven't changed anything yet. Your request " + retry_id +
                " is queued: I'll retry automatically as soon as Paytm is back and update you here." + _safety(intent))
    return ("Paytm abhi jawab nahi de raha, isliye maine abhi kuch change nahi kiya. Aapki request " + retry_id +
            " queue mein hai: Paytm wapas aate hi main khud dobara karunga aur yahin bata dunga." + _safety(intent))


def severe_text(intent: str, case_id: str, sla_min: int, automated: bool, original: str) -> str:
    sla = _sla_words(sla_min)
    if automated:   # the automated part worked; a person double-checks it
        add = (f" Because this is serious, a Paytm specialist will also review it (case {case_id}) and call you "
               f"within {sla}." if _en() else
               f" Yeh zaroori maamla hai, isliye Paytm specialist bhi ise dekhenge (case {case_id}) aur {sla} mein "
               "call karenge.")
        return original + add
    if _en():
        return ("This is serious and Paytm isn't responding right now, so I haven't changed anything. I've opened case "
                f"{case_id} for a Paytm specialist, who will call you within {sla}." + _safety(intent))
    return ("Yeh zaroori maamla hai aur Paytm abhi jawab nahi de raha, isliye maine kuch change nahi kiya. Maine Paytm "
            f"specialist ke liye case {case_id} khol diya hai, woh {sla} mein call karenge." + _safety(intent))


# ----------------------------------------------------------------------------- follow-ups (shown in the app)
def followup(kind: str, severity: str, hi: str, en: str, ref: Optional[str] = None) -> dict[str, Any]:
    STATE._followup_seq += 1
    f = {"id": f"FUP-{STATE._followup_seq:04d}", "ts": time.time(), "kind": kind, "severity": severity,
         "ref": ref, "text_hi": hi, "text_en": en}
    STATE.followups.append(f)
    STATE.log("FOLLOWUP_SENT", pipeline.ACTOR_MERCHANT, f"Follow-up to merchant ({kind}): {en}", f, ref)
    return f


# ----------------------------------------------------------------------------- human handoff (SEVERE)
_REASON_CODE = {
    "SUSPECTED_FRAUD": "REPEATED_UNKNOWN_UTR", "NEEDS_APPROVAL": "REFUND_OVER_LIMIT", "DEADLINE": "DEADLINE_URGENT",
    "NOT_UNDERSTOOD_3X": "REPEATED_ISSUE", "REPEATED": "REPEATED_ISSUE", "RETRIES_EXHAUSTED": "OUT_OF_SCOPE",
}


def _reason_code(rating: dict[str, Any], intent: str) -> str:
    if intent == "SETTLEMENT_HOLD_BANK":
        return "COMPLIANCE_HOLD"
    for r in reversed(rating["reasons"]):
        if r["code"] in _REASON_CODE:
            return _REASON_CODE[r["code"]]
    return "MERCHANT_REQUESTED_HUMAN"


def _sla_for(rating: dict[str, Any]) -> int:
    return SLA_FRAUD_MIN if any(r["code"] in ("SUSPECTED_FRAUD", "FRAUD_WORDS") for r in rating["reasons"]) \
        else SLA_DEFAULT_MIN


def open_handoff(result: dict[str, Any], rating: dict[str, Any], merchant_text: Optional[str],
                 tried: list[str]) -> dict[str, Any]:
    """Create the human case. The Paytm ticket is attached now if Paytm already made one, else by sync_handoff."""
    STATE._handoff_seq += 1
    pr = result.get("paytm_response") or {}
    existing = pr.get("escalation_ticket") or {}
    sla = _sla_for(rating)
    h = {
        "id": f"HND-{STATE._handoff_seq:04d}", "request_id": result.get("request_id"), "mid": result.get("mid"),
        "intent": result.get("intent"), "severity": SEVERE, "reasons": rating["reasons"],
        "amount_at_risk": rating.get("amount_at_risk"), "merchant_said": merchant_text,
        "consent_token": result.get("consent_token"), "reason_code": _reason_code(rating, str(result.get("intent"))),
        "tried": tried, "created_at": time.time(), "sla_min": sla, "sla_due": time.time() + sla * 60,
        "paytm_ticket_id": existing.get("ticket_id"), "claimed_by": None, "status": "OPEN", "resolution_note": None,
        "lang": pipeline.lang(),
    }
    STATE.handoffs[h["id"]] = h
    STATE.log("HUMAN_HANDOFF", pipeline.ACTOR_MERCHANT,
              f"SEVERE → human: case {h['id']} ({h['reason_code']}), callback within {sla} min"
              + (f", Paytm ticket {h['paytm_ticket_id']}" if h["paytm_ticket_id"] else ""),
              {k: v for k, v in h.items() if k != "consent_token"}, result.get("request_id"))
    return h


async def paytm_up() -> bool:
    try:
        r = await upstream.client().get(f"{upstream.PAYTM_URL}/health", timeout=1.5)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


async def sync_handoff(h: dict[str, Any]) -> bool:
    """Put the case in Paytm's employee console (8002 ESCALATE_HUMAN -> /tickets). True once it is there."""
    if h.get("paytm_ticket_id"):
        return True
    why = "; ".join(r["why"] for r in h["reasons"] if not r["code"].startswith("BASE_"))
    envelope = {
        "request_id": f"{h['request_id']}-{h['id']}", "mid": h["mid"], "intent": "ESCALATE_HUMAN",
        "payload": {"reason_code": h["reason_code"], "urgency": "URGENT" if h["sla_min"] <= SLA_FRAUD_MIN else "NORMAL",
                    "reason_text": f"[{h['id']} · {h['intent']}] {why or 'Severe case'}"
                                   + (f" · ₹{h['amount_at_risk']:,} at risk" if h.get("amount_at_risk") else ""),
                    "tried": h["tried"]},
        "selected_intervention": {"option_id": "H", "action": "HUMAN_HANDOFF", "score": 1.0},
        "consent_token": h["consent_token"], "session_id": STATE.session_id,
        "language_code": "en-IN" if h.get("lang") == "en" else "hi-IN",
    }
    resp, src = await upstream.dispatch(envelope)
    ticket = (resp or {}).get("escalation_ticket") or {}
    if src == "live" and ticket.get("ticket_id"):
        h["paytm_ticket_id"] = ticket["ticket_id"]
        STATE.log("HANDOFF_SYNCED", pipeline.ACTOR_MERCHANT,
                  f"Case {h['id']} is in Paytm's employee console as ticket {ticket['ticket_id']}",
                  {"handoff": h["id"], "ticket": ticket}, h["request_id"])
        return True
    return False


# ----------------------------------------------------------------------------- MEDIUM retry queue
Replay = Callable[[], Awaitable[dict[str, Any]]]
REPLAYING: contextvars.ContextVar[bool] = contextvars.ContextVar("triage_replaying", default=False)


def queue_retry(result: dict[str, Any], rating: dict[str, Any], merchant_text: Optional[str]) -> dict[str, Any]:
    STATE._retry_seq += 1
    r = {"id": f"RTY-{STATE._retry_seq:04d}", "request_id": result.get("request_id"), "intent": result.get("intent"),
         "severity": rating["severity"], "rating": rating, "merchant_said": merchant_text, "attempts": 0,
         "created_at": time.time(), "status": "PENDING", "lang": pipeline.lang(), "result": result}
    STATE.retry_queue[r["id"]] = r
    STATE.log("AUTO_RETRY_QUEUED", pipeline.ACTOR_MERCHANT,
              f"{rating['severity']}: Paytm unreachable, request queued as {r['id']} for automatic retry",
              {k: v for k, v in r.items() if k not in ("result",)}, result.get("request_id"))
    return r


def attach_replay(result: dict[str, Any], replay: Replay) -> None:
    """main.py hands over how to re-run this request (same endpoint, same inputs) once Paytm is back."""
    rid = (result.get("triage") or {}).get("retry_id")
    if rid and rid in STATE.retry_queue:
        STATE._replays[rid] = replay


async def _retry_one(r: dict[str, Any], up: bool) -> None:
    replay = STATE._replays.get(r["id"])
    if up and replay is not None:
        r["attempts"] += 1
        token = REPLAYING.set(True)
        try:
            pipeline.set_lang(r["lang"])
            new = await replay()
        except Exception as exc:  # noqa: BLE001
            log.warning("retry %s failed: %s", r["id"], exc)
            new = None
        finally:
            REPLAYING.reset(token)
        if new and new.get("paytm_source") == "live":
            r["status"], r["done_at"] = "DONE", time.time()
            STATE._replays.pop(r["id"], None)
            reply_hi = new.get("reply_text") if r["lang"] != "en" else None
            reply_en = new.get("reply_text") if r["lang"] == "en" else None
            followup("AUTO_RETRY_DONE", r["severity"],
                     f"Update ({r['id']}): Paytm wapas online hai. " + (reply_hi or "Aapki request ho gayi."),
                     f"Update ({r['id']}): Paytm is back. " + (reply_en or "Your request went through."), r["request_id"])
            return
    elif not up:
        r["attempts"] += 1
    if r["attempts"] >= MAX_RETRIES:
        r["status"] = "ESCALATED"
        STATE._replays.pop(r["id"], None)
        rating = {**r["rating"], "severity": SEVERE,
                  "reasons": r["rating"]["reasons"] + [{"code": "RETRIES_EXHAUSTED",
                                                        "why": f"Automatic retry failed {r['attempts']} times"}]}
        h = open_handoff(r["result"], rating, r["merchant_said"],
                         [f"Automated fix attempted, Paytm did not answer ({r['attempts']} retries)"])
        r["handoff_id"] = h["id"]
        if up:
            await sync_handoff(h)
        sla_hi, sla_en = _sla_pair(h["sla_min"])
        followup("ESCALATED_TO_HUMAN", SEVERE,
                 f"Request {r['id']} abhi bhi nahi ho payi, isliye maine case {h['id']} Paytm specialist ko de diya "
                 f"hai. Woh {sla_hi} mein call karenge.",
                 f"Request {r['id']} still hasn't gone through, so I've handed case {h['id']} to a Paytm specialist. "
                 f"They will call you within {sla_en}.", r["request_id"])


async def fetch_tickets() -> Optional[dict[str, dict[str, Any]]]:
    """Paytm's employee queue (8002 GET /tickets), by ticket id. None if Paytm can't be reached."""
    try:
        r = await upstream.client().get(f"{upstream.PAYTM_URL}/tickets", timeout=2.0)
        return {t["ticket_id"]: t for t in (r.json() or {}).get("tickets") or []}
    except Exception:  # noqa: BLE001
        return None


async def _watch_tickets() -> None:
    """Follow open human cases in Paytm's console; tell the merchant when someone claims or resolves one."""
    open_ = [h for h in STATE.handoffs.values() if h["status"] != "RESOLVED" and h.get("paytm_ticket_id")]
    if not open_:
        return
    tickets = await fetch_tickets()
    if tickets is None:
        return
    for h in open_:
        t = tickets.get(h["paytm_ticket_id"])
        if not t:
            continue
        if t.get("claimed_by") and not h.get("claimed_by"):
            h["claimed_by"], h["status"] = t["claimed_by"], "CLAIMED"
            followup("HUMAN_CLAIMED", SEVERE,
                     f"Paytm specialist {t['claimed_by']} ne aapka case {h['id']} le liya hai, jaldi call karenge.",
                     f"Paytm specialist {t['claimed_by']} has picked up your case {h['id']} and will call you shortly.",
                     h["request_id"])
        if t.get("status") == "RESOLVED":
            h["status"], h["resolution_note"] = "RESOLVED", t.get("resolution_note")
            note = t.get("resolution_note") or ""
            followup("HUMAN_RESOLVED", SEVERE,
                     f"Case {h['id']} band ho gaya." + (f" Paytm specialist: {note}" if note else ""),
                     f"Case {h['id']} is resolved." + (f" Paytm specialist: {note}" if note else ""), h["request_id"])


async def tick() -> dict[str, int]:
    """One pass of the background worker: retry queued MEDIUM requests, sync and follow human cases."""
    pending = [r for r in STATE.retry_queue.values() if r["status"] == "PENDING"]
    unsynced = [h for h in STATE.handoffs.values() if h["status"] == "OPEN" and not h.get("paytm_ticket_id")]
    up = await paytm_up() if (pending or unsynced or STATE.handoffs) else False
    if up:  # Paytm answers its health check again: stop skipping it (upstream remembers refused hosts for a while)
        upstream._down_until.pop(upstream.PAYTM_URL, None)
    for r in pending:
        await _retry_one(r, up)
    if up:
        for h in unsynced:
            if await sync_handoff(h):
                followup("HANDOFF_SYNCED", SEVERE,
                         f"Aapka case {h['id']} ab Paytm team ke paas hai (ticket {h['paytm_ticket_id']}).",
                         f"Your case {h['id']} is now with the Paytm team (ticket {h['paytm_ticket_id']}).",
                         h["request_id"])
        await _watch_tickets()
    return {"paytm_up": int(up), "retries_pending": sum(r["status"] == "PENDING" for r in STATE.retry_queue.values()),
            "handoffs_open": sum(h["status"] != "RESOLVED" for h in STATE.handoffs.values())}


async def worker_loop() -> None:
    while True:
        await asyncio.sleep(RETRY_EVERY_S)
        try:
            await tick()
        except Exception as exc:  # noqa: BLE001
            log.warning("triage worker: %s", exc)


# ----------------------------------------------------------------------------- the one entry point
async def apply(result: dict[str, Any], merchant_text: Optional[str]) -> dict[str, Any]:
    """Rate the answer and run its fallback. Mutates `result` (reply text, `triage`) before the voice is made."""
    intent = str(result.get("intent") or "UNCLEAR")
    if not REPLAYING.get():
        STATE.unclear_streak = STATE.unclear_streak + 1 if intent == "UNCLEAR" else 0
        if intent != "UNCLEAR":
            STATE.intent_counts[intent] = STATE.intent_counts.get(intent, 0) + 1
    rating = rate(result, merchant_text)
    ok = automated_ok(result)
    sev = rating["severity"]
    tri: dict[str, Any] = {**rating, "automated": ok, "fallback": "NONE", "retry_id": None, "handoff_id": None,
                           "paytm_ticket_id": None, "sla_min": None}
    original = result.get("reply_text") or ""
    reply = original

    if not enabled():
        tri["fallback"] = "DISABLED"
    elif sev == SEVERE:
        tried = ["Automated diagnosis and Paytm A2A request" if ok else "Paytm A2A request: no live answer"]
        h = open_handoff(result, rating, merchant_text, tried)
        if not h["paytm_ticket_id"] and ok:   # Paytm is reachable: put it in the console now
            await sync_handoff(h)
        tri.update(fallback="HUMAN_HANDOFF", handoff_id=h["id"], paytm_ticket_id=h["paytm_ticket_id"],
                   sla_min=h["sla_min"])
        # ESCALATE_HUMAN already tells the merchant a person will call; don't say it twice.
        if not (intent == "ESCALATE_HUMAN" and ok):
            reply = severe_text(intent, h["id"], h["sla_min"], ok, original)
    elif not ok and sev == MEDIUM and not REPLAYING.get():
        r = queue_retry(result, rating, merchant_text)
        tri.update(fallback="AUTO_RETRY", retry_id=r["id"])
        reply = medium_text(intent, r["id"])
    elif not ok and sev == LOW:
        tri["fallback"] = "AUTO_MESSAGE"
        if intent not in ("UNCLEAR", "INFO_QUERY"):
            reply = low_text(original)

    STATE.log("TRIAGE", pipeline.ACTOR_MERCHANT,
              f"Severity {sev} · " + ("handled automatically" if tri["fallback"] == "NONE" else f"fallback {tri['fallback']}"),
              {k: v for k, v in tri.items()}, result.get("request_id"))
    if reply != original:
        result["reply_text"] = result["hindi_reply"] = reply
        result["reply_source"] = "template"
    result["triage"] = tri
    return result


def reset() -> None:
    STATE._replays.clear()
