#!/usr/bin/env python3
"""Paytm-side synthetic dataset for PAYTM_MERCH_8821 ("Sharma Electronics"), derived from data/seed/.

    python data/generate_seed.py      # first, if data/seed/ is missing
    python data/generate_paytm.py     # reads data/seed/, writes data/paytm/, validates everything

Standard library + pandas only, fixed seed. data/seed/ is the single source of truth: every
shared ID and amount is copied from it, and Paytm's records only ADD detail (internal statuses,
NPCI/NACH codes, risk scores, audit fields). All pricing, policies and rate cards are
ILLUSTRATIVE, not actual Paytm or Clix Capital terms. All people and numbers are synthetic.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

SEED = 8821
rng = random.Random(SEED)
ROOT = Path(__file__).resolve().parent
SEED_DIR, OUT = ROOT / "seed", ROOT / "paytm"
REPO = ROOT.parent
ILLUSTRATIVE = "ILLUSTRATIVE: synthetic demo values, not actual Paytm pricing or policy"
MID = "PAYTM_MERCH_8821"
SNAPSHOT = datetime(2026, 11, 19, 9, 0)
DEMO_DAY = date(2026, 11, 19)
UTR_SUCCESS, UTR_PENDING, UTR_FAKE = "632184920111", "632184920999", "632184920555"
AUTO_REFUND_LIMIT = 5000
TOKEN_RE = re.compile(r"^DPDP_VERIFIED_TS_\d{10}$")

# ============================================================================ read data/seed
if not (SEED_DIR / "transactions.csv").exists():
    raise SystemExit("data/seed/ is missing: run `python data/generate_seed.py` first")


def rcsv(name: str) -> pd.DataFrame:
    df = pd.read_csv(SEED_DIR / name, dtype=str, keep_default_na=False)
    return df.replace({"NaT": "", "nan": "", "None": ""})


def rjson(name: str):
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


s_tx = rcsv("transactions.csv")
s_tx["amount_i"] = s_tx["amount"].astype(int)
s_stl = rcsv("settlements.csv")
s_ref = rcsv("refunds.csv")
s_cb = rcsv("chargebacks.csv")
s_edi = rcsv("edi_schedule.csv")
s_dev = rcsv("device_logs.csv")
s_sup = rcsv("support_history.csv")
s_cust = rcsv("customers.csv")
s_daily = rcsv("daily_sales_summary.csv")
s_profile = rjson("merchant_profile.json")
s_loan = rjson("loan.json")
s_ship = rjson("shiprocket_orders.json")["orders"]
s_strat = rjson("strategy_memory.json")
s_scen = {s["intent"]: s for s in rjson("scenarios.json")["scenarios"]}
s_bd = rjson("settlement_breakdown_2026-11-18.json")
TX = s_tx.set_index("txn_id")


def ts(x: str) -> datetime:
    return datetime.fromisoformat(x.replace(" ", "T"))


def unix(dt: datetime) -> int:  # IST wall-clock -> epoch seconds
    return int((dt - timedelta(hours=5, minutes=30) - datetime(1970, 1, 1)).total_seconds())


def sha(s: str, n: int = 10) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:n].upper()


# ============================================================================ 1. merchant master + cohort
COHORT_NAMES = ["Gupta Electricals", "Shree Balaji Electronics", "Jain Mobile Point", "Mittal Home Appliances",
                "Royal Electronics", "Arora Electric House", "New Bharat Electricals", "Krishna Mobile Care",
                "Om Sai Electronics", "Bansal Electric Store", "City Light House", "Goyal Appliances",
                "Durga Electronics", "Raj Electricals", "Star Mobile Accessories", "Singh Electronics",
                "Laxmi Home Appliances", "Ganpati Electricals", "Modern Electronics", "Verma Electric Works",
                "Sai Mobile Zone", "Kapoor Electronics", "Hari Om Electricals", "Prime Appliances",
                "Shiv Shakti Electronics", "Agarwal Lighting Centre", "Chauhan Electricals", "Galaxy Mobiles",
                "Ahuja Electronics", "Rana Electric Store", "Yadav Electricals", "Sunrise Appliances",
                "Metro Electronics", "Tiwari Electric House", "Bhatia Mobile Hub", "National Electricals",
                "Khanna Electronics", "Malhotra Appliances", "Saini Electric Mart", "Classic Electronics",
                "Joshi Electricals", "Mahadev Mobile Shop", "Dahiya Electronics", "Ever Bright Lights",
                "Saraswati Electricals", "Rathi Home Appliances", "Mehta Electronics", "Pooja Electricals",
                "Vision Electronics", "Ambika Electric House"]
GGN = ["Sector 14", "Sector 15", "Sector 17", "Sector 22", "Sector 31", "Sector 46", "Old Gurgaon", "Sohna Road",
       "Palam Vihar", "DLF Phase 3", "Sushant Lok 1", "Sector 56", "Golf Course Road", "Sector 4"]
avg_gmv_8821 = round(s_tx[s_tx.status == "SUCCESS"].amount_i.sum() / len(s_daily))
merchants = [{
    "mid": MID, "name": s_profile["name"], "category": s_profile["category"], "mcc": s_profile["mcc"], "city": "Gurugram",
    "locality": "Sector 14", "kyc_tier": s_profile["kyc_tier"], "onboarded_on": s_profile["onboarded_on"],
    "risk_tier": "LOW", "avg_daily_gmv_6m": avg_gmv_8821, "settlement_cycle": "T+1", "soundbox_count": 1,
    "has_loan": True, "lender": "Clix Capital", "is_demo_merchant": True}]
for i, name in enumerate(COHORT_NAMES):
    gmv = int(min(90000, max(9000, rng.lognormvariate(math.log(28000), 0.45))))
    merchants.append({
        "mid": f"PAYTM_MERCH_{9101 + i}", "name": name,
        "category": rng.choice(["Consumer electronics, appliances & electricals", "Mobile phones & accessories",
                                "Electricals & lighting", "Home appliances"]),
        "mcc": rng.choice(["5732", "5722", "5732", "5065"]), "city": "Gurugram", "locality": rng.choice(GGN),
        "kyc_tier": rng.choice(["Full KYC (Video KYC) + GST registered"] * 3 + ["Full KYC", "Min KYC"]),
        "onboarded_on": (date(2021, 1, 1) + timedelta(days=rng.randint(0, 1700))).isoformat(),
        "risk_tier": rng.choices(["LOW", "MEDIUM", "HIGH"], [70, 25, 5])[0], "avg_daily_gmv_6m": gmv,
        "settlement_cycle": rng.choice(["T+1"] * 9 + ["T+0 (instant)"]), "soundbox_count": rng.choice([1, 1, 1, 2]),
        "has_loan": rng.random() < 0.4, "lender": None, "is_demo_merchant": False})
for m in merchants[1:]:
    m["lender"] = rng.choice(["Clix Capital", "Other NBFC partner"]) if m["has_loan"] else None
COHORT = [m["mid"] for m in merchants[1:]]

# ============================================================================ 2. acquiring ledger
UPI_FAIL = [("Z9", "Insufficient funds in remitter account", 34), ("ZM", "Invalid MPIN", 22),
            ("U30", "Debit has failed - remitter bank issue", 14), ("U16", "Risk threshold exceeded", 6),
            ("U67", "Debit timeout", 8), ("ZA", "Transaction declined by customer", 16)]
CARD_NET = {"credit": ["VISA", "MASTERCARD", "VISA", "RUPAY"], "debit": ["RUPAY"]}
ledger, npci = [], []
reversed_ids = set(rng.sample(sorted(s_tx[(s_tx.status == "FAILED") & (s_tx.method == "UPI")].txn_id), 6))
for r in s_tx.itertuples(index=False):
    t = ts(r.timestamp)
    mdr = float(r.mdr_amount or 0)
    if r.status == "SUCCESS":
        code, desc = "00", "Approved"
    elif r.status == "PENDING":
        code, desc = "", "Deemed: awaiting final status from beneficiary bank"
    elif r.txn_id in reversed_ids:
        code, desc = "CS", "Customer debited, merchant credit failed; credit reversal request (CRR) completed"
    else:
        code, desc, _ = rng.choices(UPI_FAIL, [w for *_, w in UPI_FAIL])[0]
    if r.method == "card":
        network = rng.choice(CARD_NET[r.card_type])
    elif r.method == "wallet":
        network = "PPI_ON_UPI"
    elif r.method == "postpaid":
        network = "PAYTM_POSTPAID"
    else:
        network = "UPI"
    rrn = r.utr if r.utr else f"{t:%y%j}{rng.randrange(10**7):07d}"
    ledger.append({
        "txn_id": r.txn_id, "mid": MID, "timestamp": r.timestamp, "amount": r.amount_i, "method": r.method,
        "card_type": r.card_type, "network": network,
        "card_bin_masked": (f"{rng.choice(['4', '5', '6'])}{rng.randrange(10**5):05d}XXXXXX{rng.randrange(10**4):04d}"
                            if r.method == "card" else ""),
        "payer_app": r.payer_app, "utr": r.utr, "rrn": rrn,
        "acquirer_ref": f"ACQ{t:%y%m%d}{sha(r.txn_id, 8)}", "npci_resp_code": code if r.method in ("UPI", "wallet") else
        ("00" if r.status == "SUCCESS" else "05"),
        "npci_resp_desc": desc if r.method in ("UPI", "wallet") else ("Approved" if r.status == "SUCCESS" else "Do not honour"),
        "status": r.status, "paytm_internal_status": ("SETTLED" if r.status == "SUCCESS" else
                                                       "REVERSED" if r.txn_id in reversed_ids else
                                                       "DEEMED_PENDING" if r.status == "PENDING" else "DECLINED"),
        "customer_id": r.customer_id, "order_id": r.order_id, "channel": r.channel,
        "settlement_batch_id": r.settlement_batch_id, "mdr_rate_applied": float(r.mdr_rate or 0),
        "mdr_applied": round(mdr, 2), "gst_applied": round(mdr * 0.18, 2),
        "risk_flag": "DUPLICATE_PAYMENT" if r.tag.startswith("DUPLICATE_PAYMENT") else "",
        "ingested_at": (t + timedelta(seconds=rng.randint(1, 4))).isoformat()})
    if r.utr:
        final = {"SUCCESS": "SUCCESS", "PENDING": "PENDING"}.get(r.status, "REVERSED" if r.txn_id in reversed_ids else "FAILED")
        npci.append({
            "utr": r.utr, "txn_id": r.txn_id, "payer_psp": r.payer_app,
            "payer_vpa_masked": f"{sha(r.utr, 4).lower()}xx@{'ptyes' if r.payer_app.startswith('Paytm') else 'oksbi' if r.payer_app == 'GPay' else 'ybl' if r.payer_app == 'PhonePe' else 'upi'}",
            "payee_vpa": "sharmaelectronics@demo", "amount": r.amount_i, "status": final, "merchant_view_status": r.status,
            "resp_code": code, "resp_desc": desc, "initiated_at": r.timestamp,
            "final_at": "" if r.status == "PENDING" else (t + timedelta(seconds=rng.randint(2, 9))).isoformat(),
            "reversal_due_by": (t + timedelta(days=1)).isoformat() if r.status == "PENDING" else "",
            "order_id": r.order_id, "duplicate_group_id": f"DUPGRP-{r.order_id}" if r.tag.startswith("DUPLICATE_PAYMENT") else ""})
LEDGER = {x["txn_id"]: x for x in ledger}

# ============================================================================ 4. settlements
batches = []
tx_count = s_tx[s_tx.status == "SUCCESS"].groupby("settlement_batch_id").size().to_dict()
for r in s_stl.itertuples(index=False):
    batches.append({"batch_id": r.batch_id, "mid": MID, "txn_date": r.txn_date, "settlement_date": r.settlement_date,
                    "txn_count": tx_count.get(r.batch_id, 0), "gross": int(r.gross), "mdr": int(r.mdr),
                    "gst_on_mdr": int(r.gst_on_mdr), "refunds": int(r.refunds), "soundbox_rental": int(r.soundbox_rental),
                    "chargeback_hold": int(r.chargeback_hold), "chargeback_release": int(r.chargeback_release),
                    "net_credit": int(r.net_credit), "variance": int(r.variance), "payout_utr": r.payout_ref,
                    "bank_account_masked": "XXXXXX4821", "ifsc": "DEMO0000821", "status": "CREDITED",
                    "credited_at": r.credited_at, "reconciled": True})

lines, run = [], 0
day17 = s_tx[(s_tx.settlement_batch_id == "STL-20261118") & (s_tx.status == "SUCCESS")].sort_values("timestamp")


def add_line(kind: str, ref: str, desc: str, amt: int) -> None:
    global run
    run += amt
    lines.append({"line_id": f"L{len(lines) + 1:04d}", "batch_id": "STL-20261118", "line_type": kind, "ref_id": ref,
                  "description": desc, "amount_signed": amt, "running_net": run})


for r in day17.itertuples(index=False):
    add_line("TXN", r.txn_id, f"{r.method} {r.payer_app} {r.order_id}", r.amount_i)
for r in day17[day17.mdr_amount.astype(float) > 0].itertuples(index=False):
    add_line("MDR", r.txn_id, f"MDR {float(r.mdr_rate) * 100:g}% on ₹{r.amount_i:,}", -int(round(float(r.mdr_amount))))
mdr_total = -sum(l["amount_signed"] for l in lines if l["line_type"] == "MDR")
add_line("GST", "GST-ON-MDR", f"18% GST on ₹{mdr_total:,} MDR (ITC eligible)", -round(mdr_total * 0.18))
r4412 = s_ref[s_ref.refund_id == "RFD-4412"].iloc[0]
add_line("REFUND", "RFD-4412", "Refund for ORDER #4412 (processed 2026-11-17)", -int(r4412.amount))
add_line("RENTAL", "SB-8821-01", "Soundbox monthly rental (billing day 18)", -149)
cb9981 = s_cb[s_cb.chargeback_id == "CB-9981"].iloc[0]
add_line("CB_HOLD", "CB-9981", "Chargeback hold on ORDER #9981 (HELD)", -int(cb9981.amount))

# ============================================================================ 5. MDR rate card
rate_card = {
    "disclaimer": ILLUSTRATIVE, "effective_from": "2026-04-01", "gst_on_mdr_percent": 18,
    "tiers": {"SMALL (GMV < ₹20 lakh/month)": "applies to PAYTM_MERCH_8821", "MEDIUM": "₹20 lakh – ₹1 crore/month"},
    "rates_percent": {
        "SMALL": {"upi_p2m": 0.0, "rupay_debit": 0.0, "other_debit_card": 0.4, "credit_card": 2.0, "paytm_postpaid": 2.0,
                  "wallet_on_upi_upto_2000": 0.0, "wallet_on_upi_above_2000": 1.1, "emi_card": 2.0},
        "MEDIUM": {"upi_p2m": 0.0, "rupay_debit": 0.0, "other_debit_card": 0.4, "credit_card": 1.9, "paytm_postpaid": 1.9,
                   "wallet_on_upi_upto_2000": 0.0, "wallet_on_upi_above_2000": 1.1, "emi_card": 1.9}},
    "notes": ["UPI P2M MDR is zero for small merchants.", "MDR is charged per transaction and netted in the T+1 batch.",
              "Debit cards in data/seed are RuPay (0%)."],
}

# ============================================================================ 6/7. chargebacks + refunds
CB_REASON = {"card": ("13.1", "Merchandise/Services Not Received (illustrative network-style code)"),
             "UPI": ("UDIR-GNR", "Goods/services not received, raised via UPI dispute (illustrative code)")}
chargebacks = []
for r in s_cb.itertuples(index=False):
    lt = LEDGER[r.txn_id]
    code, desc = CB_REASON["card" if lt["method"] == "card" else "UPI"]
    raised = ts(r.raised_at)
    hist = [{"ts": raised.isoformat(), "status": "RECEIVED", "by": "NETWORK"},
            {"ts": (raised + timedelta(minutes=3)).isoformat(), "status": "HOLD_PLACED", "by": "LedgerOpsAgent",
             "note": f"₹{int(r.amount)} held in {r.held_in_batch}"}]
    if r.status in ("WON", "LOST"):
        hist.append({"ts": r.resolved_at, "status": r.status, "by": "NETWORK",
                     "note": "Hold released" if r.status == "WON" else "Debited to merchant"})
    chargebacks.append({
        "case_id": f"CBC-{r.chargeback_id.split('-')[1]}", "chargeback_id": r.chargeback_id, "mid": MID,
        "txn_id": r.txn_id, "order_id": r.order_id, "network": lt["network"], "reason_code": code, "reason_desc": desc,
        "seed_reason_code": r.reason_code, "amount": int(r.amount), "hold_amount": int(r.amount), "raised_at": r.raised_at,
        "paytm_evidence_due": r.respond_by, "network_response_due": (raised + timedelta(days=7)).isoformat(),
        "evidence_required": "Proof of delivery (OTP-verified or signed) + invoice",
        "evidence_received": r.status == "WON", "pod_awb": r.pod_awb, "status": r.status,
        "status_history": json.dumps(hist, ensure_ascii=False), "outcome": r.status if r.status != "HELD" else "",
        "held_in_batch": r.held_in_batch, "released_in_batch": r.released_in_batch, "contract_ref": r.contract_ref})

dup = s_tx[s_tx.tag.str.startswith("DUPLICATE_PAYMENT")].sort_values("timestamp")
refunds = []
for r in s_ref.itertuples(index=False):
    kind = "RTO" if "RTO" in r.reason else "RETURN"
    status = {"PROCESSED": "PROCESSED", "REQUESTED": "QUEUED"}[r.status]
    refunds.append({"refund_id": r.refund_id, "mid": MID, "order_id": r.order_id, "txn_id": r.txn_id,
                    "amount": int(r.amount), "type": kind, "reason": r.reason, "requested_at": r.requested_at,
                    "status": status, "auto_eligible": int(r.amount) <= AUTO_REFUND_LIMIT,
                    "approver": "AUTO (≤ ₹5,000)" if int(r.amount) <= AUTO_REFUND_LIMIT else "OPS_L2",
                    "processed_at": r.processed_at, "batch_id": r.deducted_in_batch.split(" ")[0] if status == "PROCESSED" else ""})
d2 = dup.iloc[1]
refunds.append({"refund_id": f"RFD-DUP-{d2.order_id}", "mid": MID, "order_id": d2.order_id, "txn_id": d2.txn_id,
                "amount": d2.amount_i, "type": "DUPLICATE", "reason": "Same customer paid twice for one order, 48 s apart",
                "requested_at": "", "status": "CANDIDATE", "auto_eligible": True, "approver": "AUTO (≤ ₹5,000)",
                "processed_at": "", "batch_id": ""})

# ============================================================================ 8-11. lending
edi_days = len(s_edi)
first_ok = int((s_edi.status == "SUCCESS").sum())
loan_book = {
    "disclaimer": ILLUSTRATIVE, "loan_id": s_loan["loan_id"], "mid": MID, "lender": "Clix Capital",
    "lender_role": "Regulated lender (NBFC); owns credit decisions incl. EDI holidays",
    "lsp": "Paytm (Lending Service Provider): sourcing, servicing, collections tech; cannot change terms on its own",
    "product": s_loan["product"], "sanctioned_amount": s_loan["sanctioned_amount"],
    "processing_fee": s_loan["processing_fee"], "net_disbursed": s_loan["net_disbursed"],
    "disbursed_on": s_loan["disbursed_on"], "apr_percent": s_loan["kfs"]["apr_percent"],
    "tenure_edis": s_loan["total_edis"], "daily_edi": s_loan["daily_edi"], "total_repayable": s_loan["total_repayable"],
    "edis_due_so_far": edi_days, "collected_so_far": s_loan["collected_so_far"], "outstanding": s_loan["loan_balance"],
    "overdue_amount": 500, "overdue_since": "2026-11-17", "dpd": 0,
    "dpd_note": "DPD counts only after the lender's 3-day grace period (lender_policies.json); the 17 Nov EDI is within grace on 19 Nov.",
    "first_attempt_success_rate": round(first_ok / edi_days, 4), "past_edi_success_rate": "96%",
    "kfs_edi_holiday_eligible": True, "edi_holiday_used_last_30_days": False, "kfs_clause_edi_holiday": "4.2",
    "mandate_umrn": s_loan["mandate"]["umrn"], "status": "ACTIVE", "as_of": SNAPSHOT.isoformat()}

kfs_md = f"""# Key Fact Statement (ILLUSTRATIVE)

> {ILLUSTRATIVE}. Not an actual Clix Capital or Paytm document.

| Item | Value |
|---|---|
| Borrower | {s_profile['name']} ({MID}) |
| Lender (Regulated Entity) | Clix Capital (NBFC) |
| Lending Service Provider | Paytm |
| Loan ID | {s_loan['loan_id']} |
| Sanctioned amount | ₹{s_loan['sanctioned_amount']:,} |
| Processing fee | ₹{s_loan['processing_fee']:,} (deducted at disbursal) |
| Net disbursed | ₹{s_loan['net_disbursed']:,} on {s_loan['disbursed_on']} |
| Repayment | ₹{s_loan['daily_edi']} per day (EDI) × {s_loan['total_edis']} = ₹{s_loan['total_repayable']:,} |
| Annual Percentage Rate (APR) | {s_loan['kfs']['apr_percent']}% (all-inclusive) |
| Collection | Daily eNACH auto-debit, mandate {s_loan['mandate']['umrn']} |
| Cooling-off / look-up period | 3 days from disbursal, no penalty |
| Foreclosure | Nil charges after 90 days |
| Grievance | Paytm LSP grievance officer → Clix Capital nodal officer → RBI Ombudsman |

## Clauses

**4.1 Missed EDI.** If an eNACH presentment is returned, the borrower may pay the same EDI the same day through a
UPI payment link. No bounce charge or penal charge applies to the first return in a 30-day window.

**4.2 EDI holiday (cash-flow hardship).**
- Maximum **2 consecutive days** per holiday.
- At most **once in any 30-day window**.
- Eligibility: loan ACTIVE, DPD = 0, first-attempt EDI success ≥ 90% over the last 90 days, and a documented
  short-term cash-flow gap (e.g. a refund or payable that pushes the next payout below committed stock costs).
- Requires the borrower's **explicit consent** and **the lender's approval**; the LSP only relays the request.
- Paused EDIs move to the end of the tenure. **No penal charges, no extra interest, no impact on DPD.**

**4.3 Data use.** Hardship and eligibility checks use settlement and bank data shared with consent via the RBI
Account Aggregator framework and recorded in the DPDP consent registry.
"""

mandates = [{"umrn": s_loan["mandate"]["umrn"], "mid": MID, "loan_id": s_loan["loan_id"],
             "sponsor_bank": "Demo Sponsor Bank", "debtor_account_masked": "XXXXXX4821", "max_amount": 1000,
             "frequency": "DAILY (as presented)", "registered_on": "2026-05-30", "valid_till": "2027-05-30",
             "status": "ACTIVE", "last_presentment": s_edi.iloc[-1].edi_date, "last_result": s_edi.iloc[-1].status,
             "last_return": "2026-11-17 (04 Balance insufficient)"}]
NACH = {"INSUFFICIENT_FUNDS": ("04", "Balance insufficient"),
        "TECHNICAL_DEST_BANK_TIMEOUT": ("TECH", "Destination bank not reachable (technical; illustrative code)")}
collections = []
for r in s_edi.itertuples(index=False):
    d = date.fromisoformat(r.edi_date)
    at = datetime(d.year, d.month, d.day, 7, 0)
    code, reason = NACH.get(r.bounce_code, ("", ""))
    collections.append({"attempt_id": f"EDI-{d:%y%m%d}-1", "edi_date": r.edi_date, "umrn": s_loan["mandate"]["umrn"],
                        "amount": 500, "channel": "eNACH", "attempt_at": at.isoformat(),
                        "result": "SUCCESS" if r.status == "SUCCESS" else "RETURNED", "return_code": code,
                        "return_reason": reason, "collected_at": (at + timedelta(hours=4)).isoformat() if r.status == "SUCCESS" else "",
                        "dpd_after": 0})
    if r.status == "BOUNCED" and r.recovery and r.recovery != "PENDING":
        m = re.search(r"(\d+)h (\d+)m", r.recovery_note)
        if r.recovery == "UPI_LINK" and m:
            when, ch = at + timedelta(hours=1 + int(m.group(1)), minutes=int(m.group(2))), "UPI_LINK"
        else:
            when, ch = at + timedelta(days=1), "RE_PRESENT"
        collections.append({"attempt_id": f"EDI-{d:%y%m%d}-2", "edi_date": r.edi_date, "umrn": s_loan["mandate"]["umrn"],
                            "amount": 500, "channel": ch, "attempt_at": when.isoformat(), "result": "SUCCESS",
                            "return_code": "", "return_reason": "", "collected_at": when.isoformat(), "dpd_after": 0})

lender_policies = {
    "disclaimer": ILLUSTRATIVE, "lender": "Clix Capital", "applies_to_product": "Merchant cash loan with daily EDI",
    "edi_holiday": {"kfs_clause": "4.2", "max_consecutive_days": 2, "max_per_rolling_days": 30, "requires_dpd": 0,
                    "min_first_attempt_success_90d": 0.90, "requires_merchant_consent": True,
                    "requires_lender_approval": True, "lsp_may_execute_alone": False,
                    "trigger": "projected_net_payout < committed payable due within 48h",
                    "penal_charges": 0, "effect": "paused EDIs appended to tenure end"},
    "upi_fallback_collection": {"kfs_clause": "4.1", "allowed_after": "first eNACH return of the day",
                                "link_validity_hours": 24, "bounce_charge_waived_if_paid_same_day": True},
    "dpd": {"grace_days": 3, "dpd_starts": "day 4 after a missed EDI"},
    "hardship": {"classify_as_friction_if": {"first_attempt_success_90d_min": 0.90, "sales_dip_max_days": 7,
                                             "sales_recovered_within_days": 3},
                 "escalate_to_collections_if": "2+ unrecovered EDIs or DPD > 7"},
    "approvals": {"edi_pause": "Clix Capital credit ops (auto-approve if all edi_holiday rules pass)",
                  "restructure": "Clix Capital credit committee (never autonomous)"},
}

# ============================================================================ 12/13. risk
risk_rows = []
daily_gmv = s_daily.set_index("date")["gross"].astype(int)
dates = list(daily_gmv.index)
edi_ok = {r.edi_date: r.status == "SUCCESS" for r in s_edi.itertuples(index=False)}
cb_dates = [ts(r.raised_at).date().isoformat() for r in s_cb.itertuples(index=False)]
for i, d in enumerate(dates):
    w7 = daily_gmv.iloc[max(0, i - 6): i + 1].mean()
    w90 = daily_gmv.iloc[max(0, i - 89): i + 1].mean()
    past = [v for k, v in edi_ok.items() if k <= d][-90:]
    ontime = sum(past) / len(past) if past else 1.0
    cb90 = sum(1 for c in cb_dates if c <= d and (date.fromisoformat(d) - date.fromisoformat(c)).days <= 90)
    ratio = w7 / w90
    score = 55 + 30 * ontime + 10 * min(1.0, ratio) - 3 * cb90
    drivers = []
    if ratio < 0.8:
        drivers.append("sales dip (7d vs 90d)")
    if past and not past[-1]:
        drivers.append("latest EDI returned")
    if cb90:
        drivers.append(f"{cb90} chargeback(s) in 90d")
    risk_rows.append({"date": d, "mid": MID, "health_score": round(score, 1),
                      "risk_tier": "LOW" if score >= 75 else "MEDIUM" if score >= 60 else "HIGH",
                      "gmv_7d_vs_90d": round(ratio, 2), "edi_on_time_90d": round(ontime, 3),
                      "chargebacks_90d": cb90,
                      "classification": "FRICTION_NOT_DEFAULT" if score >= 75 and (ratio < 0.8 or (past and not past[-1])) else "",
                      "drivers": "; ".join(drivers)})
for m in merchants[1:]:
    base = {"LOW": 84, "MEDIUM": 68, "HIGH": 52}[m["risk_tier"]]
    for d in dates:
        sc = max(20, min(99, base + rng.gauss(0, 3)))
        risk_rows.append({"date": d, "mid": m["mid"], "health_score": round(sc, 1),
                          "risk_tier": "LOW" if sc >= 75 else "MEDIUM" if sc >= 60 else "HIGH",
                          "gmv_7d_vs_90d": round(max(0.4, rng.gauss(1.0, 0.12)), 2),
                          "edi_on_time_90d": round(min(1, max(0.6, rng.gauss(0.93, 0.05))), 3) if m["has_loan"] else "",
                          "chargebacks_90d": rng.choice([0, 0, 0, 1]), "classification": "", "drivers": ""})

fraud = [
    {"signal_id": "FS-0001", "ts": "2026-10-03T19:16:10", "mid": MID, "type": "UTR_NOT_FOUND", "ref": "629874120553",
     "detail": "Merchant looked up a UTR from a customer screenshot; no such UTR in NPCI log", "score": 0.94,
     "action": "Warned merchant: do not hand over goods", "outcome": "FRAUD_PREVENTED", "linked_ticket": "TKT-PAYTM-1236"},
    {"signal_id": "FS-0002", "ts": "2026-10-03T19:16:12", "mid": MID, "type": "TAMPERED_SCREENSHOT", "ref": "629874120553",
     "detail": "Screenshot font/kerning mismatch around amount and UTR (doc-extract warnings)", "score": 0.81,
     "action": "Attached to FS-0001", "outcome": "CONFIRMED", "linked_ticket": "TKT-PAYTM-1236"},
    {"signal_id": "FS-0003", "ts": dup.iloc[1].timestamp, "mid": MID, "type": "DUPLICATE_PAYMENT", "ref": f"ORDER {d2.order_id}",
     "detail": f"Two UTRs ({dup.iloc[0].utr}, {dup.iloc[1].utr}) for one order, same customer, ₹{d2.amount_i:,} each",
     "score": 0.99, "action": "Refund candidate RFD-DUP-" + d2.order_id, "outcome": "OPEN", "linked_ticket": ""},
]
for i in range(12):
    m = rng.choice(COHORT)
    fraud.append({"signal_id": f"FS-{i + 4:04d}", "ts": (datetime(2026, 6, 1) + timedelta(days=rng.randint(0, 170),
                  hours=rng.randint(9, 21))).isoformat(), "mid": m,
                  "type": rng.choice(["UTR_NOT_FOUND", "TAMPERED_SCREENSHOT", "VELOCITY"]),
                  "ref": f"6{rng.randrange(10**11):011d}", "detail": "Cohort signal (benchmark)",
                  "score": round(rng.uniform(0.6, 0.98), 2), "action": "Merchant warned",
                  "outcome": rng.choice(["FRAUD_PREVENTED", "FALSE_POSITIVE", "FRAUD_PREVENTED"]), "linked_ticket": ""})
for f in fraud:  # never let a random ref collide with a real or the demo-fake UTR
    assert f["ref"] not in {x["utr"] for x in npci} and f["ref"] != UTR_FAKE

# ============================================================================ 14. policies
refund_policy = {"disclaimer": ILLUSTRATIVE, "autonomous_limit_inr": AUTO_REFUND_LIMIT,
                 "rules": [{"if": "amount ≤ ₹5,000 and provable (duplicate UTRs / returned goods logged)", "then": "AUTO",
                            "agent": "RiskPolicyAgent approves, LedgerOpsAgent executes"},
                           {"if": "amount > ₹5,000", "then": "HUMAN_APPROVAL", "approver": "OPS_L2"},
                           {"if": "refund to a different instrument/account than paid from", "then": "REJECT"}],
                 "duplicate_detection": {"same_order": True, "same_customer": True, "max_gap_seconds": 300}}
chargeback_policy = {"disclaimer": ILLUSTRATIVE, "hold": "Full disputed amount held from next T+1 batch",
                     "evidence_accepted": ["OTP-verified PoD", "signed PoD", "courier delivery photo", "invoice"],
                     "autonomous": {"submit_evidence_if": "PoD delivered_at ≤ dispute raised_at and recipient matches order",
                                    "requires_merchant_signoff": True},
                     "escalate_if": ["no PoD", "amount > ₹25,000", "repeat disputes from same customer"],
                     "release": "Hold released in the next batch after the network accepts evidence (demo: on submission)"}
dispute_tat = {"disclaimer": ILLUSTRATIVE, "units": "hours unless stated",
               "chargeback": {"paytm_evidence_due": 48, "network_response_days": 7},
               "refund": {"auto": 1, "human_approval": 24},
               "upi_pending": {"auto_reversal": "T+1 (NPCI deemed-transaction rules)"},
               "edi_pause": {"lender_decision": 2}, "tickets": {"L1": 4, "L2": 24, "hardware_replacement_days": 2}}

# ============================================================================ 15. devices
fleet = [{"device_id": "SB-8821-01", "mid": MID, "model": "Paytm Card Soundbox", "firmware": "4.2.1",
          "imei_masked": f"86{rng.randrange(10**4):04d}XXXXXX{rng.randrange(100):02d}", "rental_inr_per_month": 149,
          "billing_day": 18, "installed_on": "2024-03-06", "status": "DEGRADED", "replacement_eligible": True}]
for m in merchants[1:]:
    for k in range(m["soundbox_count"]):
        fleet.append({"device_id": f"SB-{m['mid'][-4:]}-{k + 1:02d}", "mid": m["mid"],
                      "model": rng.choice(["Paytm Card Soundbox", "Paytm Soundbox 5.0", "Paytm Pocket Soundbox"]),
                      "firmware": rng.choice(["4.2.1", "4.1.8", "4.2.0"]), "imei_masked": f"86{rng.randrange(10**4):04d}XXXXXX{rng.randrange(100):02d}",
                      "rental_inr_per_month": 149, "billing_day": rng.randint(1, 28),
                      "installed_on": m["onboarded_on"], "status": "ACTIVE", "replacement_eligible": False})
telemetry = []
for r in s_dev.itertuples(index=False):
    t = ts(r.ts)
    telemetry.append({"ts": r.ts, "device_id": r.device_id, "mid": MID, "battery_pct": int(r.battery_pct),
                      "battery_health_pct": int(r.battery_health_pct), "network": r.network, "signal_dbm": int(r.signal_dbm),
                      "heartbeat_ok": r.heartbeat_ok == "True", "announce_failures": int(r.announce_failures),
                      "event": r.event, "firmware": "4.2.1",
                      "server_last_seen": r.ts if r.heartbeat_ok == "True" else (t - timedelta(hours=1)).isoformat(),
                      "diagnosis": "BATTERY_DEGRADATION" if int(r.battery_health_pct) < 30 else ""})

# ============================================================================ 16. tickets
TEAM = {"ESCALATE_HUMAN": ("L2", "Device Ops"), "MANDATE_TROUBLESHOOT": ("L1", "Lending Support"),
        "SETTLEMENT_RECONCILE": ("L1", "Merchant Support"), "CHARGEBACK_RESOLVE": ("L2", "Disputes"),
        "UTR_VERIFY": ("L1", "Risk & Fraud")}
tickets = []
for r in s_sup.itertuples(index=False):
    lvl, team = TEAM.get(r.intent, ("L1", "Merchant Support"))
    op = ts(r.opened_at)
    tickets.append({"ticket_id": r.ticket_id, "mid": MID, "level": lvl, "intent": r.intent, "summary": r.summary,
                    "channel": r.channel, "opened_at": op.isoformat(), "assignee_team": team,
                    "sla_due": (op + timedelta(hours=24 if lvl == "L2" else 4)).isoformat(),
                    "status": "OPEN" if r.outcome == "OPEN" else "CLOSED", "outcome": r.outcome,
                    "resolution": r.resolution, "resolved_at": ts(r.resolved_at).isoformat() if r.resolved_at else "",
                    "csat": int(float(r.csat)) if r.csat else ""})
NEXT_TICKET = f"TKT-PAYTM-{max(int(t['ticket_id'].split('-')[-1]) for t in tickets) + 1}"

# ============================================================================ 17/18. consent + PoD
VALID_GRANT = datetime(2026, 11, 19, 8, 45)
consents = []
for c in s_profile["connectors"]:
    g = datetime.fromisoformat(c["granted_at"] + "T10:00:00")
    consents.append({"consent_id": f"CNS-{c['name']}", "mid": MID, "token": f"DPDP_VERIFIED_TS_{unix(g)}",
                     "purpose": {"SHIPROCKET_SYNC": "Dispute evidence (proof of delivery)",
                                 "VYAPAR_POS_SYNC": "Cash-flow and payables for EDI hardship checks",
                                 "RBI_ACCOUNT_AGGREGATOR": "Loan underwriting and hardship assessment"}[c["name"]],
                     "data_scope": c["holds"], "connector": c["name"], "granted_at": g.isoformat(),
                     "expires_at": (g + timedelta(days=365)).isoformat(), "status": "ACTIVE"})
consents += [
    {"consent_id": "CNS-A2A-VALID", "mid": MID, "token": f"DPDP_VERIFIED_TS_{unix(VALID_GRANT)}",
     "purpose": "A2A dispute & settlement resolution with Paytm", "data_scope": "settlement, loan, disputes for PAYTM_MERCH_8821",
     "connector": "MERCHANT_AGENT_8003", "granted_at": VALID_GRANT.isoformat(),
     "expires_at": (VALID_GRANT + timedelta(hours=24)).isoformat(), "status": "ACTIVE"},
    {"consent_id": "CNS-A2A-EXPIRED", "mid": MID, "token": f"DPDP_VERIFIED_TS_{unix(datetime(2026, 11, 10, 18, 0))}",
     "purpose": "A2A dispute & settlement resolution with Paytm", "data_scope": "settlement, loan, disputes for PAYTM_MERCH_8821",
     "connector": "MERCHANT_AGENT_8003", "granted_at": "2026-11-10T18:00:00", "expires_at": "2026-11-11T18:00:00",
     "status": "EXPIRED"},
    {"consent_id": "CNS-A2A-REVOKED", "mid": MID, "token": f"DPDP_VERIFIED_TS_{unix(datetime(2026, 11, 12, 11, 30))}",
     "purpose": "A2A dispute & settlement resolution with Paytm", "data_scope": "settlement, loan, disputes for PAYTM_MERCH_8821",
     "connector": "MERCHANT_AGENT_8003", "granted_at": "2026-11-12T11:30:00", "expires_at": "2026-11-13T11:30:00",
     "status": "REVOKED"},
]
CONSENT_VALID = consents[-3]["token"]
CONSENT_EXPIRED = consents[-2]["token"]

o9981 = next(o for o in s_ship if o["order_id"] == "9981")
pod_img = REPO / "services" / "sarvam_service" / "app" / "samples" / "pod_9981.png"
pod_hash = hashlib.sha256(pod_img.read_bytes()).hexdigest() if pod_img.exists() else None
shiprocket_pod = {
    "connector": "SHIPROCKET_SYNC", "consent_id": "CNS-SHIPROCKET_SYNC", "mid": MID,
    "received_by_paytm_at": None, "received_note": "Not yet pulled: the merchant agent pulls it during CHARGEBACK_RESOLVE",
    "order_id": "9981", "chargeback_id": "CB-9981", "payment_txn_id": o9981["payment_txn_id"], "awb": o9981["awb"],
    "courier": o9981["courier"], "ship_to": o9981["ship_to"], "amount": o9981["amount"], "items": o9981["items"],
    "shipped_at": o9981["shipped_at"], "pod": o9981["pod"],
    "document": {"path": "services/sarvam_service/app/samples/pod_9981.png", "sha256": pod_hash,
                 "expected_extraction": {"order_id": "9981", "delivery_date": "2026-11-16", "recipient_name": "Rohit Verma",
                                         "amount": 800, "signature_present": True}},
}

# ============================================================================ 19. learning
outcomes = []
for m in s_strat["memories"]:
    outcomes.append({"outcome_id": f"OUT-{m['memory_id']}", "mid": MID, "date": m["date"], "intent": m["intent"],
                     "situation": m["situation"], "options": " | ".join(m["options_considered"]),
                     "option_chosen": m["chosen"], "verified_outcome": m["verified_outcome"],
                     "time_to_outcome": m["time_to_outcome"], "success": m["success"], "source": "data/seed/strategy_memory.json"})
PLAYBOOK = {
    "MANDATE_TROUBLESHOOT": [("A: reminder only", 0.62, "120-1440"), ("B: 1-tap UPI link", 0.91, "45-240"),
                             ("C: collections call", 0.55, "720-2880")],
    "CASHFLOW_EDI_SWITCH": [("A: do nothing", 0.35, ""), ("B: KFS 4.2 EDI pause", 0.94, "60-240"),
                            ("C: short-term credit line", 0.70, "1440-4320")],
    "CHARGEBACK_RESOLVE": [("A: accept", 0.0, ""), ("B: submit PoD", 0.88, "1440-4320"), ("C: escalate", 0.60, "2880-7200")],
    "DUPLICATE_RECONCILE": [("A: auto-refund second UTR", 0.99, "5-60"), ("B: ask merchant", 0.95, "240-1440")],
    "UTR_VERIFY": [("A: trust screenshot", 0.40, ""), ("B: verify UTR in NPCI log", 0.98, "1-5")],
}
oid = 1
for _ in range(320):
    intent = rng.choice(list(PLAYBOOK))
    opt, p, tt = rng.choice(PLAYBOOK[intent])
    ok = rng.random() < p
    lo, hi = (int(x) for x in tt.split("-")) if tt else (0, 0)
    outcomes.append({"outcome_id": f"OUT-C{oid:04d}", "mid": rng.choice(COHORT),
                     "date": (date(2026, 5, 20) + timedelta(days=rng.randint(0, 180))).isoformat(), "intent": intent,
                     "situation": "cohort case", "options": " | ".join(o for o, *_ in PLAYBOOK[intent]),
                     "option_chosen": opt.split(":")[0], "verified_outcome": "resolved" if ok else "not resolved",
                     "time_to_outcome": f"{rng.randint(lo, hi)} min" if ok and hi else "", "success": ok,
                     "source": "cohort"})
    oid += 1
learn = pd.DataFrame(outcomes)

# ============================================================================ 20. initial state
utr_state = {UTR_SUCCESS: "SUCCESS_SETTLED", UTR_PENDING: "PENDING"}
initial_state = {
    "mid": MID, "as_of": SNAPSHOT.isoformat(), "restored_by": "POST /ledger/reset",
    "settlement": {"batch_id": "STL-20261118", "settlement_date": "2026-11-18", "gross": 100000, "net_credit": 95840,
                   "variance": 4160, "deductions": {"mdr": 1450, "gst_on_mdr": 261, "refund_4412": 1500,
                                                   "soundbox_rental": 149, "chargeback_hold_9981": 800},
                   "mdr_split": s_bd["by_rail"]},
    "loan": {"loan_id": s_loan["loan_id"], "lender": "Clix Capital", "edi_status": "ACTIVE", "daily_edi": 500,
             "outstanding": 42000, "overdue_amount": 500, "dpd": 0, "kfs_edi_holiday_eligible": True},
    "mandate": {"umrn": s_loan["mandate"]["umrn"], "status": "ACTIVE", "last_return_date": "2026-11-17",
                "last_return_code": "04", "last_return_reason": "Balance insufficient", "bounce_charge": 0,
                "on_time_rate_percent": 96},
    "chargebacks": {"CB-9981": {"order_id": "9981", "txn_id": cb9981.txn_id, "amount": 800, "status": "HELD",
                                "paytm_evidence_due": cb9981.respond_by}},
    "refunds": {"RFD-4412": "PROCESSED", "RFD-4490": "QUEUED", f"RFD-DUP-{d2.order_id}": "CANDIDATE"},
    "utrs": {UTR_SUCCESS: {"amount": 1250, "payer_app": "GPay", "status": "SUCCESS_SETTLED", "txn_id": TX.index[TX.utr == UTR_SUCCESS][0]},
             UTR_PENDING: {"amount": 2400, "payer_app": "PhonePe", "status": "PENDING", "txn_id": TX.index[TX.utr == UTR_PENDING][0]},
             dup.iloc[0].utr: {"amount": dup.iloc[0].amount_i, "payer_app": dup.iloc[0].payer_app, "status": "SUCCESS_SETTLED",
                               "order_id": d2.order_id, "txn_id": dup.iloc[0].txn_id},
             dup.iloc[1].utr: {"amount": d2.amount_i, "payer_app": d2.payer_app, "status": "SUCCESS_SETTLED",
                               "order_id": d2.order_id, "txn_id": d2.txn_id}},
    "unknown_utr_status": "NOT_FOUND_SUSPECTED_FAKE",
    "devices": {"SB-8821-01": "DEGRADED"}, "next_ticket_id": NEXT_TICKET,
    "consent": {"valid_token_example": CONSENT_VALID, "expired_token_example": CONSENT_EXPIRED,
                "missing_or_invalid_token": "HTTP 403"},
    "counters": {"outcomes_verified": 0, "tickets_deflected": 0, "fraud_blocked": 0, "money_recovered_inr": 0},
}

# ============================================================================ 21. scenarios through the 4 agents
def step(agent, reads, decision, change=None):
    return {"agent": agent, "reads": reads, "decision": decision, "state_change": change}


sc_paytm = {"mid": MID, "consent_required": True, "scenarios": [
    {"intent": "MANDATE_TROUBLESHOOT", "merchant_fixture": s_scen["MANDATE_TROUBLESHOOT"]["record_ids"], "agent_trace": [
        step("IntelligenceAgent", ["lending/edi_collections.csv", "lending/enach_mandates.csv", "risk/merchant_risk_scores.csv"],
             "17 Nov eNACH returned 04 (balance insufficient) after a 3-day market closure; 18 Nov EDI succeeded; health LOW risk"),
        step("RiskPolicyAgent", ["lending/lender_policies.json", "learning/outcome_history.csv"],
             "First-attempt success 95.9% ≥ 90%, DPD 0, sales recovered next day → FRICTION_NOT_DEFAULT; Option B (UPI link) best: 91% success"),
        step("ResolutionAgent", ["lending/kfs_document.md (4.1)"], "Send 1-tap UPI link for ₹500; bounce charge waived under 4.1",
             {"mandate.upi_link": "SENT"}),
        step("LedgerOpsAgent", ["lending/loan_book.json"], "On payment: mark 17 Nov EDI recovered, overdue 0",
             {"loan.overdue_amount": 0, "counters.outcomes_verified": "+1"})],
     "verified_outcome": "EDI 2026-11-17 RECOVERED_VIA_UPI_LINK, bounce charge ₹0, DPD 0, mandate ACTIVE"},
    {"intent": "SETTLEMENT_RECONCILE", "merchant_fixture": s_scen["SETTLEMENT_RECONCILE"]["record_ids"], "agent_trace": [
        step("IntelligenceAgent", ["settlement_batches.csv", "settlement_lines_2026-11-18.csv", "acquiring_ledger.csv"],
             "STL-20261118: gross ₹1,00,000 from 17 Nov; 6 deduction lines total ₹4,160"),
        step("RiskPolicyAgent", ["mdr_rate_card.json"], "All deductions match the (illustrative) rate card; nothing to dispute"),
        step("ResolutionAgent", [], "Itemise: MDR ₹1,450 (card/postpaid/wallet), GST ₹261 (ITC), refund #4412 ₹1,500, rental ₹149, hold #9981 ₹800"),
        step("LedgerOpsAgent", [], "No money moves; record explanation", {"counters.tickets_deflected": "+1"})],
     "verified_outcome": "Variance ₹4,160 explained line by line; ₹261 ITC flagged; ₹800 linked to CB-9981"},
    {"intent": "CHARGEBACK_RESOLVE", "merchant_fixture": s_scen["CHARGEBACK_RESOLVE"]["record_ids"], "agent_trace": [
        step("IntelligenceAgent", ["chargebacks.csv", "connectors/shiprocket_pod.json", "consent/dpdp_consents.csv"],
             "CB-9981 HELD ₹800, reason 13.1; PoD delivered 16 Nov 18:42 to Rohit Verma (OTP + signature); consent ACTIVE"),
        step("RiskPolicyAgent", ["policies/chargeback_policy.json", "policies/dispute_tat.json"],
             "PoD predates dispute, recipient matches, inside 48h evidence window → submit (needs merchant sign-off)"),
        step("ResolutionAgent", [], "Submit evidence pack after 1-tap sign-off", {"chargebacks.CB-9981.evidence_received": True}),
        step("LedgerOpsAgent", ["settlement_batches.csv"], "Release hold into next batch",
             {"chargebacks.CB-9981.status": "RELEASED", "counters.money_recovered_inr": "+800"})],
     "verified_outcome": "CB-9981 HELD → RELEASED; ₹800 credited in the next T+1 batch"},
    {"intent": "UTR_VERIFY", "merchant_fixture": s_scen["UTR_VERIFY"]["record_ids"], "agent_trace": [
        step("IntelligenceAgent", ["npci_utr_log.csv"], f"{UTR_SUCCESS}: SUCCESS; {UTR_PENDING}: PENDING (reversal by T+1); {UTR_FAKE}: not found"),
        step("RiskPolicyAgent", ["risk/fraud_signals.csv"], "Not found + screenshot → NOT_FOUND_SUSPECTED_FAKE (score high)"),
        step("ResolutionAgent", [], "Neutral advice: don't hand over goods until the Soundbox announces the payment"),
        step("LedgerOpsAgent", [], "Log fraud signal", {"counters.fraud_blocked": "+1"})],
     "verified_outcome": "Fake screenshot blocked; genuine and pending UTRs reported with their real status"},
    {"intent": "DUPLICATE_RECONCILE", "merchant_fixture": s_scen["DUPLICATE_RECONCILE"]["record_ids"], "agent_trace": [
        step("IntelligenceAgent", ["npci_utr_log.csv", "acquiring_ledger.csv"],
             f"Order {d2.order_id}: two SUCCESS UTRs, same customer, ₹{d2.amount_i:,} each, 48 s apart (DUPGRP-{d2.order_id})"),
        step("RiskPolicyAgent", ["policies/refund_policy.json"], f"₹{d2.amount_i:,} ≤ ₹5,000 and provable → AUTO"),
        step("ResolutionAgent", [], "Refund the second payment to the original instrument", {f"refunds.RFD-DUP-{d2.order_id}": "PROCESSED"}),
        step("LedgerOpsAgent", ["refunds.csv"], "Queue refund in next batch", {"counters.outcomes_verified": "+1"})],
     "verified_outcome": f"RFD-DUP-{d2.order_id} PROCESSED (₹{d2.amount_i:,}); order reconciled to one payment"},
    {"intent": "GROWTH_ADVISORY", "merchant_fixture": s_scen["GROWTH_ADVISORY"]["record_ids"], "agent_trace": [
        step("IntelligenceAgent", ["acquiring_ledger.csv", "merchant_master.csv"],
             "₹32,000/day, Fri–Sun 2.3×, GMV in cohort top half"),
        step("RiskPolicyAgent", ["risk/merchant_risk_scores.csv", "lending/lender_policies.json"],
             "LOW risk, DPD 0 → eligible to *see* a working-capital offer (KFS shown first)"),
        step("ResolutionAgent", [], "Advise stocking up by Thursday; optional offer with KFS link; no auto-acceptance"),
        step("LedgerOpsAgent", [], "Record advice; no money moved")],
     "verified_outcome": "Advice delivered with cited numbers; any credit needs explicit acceptance after KFS"},
    {"intent": "CASHFLOW_EDI_SWITCH", "merchant_fixture": s_scen["CASHFLOW_EDI_SWITCH"]["record_ids"], "agent_trace": [
        step("IntelligenceAgent", ["refunds.csv", "consent/dpdp_consents.csv"],
             "RFD-4490 ₹3,500 queued → projected payout ₹1,200 vs ₹4,500 payable (VYAPAR_POS_SYNC, consented)"),
        step("RiskPolicyAgent", ["lending/lender_policies.json", "lending/kfs_document.md (4.2)", "lending/loan_book.json"],
             "Clause 4.2: DPD 0, 95.9% ≥ 90%, no holiday in last 30 days, gap documented → eligible; needs lender approval"),
        step("ResolutionAgent", [], "Request Clix Capital approval with merchant consent token; approval logged",
             {"loan.lender_approval": "APPROVED (Clix Capital credit ops)"}),
        step("LedgerOpsAgent", ["lending/loan_book.json"], "Pause EDIs 19–20 Nov, append to tenure end",
             {"loan.edi_status": "PAUSED_2_DAYS", "loan.resume_date": "2026-11-21"})],
     "verified_outcome": "EDI PAUSED_2_DAYS with lender approval + KFS consent artifact; ₹1,000 freed; resumes 2026-11-21"},
    {"intent": "ESCALATE_HUMAN", "merchant_fixture": s_scen["ESCALATE_HUMAN"]["record_ids"], "agent_trace": [
        step("IntelligenceAgent", ["devices/soundbox_telemetry.csv", "devices/soundbox_fleet.csv", "support/tickets.csv"],
             "SB-8821-01 battery health 41% → 18%, heartbeats missed from 15 Nov; TKT-PAYTM-1290 still open"),
        step("RiskPolicyAgent", ["policies/dispute_tat.json"], "Hardware fault → needs a human (replacement), L2"),
        step("ResolutionAgent", [], f"Open {NEXT_TICKET} (L2, Device Ops) with diagnostics attached", {"tickets.new": NEXT_TICKET}),
        step("LedgerOpsAgent", [], "Link ticket to device and merchant; close duplicate TKT-PAYTM-1290")],
     "verified_outcome": f"{NEXT_TICKET} created with logs; replacement within 2 days; merchant repeats nothing"},
]}

# ============================================================================ write
OUT.mkdir(parents=True, exist_ok=True)
for sub in ("lending", "risk", "policies", "devices", "support", "consent", "connectors", "learning"):
    (OUT / sub).mkdir(exist_ok=True)


def wcsv(name, rows):
    pd.DataFrame(rows).to_csv(OUT / name, index=False)


def wjson(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


wcsv("merchant_master.csv", merchants)
wcsv("acquiring_ledger.csv", ledger)
wcsv("npci_utr_log.csv", npci)
wcsv("settlement_batches.csv", batches)
wcsv("settlement_lines_2026-11-18.csv", lines)
wjson("mdr_rate_card.json", rate_card)
wcsv("chargebacks.csv", chargebacks)
wcsv("refunds.csv", refunds)
wjson("lending/loan_book.json", loan_book)
(OUT / "lending" / "kfs_document.md").write_text(kfs_md, encoding="utf-8")
wcsv("lending/enach_mandates.csv", mandates)
wcsv("lending/edi_collections.csv", collections)
wjson("lending/lender_policies.json", lender_policies)
wcsv("risk/merchant_risk_scores.csv", risk_rows)
wcsv("risk/fraud_signals.csv", fraud)
wjson("policies/refund_policy.json", refund_policy)
wjson("policies/chargeback_policy.json", chargeback_policy)
wjson("policies/dispute_tat.json", dispute_tat)
wcsv("devices/soundbox_fleet.csv", fleet)
wcsv("devices/soundbox_telemetry.csv", telemetry)
wcsv("support/tickets.csv", tickets)
wcsv("consent/dpdp_consents.csv", consents)
wjson("connectors/shiprocket_pod.json", shiprocket_pod)
learn.to_csv(OUT / "learning" / "outcome_history.csv", index=False)
wjson("ledger_initial_state.json", initial_state)
wjson("scenarios_paytm.json", sc_paytm)

# ============================================================================ README
P2 = [
    ("MDR split (total ₹1,450 either way)", "card 45,000 @2% + wallet 50,000 @1.1% + UPI 5,000",
     "card+postpaid 62,600 @2% + wallet 18,000 @1.1% + UPI 19,400 (`ledger_initial_state.settlement.mdr_split`)"),
    ("Mandate bounce date", "2026-11-19", "2026-11-17 (return code 04, Balance insufficient)"),
    ("Bounce charge", "₹118", "₹0: waived under KFS 4.1 (first return in 30 days)"),
    ("Duplicate payment", "order 4455, ₹3,200 × 2, UTRs 632184925001/002",
     f"order {d2.order_id}, ₹{d2.amount_i:,} × 2, UTRs {dup.iloc[0].utr} / {dup.iloc[1].utr} (PhonePe)"),
    ("Chargeback txn_id", '"9981"', f"{cb9981.txn_id} (contract_ref keeps \"TXNID #9981\")"),
    ("Missing/invalid consent token", "HTTP 400 CONSENT_MISSING", "HTTP 403 (contract.md)"),
    ("Timestamps", "UTC (+00:00)", "IST"),
]
readme = [f"# Paytm-side dataset: {s_profile['name']} ({MID})", "",
          f"> {ILLUSTRATIVE}. Derived from `data/seed/`, which is the single source of truth.", "",
          "```bash", "python data/generate_paytm.py   # reads data/seed/, rewrites data/paytm/, runs all checks", "```", "",
          "## Cross-dataset key map", "", "| Thing | data/seed (merchant side) | data/paytm (Paytm side) |", "|---|---|---|",
          "| Merchant | merchant_profile.mid | merchant_master.mid |",
          "| Payment | transactions.txn_id / utr | acquiring_ledger.txn_id / utr (+ acquirer_ref, rrn, NPCI code), npci_utr_log.utr |",
          "| Settlement | settlements.batch_id | settlement_batches.batch_id, settlement_lines_2026-11-18.batch_id |",
          "| Refund | refunds.refund_id | refunds.refund_id (+ queue status, approver); RFD-DUP-* is Paytm-only |",
          "| Chargeback | chargebacks.chargeback_id | chargebacks.chargeback_id (+ case_id, network code, status_history) |",
          "| Shipment / PoD | shiprocket_orders.awb | connectors/shiprocket_pod.awb |",
          "| Loan | loan.loan_id, loan.mandate.umrn | lending/loan_book.loan_id, enach_mandates.umrn |",
          "| EDI | edi_schedule.edi_date | edi_collections.edi_date (1–2 attempts per date) |",
          "| Device | device_logs.device_id | soundbox_fleet / soundbox_telemetry.device_id |",
          "| Tickets | support_history.ticket_id | support/tickets.ticket_id |",
          "| Consent | merchant_profile.connectors | consent/dpdp_consents.connector |", "",
          "## Conflict log", "",
          "- **Shop type:** the request said *Sharma Kirana Store*; data/seed is *Sharma Electronics*, so the cohort is 50 Gurugram electronics/appliance stores.",
          "- **TXNID #9981:** contract.md uses \"9981\" as a txn_id; the real payment is `" + cb9981.txn_id + "`, kept in `contract_ref`.",
          "- **EDI collection:** contract.md says \"next deduction: tomorrow's settlement\"; data/seed collects by eNACH from the bank account.",
          "- **Latest EDI attempt:** the latest *attempt* is 18 Nov (SUCCESS); the latest *failure* is the 17 Nov return, still unrecovered. The checks test the latter.",
          "- **DPD 0 with ₹500 overdue:** reconciled by a 3-day grace period in `lending/lender_policies.json` (illustrative).",
          "- **#4490 refund:** requested 19 Nov 11:20, after the 09:00 snapshot; kept as QUEUED in the initial state to match the cashflow demo.",
          "- **data/seed blemishes:** an empty `resolved_at` was written as `NaT` and `csat` as `5.0`; read safely here.", "",
          "## What `services/paytm_agent` should change to match (option a: data/seed wins)", "",
          "| Item | paytm_agent/app/seed.py today | Should be |", "|---|---|---|"] + \
         [f"| {a} | {b} | {c} |" for a, b, c in P2] + [
          "", "Simplest: have `POST /ledger/reset` load `data/paytm/ledger_initial_state.json`.", "",
          "## How each scenario flows through the 4 agents", ""]
for s in sc_paytm["scenarios"]:
    readme.append(f"### {s['intent']}")
    for st in s["agent_trace"]:
        readme.append(f"1. **{st['agent']}** reads {', '.join(f'`{r}`' for r in st['reads']) or '—'}: {st['decision']}")
    readme += [f"\n**Verified outcome:** {s['verified_outcome']}", ""]
DICT = {
    "merchant_master.csv": "MID 8821 + 50 cohort stores: category, MCC, KYC tier, onboarding, risk tier, average daily GMV, settlement cycle, devices, loan flag.",
    "acquiring_ledger.csv": "Every data/seed transaction (same txn_id, amount, timestamp, utr) plus network, masked BIN, rrn, acquirer_ref, NPCI/ISO response code, internal status, batch, MDR and GST applied, risk flag, ingestion time.",
    "npci_utr_log.csv": "One row per UTR: payer PSP/VPA (masked), payee VPA, status SUCCESS/PENDING/FAILED/REVERSED, response code (00, Z9, ZM, U30, U16, U67, ZA, CS), reversal deadline for PENDING, duplicate_group_id. The demo fake UTR is absent.",
    "settlement_batches.csv": "Every T+1 batch (values identical to data/seed/settlements.csv) plus txn_count, payout UTR, account, status.",
    "settlement_lines_2026-11-18.csv": "Line items of STL-20261118: each transaction (+), MDR per transaction (−), GST, refund #4412, rental, hold #9981, with running net.",
    "mdr_rate_card.json": "Illustrative MDR by method and merchant tier.",
    "chargebacks.csv": "Case records with network reason code, hold, Paytm 48h evidence deadline, network deadline, evidence status, status_history (JSON).",
    "refunds.csv": "Refund queue: data/seed refunds + the duplicate-payment candidate; auto_eligible = amount ≤ ₹5,000.",
    "lending/loan_book.json": "Clix Capital loan (same numbers as data/seed/loan.json) + LSP role, DPD, overdue, grace note.",
    "lending/kfs_document.md": "Illustrative Key Fact Statement incl. Clause 4.1 (UPI fallback) and 4.2 (EDI holiday).",
    "lending/enach_mandates.csv": "Mandate registry for the loan.",
    "lending/edi_collections.csv": "Every collection attempt: eNACH presentment per day (same results as data/seed/edi_schedule.csv) + UPI-link / re-presentment recoveries, NACH return codes.",
    "lending/lender_policies.json": "Rules the RiskPolicyAgent applies: EDI holiday, UPI fallback, DPD grace, hardship classification, approvals.",
    "risk/merchant_risk_scores.csv": "Daily health score for 8821 (computed from its GMV trend, EDI record and chargebacks) and the cohort.",
    "risk/fraud_signals.csv": "UTR-not-found, tampered screenshot, duplicate payment and cohort signals.",
    "policies/*.json": "Refund autonomy limit (₹5,000), chargeback evidence rules, turnaround times.",
    "devices/soundbox_fleet.csv / soundbox_telemetry.csv": "Fleet registry (rental ₹149) and hourly telemetry identical to data/seed/device_logs.csv plus server fields.",
    "support/tickets.csv": "L1/L2 ticket history (same IDs as data/seed/support_history.csv); next new ID in ledger_initial_state.",
    "consent/dpdp_consents.csv": "Consent registry: 3 connector consents + valid, expired and revoked A2A tokens.",
    "connectors/shiprocket_pod.json": "PoD for #9981 as received via SHIPROCKET_SYNC, with the SHA-256 of the Sarvam sample PoD image.",
    "learning/outcome_history.csv": "8821's 8 past interventions + 320 cohort outcomes per option (feeds Option A/B/C scoring).",
    "ledger_initial_state.json": "What POST /ledger/reset should restore.",
    "scenarios_paytm.json": "Per intent: the 4-agent trace (reads, decision, state change) and verified outcome.",
}
readme += ["## Data dictionary", "", "| File | Contents |", "|---|---|"] + [f"| `{k}` | {v} |" for k, v in DICT.items()]
(OUT / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")

# ============================================================================ validation (reads back from disk)
R = lambda n: pd.read_csv(OUT / n, dtype=str, keep_default_na=False)  # noqa: E731
J = lambda n: json.loads((OUT / n).read_text(encoding="utf-8"))      # noqa: E731
led, utr, sb, sl = R("acquiring_ledger.csv"), R("npci_utr_log.csv"), R("settlement_batches.csv"), R("settlement_lines_2026-11-18.csv")
cbp, rfp, ec, cons = R("chargebacks.csv"), R("refunds.csv"), R("lending/edi_collections.csv"), R("consent/dpdp_consents.csv")
lb, st0 = J("lending/loan_book.json"), J("ledger_initial_state.json")

# hard constraints
b = sb[sb.batch_id == "STL-20261118"].iloc[0]
assert (int(b.gross), int(b.net_credit), int(b.variance)) == (100000, 95840, 4160)
assert (int(b.mdr), int(b.gst_on_mdr), int(b.refunds), int(b.soundbox_rental), int(b.chargeback_hold)) == (1450, 261, 1500, 149, 800)
assert 1450 + 261 + 1500 + 149 + 800 == 4160
assert (lb["lender"], lb["daily_edi"], lb["outstanding"], lb["kfs_edi_holiday_eligible"], lb["past_edi_success_rate"]) == \
    ("Clix Capital", 500, 42000, True, "96%") and lb["dpd"] == 0
u = utr.set_index("utr")
assert (u.loc[UTR_SUCCESS, "amount"], u.loc[UTR_SUCCESS, "payer_psp"], u.loc[UTR_SUCCESS, "status"]) == ("1250", "GPay", "SUCCESS")
assert (u.loc[UTR_PENDING, "amount"], u.loc[UTR_PENDING, "payer_psp"], u.loc[UTR_PENDING, "status"]) == ("2400", "PhonePe", "PENDING")
assert UTR_FAKE not in set(utr.utr) and UTR_FAKE not in set(led.utr), "fake UTR must be absent"
assert st0["unknown_utr_status"] == "NOT_FOUND_SUSPECTED_FAKE"
assert J("policies/refund_policy.json")["autonomous_limit_inr"] == 5000
assert all((rfp.auto_eligible == "True") == (rfp.amount.astype(int) <= 5000))

# shared IDs/amounts identical to data/seed
assert list(led.txn_id) == list(s_tx.txn_id) and list(led.amount) == list(s_tx.amount)
assert list(led.utr) == list(s_tx.utr) and list(led.timestamp) == list(s_tx.timestamp)
assert set(utr.utr) == set(s_tx.utr[s_tx.utr != ""]) and utr.utr.is_unique
cols = ["batch_id", "gross", "mdr", "gst_on_mdr", "refunds", "soundbox_rental", "chargeback_hold", "chargeback_release", "net_credit"]
assert (sb[cols].values == s_stl[cols].values).all(), "settlement batches must equal data/seed"
assert set(rfp.refund_id) - {f"RFD-DUP-{d2.order_id}"} == set(s_ref.refund_id)
for r in s_ref.itertuples(index=False):
    row = rfp[rfp.refund_id == r.refund_id].iloc[0]
    assert (row.amount, row.order_id, row.txn_id) == (r.amount, r.order_id, r.txn_id)
assert set(cbp.chargeback_id) == set(s_cb.chargeback_id)
for r in s_cb.itertuples(index=False):
    row = cbp[cbp.chargeback_id == r.chargeback_id].iloc[0]
    assert (row.amount, row.order_id, row.txn_id, row.status) == (r.amount, r.order_id, r.txn_id, r.status)
c9 = cbp[cbp.chargeback_id == "CB-9981"].iloc[0]
assert (c9.status, c9.amount, c9.paytm_evidence_due) == ("HELD", "800", "2026-11-19T14:05:00")
assert (lb["loan_id"], lb["sanctioned_amount"], lb["collected_so_far"]) == (s_loan["loan_id"], s_loan["sanctioned_amount"], s_loan["collected_so_far"])
first = ec[ec.attempt_id.str.endswith("-1")]
assert list(first.edi_date) == list(s_edi.edi_date)
assert list(first.result.map({"SUCCESS": "SUCCESS", "RETURNED": "BOUNCED"})) == list(s_edi.status)

# settlement lines reconcile exactly
amt = sl.amount_signed.astype(int)
assert amt[sl.line_type == "TXN"].sum() == 100000
assert -amt[sl.line_type != "TXN"].sum() == 4160 and amt.sum() == 95840 == int(sl.iloc[-1].running_net)
assert -amt[sl.line_type == "MDR"].sum() == 1450 and -amt[sl.line_type == "GST"].sum() == 261

# EDI ~96%, latest failure = 17 Nov, unrecovered
rate = (first.result == "SUCCESS").mean()
assert round(rate * 100) == 96, rate
fails = first[first.result == "RETURNED"]
assert fails.iloc[-1].edi_date == "2026-11-17" and fails.iloc[-1].return_code == "04"
assert not ((ec.edi_date == "2026-11-17") & ec.attempt_id.str.endswith("-2")).any()

# links
led_ids, orders = set(led.txn_id), set(led.order_id)
assert set(cbp.txn_id) <= led_ids and set(cbp.order_id) <= orders and set(rfp.txn_id) <= led_ids and set(rfp.order_id) <= orders
for r in cbp.itertuples(index=False):
    assert led.set_index("txn_id").loc[r.txn_id, "order_id"] == r.order_id
pod = J("connectors/shiprocket_pod.json")
assert pod["order_id"] == "9981" and pod["chargeback_id"] == "CB-9981" and pod["awb"] == c9.pod_awb
assert pod["pod"]["recipient"] == "Rohit Verma" and pod["pod"]["otp_verified"] and pod["payment_txn_id"] == c9.txn_id
dg = utr[utr.duplicate_group_id != ""]
assert len(dg) == 2 and dg.order_id.nunique() == 1 and (dg.status == "SUCCESS").all()
assert {"REVERSED", "FAILED", "PENDING", "SUCCESS"} <= set(utr.status)

rk = R("risk/merchant_risk_scores.csv"); r8 = rk[rk.mid == MID].set_index("date")
assert r8.health_score.astype(float).min() >= 75, "8821 must stay healthy through the dip"
assert set(r8.loc["2026-11-15":"2026-11-17", "classification"]) == {"FRICTION_NOT_DEFAULT"}

# consent
assert (cons.status == "EXPIRED").any() and (cons.status == "ACTIVE").any()
assert all(TOKEN_RE.match(t) for t in cons.token)
assert TOKEN_RE.match(st0["consent"]["valid_token_example"])

print(f"""
All checks passed. Wrote {sum(1 for _ in OUT.rglob('*') if _.is_file())} files to {OUT}
  ledger          {len(led):,} rows mirror data/seed exactly (txn_id, amount, timestamp, UTR)
  NPCI log        {len(utr):,} UTRs: {', '.join(f'{k} {v}' for k, v in utr.status.value_counts().items())}; …0555 absent
  STL-20261118    {len(sl)} lines: +₹1,00,000 − ₹4,160 = ₹95,840
  lending         {(first.result == 'SUCCESS').sum()}/{len(first)} first-attempt EDIs ({rate:.1%}); latest failure 17 Nov (04), DPD 0
  cohort          {len(merchants) - 1} Gurugram electronics stores; {len(learn):,} outcomes for Option A/B/C learning
  consent         valid {CONSENT_VALID} / expired {CONSENT_EXPIRED}
""")
