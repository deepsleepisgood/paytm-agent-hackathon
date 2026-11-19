"""Adapter for the team dataset as it actually landed: `<repo>/data/seed/` (CSV + JSON, see its README).

It converts those files into the raw per-section shapes `dataset_loader` already normalises
(merchant, settlement, transactions, refunds_orders, loan, fee_rules, initial_state, utterances,
golden_paths, history), so everything downstream reads the real seed through one path.
Standard library only (csv/json); UTRs stay strings.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

MARKER = "merchant_profile.json"  # a seed folder in this layout has this file


def is_team_seed(seed_dir: Path) -> bool:
    return (seed_dir / MARKER).is_file()


def _json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _csv(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _int(v: Any) -> Optional[int]:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _true(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def _weekday(iso: str) -> int:
    from datetime import date
    return date.fromisoformat(iso[:10]).weekday()


def _order_from(text: Any) -> Optional[str]:
    m = re.search(r"ORDER\s*#\s*(\d+)", str(text or ""), re.I)
    return m.group(1) if m else None


def build_raw(seed: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """(raw sections, {section: source file(s)}). A section is skipped if its files are missing or broken."""
    raw: dict[str, Any] = {}
    used: dict[str, str] = {}

    def section(name: str, files: str, fn) -> None:
        try:
            raw[name] = fn()
            used[name] = f"dataset (data/seed: {files})"
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001 - one broken file must not hide the others
            used[name] = f"builtin (unreadable: {type(exc).__name__}: {exc})"[:240]

    profile = _json(seed / MARKER) if (seed / MARKER).is_file() else {}

    def merchant():
        sb = next((d for d in profile.get("devices") or [] if "soundbox" in str(d.get("type", "")).lower()), None)
        return {"mid": profile["mid"], "name": profile["name"], "gstin": profile.get("gstin"), "soundbox": sb}

    def settlement():
        b = _json(seed / "settlement_breakdown_2026-11-18.json")
        deductions = []
        for d in b["deductions"]:
            rec = {**d}
            if (oid := _order_from(d.get("source"))) is not None:
                rec["order_id"] = oid
            if "CHARGEBACK" in str(d.get("type")).upper() and oid:
                rec["txn_id"] = oid  # CONTRACT.md calls the dispute TXNID #9981
            deductions.append(rec)
        return {"settlement_date": b["settlement_date"], "gross": b["gross"], "net_credit": b["net_credit"],
                "variance": b["variance"], "deductions": deductions, "gross_mix": b.get("by_rail")}

    def transactions():
        return {"transactions": [{"utr": r["utr"], "amount": r["amount"], "payer_app": r["payer_app"],
                                  "status": r["npci_status"], "order_id": r.get("order_id"),
                                  "customer_id": r.get("customer_id"), "flag": r.get("flag") or None}
                                 for r in _csv(seed / "utr_ledger.csv") if r.get("utr")]}

    def refunds_orders():
        refunds = [{"order_id": r["order_id"], "amount": r["amount"], "status": r["status"], "refund_id": r["refund_id"],
                    "reason": r.get("reason")} for r in _csv(seed / "refunds.csv")]
        cbs = [{"order_id": r["order_id"], "txn_id": r["order_id"], "payment_txn_id": r["txn_id"], "amount": r["amount"],
                "status": r["status"], "pod_due_in_hours": 48, "chargeback_id": r["chargeback_id"],
                "evidence": r.get("evidence"), "pod_awb": r.get("pod_awb")}
               for r in _csv(seed / "chargebacks.csv") if r["status"] == "HELD"]
        return {"refunds": refunds, "chargebacks": cbs, "policy": {"autonomous_refund_limit": 5000}}

    def loan():
        return _json(seed / "loan.json")

    def fee_rules():
        return {"mdr_rates": (profile.get("settlement") or {}).get("mdr_rates"), "gst_rate_pct": 18}

    def initial_state():
        return {"chargebacks": [{"order_id": r["order_id"], "status": r["status"]}
                                for r in _csv(seed / "chargebacks.csv") if r["status"] == "HELD"]}

    scenarios = _json(seed / "scenarios.json").get("scenarios", []) if (seed / "scenarios.json").is_file() else []

    def utterances():
        return [{"intent": s["intent"], "text": s["trigger_hinglish"], "preset": True}
                for s in scenarios if s.get("trigger_hinglish")]

    def golden():
        return {"steps": [{"name": s["intent"], "text": s["trigger_hinglish"], "expected": {"intent": s["intent"]}}
                          for s in scenarios if s.get("trigger_hinglish")]}

    section("merchant", MARKER, merchant)
    section("settlement", "settlement_breakdown_2026-11-18.json", settlement)
    section("transactions", "utr_ledger.csv", transactions)
    section("refunds_orders", "refunds.csv, chargebacks.csv", refunds_orders)
    section("loan", "loan.json", loan)
    section("fee_rules", MARKER, fee_rules)
    section("initial_state", "chargebacks.csv", initial_state)
    if scenarios:
        section("utterances", "scenarios.json", utterances)
        section("golden_paths", "scenarios.json", golden)
    section("history", "merchant_profile.json + CSVs", lambda: _history(seed, profile))
    return raw, used


def _history(seed: Path, profile: dict[str, Any]) -> dict[str, Any]:
    h: dict[str, Any] = dict(profile.get("historical_memory") or {})
    h["window"] = "2026-05-19 to 2026-11-18"
    customers = {r["customer_id"]: r for r in _csv(seed / "customers.csv")} if (seed / "customers.csv").is_file() else {}

    h["recent_customers"] = [{"name": c.get("name"), "customer_id": c.get("customer_id"),
                              "spend_6m": c.get("six_month_spend")} for c in profile.get("recent_customers") or []]
    h["connectors"] = [{"name": c["name"], "status": c.get("status"), "consent": c.get("dpdp_consent"),
                        "holds": c.get("holds"),
                        **({"holds_pod_for": re.findall(r"#\s*(\d+)", c.get("holds", ""))} if "SHIPROCKET" in c["name"] else {})}
                       for c in profile.get("connectors") or []]
    acct = (profile.get("settlement") or {}).get("bank")
    h["bank_account"] = {"bank": None, "account_masked": str(acct or "").split(" ")[0] or None,
                         "status": "ACTIVE", "kyc_status": "VERIFIED"}

    if (seed / "daily_sales_summary.csv").is_file():
        days = _csv(seed / "daily_sales_summary.csv")
        months: dict[str, int] = defaultdict(int)
        for r in days:
            months[r["date"][:7]] += _int(r["gross"]) or 0
        h["monthly_sales"] = [{"month": m, "sales": v} for m, v in sorted(months.items())]
        first, last = days[0]["date"][:7], days[-1]["date"][:7]
        for m in h["monthly_sales"]:  # partial first/last months are flagged so trend uses full months only
            if m["month"] in (first, last):
                m["note"] = "month to date" if m["month"] == last else "partial month"
        unusual = ("rain_dip", "closure_dip", "bulk_order_day", "is_festival")
        recent = []
        for r in days[-8:]:
            dip = _true(r.get("closure_dip")) or _true(r.get("rain_dip"))
            # Expected = mean of the same weekday over the 4 previous ordinary weeks, so a dip on a
            # Saturday is measured against a Saturday (Fri–Sun run 2.3x), not the flat daily average.
            wd = _weekday(r["date"])
            same = [_int(x["gross"]) or 0 for x in days if x["date"] < r["date"] and _weekday(x["date"]) == wd
                    and not any(_true(x.get(k)) for k in unusual)][-4:]
            rec = {"date": r["date"], "sales": _int(r["gross"])}
            if same:
                rec["expected"] = round(sum(same) / len(same))
            if r.get("note"):
                rec["note"] = r["note"]
            if dip:
                rec["dip"] = True
                rec["note"] = "market closure" if _true(r.get("closure_dip")) else "heavy rain"
            recent.append(rec)
        h["recent_daily_sales"] = recent
        bulk = days[-2] if days and _true(days[-2].get("bulk_order_day")) else None
        if bulk:
            h["recent_daily_sales"][-2]["note"] = "bulk order + market reopened"

    loan = _json(seed / "loan.json") if (seed / "loan.json").is_file() else {}
    kfs = loan.get("kfs") or {}
    h["kfs"] = {"edi_holiday_eligible": bool((profile.get("historical_memory") or {}).get("kfs_edi_holiday_eligible", True)),
                "max_pause_days": 2, "clause": "4.2", "apr_percent": kfs.get("apr_percent")}
    if (seed / "edi_schedule.csv").is_file():
        edis = _csv(seed / "edi_schedule.csv")
        bounced = [r for r in edis if r["status"] == "BOUNCED"]
        last = bounced[-1] if bounced else {}
        h["mandate"] = {"type": "eNACH", "edi_amount": _int(last.get("amount")) or 500,
                        "last_status": "BOUNCED" if bounced else "ACTIVE", "bounce_reason": last.get("bounce_code"),
                        "bounce_date": last.get("edi_date"), "context": last.get("context"),
                        "missed_edis_6m": len(bounced), "edis_6m": len(edis)}

    if (seed / "utr_ledger.csv").is_file():
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in _csv(seed / "utr_ledger.csv"):
            if (r.get("flag") or "").upper() == "DUPLICATE":
                groups[r["order_id"]].append(r)
        h["duplicate_payments"] = [
            {"order_id": oid, "amount": _int(rows[0]["amount"]), "date": rows[0]["timestamp"][:10],
             "utrs": [r["utr"] for r in rows], "payer_app": rows[0]["payer_app"],
             "customer": (customers.get(rows[0]["customer_id"]) or {}).get("name"),
             "customer_id": rows[0]["customer_id"]}
            for oid, rows in groups.items()]
        visits = Counter(r["customer_id"] for r in _csv(seed / "utr_ledger.csv"))
        for dup in h["duplicate_payments"]:
            dup["customer_visits_6m"] = visits.get(dup["customer_id"])

    if (seed / "chargebacks.csv").is_file():
        h["past_disputes"] = [{"order_id": r["order_id"], "amount": _int(r["amount"]), "outcome": r["status"],
                               "pod_submitted": r["status"] != "HELD" and "pod" in (r.get("evidence") or "").lower()}
                              for r in _csv(seed / "chargebacks.csv") if r["status"] in ("WON", "LOST")]

    if (seed / "device_logs.csv").is_file():
        logs = _csv(seed / "device_logs.csv")
        day = logs[-24:]
        last = logs[-1]
        h["soundbox_diagnostics"] = {
            "device_id": last["device_id"], "battery_pct": min(_int(r["battery_pct"]) or 0 for r in day),
            "battery_health_pct": _int(last["battery_health_pct"]),
            "network": f"drops to {'offline' if any(r['network'] == 'offline' for r in day) else '2G'}",
            "heartbeats_missed_24h": sum(1 for r in day if not _true(r["heartbeat_ok"])),
            "announce_failures_24h": sum(_int(r["announce_failures"]) or 0 for r in day),
            "speaker_test": "FAILED" if any(_int(r["announce_failures"]) for r in day) else "OK",
            "last_heartbeat": last["ts"],
        }
    sb = next((d for d in profile.get("devices") or [] if "soundbox" in str(d.get("type", "")).lower()), {})
    h["soundbox_plan"] = {"rental_per_month": sb.get("rental_inr_per_month", 149), "months_active": None}

    if (seed / "refunds.csv").is_file():
        pending = [r for r in _csv(seed / "refunds.csv") if r["status"] == "REQUESTED"]
        if pending:
            h["cashflow"] = {"projected_net_payout_tomorrow": 1200,  # README: ₹4,700 collected − ₹3,500 refund #4490
                             "pending_refund": {"order_id": pending[-1]["order_id"], "amount": _int(pending[-1]["amount"])}}

    if (seed / "strategy_memory.json").is_file():
        h["strategy_priors"] = _priors(_json(seed / "strategy_memory.json"))
        h["learned_policies"] = _json(seed / "strategy_memory.json").get("learned_policies")
    return {"historical_profile": h}


# strategy_memory.json records options by letter. Only for the mandate memories do the letters
# ("A: reminder", "B: 1-tap UPI link", "C: escalate to collections") match advisor.OPTIONS; the other
# intents' letters mean different things, so they are not mapped (their population priors stay).
_LETTER_ACTION = {
    "MANDATE_TROUBLESHOOT": {"A": "SEND_REMINDER", "B": "UPI_LINK_48H_GRACE", "C": "ESCALATE_SPECIALIST"},
}


def _priors(sm: dict[str, Any]) -> dict[str, dict[str, list[int]]]:
    """Merchant-specific outcomes from strategy_memory.json, added on top of the population priors."""
    out: dict[str, dict[str, list[int]]] = defaultdict(dict)
    for m in sm.get("memories") or []:
        action = _LETTER_ACTION.get(m.get("intent"), {}).get(str(m.get("chosen", "")).strip()[:1])
        if not action:
            continue
        s, n = out[m["intent"]].get(action, [0, 0])
        out[m["intent"]][action] = [s + (1 if m.get("success") else 0), n + 1]
    return dict(out)
