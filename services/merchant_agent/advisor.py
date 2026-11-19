"""Merchant AI Buddy cognition: PLAN.md's closed loop, merchant side.

  1. Understand + diagnose: read the query against the 6-month history (dataset `history`) and
     name the root cause, e.g. a temporary cash dip (payment friction) vs. willful default.
  2. Evaluate interventions: score 2–3 candidate actions (A/B/C) on policy, cost, merchant UX and
     *historical success*, block anything policy forbids, and pick the best.
  5. Verify + learn: read Paytm's verified outcome and append it to `strategy_memory`. The history
     score of every later evaluation uses priors + everything learned this session, so a strategy
     that keeps failing loses ground to the alternatives.
Everything here is deterministic and offline; the LLM only phrases the final reply.
"""
from __future__ import annotations

import time
from datetime import date
from typing import Any, Optional

import dataset_loader as dl
import upstream
from schemas import Slots
from state import STATE

# score = value x P(success): value weighs policy fit, cost and merchant UX; P(success) is the historical
# success rate. Multiplying (not adding) lets a strategy that keeps failing lose to the alternatives.
WEIGHTS = {"policy": 0.4, "cost": 0.3, "ux": 0.3}
LEARNED_WEIGHT = 2  # this merchant's own verified outcomes count double against the population priors


def _opt(oid: str, action: str, label: str, policy: float, cost: float, ux: float) -> dict[str, Any]:
    return {"id": oid, "action": action, "label": label, "policy": policy, "cost": cost, "ux": ux}


# Candidate interventions per intent. policy = how well it fits RBI/KFS/Paytm rules, cost = cheapness
# for merchant + Paytm, ux = effort and anxiety for the merchant. All in 0..1; history comes from memory.
OPTIONS: dict[str, list[dict[str, Any]]] = {
    "MANDATE_TROUBLESHOOT": [
        _opt("A", "SEND_REMINDER", "Send a reminder and retry the eNACH debit", 0.9, 0.95, 0.5),
        _opt("B", "UPI_LINK_48H_GRACE", "1-tap UPI link for the missed EDI + 48h KFS grace, penalty waived", 0.9, 0.85, 0.95),
        _opt("C", "ESCALATE_SPECIALIST", "Hand over to a collections specialist", 0.8, 0.4, 0.3),
    ],
    "SETTLEMENT_RECONCILE": [
        _opt("A", "ITEMISE_AND_LOG_ITC", "Itemise every deduction, auto-log GST ITC, flag open holds", 1.0, 1.0, 0.95),
        _opt("B", "RAISE_SETTLEMENT_DISPUTE", "Raise a settlement dispute ticket", 0.7, 0.5, 0.4),
        _opt("C", "ESCALATE_HUMAN", "Ask an L2 agent to explain the payout", 0.8, 0.3, 0.4),
    ],
    "CHARGEBACK_RESOLVE": [
        _opt("A", "SUBMIT_POD_REPRESENTMENT", "Fight the chargeback with signed Proof of Delivery", 1.0, 0.9, 0.85),
        _opt("B", "ACCEPT_CHARGEBACK", "Accept the chargeback and write off the amount", 0.9, 0.2, 0.7),
        _opt("C", "ESCALATE_HUMAN", "Ask an L2 agent to handle the dispute", 0.8, 0.4, 0.4),
    ],
    "UTR_VERIFY": [
        _opt("A", "VERIFY_WITH_NPCI", "Check the UTR against NPCI + acquiring ledger before releasing goods", 1.0, 0.95, 0.85),
        _opt("B", "ASK_CUSTOMER_TO_REPAY", "Ask the customer to pay again by QR", 0.8, 0.8, 0.3),
        _opt("C", "RELEASE_ON_SCREENSHOT", "Trust the screenshot and hand over goods", 0.1, 1.0, 0.9),
    ],
    "DUPLICATE_RECONCILE": [
        _opt("A", "AUTO_REFUND_DUPLICATE", "Match both UTRs and refund the duplicate instantly", 0.95, 0.85, 0.95),
        _opt("B", "STORE_CREDIT", "Keep it as store credit for the customer's next purchase", 0.5, 0.95, 0.5),
        _opt("C", "ESCALATE_HUMAN", "Ask an L2 agent to reverse it", 0.8, 0.4, 0.4),
    ],
    "GROWTH_ADVISORY": [
        _opt("A", "STOCK_UP_SELF_FUNDED", "Stock up before Fri–Sun from own cash", 1.0, 0.8, 0.6),
        _opt("B", "KFS_WORKING_CAPITAL_LINE", "Stock up before Fri–Sun with a KFS-transparent working-capital line", 0.95, 0.7, 0.95),
        _opt("C", "NO_CHANGE", "Keep the current stock plan", 1.0, 1.0, 0.3),
    ],
    "CASHFLOW_EDI_SWITCH": [
        _opt("A", "DELAY_SUPPLIER_PAYMENT", "Ask the supplier for 2 more days", 0.9, 0.6, 0.3),
        _opt("B", "KFS_EDI_PAUSE_2D", "Pause the loan EDI for 2 days under KFS clause 4.2", 0.9, 0.85, 0.95),
        _opt("C", "SHORT_TERM_TOPUP", "Take a short-term top-up loan", 0.8, 0.3, 0.6),
    ],
    "ESCALATE_HUMAN": [
        _opt("A", "SELF_SERVE_TROUBLESHOOT", "Guide the merchant through a restart / settings check", 1.0, 1.0, 0.5),
        _opt("B", "L2_PRIORITY_REPLACEMENT", "Priority L2 ticket with device diagnostics attached", 1.0, 0.6, 0.95),
        _opt("C", "L2_CALLBACK", "L2 callback within 2 hours", 1.0, 0.6, 0.8),
    ],
    "REFUND_MANAGE": [
        _opt("A", "TRACK_EXISTING_REFUND", "Explain the status of the existing refund", 1.0, 1.0, 0.85),
        _opt("B", "INITIATE_REFUND", "Initiate the refund now", 0.9, 0.8, 0.9),
        _opt("C", "ESCALATE_HUMAN", "Ask an L2 agent to process it", 0.9, 0.4, 0.4),
    ],
    "FEE_GST_LOAN": [
        _opt("A", "EXPLAIN_AND_LOG_ITC", "Explain fees, GST and EDI; auto-log the GST ITC", 1.0, 1.0, 0.9),
        _opt("B", "MDR_OPTIMISATION_NUDGE", "Suggest nudging customers to 0% bank-UPI", 1.0, 0.9, 0.7),
        _opt("C", "ESCALATE_HUMAN", "Ask an L2 agent to explain", 0.9, 0.4, 0.4),
    ],
    "SOUNDBOX_RETURN": [
        _opt("A", "SCHEDULE_PICKUP_STOP_RENTAL", "Schedule doorstep pickup and stop rental billing", 1.0, 0.8, 0.95),
        _opt("B", "RETENTION_RENTAL_WAIVER", "Offer a rental waiver to keep the device", 0.9, 0.6, 0.5),
        _opt("C", "ESCALATE_HUMAN", "Ask an L2 agent to handle the return", 0.9, 0.4, 0.4),
    ],
    "LOAN_CLOSURE_NOC": [
        _opt("A", "FORECLOSURE_QUOTE_AND_NOC", "Share the KFS foreclosure quote and raise the NOC request", 1.0, 0.9, 0.95),
        _opt("B", "CONTINUE_EDI", "Continue daily EDIs until the loan ends", 1.0, 0.8, 0.3),
        _opt("C", "ESCALATE_HUMAN", "Ask the lender's desk to call back", 0.9, 0.4, 0.4),
    ],
    "BANK_KYC_UPDATE": [
        _opt("A", "SECURE_LINK_PENNY_DROP", "Send a secure re-KYC link with penny-drop verification", 1.0, 0.9, 0.9),
        _opt("B", "BRANCH_VISIT", "Ask the merchant to visit a service centre", 1.0, 0.5, 0.2),
        _opt("C", "ESCALATE_HUMAN", "Ask an L2 agent to call back", 0.9, 0.4, 0.4),
    ],
    "SETTLEMENT_HOLD_BANK": [
        _opt("A", "CHECK_BANK_STATUS", "Check bank/KYC status and list every open hold", 1.0, 1.0, 0.9),
        _opt("B", "UPDATE_BANK_ACCOUNT", "Start a bank-account update", 0.9, 0.7, 0.5),
        _opt("C", "ESCALATE_HUMAN", "Ask an L2 agent to check the hold", 0.9, 0.4, 0.4),
    ],
}

# Prior outcomes per (intent, action): [successes, trials] from the merchant base. The dataset can
# override them via history.strategy_priors. Unlisted actions start at the uninformative 1/2.
STRATEGY_PRIORS: dict[str, dict[str, list[int]]] = {
    "MANDATE_TROUBLESHOOT": {"SEND_REMINDER": [2, 6], "UPI_LINK_48H_GRACE": [11, 12], "ESCALATE_SPECIALIST": [3, 5]},
    "SETTLEMENT_RECONCILE": {"ITEMISE_AND_LOG_ITC": [19, 20], "RAISE_SETTLEMENT_DISPUTE": [3, 6], "ESCALATE_HUMAN": [4, 6]},
    "CHARGEBACK_RESOLVE": {"SUBMIT_POD_REPRESENTMENT": [2, 2], "ACCEPT_CHARGEBACK": [0, 1], "ESCALATE_HUMAN": [1, 2]},
    "UTR_VERIFY": {"VERIFY_WITH_NPCI": [24, 24], "ASK_CUSTOMER_TO_REPAY": [5, 8], "RELEASE_ON_SCREENSHOT": [6, 10]},
    "DUPLICATE_RECONCILE": {"AUTO_REFUND_DUPLICATE": [6, 6], "STORE_CREDIT": [2, 5], "ESCALATE_HUMAN": [3, 4]},
    "GROWTH_ADVISORY": {"STOCK_UP_SELF_FUNDED": [4, 7], "KFS_WORKING_CAPITAL_LINE": [8, 10], "NO_CHANGE": [1, 4]},
    "CASHFLOW_EDI_SWITCH": {"DELAY_SUPPLIER_PAYMENT": [2, 5], "KFS_EDI_PAUSE_2D": [7, 8], "SHORT_TERM_TOPUP": [2, 4]},
    "ESCALATE_HUMAN": {"SELF_SERVE_TROUBLESHOOT": [3, 8], "L2_PRIORITY_REPLACEMENT": [9, 10], "L2_CALLBACK": [6, 8]},
}

SUCCESS_STATUSES = {
    "RECONCILED", "RELEASED", "SUCCESS", "SETTLED", "OK", "PROCESSED", "INITIATED", "ESCALATED", "RESOLVED", "WON",
    "UPI_LINK_SENT", "EDI_PAUSED", "REFUND_INITIATED", "OFFER_PREAPPROVED", "RETURN_INITIATED",
    "FORECLOSURE_QUOTE_READY", "KYC_UPDATE_LINK_SENT", "NO_BANK_HOLD", "NOT_FOUND_SUSPECTED_FAKE",
    "NO_CHARGEBACK_FOUND", "NO_DUPLICATE_FOUND", "CHARGEBACK_REVERSED",
}
FAILED_STATUSES = {"FAILED", "REJECTED", "ERROR", "EDI_PAUSE_NOT_ELIGIBLE", "SETTLEMENT_HELD_BANK_INACTIVE", "DECLINED"}


# ----------------------------------------------------------------------------- helpers


def _hist() -> dict[str, Any]:
    return dl.DATA.history


def _inr(n: Any) -> str:
    v = dl.num(n)
    return f"₹{dl._inr_commas(v)}" if v is not None else "₹?"


def _mult(h: dict[str, Any]) -> str:
    m = h.get("weekend_multiplier")
    return f"{m:g}x" if isinstance(m, (int, float)) else str(m)


def _span(dates: list[str]) -> str:
    """['2026-11-14', '2026-11-15', '2026-11-16'] -> '14–16 Nov'"""
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    try:
        first, last = dates[0], dates[-1]
        mon = months[int(last[5:7]) - 1]
        return f"{int(first[8:10])}–{int(last[8:10])} {mon}" if first != last else f"{int(last[8:10])} {mon}"
    except (IndexError, ValueError):
        return ", ".join(dates)


def profile() -> dict[str, Any]:
    """The headline 6-month numbers (PLAN.md seed profile) for responses and the UI's insights banner."""
    h, d = _hist(), dl.DATA
    return {
        "mid": d.merchant["mid"], "merchant_name": d.merchant["name"], "window": h.get("window"),
        "daily_avg_sales": h.get("daily_avg_sales"), "weekend_multiplier": h.get("weekend_multiplier"),
        "weekend_days": h.get("weekend_days"), "past_edi_success_rate": h.get("past_edi_success_rate"),
        "supplier_payable_tomorrow": h.get("supplier_payable_tomorrow"), "active_lender": h.get("active_lender"),
        "daily_edi": d.loan.get("edi_per_day"), "loan_balance": d.loan.get("balance"),
        "kfs_edi_holiday_eligible": (h.get("kfs") or {}).get("edi_holiday_eligible"),
        "connectors": {k: {"status": v.get("status"), "consent": v.get("consent")}
                       for k, v in (h.get("connectors") or {}).items()},
    }


# ----------------------------------------------------------------------------- 1. diagnose


def _expected_sales(h: dict[str, Any], row: dict[str, Any]) -> float:
    """What a normal day like this one sells: the row's own `expected` (same weekday, past weeks) if the
    dataset gives it, else the weekday/weekend split of the daily average (Fri–Sun run `weekend_multiplier`x)."""
    if (e := dl.num(row.get("expected"))) is not None:
        return float(e)
    avg = float(dl.num(h.get("daily_avg_sales")) or 0)
    m = float(dl.num(h.get("weekend_multiplier")) or 1)
    weekday_avg = avg * 7 / (4 + 3 * m)  # 4 weekdays at b, 3 weekend days at m·b, averaging to avg
    try:
        weekend = date.fromisoformat(str(row["date"])[:10]).weekday() >= 4  # Fri, Sat, Sun
    except ValueError:
        return avg
    return weekday_avg * m if weekend else weekday_avg


def _sales_dip(h: dict[str, Any]) -> dict[str, Any]:
    rows = [r for r in h.get("recent_daily_sales") or [] if isinstance(r, dict) and dl.num(r.get("sales")) is not None]
    exp = {r["date"]: _expected_sales(h, r) for r in rows}
    dip = [r for r in rows if r.get("dip")] or [r for r in rows if exp[r["date"]] and r["sales"] < 0.75 * exp[r["date"]]]
    expected_total = sum(exp[r["date"]] for r in dip)
    dip_pct = round((1 - sum(r["sales"] for r in dip) / expected_total) * 100) if dip and expected_total else 0
    after = [r for r in rows if dip and r["date"] > dip[-1]["date"]]
    recovered = any(r["sales"] >= 0.9 * exp[r["date"]] for r in after)
    note = next((r.get("note") for r in dip if r.get("note")), None)
    first_back = next((r for r in after if r["sales"] >= 0.9 * exp[r["date"]]), None)
    return {"dip_pct": dip_pct, "dip_dates": [r["date"] for r in dip], "cause": note, "recovered": recovered,
            "latest_day": first_back or (rows[-1] if rows else None)}


def _diag_mandate(h: dict[str, Any], slots: Slots, extra: dict[str, Any]) -> dict[str, Any]:
    dip, rate = _sales_dip(h), dl.num(h.get("past_edi_success_rate")) or 0
    m = h.get("mandate") or {}
    if dip["dip_pct"] >= 25 and rate >= 90:
        cls, root = "PAYMENT_FRICTION", "TEMPORARY_CASH_DIP"
        summary = (f"Friction, not default: sales fell {dip['dip_pct']}% on {_span(dip['dip_dates'])}"
                   f"{' (' + dip['cause'] + ')' if dip['cause'] else ''} vs {_inr(h.get('daily_avg_sales'))}/day; "
                   f"{rate:g}% of EDIs paid on time in 6 months")
        tip = (f"बिक्री लौट आई है, Fri–Sun की {_mult(h)} sale से EDI आराम से चलेगी।" if dip["recovered"]
               else f"Fri–Sun में {_mult(h)} sale होती है, EDI weekend के बाद संभल जाएगी।")
    elif rate < 80 and dip["dip_pct"] < 10:
        cls, root = "WILLFUL_DEFAULT_RISK", "REPEATED_MISSES_WITHOUT_CASH_DIP"
        summary = f"Repeated misses ({rate:g}% on-time) with normal sales — needs a specialist"
        tip = "समय पर EDI से आपका credit limit बढ़ सकता है।"
    else:
        cls, root = "NEEDS_REVIEW", "UNCLEAR"
        summary = f"EDI bounced; sales dip {dip['dip_pct']}%, {rate:g}% on-time history"
        tip = "EDI के दिन account में ₹500 का buffer रखें।"
    evidence = [
        f"eNACH bounce {m.get('bounce_date')}: {m.get('bounce_reason')}",
        f"Sales dip {dip['dip_pct']}% on {_span(dip['dip_dates'])}" if dip["dip_dates"] else "No sales dip found",
        f"{rate:g}% EDIs on time ({m.get('missed_edis_6m', '?')} missed of {m.get('edis_6m', '?')})",
    ]
    if dip["recovered"] and dip["latest_day"]:
        evidence.append(f"Recovered: {_inr(dip['latest_day']['sales'])} on {dip['latest_day']['date']}")
    return {"root_cause": root, "classification": cls, "summary": summary, "evidence": evidence, "tip_hi": tip,
            "metrics": {"sales_dip_pct": dip["dip_pct"], "dip_dates": dip["dip_dates"], "recovered": dip["recovered"],
                        "edi_success_rate": rate}}


def _diag_settlement(h, slots, extra):
    s, d = dl.DATA.settlement, dl.DATA
    gross, var = dl.num(s["gross"]) or 0, dl.num(s["variance"]) or 0
    mdr = d.deduction_amount("MDR") or 0
    hold = d.deduction("CHARGEBACK", "HOLD")
    return {"root_cause": "ITEMISED_DEDUCTIONS", "classification": "EXPLAINED",
            "summary": f"{_inr(var)} ({var / gross * 100:.2f}% of gross) = MDR, GST, refund, rental and holds; "
                       f"effective MDR {mdr / gross * 100:.2f}%" if gross else "Settlement itemised",
            "evidence": [f"Gross {_inr(gross)} vs bank credit {_inr(s['net_bank_credit'])}",
                         f"GST ITC {_inr(d.deduction_amount('GST'))} claimable"]
            + ([f"Chargeback hold #{hold.get('order_id')} {_inr(hold['amount'])} is recoverable"] if hold else []),
            "tip_hi": "Bank UPI पर MDR 0% है, QR पर UPI को बढ़ावा दीजिए।",
            "metrics": {"variance_pct": round(var / gross * 100, 2) if gross else None,
                        "effective_mdr_pct": round(mdr / gross * 100, 2) if gross else None}}


def _diag_chargeback(h, slots, extra):
    past = [x for x in h.get("past_disputes") or [] if isinstance(x, dict)]
    with_pod = [x for x in past if x.get("pod_submitted")]
    won = [x for x in with_pod if str(x.get("outcome", "")).upper() == "WON"]
    cb = dl.DATA.chargeback(slots.order_id) or dl.DATA.chargeback() or {}
    oid = cb.get("order_id")
    shiprocket = dl.DATA.connector("SHIPROCKET_SYNC")
    pod_ready = bool(extra.get("pod_submitted")) or bool(shiprocket and oid in [str(x) for x in shiprocket.get("holds_pod_for") or []])
    return {"root_cause": "CUSTOMER_DISPUTE", "classification": "WINNABLE_WITH_POD" if pod_ready else "NEEDS_POD",
            "summary": f"Dispute #{oid}: " + ("signed PoD available" if pod_ready else "PoD needed")
                       + f"; {len(won)}/{len(with_pod)} past disputes with PoD were won",
            "evidence": [f"Past disputes: {len(past)}, won with PoD: {len(won)}/{len(with_pod)}"]
            + (["Shiprocket connector holds the signed PoD"] if shiprocket and pod_ready else []),
            "tip_hi": (f"PoD के साथ पिछले {len(with_pod)} में से {len(won)} disputes आप जीते हैं।" if with_pod
                       else "हर delivery का signed PoD संभाल कर रखें।"),
            "metrics": {"pod_win_rate": round(len(won) / len(with_pod), 2) if with_pod else None, "pod_ready": pod_ready}}


def _diag_utr(h, slots, extra):
    return {"root_cause": "PAYMENT_CONFIRMATION", "classification": "VERIFY_BEFORE_RELEASE",
            "summary": "Screenshots can be edited; only the NPCI/acquiring ledger proves the money arrived",
            "evidence": [f"UTR {slots.utr_number}" if slots.utr_number else "No UTR yet"],
            "tip_hi": "Screenshot पर नहीं, Soundbox की आवाज़ या UTR check पर ही सामान दीजिए।", "metrics": {}}


def _diag_duplicate(h, slots, extra):
    dup = dl.DATA.duplicate_payment(slots.order_id) if slots.order_id else dl.DATA.duplicate_payment()
    if not dup:
        return {"root_cause": "NO_DUPLICATE_ON_FILE", "classification": "CHECK_WITH_PAYTM",
                "summary": "No duplicate found in the local khata; asking Paytm to match UTRs",
                "evidence": [], "tip_hi": "", "metrics": {}}
    name = dup.get("customer")
    cust = next((c for c in h.get("recent_customers") or [] if isinstance(c, dict) and c.get("name") == name), {})
    if dup.get("customer_visits_6m"):
        cust = {**cust, "visits_6m": dup["customer_visits_6m"]}
    return {"root_cause": "CUSTOMER_PAID_TWICE", "classification": "GENUINE_DUPLICATE",
            "summary": f"{name} paid {_inr(dup.get('amount'))} twice for order #{dup.get('order_id')}"
                       + (f"; repeat customer ({cust.get('visits_6m')} visits in 6 months)" if cust else ""),
            "evidence": [f"UTRs {', '.join(map(str, dup.get('utrs') or []))} on {dup.get('date')}"],
            "tip_hi": (f"{name} आपके repeat customer हैं, तुरंत refund से भरोसा बढ़ेगा।" if cust
                       else "Duplicate का तुरंत refund customer का भरोसा बढ़ाता है।"),
            "metrics": {"customer_visits_6m": cust.get("visits_6m"), "amount": dl.num(dup.get("amount")),
                        "order_id": dl.digits(dup.get("order_id"))}}


def _diag_growth(h, slots, extra):
    trend = upstream.six_month_trend_pct()
    months = [m for m in h.get("monthly_sales") or [] if isinstance(m, dict)]
    best = max(months, key=lambda m: m["sales"]) if months else None
    top = sorted((c for c in h.get("recent_customers") or [] if isinstance(c, dict)),
                 key=lambda c: -(dl.num(c.get("spend_6m")) or 0))[:3]
    return {"root_cause": "WEEKEND_DEMAND_PEAK", "classification": "GROWTH_OPPORTUNITY",
            "summary": f"Fri–Sun sales run {_mult(h)} weekdays"
                       + (f"; 6-month trend {trend:+d}%" if trend is not None else "")
                       + (f"; best month {best['month']}" + (f" ({best['note']})" if best.get("note") else "") if best else ""),
            "evidence": [f"Daily average {_inr(h.get('daily_avg_sales'))}",
                         f"Top customers: {', '.join(c.get('name', '?') for c in top)}" if top else "No customer data"],
            "tip_hi": f"Fri–Sun में {_mult(h)} बिक्री होती है, गुरुवार तक stock भर लीजिए।",
            "metrics": {"six_month_trend_pct": trend, "weekend_multiplier": h.get("weekend_multiplier"),
                        "best_month": best.get("month") if best else None}}


def cashflow_gap(extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    h = _hist()
    cf = h.get("cashflow") or {}
    alert = (extra or {}).get("alert_data") or {}
    payout = dl.num(alert.get("projected_net_payout")) or dl.num(cf.get("projected_net_payout_tomorrow")) or 0
    due = dl.num(h.get("supplier_payable_tomorrow")) or 0
    refund = alert.get("refund_request") or cf.get("pending_refund") or {}
    return {"projected_net_payout": payout, "tomorrow_stock_due": due, "shortfall": max(due - payout, 0),
            "refund_request": refund, "payables_source": "VYAPAR_POS_SYNC" if dl.DATA.connector("VYAPAR_POS_SYNC")
            else "merchant_history"}


def _diag_cashflow(h, slots, extra):
    gap = cashflow_gap(extra)
    kfs = h.get("kfs") or {}
    return {"root_cause": "REFUND_DRAINS_PAYOUT" if gap["refund_request"] else "LOW_PAYOUT",
            "classification": "LIQUIDITY_GAP" if gap["shortfall"] > 0 else "NO_GAP",
            "summary": f"Tomorrow's payout {_inr(gap['projected_net_payout'])} vs stock payable "
                       f"{_inr(gap['tomorrow_stock_due'])}: gap {_inr(gap['shortfall'])}",
            "evidence": [f"Refund request {_inr((gap['refund_request'] or {}).get('amount'))} on order "
                         f"#{(gap['refund_request'] or {}).get('order_id')}" if gap["refund_request"] else "No refund pending",
                         f"KFS clause {kfs.get('clause')}: EDI holiday "
                         f"{'eligible' if kfs.get('edi_holiday_eligible') else 'not eligible'} (max {kfs.get('max_pause_days')} days)"],
            "tip_hi": f"Weekend की {_mult(h)} बिक्री से EDI फिर आराम से चलेगी।",
            "metrics": gap}


def _diag_escalate(h, slots, extra):
    if extra.get("issue_type") == "HARDWARE_SOUNDBOX":
        diag = h.get("soundbox_diagnostics") or {}
        health = dl.num(diag.get("battery_health_pct"))
        causes = [c for c, bad in (
            ("BATTERY_DEGRADED", health is not None and health < 40),
            ("LOW_BATTERY", (dl.num(diag.get("battery_pct")) or 100) < 20),
            ("WEAK_NETWORK", any(w in str(diag.get("network", "")).lower() for w in ("weak", "offline", "2g"))),
            ("SPEAKER_FAILED", str(diag.get("speaker_test", "")).upper() == "FAILED")) if bad]
        parts = [f"battery health {health:g}%" if health is not None else f"battery {diag.get('battery_pct')}%",
                 str(diag.get("network") or ""),
                 f"{diag['heartbeats_missed_24h']} heartbeats missed" if diag.get("heartbeats_missed_24h") else "",
                 f"{diag['announce_failures_24h']} payments not announced in 24h" if diag.get("announce_failures_24h")
                 else f"speaker test {diag.get('speaker_test')}"]
        return {"root_cause": "+".join(causes) or "DEVICE_FAULT", "classification": "HARDWARE_FAULT",
                "summary": "Soundbox logs: " + ", ".join(p for p in parts if p),
                "evidence": [f"Device {diag.get('device_id') or ''} last heartbeat {diag.get('last_heartbeat')}".strip()],
                "tip_hi": "तब तक Paytm app में payment notification चालू रखिए।", "metrics": diag}
    return {"root_cause": "SUPPORT_REQUEST", "classification": "HUMAN_REQUESTED",
            "summary": "Merchant asked for a human", "evidence": [], "tip_hi": "", "metrics": {}}


def _diag_simple(root: str, cls: str, summary: str, tip: str):
    return lambda h, slots, extra: {"root_cause": root, "classification": cls, "summary": summary, "evidence": [],
                                    "tip_hi": tip, "metrics": {}}


def _diag_soundbox_return(h, slots, extra):
    plan = h.get("soundbox_plan") or {}
    rent, months = dl.num(plan.get("rental_per_month")) or 0, dl.num(plan.get("months_active")) or 0
    return {"root_cause": "DEVICE_NOT_NEEDED", "classification": "SERVICE_REQUEST",
            "summary": f"Soundbox rented {months:g} months at {_inr(rent)}/month ({_inr(rent * months)} paid so far)",
            "evidence": [], "tip_hi": "Pickup तक device चालू रखें, आखिरी bill pro-rata कटेगा।",
            "metrics": {"rental_per_month": rent, "months_active": months}}


def _diag_noc(h, slots, extra):
    rate = h.get("past_edi_success_rate")
    return {"root_cause": "LOAN_CLOSURE", "classification": "SERVICE_REQUEST",
            "summary": f"Outstanding {_inr(dl.DATA.loan.get('balance'))} with {h.get('active_lender')}; {rate}% on-time EDIs",
            "evidence": [], "tip_hi": f"{rate}% समय पर EDI से आपका credit profile मज़बूत है।",
            "metrics": {"outstanding": dl.DATA.loan.get("balance"), "edi_success_rate": rate}}


def _diag_hold(h, slots, extra):
    bank = h.get("bank_account") or {}
    st = str(bank.get("status", "ACTIVE")).upper()
    return {"root_cause": "NO_BANK_ISSUE" if st == "ACTIVE" else "BANK_ACCOUNT_INACTIVE",
            "classification": "INFO" if st == "ACTIVE" else "SETTLEMENT_BLOCKED",
            "summary": f"{bank.get('bank')} {bank.get('account_masked')} is {st}; last credit "
                       f"{_inr((bank.get('last_credit') or {}).get('amount'))} on {(bank.get('last_credit') or {}).get('date')}",
            "evidence": [], "tip_hi": "Account details बदलें तो पहले penny-drop verify करवाइए।" if st == "ACTIVE"
            else "Account चालू होते ही रुका settlement अगले cycle में आ जाएगा।", "metrics": {"bank_status": st}}


_DIAGNOSE = {
    "MANDATE_TROUBLESHOOT": _diag_mandate,
    "SETTLEMENT_RECONCILE": _diag_settlement,
    "CHARGEBACK_RESOLVE": _diag_chargeback,
    "UTR_VERIFY": _diag_utr,
    "DUPLICATE_RECONCILE": _diag_duplicate,
    "GROWTH_ADVISORY": _diag_growth,
    "CASHFLOW_EDI_SWITCH": _diag_cashflow,
    "ESCALATE_HUMAN": _diag_escalate,
    "REFUND_MANAGE": _diag_simple("CUSTOMER_REFUND", "INFO", "Refunds are deducted from the next settlement",
                                  "Refund उसी UPI app में जाता है जिससे customer ने pay किया था।"),
    "FEE_GST_LOAN": _diag_simple("FEES_AND_EDI", "INFO", "MDR, GST on MDR (ITC eligible) and the daily EDI",
                                 "हर महीने का GST ITC GSTR-3B में claim करना न भूलें।"),
    "SOUNDBOX_RETURN": _diag_soundbox_return,
    "LOAN_CLOSURE_NOC": _diag_noc,
    "BANK_KYC_UPDATE": _diag_simple("ACCOUNT_CHANGE", "SERVICE_REQUEST",
                                    "Settlement-account change needs re-KYC and penny-drop verification",
                                    "Verify होने तक settlement पुराने account में ही आएगा।"),
    "SETTLEMENT_HOLD_BANK": _diag_hold,
}


def diagnose(intent: str, slots: Slots, merchant_text: Optional[str] = None,
             extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """PLAN.md step 1: root cause from the 6-month history. `tip_hi` is the business tip for the reply."""
    h = _hist()
    out = _DIAGNOSE.get(intent, _diag_simple("UNKNOWN", "INFO", "", ""))(h, slots, extra or {})
    return {"intent": intent, **out, "data_window": h.get("window"), "profile": profile()}


# ----------------------------------------------------------------------------- 2. evaluate


def _priors() -> dict[str, dict[str, list[float]]]:
    out = {i: {a: list(v) for a, v in acts.items()} for i, acts in STRATEGY_PRIORS.items()}
    for intent, acts in (_hist().get("strategy_priors") or {}).items():
        if not isinstance(acts, dict):
            continue
        for action, v in acts.items():
            if isinstance(v, (list, tuple)) and len(v) == 2:
                s, n = dl.num(v[0]), dl.num(v[1])
            elif isinstance(v, dict):
                n = dl.num(dl.pick(v, "trials", "samples", "n", "attempts"))
                s = dl.num(dl.pick(v, "successes", "wins", "resolved"))
                if s is None and n is not None and (r := dl.pct(dl.pick(v, "success_rate", "rate"))) is not None:
                    s = n * r / 100
            else:
                continue
            if s is not None and n:  # this merchant's recorded outcomes add to the population priors
                s0, n0 = out.setdefault(str(intent).upper(), {}).get(str(action).upper(), [0, 0])
                out[str(intent).upper()][str(action).upper()] = [s0 + s, n0 + n]
    return out


def history_stats(intent: str, action: str) -> dict[str, Any]:
    """Laplace-smoothed success rate from priors + outcomes verified this session."""
    s0, n0 = _priors().get(intent, {}).get(action, [0, 0])
    learned = [m for m in STATE.strategy_memory if m["intent"] == intent and m["action"] == action]
    ls = sum(1 for m in learned if m["outcome"] == "SUCCESS")
    rate = (s0 + LEARNED_WEIGHT * ls + 1) / (n0 + LEARNED_WEIGHT * len(learned) + 2)
    return {"success_rate": round(rate, 3), "prior_trials": n0, "learned_trials": len(learned), "learned_successes": ls}


def _adjust(intent: str, insight: dict[str, Any], slots: Slots, extra: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Context-specific score changes and policy blocks: {action: {field: value, 'blocked': reason}}."""
    cls, d, h = insight.get("classification"), dl.DATA, _hist()
    adj: dict[str, dict[str, Any]] = {}
    if intent == "MANDATE_TROUBLESHOOT":
        if cls == "PAYMENT_FRICTION":
            adj["SEND_REMINDER"] = {"ux": 0.3}  # a reminder doesn't fix a cash dip
        elif cls == "WILLFUL_DEFAULT_RISK":
            adj["UPI_LINK_48H_GRACE"] = {"blocked": "KFS grace is for payment friction, not repeated default"}
            adj["ESCALATE_SPECIALIST"] = {"policy": 1.0, "ux": 0.6}
    elif intent == "CASHFLOW_EDI_SWITCH":
        kfs = h.get("kfs") or {}
        if not kfs.get("edi_holiday_eligible"):
            adj["KFS_EDI_PAUSE_2D"] = {"blocked": "Loan is not eligible for a KFS EDI holiday"}
        elif STATE.loan_edi_status != "ACTIVE":
            adj["KFS_EDI_PAUSE_2D"] = {"blocked": "EDI is already paused"}
        if insight.get("classification") == "NO_GAP":
            adj["KFS_EDI_PAUSE_2D"] = {**adj.get("KFS_EDI_PAUSE_2D", {}), "policy": 0.2}
    elif intent == "ESCALATE_HUMAN":
        if extra.get("issue_type") == "HARDWARE_SOUNDBOX":
            adj["SELF_SERVE_TROUBLESHOOT"] = {"ux": 0.2}  # speaker already failed its self-test
        else:
            adj["L2_PRIORITY_REPLACEMENT"] = {"blocked": "No hardware fault reported"}
    elif intent == "REFUND_MANAGE":
        known = d.refund(slots.order_id) if slots.order_id else None
        if slots.order_id and slots.amount and not known:
            adj["TRACK_EXISTING_REFUND"] = {"blocked": "No existing refund for this order"}
            if slots.amount > float(d.refund_limit):
                adj["INITIATE_REFUND"] = {"blocked": f"Above the {_inr(d.refund_limit)} autonomous refund limit"}
        else:
            adj["INITIATE_REFUND"] = {"blocked": "Order number and amount needed to start a refund"}
    elif intent == "DUPLICATE_RECONCILE":
        amt = (insight.get("metrics") or {}).get("amount")
        if amt and amt > float(d.refund_limit):
            adj["AUTO_REFUND_DUPLICATE"] = {"blocked": f"Above the {_inr(d.refund_limit)} autonomous refund limit"}
    elif intent == "UTR_VERIFY":
        adj["RELEASE_ON_SCREENSHOT"] = {"blocked": "Screenshots are not proof of payment"}
    elif intent == "CHARGEBACK_RESOLVE" and not (insight.get("metrics") or {}).get("pod_ready"):
        adj["SUBMIT_POD_REPRESENTMENT"] = {"ux": 0.6}  # merchant still has to find the PoD
    return adj


def evaluate(intent: str, insight: dict[str, Any], slots: Slots,
             extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """PLAN.md step 2: score options A/B/C and pick the best one policy allows."""
    adj = _adjust(intent, insight, slots, extra or {})
    options = []
    for o in OPTIONS.get(intent, OPTIONS["ESCALATE_HUMAN"]):
        a = adj.get(o["action"], {})
        hist = history_stats(intent, o["action"])
        scores = {k: a.get(k, o[k]) for k in ("policy", "cost", "ux")} | {"history": hist["success_rate"]}
        value = sum(WEIGHTS[k] * scores[k] for k in WEIGHTS)
        total = round(value * hist["success_rate"], 3)
        options.append({"id": o["id"], "action": o["action"], "label": o["label"], "scores": scores,
                        "history": hist, "total": 0.0 if a.get("blocked") else total,
                        "blocked_by_policy": a.get("blocked"), "selected": False})
    allowed = [o for o in options if not o["blocked_by_policy"]] or options
    best = max(allowed, key=lambda o: o["total"])
    best["selected"] = True
    runner = max((o for o in allowed if o is not best), key=lambda o: o["total"], default=None)
    why = (f"Option {best['id']} ({best['action']}) scores {best['total']:.2f}"
           + (f" vs {runner['id']} {runner['total']:.2f}" if runner else "")
           + f"; history {best['history']['success_rate']:.0%} success"
           + (f"; root cause {insight.get('classification')}" if insight.get("classification") else ""))
    blocked = [f"{o['id']}: {o['blocked_by_policy']}" for o in options if o["blocked_by_policy"]]
    return {
        "options": options,
        "selected": best["id"],
        "selected_intervention": {"option_id": best["id"], "action": best["action"], "label": best["label"],
                                  "score": best["total"]},
        "rationale": why + (f". Blocked: {'; '.join(blocked)}" if blocked else ""),
        "scoring": {"total": "value × historical success rate", "value_weights": WEIGHTS,
                    "learned_outcome_weight": LEARNED_WEIGHT},
    }


# ----------------------------------------------------------------------------- 5. verify & learn


def verify_and_learn(intent: str, evaluation: dict[str, Any], resp: dict[str, Any], paytm_source: str,
                     request_id: str) -> dict[str, Any]:
    status = str(resp.get("status") or "").upper()
    vo = resp.get("verified_outcome")
    if isinstance(vo, dict) and isinstance(vo.get("resolved"), bool):
        resolved: Optional[bool] = vo["resolved"]
        basis = "paytm_verified_outcome"
    elif status in FAILED_STATUSES:
        resolved, basis = False, "status"
    elif status in SUCCESS_STATUSES:
        resolved, basis = True, "status"
    else:
        resolved, basis = None, "status"  # HELD / PENDING / NEEDS_INFO / ALERT_RAISED: not an outcome yet
    sel = evaluation.get("selected_intervention") or {}
    record = {
        "intent": intent, "option_id": sel.get("option_id"), "action": sel.get("action"),
        "outcome": {True: "SUCCESS", False: "FAILED", None: "PENDING"}[resolved], "paytm_status": status,
        "verified_by": f"paytm_agent ({paytm_source})", "basis": basis, "request_id": request_id, "ts": time.time(),
    }
    if resolved is not None:
        STATE.strategy_memory.append(record)
    return {**record, "learned": resolved is not None,
            "strategy_success_rate": history_stats(intent, str(sel.get("action")))["success_rate"]}


def memory_summary() -> dict[str, Any]:
    by_intent: dict[str, dict[str, Any]] = {}
    for m in STATE.strategy_memory:
        by_intent.setdefault(m["intent"], {})[m["action"]] = history_stats(m["intent"], m["action"])
    return {
        "verified_outcomes_learned": len(STATE.strategy_memory),
        "successes": sum(1 for m in STATE.strategy_memory if m["outcome"] == "SUCCESS"),
        "by_intent": by_intent,
        "recent": STATE.strategy_memory[-10:],
    }
