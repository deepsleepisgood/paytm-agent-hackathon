# Paytm-side dataset: Sharma Electronics (PAYTM_MERCH_8821)

> ILLUSTRATIVE: synthetic demo values, not actual Paytm pricing or policy. Derived from `data/seed/`, which is the single source of truth.

```bash
python data/generate_paytm.py   # reads data/seed/, rewrites data/paytm/, runs all checks
```

## Cross-dataset key map

| Thing | data/seed (merchant side) | data/paytm (Paytm side) |
|---|---|---|
| Merchant | merchant_profile.mid | merchant_master.mid |
| Payment | transactions.txn_id / utr | acquiring_ledger.txn_id / utr (+ acquirer_ref, rrn, NPCI code), npci_utr_log.utr |
| Settlement | settlements.batch_id | settlement_batches.batch_id, settlement_lines_2026-11-18.batch_id |
| Refund | refunds.refund_id | refunds.refund_id (+ queue status, approver); RFD-DUP-* is Paytm-only |
| Chargeback | chargebacks.chargeback_id | chargebacks.chargeback_id (+ case_id, network code, status_history) |
| Shipment / PoD | shiprocket_orders.awb | connectors/shiprocket_pod.awb |
| Loan | loan.loan_id, loan.mandate.umrn | lending/loan_book.loan_id, enach_mandates.umrn |
| EDI | edi_schedule.edi_date | edi_collections.edi_date (1–2 attempts per date) |
| Device | device_logs.device_id | soundbox_fleet / soundbox_telemetry.device_id |
| Tickets | support_history.ticket_id | support/tickets.ticket_id |
| Consent | merchant_profile.connectors | consent/dpdp_consents.connector |

## Conflict log

- **Shop type:** the request said *Sharma Kirana Store*; data/seed is *Sharma Electronics*, so the cohort is 50 Gurugram electronics/appliance stores.
- **TXNID #9981:** contract.md uses "9981" as a txn_id; the real payment is `PTM26111400012`, kept in `contract_ref`.
- **EDI collection:** contract.md says "next deduction: tomorrow's settlement"; data/seed collects by eNACH from the bank account.
- **Latest EDI attempt:** the latest *attempt* is 18 Nov (SUCCESS); the latest *failure* is the 17 Nov return, still unrecovered. The checks test the latter.
- **DPD 0 with ₹500 overdue:** reconciled by a 3-day grace period in `lending/lender_policies.json` (illustrative).
- **#4490 refund:** requested 19 Nov 11:20, after the 09:00 snapshot; kept as QUEUED in the initial state to match the cashflow demo.
- **data/seed blemishes:** an empty `resolved_at` was written as `NaT` and `csat` as `5.0`; read safely here.

## What `services/paytm_agent` should change to match (option a: data/seed wins)

| Item | paytm_agent/app/seed.py today | Should be |
|---|---|---|
| MDR split (total ₹1,450 either way) | card 45,000 @2% + wallet 50,000 @1.1% + UPI 5,000 | card+postpaid 62,600 @2% + wallet 18,000 @1.1% + UPI 19,400 (`ledger_initial_state.settlement.mdr_split`) |
| Mandate bounce date | 2026-11-19 | 2026-11-17 (return code 04, Balance insufficient) |
| Bounce charge | ₹118 | ₹0: waived under KFS 4.1 (first return in 30 days) |
| Duplicate payment | order 4455, ₹3,200 × 2, UTRs 632184925001/002 | order 4489, ₹1,180 × 2, UTRs 632299206882 / 632230725895 (PhonePe) |
| Chargeback txn_id | "9981" | PTM26111400012 (contract_ref keeps "TXNID #9981") |
| Missing/invalid consent token | HTTP 400 CONSENT_MISSING | HTTP 403 (contract.md) |
| Timestamps | UTC (+00:00) | IST |

Simplest: have `POST /ledger/reset` load `data/paytm/ledger_initial_state.json`.

## How each scenario flows through the 4 agents

### MANDATE_TROUBLESHOOT
1. **IntelligenceAgent** reads `lending/edi_collections.csv`, `lending/enach_mandates.csv`, `risk/merchant_risk_scores.csv`: 17 Nov eNACH returned 04 (balance insufficient) after a 3-day market closure; 18 Nov EDI succeeded; health LOW risk
1. **RiskPolicyAgent** reads `lending/lender_policies.json`, `learning/outcome_history.csv`: First-attempt success 95.9% ≥ 90%, DPD 0, sales recovered next day → FRICTION_NOT_DEFAULT; Option B (UPI link) best: 91% success
1. **ResolutionAgent** reads `lending/kfs_document.md (4.1)`: Send 1-tap UPI link for ₹500; bounce charge waived under 4.1
1. **LedgerOpsAgent** reads `lending/loan_book.json`: On payment: mark 17 Nov EDI recovered, overdue 0

**Verified outcome:** EDI 2026-11-17 RECOVERED_VIA_UPI_LINK, bounce charge ₹0, DPD 0, mandate ACTIVE

### SETTLEMENT_RECONCILE
1. **IntelligenceAgent** reads `settlement_batches.csv`, `settlement_lines_2026-11-18.csv`, `acquiring_ledger.csv`: STL-20261118: gross ₹1,00,000 from 17 Nov; 6 deduction lines total ₹4,160
1. **RiskPolicyAgent** reads `mdr_rate_card.json`: All deductions match the (illustrative) rate card; nothing to dispute
1. **ResolutionAgent** reads —: Itemise: MDR ₹1,450 (card/postpaid/wallet), GST ₹261 (ITC), refund #4412 ₹1,500, rental ₹149, hold #9981 ₹800
1. **LedgerOpsAgent** reads —: No money moves; record explanation

**Verified outcome:** Variance ₹4,160 explained line by line; ₹261 ITC flagged; ₹800 linked to CB-9981

### CHARGEBACK_RESOLVE
1. **IntelligenceAgent** reads `chargebacks.csv`, `connectors/shiprocket_pod.json`, `consent/dpdp_consents.csv`: CB-9981 HELD ₹800, reason 13.1; PoD delivered 16 Nov 18:42 to Rohit Verma (OTP + signature); consent ACTIVE
1. **RiskPolicyAgent** reads `policies/chargeback_policy.json`, `policies/dispute_tat.json`: PoD predates dispute, recipient matches, inside 48h evidence window → submit (needs merchant sign-off)
1. **ResolutionAgent** reads —: Submit evidence pack after 1-tap sign-off
1. **LedgerOpsAgent** reads `settlement_batches.csv`: Release hold into next batch

**Verified outcome:** CB-9981 HELD → RELEASED; ₹800 credited in the next T+1 batch

### UTR_VERIFY
1. **IntelligenceAgent** reads `npci_utr_log.csv`: 632184920111: SUCCESS; 632184920999: PENDING (reversal by T+1); 632184920555: not found
1. **RiskPolicyAgent** reads `risk/fraud_signals.csv`: Not found + screenshot → NOT_FOUND_SUSPECTED_FAKE (score high)
1. **ResolutionAgent** reads —: Neutral advice: don't hand over goods until the Soundbox announces the payment
1. **LedgerOpsAgent** reads —: Log fraud signal

**Verified outcome:** Fake screenshot blocked; genuine and pending UTRs reported with their real status

### DUPLICATE_RECONCILE
1. **IntelligenceAgent** reads `npci_utr_log.csv`, `acquiring_ledger.csv`: Order 4489: two SUCCESS UTRs, same customer, ₹1,180 each, 48 s apart (DUPGRP-4489)
1. **RiskPolicyAgent** reads `policies/refund_policy.json`: ₹1,180 ≤ ₹5,000 and provable → AUTO
1. **ResolutionAgent** reads —: Refund the second payment to the original instrument
1. **LedgerOpsAgent** reads `refunds.csv`: Queue refund in next batch

**Verified outcome:** RFD-DUP-4489 PROCESSED (₹1,180); order reconciled to one payment

### GROWTH_ADVISORY
1. **IntelligenceAgent** reads `acquiring_ledger.csv`, `merchant_master.csv`: ₹32,000/day, Fri–Sun 2.3×, GMV in cohort top half
1. **RiskPolicyAgent** reads `risk/merchant_risk_scores.csv`, `lending/lender_policies.json`: LOW risk, DPD 0 → eligible to *see* a working-capital offer (KFS shown first)
1. **ResolutionAgent** reads —: Advise stocking up by Thursday; optional offer with KFS link; no auto-acceptance
1. **LedgerOpsAgent** reads —: Record advice; no money moved

**Verified outcome:** Advice delivered with cited numbers; any credit needs explicit acceptance after KFS

### CASHFLOW_EDI_SWITCH
1. **IntelligenceAgent** reads `refunds.csv`, `consent/dpdp_consents.csv`: RFD-4490 ₹3,500 queued → projected payout ₹1,200 vs ₹4,500 payable (VYAPAR_POS_SYNC, consented)
1. **RiskPolicyAgent** reads `lending/lender_policies.json`, `lending/kfs_document.md (4.2)`, `lending/loan_book.json`: Clause 4.2: DPD 0, 95.9% ≥ 90%, no holiday in last 30 days, gap documented → eligible; needs lender approval
1. **ResolutionAgent** reads —: Request Clix Capital approval with merchant consent token; approval logged
1. **LedgerOpsAgent** reads `lending/loan_book.json`: Pause EDIs 19–20 Nov, append to tenure end

**Verified outcome:** EDI PAUSED_2_DAYS with lender approval + KFS consent artifact; ₹1,000 freed; resumes 2026-11-21

### ESCALATE_HUMAN
1. **IntelligenceAgent** reads `devices/soundbox_telemetry.csv`, `devices/soundbox_fleet.csv`, `support/tickets.csv`: SB-8821-01 battery health 41% → 18%, heartbeats missed from 15 Nov; TKT-PAYTM-1290 still open
1. **RiskPolicyAgent** reads `policies/dispute_tat.json`: Hardware fault → needs a human (replacement), L2
1. **ResolutionAgent** reads —: Open TKT-PAYTM-1291 (L2, Device Ops) with diagnostics attached
1. **LedgerOpsAgent** reads —: Link ticket to device and merchant; close duplicate TKT-PAYTM-1290

**Verified outcome:** TKT-PAYTM-1291 created with logs; replacement within 2 days; merchant repeats nothing

## Data dictionary

| File | Contents |
|---|---|
| `merchant_master.csv` | MID 8821 + 50 cohort stores: category, MCC, KYC tier, onboarding, risk tier, average daily GMV, settlement cycle, devices, loan flag. |
| `acquiring_ledger.csv` | Every data/seed transaction (same txn_id, amount, timestamp, utr) plus network, masked BIN, rrn, acquirer_ref, NPCI/ISO response code, internal status, batch, MDR and GST applied, risk flag, ingestion time. |
| `npci_utr_log.csv` | One row per UTR: payer PSP/VPA (masked), payee VPA, status SUCCESS/PENDING/FAILED/REVERSED, response code (00, Z9, ZM, U30, U16, U67, ZA, CS), reversal deadline for PENDING, duplicate_group_id. The demo fake UTR is absent. |
| `settlement_batches.csv` | Every T+1 batch (values identical to data/seed/settlements.csv) plus txn_count, payout UTR, account, status. |
| `settlement_lines_2026-11-18.csv` | Line items of STL-20261118: each transaction (+), MDR per transaction (−), GST, refund #4412, rental, hold #9981, with running net. |
| `mdr_rate_card.json` | Illustrative MDR by method and merchant tier. |
| `chargebacks.csv` | Case records with network reason code, hold, Paytm 48h evidence deadline, network deadline, evidence status, status_history (JSON). |
| `refunds.csv` | Refund queue: data/seed refunds + the duplicate-payment candidate; auto_eligible = amount ≤ ₹5,000. |
| `lending/loan_book.json` | Clix Capital loan (same numbers as data/seed/loan.json) + LSP role, DPD, overdue, grace note. |
| `lending/kfs_document.md` | Illustrative Key Fact Statement incl. Clause 4.1 (UPI fallback) and 4.2 (EDI holiday). |
| `lending/enach_mandates.csv` | Mandate registry for the loan. |
| `lending/edi_collections.csv` | Every collection attempt: eNACH presentment per day (same results as data/seed/edi_schedule.csv) + UPI-link / re-presentment recoveries, NACH return codes. |
| `lending/lender_policies.json` | Rules the RiskPolicyAgent applies: EDI holiday, UPI fallback, DPD grace, hardship classification, approvals. |
| `risk/merchant_risk_scores.csv` | Daily health score for 8821 (computed from its GMV trend, EDI record and chargebacks) and the cohort. |
| `risk/fraud_signals.csv` | UTR-not-found, tampered screenshot, duplicate payment and cohort signals. |
| `policies/*.json` | Refund autonomy limit (₹5,000), chargeback evidence rules, turnaround times. |
| `devices/soundbox_fleet.csv / soundbox_telemetry.csv` | Fleet registry (rental ₹149) and hourly telemetry identical to data/seed/device_logs.csv plus server fields. |
| `support/tickets.csv` | L1/L2 ticket history (same IDs as data/seed/support_history.csv); next new ID in ledger_initial_state. |
| `consent/dpdp_consents.csv` | Consent registry: 3 connector consents + valid, expired and revoked A2A tokens. |
| `connectors/shiprocket_pod.json` | PoD for #9981 as received via SHIPROCKET_SYNC, with the SHA-256 of the Sarvam sample PoD image. |
| `learning/outcome_history.csv` | 8821's 8 past interventions + 320 cohort outcomes per option (feeds Option A/B/C scoring). |
| `ledger_initial_state.json` | What POST /ledger/reset should restore. |
| `scenarios_paytm.json` | Per intent: the 4-agent trace (reads, decision, state change) and verified outcome. |
