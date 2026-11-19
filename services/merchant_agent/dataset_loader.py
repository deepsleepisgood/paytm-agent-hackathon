"""Team merchant dataset loader (repo-root `dataset/`, authored by a teammate).

The merchant agent reads seed data, utterances and golden paths from the shared dataset,
so the whole team works from one source of truth. The dataset's schema isn't frozen yet, so:
  * each file falls back to the CONTRACT.md seed below if it is missing or unusable;
  * field names are read tolerantly (several likely spellings, any case or separator);
  * GET /health -> "dataset" reports, per file, whether it loaded or fell back (and which
    fields fell back), and whether the settlement numbers add up.
Set DATASET_DIR to use another folder. POST /reset reloads from disk.

Other modules must read `dataset_loader.DATA` at call time (not `from ... import DATA`),
so that a reload is picked up everywhere.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional, Union

import seed_adapter
from schemas import INTENTS

log = logging.getLogger("merchant_agent.dataset")

HERE = Path(__file__).resolve().parent
# The team dataset landed at <repo root>/data/seed (CSV + JSON, read via seed_adapter). The older
# per-file layout under <repo root>/dataset is still supported.
_REPO = HERE.parents[1]  # services/merchant_agent -> <repo root>
DEFAULT_ROOT = _REPO / "data" if (_REPO / "data" / "seed" / "merchant_profile.json").is_file() else _REPO / "dataset"

try:  # this module is imported first and loads DATA at import, so read .env (DATASET_DIR) here too
    from dotenv import load_dotenv

    load_dotenv(HERE / ".env")
except ImportError:  # pragma: no cover
    pass

FILES: dict[str, str] = {
    "merchant": "seed/merchant.json",
    "settlement": "seed/settlement.json",
    "transactions": "seed/transactions.json",
    "refunds_orders": "seed/refunds_orders.json",
    "loan": "seed/loan.json",
    "fee_rules": "seed/fee_rules.json",
    "initial_state": "seed/initial_state.json",
    "utterances": "intents/utterances.json",
    "golden_paths": "golden/golden_paths.json",
    # PLAN.md V3: 6-month historical memory (sales, EDI record, payables, customers, connectors).
    # If this file is missing, a `historical_profile` / `history` block inside merchant.json is used.
    "history": "seed/merchant_history.json",
}

Number = Union[int, float]

# ----------------------------------------------------------------------------- built-in seed (CONTRACT.md)

BUILTIN_MERCHANT: dict[str, Any] = {"mid": "PAYTM_MERCH_8821", "name": "Sharma Electronics", "gstin": None, "soundbox": None}
BUILTIN_SETTLEMENT: dict[str, Any] = {
    "settlement_date": "2026-11-18",
    "gross": 100000,
    "net_bank_credit": 95840,
    "variance": 4160,
    "deductions": [
        {"head": "MDR_FEE", "label": "MDR Fee", "amount": 1450},
        {"head": "GST_ON_MDR", "label": "GST on MDR", "amount": 261, "itc_eligible": True},
        {"head": "CUSTOMER_REFUND", "label": "Customer Refund", "amount": 1500, "order_id": "4412", "status": "PROCESSED"},
        {"head": "SOUNDBOX_RENTAL", "label": "Soundbox Rental", "amount": 149},
        {"head": "CHARGEBACK_HOLD", "label": "Chargeback Hold", "amount": 800, "order_id": "9981", "txn_id": "9981", "status": "HELD"},
    ],
}
BUILTIN_UTRS: dict[str, dict[str, Any]] = {
    "632184920111": {"utr_number": "632184920111", "amount": 1250, "payer_app": "GPay", "status": "SUCCESS", "settled": True},
    "632184920999": {"utr_number": "632184920999", "amount": 2400, "payer_app": "PhonePe", "status": "PENDING",
                     "note": "NPCI T+1 auto-reversal"},
}
BUILTIN_REFUNDS: dict[str, dict[str, Any]] = {"4412": {"order_id": "4412", "amount": 1500, "status": "PROCESSED"}}
BUILTIN_CHARGEBACKS: dict[str, dict[str, Any]] = {
    "9981": {"order_id": "9981", "txn_id": "9981", "amount": 800, "status": "HELD", "pod_due_in_hours": 48}
}
BUILTIN_REFUND_LIMIT: Number = 5000
BUILTIN_LOAN: dict[str, Any] = {"edi_per_day": 500, "balance": 42000, "next_deduction": "tomorrow's settlement"}
BUILTIN_FEES: dict[str, Any] = {
    "mdr_rates": {"credit_card": "2%", "wallet_on_upi_above_2k": "1.1%", "bank_upi": "0%"},
    "gst_rate_pct": 18,
}
BUILTIN_UTTERANCES: list[dict[str, Any]] = [
    # PLAN.md demo chips (preset) + one example per V3 intent. When the dataset's utterances.json exists,
    # these are still used for routing (few-shot / exact match) for any intent the dataset doesn't cover.
    {"text": "Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?", "intent": "SETTLEMENT_RECONCILE", "preset": True},
    {"text": "Mera ₹500 ka loan EDI mandate fail ho gaya", "intent": "MANDATE_TROUBLESHOOT", "preset": True},
    {"text": "Mere pichle 6 mahine ke data se business badhane ka suggestion do", "intent": "GROWTH_ADVISORY", "preset": True},
    {"text": "Customer ne order 4489 ke liye do baar payment kar diya", "intent": "DUPLICATE_RECONCILE", "preset": True},
    {"text": "Refund ke baad kal stock ke liye paise kam pad rahe hain, EDI ruk sakti hai?", "intent": "CASHFLOW_EDI_SWITCH", "preset": True},
    {"text": "Soundbox wapas karna hai, uska bill abhi bhi kat raha hai", "intent": "SOUNDBOX_RETURN", "preset": True},
    {"text": "Loan poora settle karna hai, NOC kab milega?", "intent": "LOAN_CLOSURE_NOC", "preset": True},
    {"text": "Mujhe settlement ka bank account aur KYC change karna hai", "intent": "BANK_KYC_UPDATE", "preset": True},
    {"text": "Settlement hold pe hai kya? Bank account inactive dikha raha hai", "intent": "SETTLEMENT_HOLD_BANK", "preset": True},
]

# PLAN.md "6-Month Historical Memory", aligned with the team dataset (data/seed) so the offline
# fallback tells the same story: a market closure on 14–16 Nov (~37% below the same weekdays) explains
# the 17 Nov eNACH bounce; 17 Nov's ₹1,00,000 (market reopened + a PG fit-out order) is the gross
# settled on 18 Nov. `expected` = mean of the same weekday over the 4 previous ordinary weeks.
BUILTIN_HISTORY: dict[str, Any] = {
    "window": "2026-05-19 to 2026-11-18",
    "daily_avg_sales": 32000,
    "weekend_multiplier": 2.3,
    "weekend_days": "Fri–Sun",
    "past_edi_success_rate": 96,
    "supplier_payable_tomorrow": 4500,
    "active_lender": "Clix Capital",
    "kfs": {"edi_holiday_eligible": True, "max_pause_days": 2, "clause": "4.2", "apr_percent": 31.89},
    "monthly_sales": [
        {"month": "2026-06", "sales": 1041515}, {"month": "2026-07", "sales": 771130},
        {"month": "2026-08", "sales": 812092}, {"month": "2026-09", "sales": 945954},
        {"month": "2026-10", "sales": 1073613}, {"month": "2026-11", "sales": 782406, "note": "month to date"},
    ],
    "recent_daily_sales": [
        {"date": "2026-11-11", "sales": 19815}, {"date": "2026-11-12", "sales": 18915},
        {"date": "2026-11-13", "sales": 45501},
        {"date": "2026-11-14", "sales": 31173, "expected": 47432, "note": "market closure", "dip": True},
        {"date": "2026-11-15", "sales": 28232, "expected": 49232, "note": "market closure", "dip": True},
        {"date": "2026-11-16", "sales": 14109, "expected": 20838, "note": "market closure", "dip": True},
        {"date": "2026-11-17", "sales": 100000, "expected": 19676, "note": "bulk order + market reopened"},
        {"date": "2026-11-18", "sales": 22301, "expected": 21294},
    ],
    "mandate": {"type": "eNACH", "edi_amount": 500, "last_status": "BOUNCED", "bounce_reason": "INSUFFICIENT_FUNDS",
                "bounce_date": "2026-11-17", "context": "market closure 14-16 Nov (sales -40%)",
                "missed_edis_6m": 7, "edis_6m": 171},
    "recent_customers": [
        {"name": "Vikram Malhotra", "customer_id": "C001", "spend_6m": 166203},
        {"name": "Sunita Rana", "customer_id": "C003", "spend_6m": 95475},
        {"name": "Geeta Saini", "customer_id": "C002", "spend_6m": 78314},
        {"name": "Babita Malhotra", "customer_id": "C006", "spend_6m": 68133},
        {"name": "Pooja Kapoor (electrician)", "customer_id": "C005", "spend_6m": 53285},
    ],
    "duplicate_payments": [
        {"order_id": "4489", "customer": "Sunita Yadav", "customer_id": "C017", "customer_visits_6m": 23, "amount": 1180,
         "date": "2026-11-18", "utrs": ["632299206882", "632230725895"], "payer_app": "PhonePe"},
    ],
    "past_disputes": [
        {"order_id": "9920", "amount": 2949, "pod_submitted": False, "outcome": "LOST"},
        {"order_id": "9962", "amount": 2198, "pod_submitted": True, "outcome": "WON"},
    ],
    "connectors": {
        "SHIPROCKET_SYNC": {"status": "ACTIVE", "consent": "GRANTED", "holds_pod_for": ["9981"]},
        "VYAPAR_POS_SYNC": {"status": "ACTIVE", "consent": "GRANTED", "stock_payable_tomorrow": 4500},
        "RBI_ACCOUNT_AGGREGATOR": {"status": "ACTIVE", "consent": "GRANTED"},
    },
    "bank_account": {"bank": None, "account_masked": "XXXXXX4821", "status": "ACTIVE", "kyc_status": "VERIFIED",
                     "last_credit": {"date": "2026-11-18", "amount": 95840}},
    "soundbox_diagnostics": {"device_id": "SB-8821-01", "battery_pct": 18, "battery_health_pct": 18,
                             "network": "drops to offline", "heartbeats_missed_24h": 7, "announce_failures_24h": 60,
                             "speaker_test": "FAILED", "last_heartbeat": "2026-11-18T23:00:00"},
    "soundbox_plan": {"rental_per_month": 149, "months_active": None},
    "cashflow": {"projected_net_payout_tomorrow": 1200, "pending_refund": {"order_id": "4490", "amount": 3500}},
    # Same as 8002's CreditOffer: a pre-approved limit with no rate quoted. Rate and tenure belong in the
    # NBFC's KFS, which the merchant must see before any drawdown; inventing them would mislead.
    "growth_offer": {"type": "WORKING_CAPITAL_LINE", "amount": 150000, "lender": "Clix Capital", "kfs_required": True},
}

# ----------------------------------------------------------------------------- tolerant readers


def _norm_key(k: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def pick(d: Any, *names: str) -> Any:
    """First non-empty value among `names`, ignoring case and separators (gross_mix == grossMix == "Gross Mix")."""
    if not isinstance(d, dict):
        return None
    index = {_norm_key(k): k for k in d}
    for n in names:
        k = index.get(_norm_key(n))
        if k is not None and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def num(v: Any) -> Optional[Number]:
    """1450 / 1450.0 / "₹1,450" / "1450" -> 1450 (int when whole)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        s = re.sub(r"(?i)[₹,\s]|rs\.?|inr|/-", "", v)
        try:
            f = float(s)
        except ValueError:
            return None
    else:
        return None
    return int(f) if f.is_integer() else f


def amount_of(v: Any) -> Optional[Number]:
    return num(pick(v, "amount", "value", "amt")) if isinstance(v, dict) else num(v)


def digits(v: Any) -> Optional[str]:
    """'#9981' / 'ORDER #9981' / 9981 -> '9981'. Ignores dicts/lists."""
    if v is None or isinstance(v, (bool, dict, list)):
        return None
    d = re.sub(r"\D", "", str(v))
    return d or None


def pct(v: Any) -> Optional[Number]:
    """0.18 / 18 / '18%' / {'rate_pct': 18} -> 18."""
    if isinstance(v, dict):
        v = pick(v, "rate_pct", "pct", "percent", "percentage", "rate", "value")
    n = num(v.replace("%", "")) if isinstance(v, str) else num(v)
    if n is None:
        return None
    if 0 < n < 1:
        n = round(n * 100, 4)
    return int(n) if float(n).is_integer() else n


def _walk(obj: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[dict, tuple[str, ...]]]:
    """Yield every dict in a JSON tree with the chain of keys leading to it."""
    if isinstance(obj, dict):
        yield obj, path
        for k, v in obj.items():
            yield from _walk(v, path + (str(k),))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, path)


def _head(label: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(label).upper()).strip("_")


def _inr_commas(n: Number) -> str:
    s = str(int(n))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


class Unusable(ValueError):
    """The file parsed as JSON but none of its fields could be recognised."""


# ----------------------------------------------------------------------------- per-file normalisers
# Each returns (value, fields_that_fell_back_to_builtin).


def _merchant(raw: Any) -> tuple[dict, list[str]]:
    m = pick(raw, "merchant") if isinstance(pick(raw, "merchant"), dict) else raw
    if not isinstance(m, dict):
        raise Unusable("not a JSON object")
    sb = pick(m, "soundbox", "soundbox_device", "device", "devices")
    if isinstance(sb, list):
        sb = next((d for d in sb if "sound" in json.dumps(d, ensure_ascii=False).lower()), sb[0] if sb else None)
    out = {
        "mid": pick(m, "mid", "merchant_id"),
        "name": pick(m, "name", "merchant_name", "business_name", "trade_name", "shop_name", "legal_name"),
        "gstin": pick(m, "gstin", "gst_number", "gst_no", "gstin_number"),
        "soundbox": sb if isinstance(sb, (dict, str)) else None,
    }
    if out["mid"] is None and out["name"] is None and out["gstin"] is None:
        raise Unusable("no mid / name / gstin found")
    fell = [k for k in ("mid", "name") if out[k] is None]
    for k in fell:
        out[k] = BUILTIN_MERCHANT[k]
    out["mid"], out["name"] = str(out["mid"]), str(out["name"])
    return out, fell


def _total(v: Any) -> Optional[Number]:
    """A number, or a payment-mix dict/list summed (prefers an explicit total)."""
    if (n := num(v)) is not None:
        return n
    if isinstance(v, dict):
        if (t := num(pick(v, "total", "gross", "sum", "amount"))) is not None:
            return t
        parts = [_total(x) for x in v.values()]
    elif isinstance(v, list):
        parts = [_total(x) for x in v]
    else:
        return None
    parts = [p for p in parts if p is not None]
    return sum(parts) if parts else None


_HEAD_KEYS = ("head", "code", "type", "name", "component", "label", "category", "reason", "id")


def _deductions(v: Any) -> list[dict]:
    items: list[dict] = []
    if isinstance(v, dict):  # {"MDR Fee": 1450, "Chargeback Hold": {"amount": 800, ...}}
        for k, x in v.items():
            if isinstance(x, dict):
                items.append({"head": k, **x})
            elif num(x) is not None:
                items.append({"head": k, "amount": x})
    elif isinstance(v, list):
        items = [x for x in v if isinstance(x, dict)]
    out = []
    for d in items:
        label, amount = pick(d, *_HEAD_KEYS), num(pick(d, "amount", "value", "amt"))
        if label is None or amount is None:
            continue
        rec = {**d, "head": _head(label), "label": str(label), "amount": amount}
        for k in ("order_id", "txn_id"):
            if (val := digits(pick(d, k))) is not None:
                rec[k] = val
        if (st := pick(d, "status", "state")) is not None:
            rec["status"] = str(st).upper()
        out.append(rec)
    return out


def _settlement(raw: Any) -> tuple[dict, list[str]]:
    s = raw
    if isinstance(pick(raw, "settlement"), dict):
        s = pick(raw, "settlement")
    many = pick(raw, "settlements") if isinstance(raw, dict) else raw if isinstance(raw, list) else None
    if isinstance(many, list) and many:
        want = BUILTIN_SETTLEMENT["settlement_date"]
        s = next((x for x in many if isinstance(x, dict) and pick(x, "settlement_date", "date") == want), many[0])
    if not isinstance(s, dict):
        raise Unusable("no settlement object")

    mix = pick(s, "gross_mix", "payment_mix", "sales_mix", "mix", "gross_breakdown", "collections")
    gross = _total(pick(s, "gross", "expected_gross", "gross_sales", "gross_amount", "gross_total", "total_gross",
                        "gross_collection"))
    if gross is None:
        gross = _total(mix)
    net = num(pick(s, "net_bank_credit", "net_credit", "bank_credit", "bank_credit_received", "net_payout",
                   "net_settlement", "net_settled", "net_amount", "net"))
    deductions = _deductions(pick(s, "deductions", "breakdown", "deduction_breakdown", "variance_breakdown",
                                  "line_items", "components"))
    variance = num(pick(s, "variance", "total_deductions", "deductions_total", "difference"))
    if gross is None and net is None and not deductions:
        raise Unusable("no gross / net / deductions found")
    if variance is None and gross is not None and net is not None:
        variance = gross - net
    elif variance is None and deductions:
        variance = sum(d["amount"] for d in deductions)

    out: dict[str, Any] = {
        "settlement_date": str(pick(s, "settlement_date", "date") or "") or None,
        "gross": gross,
        "net_bank_credit": net,
        "variance": variance,
        "deductions": deductions or None,
    }
    fell = [k for k, v in out.items() if v is None]
    for k in fell:
        out[k] = BUILTIN_SETTLEMENT[k]
    if mix is not None:
        out["gross_mix"] = mix
    return out, fell


def _utr_rec(utr: str, d: dict) -> dict:
    return {
        **d,
        "utr_number": utr,
        "amount": num(pick(d, "amount", "amt")),
        "payer_app": pick(d, "payer_app", "app", "payer_psp", "psp", "upi_app", "payer"),
        "status": str(pick(d, "status", "state", "txn_status") or "UNKNOWN").upper(),
    }


def _utrs(raw: Any) -> tuple[dict, list[str]]:
    out: dict[str, dict] = {}
    for d, _ in _walk(raw):
        utr = digits(pick(d, "utr", "utr_number", "utr_no", "rrn", "upi_ref", "upi_ref_no", "upi_reference"))
        if utr and len(utr) == 12:
            out.setdefault(utr, _utr_rec(utr, d))
        for k, v in d.items():  # keyed by UTR: {"632184920111": {...}}
            if re.fullmatch(r"\d{12}", str(k)) and isinstance(v, dict):
                out.setdefault(str(k), _utr_rec(str(k), v))
    if not out:
        raise Unusable("no 12-digit UTRs found")
    return out, []


def _orders(raw: Any) -> tuple[dict, dict, Optional[Number]]:
    """(refunds, chargebacks, refund_limit) from any nesting; records are classified by context."""
    refunds: dict[str, dict] = {}
    chargebacks: dict[str, dict] = {}
    limit: Optional[Number] = None
    for d, path in _walk(raw):
        ctx = " ".join(path).lower()
        for k, v in d.items():
            kn = _norm_key(k)
            is_limit_key = "limit" in kn or "threshold" in kn or kn.startswith("max")
            if limit is None and is_limit_key and ("refund" in kn or "refund" in ctx or "autonom" in kn):
                limit = num(v) if not isinstance(v, dict) else amount_of(v)
        oid = digits(pick(d, "order_id", "orderid", "order", "order_no", "order_number"))
        if not oid:
            continue
        blob = f"{ctx} {' '.join(map(str, d.keys()))} {pick(d, 'type', 'kind', 'category', 'event') or ''}".lower()
        status = pick(d, "status", "state")
        rec: dict[str, Any] = {
            **d,
            "order_id": oid,
            "amount": num(pick(d, "amount", "refund_amount", "hold_amount", "disputed_amount", "chargeback_amount")),
            "status": str(status).upper() if status is not None else None,
        }
        if (txn := digits(pick(d, "txn_id", "txnid", "transaction_id"))) is not None:
            rec["txn_id"] = txn
        if (due := num(pick(d, "pod_due_in_hours", "pod_due_hours", "pod_deadline_hours", "due_in_hours"))) is not None:
            rec["pod_due_in_hours"] = due
        if any(w in blob for w in ("chargeback", "dispute", "hold")) or rec["status"] in ("HELD", "RELEASED"):
            chargebacks.setdefault(oid, rec)
        elif "refund" in blob or rec["status"] in ("PROCESSED", "INITIATED", "REFUNDED"):
            refunds.setdefault(oid, rec)
    return refunds, chargebacks, limit


def _loan(raw: Any) -> tuple[dict, list[str]]:
    l = raw
    if isinstance(pick(raw, "loan"), dict):
        l = pick(raw, "loan")
    if isinstance(pick(raw, "loans"), list):
        l = pick(raw, "loans")[0]
    out = {
        "edi_per_day": num(pick(l, "edi_per_day", "edi", "daily_edi", "edi_amount", "edi_daily", "daily_edi_amount",
                                "daily_deduction")),
        "balance": num(pick(l, "balance", "outstanding", "outstanding_balance", "balance_outstanding",
                            "principal_outstanding", "remaining_balance", "loan_balance")),
        "next_deduction": pick(l, "next_deduction", "next_deduction_date", "next_edi_date", "next_edi", "next_debit"),
    }
    if out["edi_per_day"] is None and out["balance"] is None:
        raise Unusable("no EDI / balance found")
    fell = [k for k in ("edi_per_day", "balance") if out[k] is None]  # next_deduction is optional: silent default
    for k in (*fell, "next_deduction"):
        if out[k] is None:
            out[k] = BUILTIN_LOAN[k]
    for k in ("loan_id", "lender", "tenure_days", "sanctioned_amount"):
        if (v := pick(l, k)) is not None:
            out[k] = v
    return out, fell


def _fees(raw: Any) -> tuple[dict, list[str]]:
    rates_raw = pick(raw, "mdr_rates", "mdr", "rates", "mdr_rules", "mdr_slabs")
    rates: dict[str, Any] = {}
    if isinstance(rates_raw, dict):
        for k, v in rates_raw.items():
            p = pct(v)
            rates[str(k)] = f"{p}%" if p is not None else v
    elif isinstance(rates_raw, list):
        for item in rates_raw:
            if not isinstance(item, dict):
                continue
            name = pick(item, "instrument", "mode", "method", "payment_mode", "channel", "name", "type")
            p = pct(pick(item, "rate", "mdr", "mdr_rate", "pct", "percent", "rate_pct"))
            if name is not None:
                rates[str(name)] = f"{p}%" if p is not None else None
    gst = pct(pick(raw, "gst_rate", "gst_rate_pct", "gst_pct", "gst_percent", "gst_on_mdr_rate", "gst_on_mdr", "gst"))
    out: dict[str, Any] = {"mdr_rates": rates or None, "gst_rate_pct": gst}
    if out["mdr_rates"] is None and gst is None:
        raise Unusable("no MDR rates / GST rate found")
    fell = [k for k, v in out.items() if v is None]
    for k in fell:
        out[k] = BUILTIN_FEES[k]
    return out, fell


_TEXT_KEYS = ("text", "utterance", "phrase", "query", "hinglish", "hindi", "devanagari", "romanised", "romanized",
              "transcript", "example", "sentence")


def _flag(v: Any) -> bool:
    """A boolean-ish preset flag (True / 1 / "yes"). A *string* under a chip key is chip text, not a flag."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v == 1
    return isinstance(v, str) and v.strip().lower() in ("true", "yes", "y", "1")


def _utterances(raw: Any) -> tuple[list[dict], list[str]]:
    out: list[dict] = []
    index: dict[tuple[str, str], dict] = {}

    def add(text: Any, intent: Optional[str], preset: bool, chip: Any = None) -> None:
        if not (isinstance(text, str) and text.strip() and intent in INTENTS):
            return
        key = (text.strip(), intent)
        if key in index:
            index[key]["preset"] = index[key]["preset"] or preset
            return
        rec: dict[str, Any] = {"text": text.strip(), "intent": intent, "preset": preset}
        if isinstance(chip, str) and chip.strip():
            rec["chip_label"] = chip.strip()
        index[key] = rec
        out.append(rec)

    def visit(obj: Any, intent: Optional[str], preset: bool) -> None:
        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, str):
                    add(item, intent, preset)
                else:
                    visit(item, intent, preset)
            return
        if not isinstance(obj, dict):
            return
        own = str(pick(obj, "intent", "expected_intent", "label") or "").strip().upper()
        cur_intent = own if own in INTENTS else intent
        cur_preset = preset or any(
            ("preset" in _norm_key(k) or "chip" in _norm_key(k)) and _flag(v)
            for k, v in obj.items() if not isinstance(v, (dict, list))
        )
        chip = pick(obj, "chip_label", "chip_text", "chip", "display", "title", "button")
        for tk in _TEXT_KEYS:
            add(pick(obj, tk), cur_intent, cur_preset, chip)
        for k, v in obj.items():
            ku, kn = str(k).strip().upper(), _norm_key(k)
            child_intent = ku if ku in INTENTS else cur_intent
            child_preset = cur_preset or "preset" in kn or "chip" in kn
            if isinstance(v, (dict, list)):
                visit(v, child_intent, child_preset)
            elif isinstance(v, str) and ku in INTENTS:
                add(v, ku, cur_preset)
            elif isinstance(v, str) and ("preset" in kn or "chip" in kn) and kn not in ("chiplabel", "chiptext"):
                add(v, cur_intent, True)

    visit(raw, None, False)
    if not out:
        raise Unusable("no utterances with a recognised intent")
    return out, []


_HISTORY_BLOCKS = ("historical_profile", "historical_memory", "history", "merchant_history", "six_month_history",
                   "profile", "business_profile")
_HISTORY_SCALARS: dict[str, tuple[str, ...]] = {  # headline numbers: reported if they fall back
    "daily_avg_sales": ("daily_avg_sales", "avg_daily_sales", "daily_average_sales", "daily_avg", "average_daily_sales"),
    "weekend_multiplier": ("weekend_multiplier", "weekend_peak_multiplier", "weekend_spike", "weekend_uplift"),
    "past_edi_success_rate": ("past_edi_success_rate", "edi_success_rate", "edi_success_pct", "edi_repayment_rate"),
    "supplier_payable_tomorrow": ("supplier_payable_tomorrow", "tomorrow_stock_payable", "stock_payable_tomorrow",
                                  "supplier_payables_tomorrow", "tomorrow_stock_due", "stock_due_tomorrow"),
    "active_lender": ("active_lender", "lender", "nbfc", "partner_nbfc"),
}
_HISTORY_EXTRAS: dict[str, tuple[str, ...]] = {  # optional detail: silent default
    "window": ("window", "period", "data_window"),
    "weekend_days": ("weekend_days", "peak_days"),
    "kfs": ("kfs", "kfs_terms", "active_loan_kfs", "loan_kfs"),
    "monthly_sales": ("monthly_sales", "sales_by_month", "monthly_gross", "six_month_sales"),
    "recent_daily_sales": ("recent_daily_sales", "daily_sales", "last_7_days", "recent_sales", "daily_gross"),
    "mandate": ("mandate", "enach", "emandate", "edi_mandate"),
    "recent_customers": ("recent_customers", "customers", "top_customers", "repeat_customers"),
    "duplicate_payments": ("duplicate_payments", "duplicates", "double_payments"),
    "past_disputes": ("past_disputes", "dispute_history", "disputes", "chargeback_history"),
    "connectors": ("connectors", "consented_connectors", "integrations"),
    "bank_account": ("bank_account", "settlement_account", "bank"),
    "soundbox_diagnostics": ("soundbox_diagnostics", "device_diagnostics", "soundbox_health", "device_logs"),
    "soundbox_plan": ("soundbox_plan", "soundbox_rental", "device_plan"),
    "growth_offer": ("growth_offer", "credit_offer", "working_capital_offer", "preapproved_offer"),
    "cashflow": ("cashflow", "cash_flow", "liquidity", "cashflow_forecast"),
    "strategy_priors": ("strategy_priors", "intervention_outcomes", "strategy_memory"),
}


def _multiplier(v: Any) -> Optional[Number]:
    """2.3 / "2.3x" / "2.3x (Fri–Sun)" -> 2.3"""
    if (n := num(v)) is not None:
        return n
    m = re.search(r"\d+(?:\.\d+)?", str(v)) if isinstance(v, str) else None
    return num(m.group(0)) if m else None


def _series(v: Any, key: str) -> Optional[list[dict]]:
    """[{month|date, sales}] from a list of dicts or a {period: amount} dict."""
    rows: list[dict] = []
    if isinstance(v, dict):
        v = [{key: k, **(x if isinstance(x, dict) else {"sales": x})} for k, x in v.items()]
    for x in v if isinstance(v, list) else []:
        if not isinstance(x, dict):
            continue
        period, amount = pick(x, key, "date", "month", "period", "day"), num(pick(x, "sales", "gross", "amount", "total", "value"))
        if period is None or amount is None:
            continue
        note = pick(x, "note", "event", "reason", "remark")
        dip = x.get("dip") is True or bool(note and re.search(r"rain|flood|bandh|holiday|strike|curfew|dip", str(note), re.I))
        rows.append({**x, key: str(period), "sales": amount, **({"note": note} if note else {}), **({"dip": True} if dip else {})})
    return rows or None


def _connectors(v: Any) -> Optional[dict]:
    if isinstance(v, list):
        v = {str(pick(c, "name", "connector", "id")): c for c in v if isinstance(c, dict) and pick(c, "name", "connector", "id")}
    if not isinstance(v, dict):
        return None
    out = {}
    for name, c in v.items():
        c = c if isinstance(c, dict) else {"status": c}
        out[_head(name)] = {**c, "status": str(pick(c, "status", "state") or "ACTIVE").upper(),
                            "consent": str(pick(c, "consent", "dpdp_consent", "consent_status") or "GRANTED").upper()}
    return out


def _history(raw: Any) -> tuple[dict, list[str]]:
    h = raw
    for k in _HISTORY_BLOCKS:
        if isinstance(pick(raw, k), dict):
            h = pick(raw, k)
            break
    if not isinstance(h, dict):
        raise Unusable("not a JSON object")
    out: dict[str, Any] = json.loads(json.dumps(BUILTIN_HISTORY))
    found: list[str] = []
    for key, names in _HISTORY_SCALARS.items():
        v = pick(h, *names)
        if key == "weekend_multiplier":
            v = _multiplier(v)
        elif key == "past_edi_success_rate":
            v = pct(v)
        elif key == "active_lender":
            v = str(v) if isinstance(v, (str, int)) else pick(v, "name", "lender") if isinstance(v, dict) else None
        elif v is not None:
            v = num(v)
        if v is not None:
            out[key] = v
            found.append(key)
    for key, names in _HISTORY_EXTRAS.items():
        v = pick(h, *names)
        if key in ("monthly_sales", "recent_daily_sales"):
            v = _series(v, "month" if key == "monthly_sales" else "date")
        elif key == "connectors":
            v = _connectors(v)
        if v is not None:
            out[key] = v
            found.append(key)
    if (eligible := pick(h, "kfs_edi_holiday_eligible", "edi_holiday_eligible")) is not None:
        out["kfs"] = {**out["kfs"], "edi_holiday_eligible": _flag(eligible)}
        found.append("kfs")
    if not found:
        raise Unusable("no historical-profile fields found")
    return out, [k for k in _HISTORY_SCALARS if k not in found]


head_code = _head


def normalise_deductions(v: Any) -> list[dict]:
    """Settlement breakdown in any shape (list or {label: amount}) -> [{head, label, amount, ...}]."""
    return _deductions(v)


def normalise_loan(v: Any) -> Optional[dict]:
    try:
        return _loan(v)[0] if v else None
    except Unusable:
        return None


def golden_steps(raw: Any) -> list[dict]:
    """Best-effort view of golden_paths.json: [{name, text|file+doc_type, intent, status, gst_itc, fraud_alert}]."""
    steps: Any = raw
    if isinstance(raw, dict):
        steps = pick(raw, "steps", "golden_paths", "paths", "scenarios", "flows", "demo_steps", "cases")
        if steps is None:
            steps = [{"name": k, **v} for k, v in raw.items() if isinstance(v, dict)]
        elif isinstance(steps, dict):
            steps = [{"name": k, **v} if isinstance(v, dict) else v for k, v in steps.items()]
    out = []
    for i, st in enumerate(steps if isinstance(steps, list) else []):
        if not isinstance(st, dict):
            continue
        inp = pick(st, "input", "trigger", "request", "action", "when", "given")
        src = inp if isinstance(inp, dict) else st
        text = inp if isinstance(inp, str) else pick(src, "text", "utterance", "query", "transcript", "input_text",
                                                      "say", "message", "trigger")
        file = pick(src, "file", "test_file", "upload", "filename", "document", "doc", "image", "attachment")
        doc_type = pick(src, "doc_type", "document_type")
        if isinstance(file, dict):
            doc_type = doc_type or pick(file, "doc_type", "type")
            file = pick(file, "path", "file", "name", "filename")
        if file and not doc_type:
            f = str(file).lower()
            doc_type = "pod" if "pod" in f else "upi_screenshot" if re.search(r"upi|screenshot|fake", f) else None
        exp = pick(st, "expected", "expect", "expected_result", "expected_results", "result", "then", "assert", "output")
        exp = exp if isinstance(exp, dict) else st
        intent = str(pick(exp, "intent", "expected_intent") or "").strip().upper()
        out.append({
            "name": str(pick(st, "name", "title", "step", "id") or f"step_{i + 1}"),
            "text": text if isinstance(text, str) else None,
            "file": str(file) if file else None,
            "doc_type": doc_type if doc_type in ("pod", "upi_screenshot") else None,
            "intent": intent if intent in INTENTS else None,
            "status": pick(exp, "status", "paytm_status", "expected_status", "final_status", "ledger_status",
                           "chargeback_status", "utr_status"),
            "gst_itc": amount_of(pick(exp, "gst_itc", "gst_itc_logged", "itc", "itc_logged", "gst_itc_amount")),
            "fraud_alert": pick(exp, "fraud_alert", "fraud", "fraud_flag", "fraud_alert_raised"),
        })
    return out


# ----------------------------------------------------------------------------- dataset object


@dataclass
class Dataset:
    root: Path
    sources: dict[str, str] = field(default_factory=dict)
    merchant: dict[str, Any] = field(default_factory=lambda: dict(BUILTIN_MERCHANT))
    settlement: dict[str, Any] = field(default_factory=lambda: json.loads(json.dumps(BUILTIN_SETTLEMENT)))
    utrs: dict[str, dict] = field(default_factory=lambda: json.loads(json.dumps(BUILTIN_UTRS)))
    refunds: dict[str, dict] = field(default_factory=lambda: json.loads(json.dumps(BUILTIN_REFUNDS)))
    chargebacks: dict[str, dict] = field(default_factory=lambda: json.loads(json.dumps(BUILTIN_CHARGEBACKS)))
    refund_limit: Number = BUILTIN_REFUND_LIMIT
    loan: dict[str, Any] = field(default_factory=lambda: dict(BUILTIN_LOAN))
    fees: dict[str, Any] = field(default_factory=lambda: json.loads(json.dumps(BUILTIN_FEES)))
    initial_chargeback_status: dict[str, str] = field(default_factory=dict)
    utterances: list[dict] = field(default_factory=lambda: json.loads(json.dumps(BUILTIN_UTTERANCES)))
    history: dict[str, Any] = field(default_factory=lambda: json.loads(json.dumps(BUILTIN_HISTORY)))
    golden_raw: Any = None

    def routing_utterances(self) -> list[dict]:
        """Dataset utterances + built-in examples for any intent the dataset doesn't cover yet."""
        covered = {u["intent"] for u in self.utterances}
        return self.utterances + [u for u in BUILTIN_UTTERANCES if u["intent"] not in covered]

    def connector(self, name: str) -> Optional[dict]:
        c = (self.history.get("connectors") or {}).get(_head(name))
        return c if c and c.get("status") == "ACTIVE" and c.get("consent") == "GRANTED" else None

    def duplicate_payment(self, order_id: Optional[str] = None) -> Optional[dict]:
        dups = [x for x in self.history.get("duplicate_payments") or [] if isinstance(x, dict)]
        if order_id:
            return next((x for x in dups if digits(pick(x, "order_id", "order")) == order_id), None)
        return dups[0] if dups else None

    def history_utr(self, utr: str) -> Optional[dict]:
        """UTRs that only appear in history (e.g. the duplicate payment's two UTRs)."""
        for dup in self.history.get("duplicate_payments") or []:
            if isinstance(dup, dict) and utr in [str(u) for u in dup.get("utrs") or []]:
                return {"utr_number": utr, "amount": num(dup.get("amount")), "payer_app": dup.get("payer_app"),
                        "status": "SUCCESS", "order_id": dup.get("order_id"), "note": "duplicate payment"}
        return None

    # -- lookups -------------------------------------------------------------
    def deduction(self, *needles: str) -> Optional[dict]:
        """First settlement deduction whose head contains any needle (e.g. 'GST', 'CHARGEBACK')."""
        for d in self.settlement["deductions"]:
            if any(n in d["head"] for n in needles):
                return d
        return None

    def deduction_amount(self, *needles: str) -> Optional[Number]:
        d = self.deduction(*needles)
        return d["amount"] if d else None

    def chargeback(self, order_id: Optional[str] = None) -> Optional[dict]:
        if order_id:
            return self.chargebacks.get(order_id) or next(
                (c for c in self.chargebacks.values() if c.get("txn_id") == order_id), None)
        return next(iter(self.chargebacks.values()), None)

    def refund(self, order_id: Optional[str] = None) -> Optional[dict]:
        return self.refunds.get(order_id) if order_id else next(iter(self.refunds.values()), None)

    def gst_basis(self) -> str:
        mdr = self.deduction_amount("MDR")
        return f"{self.fees['gst_rate_pct']}% GST on MDR" + (f" ₹{_inr_commas(mdr)}" if mdr else "") + " (ITC eligible)"

    def gst_itc(self) -> Optional[dict]:
        gst = self.deduction_amount("GST")
        if not gst:
            return None
        return {"amount": gst, "settlement_date": self.settlement["settlement_date"], "basis": self.gst_basis(),
                "itc_eligible": True, "gstin": self.merchant.get("gstin")}

    def order_ids(self) -> set[str]:
        ids = set(self.refunds) | set(self.chargebacks)
        ids |= {c["txn_id"] for c in self.chargebacks.values() if c.get("txn_id")}
        return ids

    def presets(self) -> list[dict]:
        return [u for u in self.utterances if u.get("preset")]

    def golden_steps(self) -> list[dict]:
        return golden_steps(self.golden_raw) if self.golden_raw is not None else []

    def test_file(self, name: str) -> Optional[Path]:
        p = Path(name)
        samples = _REPO / "services" / "sarvam_service" / "app" / "samples"  # Person 1's connector documents
        for cand in (self.root / p, self.root / "test_files" / p.name, samples / p.name):
            if cand.is_file():
                return cand
        return None

    def checks(self) -> list[dict]:
        s = self.settlement
        g, n, v = s["gross"], s["net_bank_credit"], s["variance"]
        dsum = sum(d["amount"] for d in s["deductions"])
        return [
            {"check": "gross - net_bank_credit == variance", "ok": abs((g - n) - v) < 0.01, "detail": f"{g} - {n} = {g - n} vs {v}"},
            {"check": "sum(deductions) == variance", "ok": abs(dsum - v) < 0.01, "detail": f"{dsum} vs {v}"},
        ]

    def status(self) -> dict:
        return {
            "dir": str(self.root),
            "found": self.root.is_dir(),
            "files": dict(self.sources),
            "checks": self.checks(),
            "counts": {
                "utrs": len(self.utrs),
                "refunds": len(self.refunds),
                "chargebacks": len(self.chargebacks),
                "utterances": len(self.utterances),
                "presets": len(self.presets()),
                "golden_steps": len(self.golden_steps()),
            },
        }


def _resolve(root: Optional[Union[str, Path]]) -> Path:
    p = Path(root) if root else Path(os.getenv("DATASET_DIR") or DEFAULT_ROOT)
    return p if p.is_absolute() else (HERE / p).resolve()


def load(root: Optional[Union[str, Path]] = None) -> Dataset:
    ds = Dataset(root=_resolve(root))
    raw: dict[str, Any] = {}
    seed_dir = ds.root / "seed"
    if seed_adapter.is_team_seed(seed_dir):  # data/seed layout (CSV + JSON)
        raw, used = seed_adapter.build_raw(seed_dir)
        for key in FILES:
            ds.sources[key] = used.get(key, "builtin (missing)")
    for key, rel in (() if raw else FILES.items()):
        path = ds.root / rel
        if not path.is_file():
            ds.sources[key] = "builtin (missing)"
            continue
        try:
            raw[key] = json.loads(path.read_text(encoding="utf-8-sig"))
            ds.sources[key] = "dataset"
        except Exception as exc:  # noqa: BLE001 - a broken file must never take the service down
            ds.sources[key] = f"builtin (unreadable: {type(exc).__name__}: {exc})"[:240]

    def section(key: str, fn: Any) -> Any:
        if key not in raw:
            return None
        try:
            value, fell = fn(raw[key])
        except Exception as exc:  # noqa: BLE001
            ds.sources[key] = f"builtin (unusable: {exc})"[:240]
            return None
        if fell:
            ds.sources[key] = f"dataset (builtin for: {', '.join(fell)})"
        return value

    if (v := section("merchant", _merchant)) is not None:
        ds.merchant = v
    if (v := section("settlement", _settlement)) is not None:
        ds.settlement = v
    if (v := section("transactions", _utrs)) is not None:
        ds.utrs = v
    if (v := section("loan", _loan)) is not None:
        ds.loan = v
    if (v := section("fee_rules", _fees)) is not None:
        ds.fees = v
    if (v := section("utterances", _utterances)) is not None:
        ds.utterances = v
    if "history" not in raw and isinstance(raw.get("merchant"), dict) and any(
            pick(raw["merchant"], k) is not None for k in (*_HISTORY_BLOCKS, *_HISTORY_SCALARS["daily_avg_sales"])):
        raw["history"] = raw["merchant"]  # profile embedded in merchant.json
        ds.sources["history"] = "dataset (from merchant.json)"
    if (v := section("history", _history)) is not None:
        ds.history = v

    if "refunds_orders" in raw:
        try:
            refunds, chargebacks, limit = _orders(raw["refunds_orders"])
            fell = [name for name, val in (("refunds", refunds), ("chargebacks", chargebacks), ("refund_limit", limit))
                    if not val]
            if len(fell) == 3:
                raise Unusable("no refunds / chargebacks / refund limit found")
            ds.refunds = refunds or ds.refunds
            ds.chargebacks = chargebacks or ds.chargebacks
            ds.refund_limit = limit if limit else ds.refund_limit
            if fell:
                ds.sources["refunds_orders"] = f"dataset (builtin for: {', '.join(fell)})"
        except Exception as exc:  # noqa: BLE001
            ds.sources["refunds_orders"] = f"builtin (unusable: {exc})"[:240]

    ds.initial_chargeback_status = {oid: c["status"] for oid, c in ds.chargebacks.items() if c.get("status")}
    if "initial_state" in raw:  # reset target, e.g. chargeback #9981 -> HELD
        try:
            _, initial_cbs, _ = _orders(raw["initial_state"])
            ds.initial_chargeback_status.update({oid: c["status"] for oid, c in initial_cbs.items() if c.get("status")})
        except Exception as exc:  # noqa: BLE001
            ds.sources["initial_state"] = f"builtin (unusable: {exc})"[:240]

    if "golden_paths" in raw:
        ds.golden_raw = raw["golden_paths"]
        if not ds.golden_steps():
            ds.sources["golden_paths"] = "dataset (no steps recognised)"

    fallbacks = {k: v for k, v in ds.sources.items() if not v.startswith("dataset") or "builtin for" in v}
    if fallbacks and ds.root.is_dir():
        log.warning("Dataset %s: using built-in seed for %s", ds.root, fallbacks)
    elif not ds.root.is_dir():
        log.info("Dataset folder %s not found; using built-in CONTRACT.md seed", ds.root)
    return ds


_root_override: Optional[Path] = None


def reload(root: Optional[Union[str, Path]] = None) -> Dataset:
    """Reload from disk. Passing `root` switches folders (used by tests); later reloads keep it."""
    global DATA, _root_override
    if root is not None:
        _root_override = Path(root)
    DATA = load(_root_override)
    return DATA


DATA: Dataset = load()
