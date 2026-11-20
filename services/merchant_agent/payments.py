"""Payment check: the merchant never has to read out a UTR.

Two things happen at a shop counter every day:

  "Customer ka paisa kat gaya par mere paas nahi aaya"   - the customer was debited, the merchant sees nothing.
  "Customer ki screen ghoom rahi hai"                     - the customer's app is stuck, so they pay again.

The buddy finds the payment itself in Paytm's transaction feed (8002 GET /ledger/{mid}), asks Paytm's agent for its
real status over A2A, and acts:

  stuck (PENDING)      -> verify with Paytm, raise a Paytm ticket so someone chases it, watch it until it lands
  paid twice           -> Paytm refunds the second payment to the customer (DUPLICATE_RECONCILE, real ledger change)
  received             -> verify with Paytm, tell the merchant to hand over the goods and the customer not to pay again
  failed               -> nothing was taken from the customer, ask them to pay again

Every action goes to 8002 and its answer is reported as given. If Paytm cannot be reached nothing is claimed.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import facts
import pipeline
import upstream
from schemas import Slots
from state import STATE

log = logging.getLogger("merchant_agent.payments")

RECENT_HOURS = 24  # "recent" = the last day of the merchant's payment feed

_SPIN = re.compile(r"screen|ghoom|ghum|rotat|spin|loading|load\s*ho|atak|atka|stuck|processing|chakkar|स्क्रीन|घूम|अटक|लोड",
                   re.I)
_DEBIT = re.compile(r"kat\s*gay|kat\s*chuk|cut\s*gay|debit|deduct|nikal\s*gay|कट\s*गय|डेबिट|निकल\s*गय", re.I)
# Only an amount said as money ("₹2,400", "2400 rupaye"): a bare number may be an order id.
_AMOUNT = re.compile(r"(?:₹|\brs\.?|\binr)\s*([\d,]+)|(\d[\d,]*)\s*(?:rs\b|rupees?|rupay\w*|रुपये|रुपए|रु\b)", re.I)


# ----------------------------------------------------------------------------- the payment feed

def _seed_feed() -> list[dict[str, Any]]:
    """data/seed/utr_ledger.csv, in 8002's shape. Used for names (8002 has none) and when 8002 is down."""
    status = {"SUCCESS": "SUCCESS_SETTLED"}
    return [{"utr": r["utr"], "amount_inr": int(float(r["amount"])), "payer_app": r["payer_app"],
             "lookup_status": status.get(r["npci_status"], r["npci_status"]), "order_id": r.get("order_id") or None,
             "received_at": r["timestamp"], "refunded": False, "customer_id": r.get("customer_id"),
             "flag": r.get("flag") or None}
            for r in facts._rows("utr_ledger.csv")]


def _names() -> dict[str, str]:
    return {r["customer_id"]: r["name"] for r in facts._rows("customers.csv")}


def _ts(t: dict[str, Any]) -> datetime:
    try:
        return datetime.fromisoformat(str(t.get("received_at"))[:19])
    except ValueError:
        return datetime.min


async def feed(mid: str) -> tuple[list[dict[str, Any]], str]:
    """(recent payments, newest first; "live" if read from Paytm's own ledger, else "seed")."""
    seed = {t["utr"]: t for t in _seed_feed()}
    led = await upstream.paytm_ledger(mid)
    txns, source = (led.get("transactions"), "live") if isinstance(led, dict) and led.get("transactions") else (
        list(seed.values()), "seed")
    names = _names()
    out = []
    for t in txns:
        s = seed.get(t.get("utr"), {})
        cid = s.get("customer_id")
        name = names.get(cid) if cid and cid != "WALKIN" else None
        out.append({**t, "customer": name.split()[0] if name else None, "flag": s.get("flag")})
    out.sort(key=_ts, reverse=True)
    if out:
        cutoff = _ts(out[0]) - timedelta(hours=RECENT_HOURS)
        out = [t for t in out if _ts(t) >= cutoff]
    return out, source


def duplicates(txns: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Orders with two or more settled payments (oldest first) that Paytm has not refunded yet."""
    by_order: dict[str, list[dict[str, Any]]] = {}
    for t in txns:
        if t.get("order_id") and t.get("lookup_status") == "SUCCESS_SETTLED":
            by_order.setdefault(str(t["order_id"]), []).append(t)
    pairs = [sorted(v, key=_ts) for v in by_order.values() if len(v) > 1]
    return [p for p in pairs if not any(x.get("refunded") for x in p[1:])]


def spoken_amount(text: str, slots: Optional[Slots]) -> Optional[int]:
    if slots and slots.amount:
        return int(slots.amount)
    m = _AMOUNT.search(text or "")
    if m:
        try:
            return int((m.group(1) or m.group(2)).replace(",", ""))
        except ValueError:
            return None
    return None


def situation(text: str) -> str:
    t = text or ""
    return "spinning" if _SPIN.search(t) else "debited" if _DEBIT.search(t) else "check"


# ----------------------------------------------------------------------------- A2A actions (all real 8002 calls)

async def _a2a(request_id: str, n: int, mid: str, consent_token: str, intent: str, payload: dict[str, Any],
               action: str) -> tuple[dict[str, Any], str]:
    envelope = {"request_id": f"{request_id}-{n}", "mid": mid, "intent": intent, "payload": payload,
                "selected_intervention": {"option_id": "A", "action": action, "score": 1.0},
                "consent_token": consent_token, "session_id": STATE.session_id, "language_code": pipeline.tts_code()}
    STATE.log("MERCHANT_TO_PAYTM", pipeline.ACTOR_MERCHANT, f"A2A request → Paytm: {intent} / {action}", envelope,
              request_id)
    resp, src = await upstream.dispatch(envelope)
    STATE.log("PAYTM_TO_MERCHANT", pipeline.ACTOR_PAYTM,
              f"A2A response ← Paytm: {resp.get('status')}" + (" [mock]" if src == "mock" else ""),
              {**resp, "_source": src}, request_id)
    return resp, src


def _when(t: dict[str, Any]) -> str:
    d = _ts(t)
    if d == datetime.min:
        return ""
    hour = d.strftime("%I:%M %p").lstrip("0")
    return f"{d.day} {d.strftime('%b')}, {hour}"


def _who(t: dict[str, Any]) -> str:
    return t.get("customer") or ""


# ----------------------------------------------------------------------------- the check

async def check(*, request_id: str, mid: str, consent_token: str, merchant_text: str, slots: Optional[Slots],
                intent_source: str, transcript: Optional[str] = None,
                transcript_source: Optional[str] = None) -> dict[str, Any]:
    STATE.log("INTENT_CLASSIFIED", pipeline.ACTOR_MERCHANT, f"Intent: UTR_VERIFY / payment check, no UTR ({intent_source})",
              {"intent": "UTR_VERIFY", "source": intent_source, "mode": "PAYMENT_CHECK"}, request_id)
    txns, feed_source = await feed(mid)
    amount = spoken_amount(merchant_text, slots)
    sit = situation(merchant_text)
    pool = [t for t in txns if amount is None or t.get("amount_inr") == amount]
    stuck = [t for t in pool if t.get("lookup_status") == "PENDING"]
    doubles = [p for p in duplicates(txns) if amount is None or p[-1].get("amount_inr") == amount]
    received = [t for t in pool if t.get("lookup_status") == "SUCCESS_SETTLED"]
    failed = [t for t in pool if t.get("lookup_status") == "FAILED"]
    STATE.log("PAYMENTS_SCANNED", pipeline.ACTOR_MERCHANT,
              f"Scanned {len(txns)} payments of the last {RECENT_HOURS}h ({feed_source}): "
              f"{len(stuck)} stuck, {len(doubles)} paid twice" + (f", looking for ₹{amount:,}" if amount else ""),
              {"situation": sit, "amount": amount, "feed": feed_source, "stuck": [t["utr"] for t in stuck],
               "doubles": [[x["utr"] for x in p] for p in doubles]}, request_id)

    findings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    n = 0
    offline = False

    # Which problem the merchant is describing decides what is looked at. A spinning screen is the customer at the
    # counter right now: their payment is the newest one (or the one with the amount they said), and if they already
    # paid twice that is fixed first. "Paisa kat gaya" is any stuck payment, plus any double payment.
    if sit == "spinning" and pool:
        newest = pool[0]
        stuck = [newest] if newest.get("lookup_status") == "PENDING" else []
        received = [newest] if newest.get("lookup_status") == "SUCCESS_SETTLED" else []
        failed = [newest] if newest.get("lookup_status") == "FAILED" else []
        order = ("doubles", "stuck", "received")
    else:
        order = ("stuck", "doubles", "received")
    for kind in order:
        if kind == "stuck":
            for t in stuck[:2]:
                n += 1
                resp, src = await _a2a(request_id, n, mid, consent_token, "UTR_VERIFY",
                                       {"utr": t["utr"], "utr_number": t["utr"], "amount": t["amount_inr"]},
                                       "VERIFY_PENDING_PAYMENT")
                offline |= src != "live"
                look = str((resp.get("data") or {}).get("lookup_status") or t["lookup_status"]).upper()
                f = {"kind": "STUCK", "utr": t["utr"], "amount_inr": t["amount_inr"], "payer_app": t.get("payer_app"),
                     "customer": _who(t), "at": _when(t), "paytm_status": look, "source": src,
                     "reverses_by": (_ts(t) + timedelta(days=1)).strftime("%d %b").lstrip("0")}
                if look == "PENDING" and src == "live":
                    watch = STATE.payment_watch.get(t["utr"])
                    if watch and watch.get("ticket_id"):
                        f["ticket_id"] = watch["ticket_id"]
                    else:
                        n += 1
                        tr, tsrc = await _a2a(
                            request_id, n, mid, consent_token, "ESCALATE_HUMAN",
                            {"reason_code": "MERCHANT_REQUESTED_HUMAN", "urgency": "NORMAL",
                             "reason_text": (f"UPI payment {t['utr']} of Rs {t['amount_inr']} via {t.get('payer_app')} "
                                             f"is PENDING since {t.get('received_at')}: customer debited, merchant not "
                                             "credited. Push it to complete or confirm the auto-reversal."),
                             "tried": ["Found the payment in the merchant's feed without a UTR",
                                       "Verified the status with Paytm: PENDING",
                                       "Told the merchant to hold the goods until it completes"]},
                            "RAISE_PENDING_PAYMENT_TICKET")
                        ticket = tr.get("escalation_ticket") or {}
                        if tsrc == "live" and ticket.get("ticket_id"):
                            f["ticket_id"] = ticket["ticket_id"]
                            actions.append({"type": "TICKET", "id": ticket["ticket_id"],
                                            "what": f"Paytm ticket to chase ₹{t['amount_inr']:,} ({t['utr']})"})
                    STATE.payment_watch[t["utr"]] = {"utr": t["utr"], "amount_inr": t["amount_inr"],
                                                     "customer": _who(t), "payer_app": t.get("payer_app"),
                                                     "status": look, "ticket_id": f.get("ticket_id"),
                                                     "since": request_id}
                    actions.append({"type": "WATCH", "utr": t["utr"],
                                    "what": f"Watching ₹{t['amount_inr']:,} until it lands or goes back"})
                findings.append(f)
        elif kind == "doubles":
            for pair in doubles[:1]:
                later = pair[-1]
                n += 1
                resp, src = await _a2a(request_id, n, mid, consent_token, "DUPLICATE_RECONCILE",
                                       {"order_id": later["order_id"]}, "AUTO_REFUND_DUPLICATE")
                offline |= src != "live"
                d = resp.get("data") or {}
                refunded = src == "live" and str(resp.get("status")).upper() == "RESOLVED"
                f = {"kind": "PAID_TWICE", "order_id": later["order_id"], "amount_inr": later["amount_inr"],
                     "customer": _who(later), "at": _when(later), "utrs": [x["utr"] for x in pair],
                     "refunded_utr": (d.get("refund") or {}).get("utr") or later["utr"], "refunded": refunded,
                     "refund_status": d.get("refund_status"), "paytm_status": resp.get("status"), "source": src}
                findings.append(f)
                if refunded:
                    actions.append({"type": "REFUND", "order": later["order_id"], "amount_inr": later["amount_inr"],
                                    "what": f"Paytm refunded the second ₹{later['amount_inr']:,} to the customer"})
        elif kind == "received" and (sit == "spinning" or amount is not None) and not findings:
            for t in received[:1]:
                n += 1
                resp, src = await _a2a(request_id, n, mid, consent_token, "UTR_VERIFY",
                                       {"utr": t["utr"], "utr_number": t["utr"], "amount": t["amount_inr"]},
                                       "CONFIRM_RECEIVED")
                offline |= src != "live"
                look = str((resp.get("data") or {}).get("lookup_status") or t["lookup_status"]).upper()
                findings.append({"kind": "RECEIVED", "utr": t["utr"], "amount_inr": t["amount_inr"],
                                 "payer_app": t.get("payer_app"), "customer": _who(t), "at": _when(t),
                                 "paytm_status": look, "source": src})
    if not findings and (amount is not None or sit == "spinning") and failed:
        t = failed[0]
        findings.append({"kind": "FAILED", "utr": t["utr"], "amount_inr": t["amount_inr"], "payer_app": t.get("payer_app"),
                         "customer": _who(t), "at": _when(t), "paytm_status": "FAILED", "source": feed_source})

    reply = _reply(findings, amount, offline)
    STATE.log("PAYMENT_CHECK_DONE", pipeline.ACTOR_MERCHANT,
              "; ".join(a["what"] for a in actions) or "Checked payments: nothing to fix",
              {"findings": findings, "actions": actions}, request_id)
    main = findings[0] if findings else {}
    status = {"STUCK": "PENDING", "PAID_TWICE": "REFUND_INITIATED" if main.get("refunded") else "DUPLICATE_FOUND",
              "RECEIVED": "SUCCESS", "FAILED": "FAILED"}.get(main.get("kind"), "ALL_CLEAR")
    return await pipeline.finish({
        "request_id": request_id, "mid": mid, "transcript": transcript, "transcript_source": transcript_source,
        "consent_token": consent_token, "intent": "UTR_VERIFY", "intent_source": intent_source,
        "slots": (slots or Slots()).model_dump(), "doc_extract": None,
        "historical_insight": {}, "intervention_evaluation": {}, "verified_outcome": {}, "pending_action": None,
        "paytm_response": {"status": status, "data": {"findings": findings}},
        "paytm_source": "live" if findings and not offline else ("none" if not findings else "mock"),
        "paytm_agent_trace": [], "hindi_reply": reply, "reply_text": reply, "reply_source": "template",
        "audio_base64": None, "audio_source": "unavailable", "language_code": pipeline.tts_code(),
        "fraud_alert": None, "gst_itc_logged": None, "local_gst_itc_log": STATE.local_gst_itc_log,
        "proactive": None, "a2a_events": STATE.a2a_events,
        "payment_check": {"situation": sit, "amount": amount, "feed": feed_source, "scanned": len(txns),
                          "findings": findings, "actions": actions},
    }, merchant_text, "Payment check reply ready")


# ----------------------------------------------------------------------------- what the merchant hears

def _rs(n: Any) -> str:
    return f"₹{int(n):,}" if n is not None else ""


def _reply(findings: list[dict[str, Any]], amount: Optional[int], offline: bool) -> str:
    en = pipeline.lang() == "en"
    if offline and findings and all(f.get("source") != "live" for f in findings):
        return ("I can't reach Paytm right now, so I haven't changed anything. Please hold the goods and ask me again "
                "in a minute." if en else
                "Abhi Paytm se connect nahi ho pa raha, isliye maine kuch change nahi kiya. Saman abhi rok kar rakhiye "
                "aur ek minute baad phir poochiye.")
    if not findings:
        if amount is not None:
            return (f"I can't see any {_rs(amount)} payment in the last day. Please don't hand over the goods yet; "
                    "ask the customer to show the payment on their app." if en else
                    f"Pichhle ek din mein {_rs(amount)} ka koi payment nahi dikha. Abhi saman mat dijiye, customer se "
                    "kahiye app mein payment dikhaye.")
        return ("I checked your recent payments: nothing is stuck and nobody paid twice. All of them reached you."
                if en else "Maine aapke recent payments check kiye: koi payment atka nahi hai aur kisi ne do baar pay "
                           "nahi kiya. Sab paisa aapke account mein aa gaya hai.")
    parts = [_line(f, en) for f in findings[:2]]
    return " ".join(p for p in parts if p)


def _line(f: dict[str, Any], en: bool) -> str:
    who = f.get("customer")
    amt, at = _rs(f.get("amount_inr")), f.get("at")
    if f["kind"] == "STUCK":
        ticket = f.get("ticket_id")
        if en:
            s = (f"Found it: {who + chr(39) + 's ' if who else 'the '}{amt} from {f.get('payer_app')} ({at}) is stuck "
                 "between the banks, so it has not reached you yet. The customer's money is safe: it either arrives "
                 f"with you or goes back to them by {f['reverses_by']}.")
            s += f" I've raised Paytm ticket {ticket} and I'm watching it." if ticket else " I'm watching it."
            return s + " Hold the goods until then."
        s = (f"Mil gaya: {who + ' ka ' if who else ''}{amt} {f.get('payer_app')} se ({at}) bank ke beech atka hua "
             "hai, isliye aapke paas nahi aaya. Customer ka paisa safe hai: ya toh aapke account mein aayega, ya "
             f"{f['reverses_by']} tak unhe wapas mil jayega.")
        s += f" Maine Paytm par ticket {ticket} khol diya hai aur main ise watch kar raha hoon." if ticket else \
            " Main ise watch kar raha hoon."
        return s + " Tab tak saman rok kar rakhiye."
    if f["kind"] == "PAID_TWICE":
        if f.get("refunded"):
            return (f"{who or 'A customer'} paid {amt} twice for order {f['order_id']}, probably while their screen was "
                    "stuck. Paytm has refunded the second payment to them; you keep the first. Your books are square."
                    if en else
                    f"{who or 'Customer'} ne order {f['order_id']} ke liye {amt} do baar pay kar diya, shayad screen "
                    "atakne ki wajah se. Paytm ne doosra payment unhe refund kar diya hai, pehla aapke paas hai. "
                    "Hisaab barabar hai.")
        return (f"{who or 'A customer'} paid {amt} twice for order {f['order_id']}, but Paytm hasn't confirmed the refund "
                "yet." if en else
                f"{who or 'Customer'} ne order {f['order_id']} ke liye {amt} do baar pay kiya hai, par Paytm ne abhi "
                "refund confirm nahi kiya.")
    if f["kind"] == "RECEIVED":
        return (f"{amt} from {who + ' via ' if who else ''}{f.get('payer_app')} reached your account ({at}). You can hand "
                "over the goods. Tell the customer not to pay again; their screen will update on its own." if en else
                f"{amt} {who + ' se ' if who else ''}{f.get('payer_app')} par aapke account mein aa gaya hai ({at}). "
                "Saman de sakte hain. Customer ko boliye dobara pay na karein, unki screen apne aap update ho jayegi.")
    if f["kind"] == "FAILED":
        return (f"The {amt} payment ({at}) failed, so nothing was taken from the customer. Ask them to pay again."
                if en else f"{amt} ka payment ({at}) fail ho gaya tha, customer ka paisa kata hi nahi. Unse dobara pay "
                           "karne ko kahiye.")
    return ""


# ----------------------------------------------------------------------------- the watch ("main ise watch kar raha hoon")

WATCH_EVERY_S = float(os.getenv("PAYMENT_WATCH_EVERY_S", "20"))
_DONE = {"SUCCESS_SETTLED": "ARRIVED", "FAILED": "WENT_BACK", "REVERSED": "WENT_BACK"}


def watch_message(w: dict[str, Any], en: bool) -> Optional[str]:
    """What to tell the merchant once a watched payment has landed or gone back (None while still pending)."""
    if not w.get("outcome"):
        return None
    who, amt = w.get("customer"), _rs(w.get("amount_inr"))
    if w["outcome"] == "ARRIVED":
        return (f"{who + chr(39) + 's ' if who else 'The '}{amt} has now reached your account. You can hand over the goods."
                if en else f"{who + ' ka ' if who else ''}{amt} ab aapke account mein aa gaya hai. Saman de sakte hain.")
    return (f"{who + chr(39) + 's ' if who else 'The '}{amt} did not go through and has gone back to the customer. "
            "Ask them to pay again." if en else
            f"{who + ' ka ' if who else ''}{amt} complete nahi hua, paisa customer ko wapas chala gaya. Unse dobara pay "
            "karne ko kahiye.")


async def recheck(mid: str) -> list[dict[str, Any]]:
    """Re-read Paytm's ledger for every payment still being watched; returns the ones that just settled either way."""
    open_ = {u: w for u, w in STATE.payment_watch.items() if w.get("status") == "PENDING"}
    if not open_:
        return []
    led = await upstream.paytm_ledger(mid)
    if not isinstance(led, dict):
        return []
    now = {t.get("utr"): t for t in led.get("transactions") or []}
    changed = []
    for utr, w in open_.items():
        status = str((now.get(utr) or {}).get("lookup_status") or "PENDING").upper()
        if status in _DONE:
            w.update(status=status, outcome=_DONE[status], resolved_at=time.time())
            STATE.log("PAYMENT_WATCH_UPDATE", pipeline.ACTOR_MERCHANT, f"Watched payment {utr}: {status}", dict(w),
                      w.get("since"))
            changed.append(w)
    return changed


async def watch_loop(mid: str) -> None:
    """Background: keeps checking stuck payments with Paytm so the merchant doesn't have to ask again."""
    while True:
        await asyncio.sleep(WATCH_EVERY_S)
        try:
            await recheck(mid)
        except Exception as exc:  # noqa: BLE001
            log.warning("payment watch: %s", exc)
