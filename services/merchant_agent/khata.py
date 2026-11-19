"""Khata bookkeeping ledger: GET /merchant/khata-export (JSON or Tally-ready CSV).

Turns the merchant's settlement (gross sales, MDR, GST on MDR, refunds, rentals, holds, bank credit),
the GST ITC log and every money-moving action the buddy completed (chargeback released, duplicate
refunded, refund initiated, EDI paused) into double-entry vouchers that import into Tally as a journal:
one row per voucher with a debit ledger, a credit ledger and an amount.
"""
from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import dataset_loader as dl
from state import STATE

RECEIVABLE = "Paytm Settlement Receivable"
CSV_COLUMNS = ["Date", "Voucher Type", "Voucher No", "Debit Ledger", "Credit Ledger", "Amount",
               "GST ITC Eligible", "Reference", "Status", "Narration"]

# Settlement deduction head -> (debit ledger, voucher type)
_LEDGERS = (
    ("GST", "Input GST on MDR (ITC)"),
    ("MDR", "MDR Charges - Paytm"),
    ("REFUND", "Sales Returns - Customer Refunds"),
    ("SOUNDBOX", "Soundbox Rental Expense"),
    ("RENTAL", "Soundbox Rental Expense"),
    ("CHARGEBACK", "Chargeback Hold Receivable - Paytm"),
    ("HOLD", "Chargeback Hold Receivable - Paytm"),
    ("EDI", "Loan EDI - Lender"),
    ("LOAN", "Loan EDI - Lender"),
)


def _tally_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d-%m-%Y")
    except (TypeError, ValueError):
        return str(iso)


def _ledger_for(head: str, label: str) -> str:
    return next((ledger for needle, ledger in _LEDGERS if needle in head), f"{label} - Paytm deduction")


# ----------------------------------------------------------------------------- runtime entries


def record(intent: str, resp: dict[str, Any], request_id: str) -> Optional[dict[str, Any]]:
    """Add a khata entry for a completed money-moving action. Idempotent per (kind, reference)."""
    status = str(resp.get("status") or "").upper()
    data = resp.get("data") or {}
    today = dl.DATA.settlement["settlement_date"]
    entry: Optional[dict[str, Any]] = None
    if intent == "CHARGEBACK_RESOLVE" and status in ("RELEASED", "CHARGEBACK_REVERSED", "WON"):
        oid = str(data.get("order_id") or "")
        entry = {"kind": "CHARGEBACK_RELEASED", "reference": f"ORDER #{oid}", "amount": dl.num(data.get("amount")),
                 "voucher_type": "Journal", "debit": RECEIVABLE, "credit": "Chargeback Hold Receivable - Paytm",
                 "narration": f"Chargeback #{oid} won with PoD; hold released, credit in T+1 settlement"}
    elif intent == "DUPLICATE_RECONCILE" and status == "REFUND_INITIATED":
        entry = {"kind": "DUPLICATE_REFUND", "reference": f"ORDER #{data.get('order_id')} / UTR {data.get('refunded_utr')}",
                 "amount": dl.num(data.get("amount")), "voucher_type": "Payment",
                 "debit": "Customer Advance - Duplicate Payment", "credit": RECEIVABLE,
                 "narration": f"Duplicate payment by {data.get('customer') or 'customer'} refunded (T+1)"}
    elif intent == "REFUND_MANAGE" and status == "INITIATED":
        entry = {"kind": "REFUND_INITIATED", "reference": f"ORDER #{data.get('order_id')}",
                 "amount": dl.num(data.get("amount")), "voucher_type": "Journal",
                 "debit": "Sales Returns - Customer Refunds", "credit": RECEIVABLE,
                 "narration": "Customer refund initiated via Paytm; deducted from next settlement"}
    elif str(data.get("loan_edi_status") or "").upper().startswith("PAUSED"):
        art = (data.get("kfs_consent_artifact") or {}).get("artifact_id")
        entry = {"kind": "EDI_PAUSED", "reference": art or data.get("loan_edi_status"),
                 "amount": dl.num(data.get("edi_saved_inr")), "voucher_type": "Memorandum",
                 "debit": f"Loan - {data.get('nbfc') or 'Lender'}", "credit": "EDI Holiday (KFS clause 4.2)",
                 "narration": f"EDI paused {data.get('pause_days')} days, resumes {data.get('resume_date')}; "
                              "no cash movement (memo)"}
    if entry is None or entry["amount"] is None:
        return None
    if any(e["kind"] == entry["kind"] and e["reference"] == entry["reference"] for e in STATE.khata_entries):
        return None
    entry.update({"date": today, "request_id": request_id, "logged_at": time.time()})
    STATE.khata_entries.append(entry)
    return entry


# ----------------------------------------------------------------------------- export


def build() -> dict[str, Any]:
    d, h = dl.DATA, dl.DATA.history
    s = d.settlement
    sdate = s["settlement_date"]
    try:
        sales_date = (date.fromisoformat(sdate) - timedelta(days=1)).isoformat()
    except ValueError:
        sales_date = sdate
    bank = h.get("bank_account") or {}
    released = {e["reference"] for e in STATE.khata_entries if e["kind"] == "CHARGEBACK_RELEASED"}
    itc_logged = sum(dl.num(e.get("amount")) or 0 for e in STATE.local_gst_itc_log if e.get("settlement_date") == sdate)

    vouchers: list[dict[str, Any]] = []

    def add(vtype: str, debit: str, credit: str, amount: Any, narration: str, *, on: str = sdate,
            ref: str = "", status: str = "", itc: bool = False) -> None:
        vouchers.append({"date": on, "voucher_type": vtype, "voucher_no": f"PTM-{on.replace('-', '')}-{len(vouchers) + 1:03d}",
                         "debit_ledger": debit, "credit_ledger": credit, "amount": dl.num(amount),
                         "gst_itc_eligible": itc, "reference": ref, "status": status, "narration": narration})

    add("Sales", RECEIVABLE, "Sales - Paytm QR/UPI", s["gross"],
        f"Gross collections of {sales_date} via Paytm, settled T+1 on {sdate}", ref=f"Settlement {sdate}")
    totals = {"mdr_fees": 0, "gst_on_mdr": 0, "customer_refunds": 0, "soundbox_rental": 0, "chargeback_hold": 0,
              "other_deductions": 0}
    for item in s["deductions"]:
        head, amount = item["head"], dl.num(item["amount"]) or 0
        key = ("gst_on_mdr" if "GST" in head else "mdr_fees" if "MDR" in head else "customer_refunds" if "REFUND" in head
               else "soundbox_rental" if ("SOUNDBOX" in head or "RENTAL" in head)
               else "chargeback_hold" if ("CHARGEBACK" in head or "HOLD" in head) else "other_deductions")
        totals[key] += amount
        ref = f"ORDER #{item['order_id']}" if item.get("order_id") else ""
        status = str(item.get("status") or "")
        if key == "chargeback_hold" and ref in released:
            status = "RELEASED"
        elif key == "gst_on_mdr":
            status = "ITC LOGGED" if itc_logged else "ITC CLAIMABLE"
        add("Journal", _ledger_for(head, item.get("label", head)), RECEIVABLE, amount,
            f"{item.get('label', head)} deducted from settlement {sdate}", ref=ref, status=status,
            itc=key == "gst_on_mdr" or bool(item.get("itc_eligible")))
    add("Receipt", f"{bank.get('bank') or 'Bank'} {bank.get('account_masked') or ''}".strip(), RECEIVABLE,
        s["net_bank_credit"], f"Net settlement credited by Paytm on {sdate}", ref=f"Settlement {sdate}")

    for e in STATE.khata_entries:
        add(e["voucher_type"], e["debit"], e["credit"], e["amount"], e["narration"], on=e["date"],
            ref=e["reference"], status=e["kind"])

    deductions = sum(totals.values())
    gross, net = dl.num(s["gross"]) or 0, dl.num(s["net_bank_credit"]) or 0
    summary = {
        "settlement_date": sdate, "sales_date": sales_date, "gross_sales": gross, **totals,
        "total_deductions": deductions, "bank_credit": net,
        "gst_itc_claimable": totals["gst_on_mdr"], "gst_itc_logged": itc_logged,
        "reconciled": abs(gross - deductions - net) < 0.01,
        "post_settlement_entries": len(STATE.khata_entries),
    }
    sales_register = [{"date": r["date"], "gross_sales": r["sales"], **({"note": r["note"]} if r.get("note") else {})}
                      for r in h.get("recent_daily_sales") or [] if isinstance(r, dict)]
    return {
        "mid": d.merchant["mid"], "merchant_name": d.merchant["name"], "gstin": d.merchant.get("gstin"),
        "generated_at": datetime.now(timezone.utc).isoformat(), "format": "tally-journal-v1",
        "period": {"from": sales_register[0]["date"] if sales_register else sales_date, "to": sdate},
        "summary": summary,
        "sales_register": sales_register,
        "gst_itc_register": STATE.local_gst_itc_log,
        "vouchers": vouchers,
        "csv_columns": CSV_COLUMNS,
    }


def to_csv(khata: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for v in khata["vouchers"]:
        w.writerow([_tally_date(v["date"]), v["voucher_type"], v["voucher_no"], v["debit_ledger"], v["credit_ledger"],
                    f"{v['amount']:.2f}" if v["amount"] is not None else "", "Yes" if v["gst_itc_eligible"] else "No",
                    v["reference"], v["status"], v["narration"]])
    return "﻿" + buf.getvalue()  # BOM so Excel/Tally read ₹ and Hindi names correctly
