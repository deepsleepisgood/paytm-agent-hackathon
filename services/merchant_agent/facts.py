"""A compact, read-only snapshot of the merchant's own books, for open questions (INFO_QUERY).

"मेरा अगला settlement कब आएगा?" fits none of the 14 action intents, and the buddy used to refuse it.
These facts let the LLM answer such questions from real data; every number in its answer is checked against
this snapshot (pipeline.ungrounded_numbers). Built from <dataset>/seed/*.csv when present, else the built-in data.
"""
from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import dataset_loader as dl
from state import STATE


def _rows(name: str) -> list[dict[str, str]]:
    p = Path(dl.DATA.root) / "seed" / name
    if not p.is_file():
        return []
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(v: Any) -> Any:
    try:
        f = float(v)
        return int(f) if f == int(f) else round(f, 2)
    except (TypeError, ValueError):
        return v


@lru_cache(maxsize=4)
def _snapshot(root: str) -> dict[str, Any]:
    d, h = dl.DATA, dl.DATA.history
    prof: dict[str, Any] = {}
    p = Path(root) / "seed" / "merchant_profile.json"
    if p.is_file():
        prof = json.loads(p.read_text(encoding="utf-8"))
    as_of = str(prof.get("as_of") or "")[:10] or date.today().isoformat()
    today = datetime.fromisoformat(as_of).date()

    stl = _rows("settlements.csv")
    last = [{"settlement_date": r["settlement_date"], "for_sales_of": r["txn_date"], "gross": _num(r["gross"]),
             "deductions": _num(r["variance"]), "bank_credit": _num(r["net_credit"]), "credited_at": r["credited_at"],
             "status": r["status"]} for r in stl[-3:]]
    sales = _rows("daily_sales_summary.csv")
    week = [{"date": r.get("date"), "day": r.get("weekday") or r.get("day"), "sales": _num(r.get("gross_sales") or r.get("gross") or list(r.values())[2]),
             "note": (r.get("notes") or r.get("note") or "")[:80]} for r in sales[-7:]]
    txns_today = [r for r in _rows("transactions.csv") if r.get("timestamp", "").startswith(as_of)]
    edi = _rows("edi_schedule.csv")
    payables = [r for r in _rows("supplier_payables.csv") if (r.get("due_date") or "") >= as_of][:3]

    cycle = (prof.get("settlement") or {}).get("cycle") or "T+1"
    snap = {
        "today": as_of,
        "merchant": {"name": d.merchant.get("name"), "mid": d.merchant.get("mid"), "store_hours": prof.get("store_hours")},
        "settlement": {
            "cycle": cycle, "bank_account": (prof.get("settlement") or {}).get("bank"),
            "next_settlement": {"date": (today + timedelta(days=1)).isoformat(), "time": "around 08:00",
                                "for_sales_of": as_of, "amount": "depends on today's sales (not final yet)"},
            "recent": last,
        },
        "sales": {"daily_average": h.get("daily_avg_sales"), "weekend_multiplier": h.get("weekend_multiplier"),
                  "last_7_days": week,
                  "today_so_far": {"transactions": len(txns_today),
                                   "amount": int(sum(float(r.get("amount") or 0) for r in txns_today))}},
        "loan": {"lender": d.loan.get("lender") or h.get("active_lender"), "balance": d.loan.get("balance"),
                 "daily_edi": d.loan.get("edi_per_day"),
                 "last_edi": ({"date": edi[-1].get("edi_date"), "status": edi[-1].get("status")} if edi else None),
                 "next_edi_date": as_of},
        "open_chargebacks": [{"order_id": oid, "amount": cb.get("amount"), "status": cb.get("status", "HELD")}
                             for oid, cb in d.chargebacks.items()],
        "soundbox": {"rent_per_month": d.deduction_amount("SOUNDBOX", "RENTAL") or 149},
        "fees": {"mdr_rates": d.fees.get("mdr_rates"), "gst_on_mdr_pct": d.fees.get("gst_rate_pct")},
        "supplier_payables_due": [{"supplier": r.get("supplier") or r.get("supplier_name"), "amount": _num(r.get("amount")),
                                   "due": r.get("due_date")} for r in payables],
    }
    return snap


def merchant_facts() -> dict[str, Any]:
    snap = json.loads(json.dumps(_snapshot(str(dl.DATA.root)), default=str))
    snap["loan"]["edi_status_now"] = STATE.loan_edi_status  # live: changes when the EDI is paused
    return snap


def reset() -> None:
    _snapshot.cache_clear()
