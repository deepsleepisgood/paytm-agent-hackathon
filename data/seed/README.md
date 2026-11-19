# Seed data: Sharma Electronics (PAYTM_MERCH_8821)

Synthetic, deterministic dataset for the Build for Bharat demo. **Every name, number, GSTIN, UTR and address is invented.**

```bash
pip install pandas
python data/generate_seed.py   # rewrites data/seed/* and runs all validation checks
```

Period: 2026-05-19 → 2026-11-18 (184 days). Snapshot: 2026-11-19 09:00 IST on the demo day (2026-11-19).
Seed: `8821`. Re-running produces byte-identical files.

## How the contract values reconcile

| Contract value | How the data makes it true |
|---|---|
| Daily average ₹32,000 | The 184 daily totals are scaled to exactly ₹58,88,000 (= ₹32,000 × 184), with every effect below included. |
| Fri–Sun 2.3× | The weekend factor is calibrated until the observed Fri–Sun average ÷ Mon–Thu average is 2.30. |
| ₹1,00,000 gross in one settlement | `STL-20261118` is the **T+1 batch for Tue 17 Nov**: the market reopened after a 3-day closure and Rao PG & Hostels paid **₹55,000 by credit card** to fit out a new PG (fans, LED panels, wiring). |
| MDR ₹1,450 (UPI is 0%) | That day's MDR-bearing volume: card + Paytm Postpaid ₹62,600 × 2% = ₹1,252, wallet-on-UPI over ₹2,000 ₹18,000 × 1.1% = ₹198. UPI ₹19,400 × 0%. Electronics sees more card use than a kirana, but UPI is still the largest rail over 6 months. |
| GST ₹261 | 18% of ₹1,450. The store is GST-registered (turnover ~₹1.17 Cr/yr), so it's claimable as ITC. |
| Refund #4412 ₹1,500 | Philips kettle bought 10 Oct as a Diwali gift, failed after first use, returned 16 Nov, refund processed 17 Nov → deducted in the 18 Nov batch. |
| Soundbox ₹149 | Monthly rental, billed on the 18th of each month. |
| Chargeback #9981 ₹800 HELD | ONDC order placed 14 Nov, delivered 16 Nov (OTP + signature), dispute raised 17 Nov → held in the 18 Nov batch. |
| Net ₹95,840 | 1,00,000 − (1,450 + 261 + 1,500 + 149 + 800) = 95,840. |
| EDI ₹500/day, 96% success | eNACH from 1 Jun: 164 of 171 first attempts succeeded (95.9%). EDI is debited from the **bank account**, not netted from settlements, which is why it's absent from the 18 Nov breakdown and how a mandate can bounce. |
| Loan balance ₹42,000 | Total repayable ₹1,27,000 (254 × ₹500) − collected ₹85,000 (164 successes + 6 recovered bounces). The 17 Nov bounce is not yet recovered. |
| ₹4,500 due tomorrow | `PAY-TOMORROW`: Gaffar Market accessories wholesaler invoice of 18 Nov (chargers, earphones for the weekend), due Fri 20 Nov. |
| Cashflow: payout ₹1,200 | Contract V2 numbers kept (plan.md's ₹8,500 refund was not used): ₹4,700 collected by 11:30 on 19 Nov − ₹3,500 refund request #4490 = ₹1,200. |
| UTRs | `632184920111` ₹1,250 GPay SUCCESS (18 Nov 11:03), `632184920999` ₹2,400 PhonePe PENDING (18 Nov 18:15). `632184920555` (fake-screenshot test) is deliberately **absent**. |
| Connectors | SHIPROCKET_SYNC, VYAPAR_POS_SYNC, RBI_ACCOUNT_AGGREGATOR are all ACTIVE with DPDP consent GRANTED. |

Other decisions:
- **Shop type:** an electronics, appliances and electricals shop, as in contract.md (*Sharma Electronics*). Bills are fewer and larger than a kirana's, card use is higher, summer lifts fan sales, and Dhanteras (6 Nov) is the biggest day of the festive run.
- **Khata** (store credit) goes to 8 local electricians who buy wires and switches for site jobs.
- **Rain in November** isn't realistic for Gurugram, so the dip before the 17 Nov bounce is a **market closure** (14–16 Nov). Monsoon rain explains the July/August bounces.
- **Chargeback #9981** uses exactly the values on `services/sarvam_service/app/samples/pod_9981.png` (₹800, delivered 2026-11-16 to Rohit Verma, OTP-verified, AWB DEX7781203345).
- contract.md calls the dispute `TXNID #9981`; the real payment row has a normal txn_id, and `chargebacks.csv.contract_ref` keeps the contract's name.
- **Intent names:** `scenarios.json` uses the 8 plan.md names and adds `contract_v1_intent` for the 6 older names.

## Scenario stories

- **MANDATE_TROUBLESHOOT**: Market closure cut sales ~40% for 3 days, so the 17 Nov eNACH bounced; sales recovered the same day and the EDI record is 96% on time: friction, not default. → *EDI for 2026-11-17 marked RECOVERED_VIA_UPI_LINK, no penalty, mandate stays ACTIVE*
- **SETTLEMENT_RECONCILE**: ₹1,00,000 gross on 17 Nov (PG owner's card order) -> MDR ₹1,450 + GST ₹261 (ITC) + refund #4412 ₹1,500 + Soundbox ₹149 + hold #9981 ₹800 = ₹4,160; net ₹95,840. → *Merchant sees itemised ₹4,160; ₹261 logged to ITC register; ₹800 linked to CB-9981*
- **CHARGEBACK_RESOLVE**: ONDC buyer claims non-delivery, but Shiprocket holds an OTP-verified, signed PoD (delivered 16 Nov to Rohit Verma); merchant signs off in one tap. → *CB-9981 HELD -> RELEASED; ₹800 added back in the next settlement*
- **UTR_VERIFY**: …0111 is a settled GPay payment, …0999 is PhonePe PENDING (auto-reversal T+1), …0555 is not in the NPCI log. → *Fraud blocked; no goods released against an unverified screenshot*
- **DUPLICATE_RECONCILE**: PhonePe charged ₹1,180 twice, 48 seconds apart, for one order; both UTRs map to the same order. → *Refund for the second UTR PROCESSED; order reconciled to one payment*
- **GROWTH_ADVISORY**: ₹32,000/day average with a 2.3x Fri–Sun peak; chargers, earphones, LED bulbs and extension boards run out on weekends. → *Advice delivered with cited numbers; no money moved without consent*
- **CASHFLOW_EDI_SWITCH**: A ₹3,500 refund (#4490) leaves a ₹1,200 payout against ₹4,500 owed to the Gaffar Market accessories wholesaler on Friday for weekend stock. → *loan_edi_status PAUSED_2_DAYS, ₹1,000 freed, EDI resumes 2026-11-21*
- **ESCALATE_HUMAN**: Battery health fell from 41% to 18%; heartbeats and announcements fail from 15 Nov. → *TKT-PAYTM-xxxx created with logs; merchant not asked to repeat anything*

## Data dictionary

### `merchant_profile.json`
Merchant identity, KYC, address, settlement terms + MDR rates, devices, the 3 consented connectors, `historical_memory` (the 8 contract values, verbatim) and the top 10 customers.

### `customers.csv`
| Column | Meaning |
|---|---|
| `customer_id` | C001–C150, plus WALKIN for unidentified one-off shoppers |
| `name` | Synthetic Indian name |
| `phone_masked` | Masked mobile |
| `locality` | Gurugram sector (in-store) or NCR area (ONDC) |
| `segment` | regular / electrician (buys on khata) / ondc / bulk / walk_in |
| `first_seen` | First transaction date |
| `on_khata` | True if the customer buys on store credit |
| `preferred_app` | Most used UPI app |

### `transactions.csv`
| Column | Meaning |
|---|---|
| `txn_id` | PTM + yymmdd + daily sequence |
| `timestamp` | IST, store hours 07:00–22:00 |
| `amount` | INR integer |
| `method` | UPI / card / wallet / postpaid |
| `card_type` | credit / debit (RuPay) for cards |
| `payer_app` | GPay, PhonePe, Paytm, BHIM, Amazon Pay, Paytm Wallet, Paytm Postpaid, Card (…) |
| `utr` | 12-digit UPI reference (UPI and wallet-on-UPI only); read as text, e.g. `dtype={'utr': str}` |
| `status` | SUCCESS / PENDING / FAILED (only SUCCESS counts toward gross) |
| `customer_id` | FK → customers.csv |
| `order_id` | BILL-yymmdd-nnnn (POS bill), 44xx (phone/home-delivery order) or 99xx (ONDC order) |
| `channel` | in-store / ONDC |
| `mdr_rate` | Rate applied (see merchant_profile.settlement.mdr_rates) |
| `mdr_amount` | MDR on this transaction (2 decimals; batch MDR is rounded to whole rupees) |
| `settlement_batch_id` | FK → settlements.csv (T+1) |
| `tag` | Marks demo-relevant records (e.g. ORDER_9981, UTR_SUCCESS) |

### `daily_sales_summary.csv`
| Column | Meaning |
|---|---|
| `date` | Calendar day |
| `weekday` | Day name |
| `gross` | Sum of SUCCESS transactions |
| `txn_count` | Number of SUCCESS transactions |
| `avg_ticket` | gross / txn_count |
| `upi_share_by_value` | UPI share of gross |
| `is_weekend` | Fri, Sat or Sun |
| `is_festival` | Diwali run-up 31 Oct – 8 Nov (Dhanteras 6 Nov) |
| `rain_dip` | Heavy-rain day (monsoon) |
| `closure_dip` | Market closure 14–16 Nov (~40% dip) |
| `bulk_order_day` | 17 Nov PG fit-out order |
| `note` | Human-readable context |

### `settlements.csv`
| Column | Meaning |
|---|---|
| `batch_id` | STL-<settlement date> |
| `settlement_date` | Credit date (T+1) |
| `txn_date` | Transactions covered |
| `gross` | Sum of SUCCESS transactions on txn_date |
| `mdr` | Whole-rupee MDR |
| `gst_on_mdr` | 18% of MDR |
| `refunds` | Refunds processed on txn_date |
| `soundbox_rental` | ₹149 on the 18th of each month |
| `chargeback_hold` | Disputes raised on txn_date |
| `chargeback_release` | Won disputes resolved on txn_date |
| `net_credit` | gross − deductions + releases |
| `variance` | gross − net_credit |
| `credited_at` | Bank credit time |
| `payout_ref` | Payout reference |
| `status` | SUCCESS |

### `settlement_breakdown_2026-11-18.json`
The contract batch, item by item, with the rail-level MDR calculation and the source record of every deduction.

### `loan.json`
Clix Capital loan: amounts, eNACH mandate, KFS (APR, clauses 4.1–4.3 incl. the 4.2 EDI holiday), collected and balance.

### `edi_schedule.csv`
| Column | Meaning |
|---|---|
| `edi_date` | Presentment date (daily from 1 Jun) |
| `amount` | ₹500 |
| `channel` | eNACH |
| `status` | SUCCESS / BOUNCED |
| `bounce_code` | Reason code |
| `bounce_reason` | Bank reason |
| `context` | What caused it |
| `recovery` | REMINDER_ONLY / UPI_LINK / AUTO_RETRY / PENDING |
| `recovery_note` | How and how fast it was recovered |
| `cumulative_collected` | Running total collected |
| `balance_after` | total_repayable − cumulative_collected |

### `refunds.csv`
| Column | Meaning |
|---|---|
| `refund_id` | RFD-… |
| `order_id` | FK → transactions.order_id |
| `txn_id` | FK → transactions.csv |
| `customer_id` | FK → customers.csv |
| `amount` | INR |
| `reason` | Why |
| `requested_at` | Request time |
| `processed_at` | Processing time (null if pending) |
| `status` | PROCESSED / REQUESTED |
| `deducted_in_batch` | Settlement batch that deducts it |

### `chargebacks.csv`
| Column | Meaning |
|---|---|
| `chargeback_id` | CB-… |
| `txn_id` | FK → transactions.csv |
| `order_id` | FK → shiprocket_orders.json |
| `customer_id` | FK → customers.csv |
| `amount` | INR held |
| `reason_code` | Dispute reason |
| `raised_at` | Dispute time |
| `respond_by` | 48h deadline |
| `status` | HELD / WON / LOST |
| `resolved_at` | Resolution time |
| `held_in_batch` | Batch with the hold |
| `released_in_batch` | Batch with the release |
| `pod_awb` | Shipment AWB |
| `evidence` | What evidence exists |
| `contract_ref` | Contract name for the record |

### `shiprocket_orders.json`
SHIPROCKET_SYNC connector view: every ONDC order with items, courier, AWB, status and PoD (delivered_at, recipient, otp_verified, signature, document).

### `utr_ledger.csv`
| Column | Meaning |
|---|---|
| `utr` | 12-digit UPI reference (read as text: `pd.read_csv(..., dtype={'utr': str})`) |
| `txn_id` | FK → transactions.csv |
| `amount` | INR |
| `payer_app` | UPI app |
| `payer_vpa_masked` | Masked payer VPA |
| `npci_status` | SUCCESS / PENDING / FAILED |
| `timestamp` | IST |
| `order_id` | Order / bill |
| `customer_id` | FK → customers.csv |
| `flag` | DUPLICATE / PENDING_AUTO_REVERSAL_T+1 / blank |

### `supplier_payables.csv`
| Column | Meaning |
|---|---|
| `payable_id` | PAY-… |
| `supplier` | Distributor |
| `invoice_no` | Invoice |
| `amount` | INR |
| `invoice_date` | Invoice date |
| `due_date` | Due date |
| `status` | PAID / DUE |
| `paid_on` | Payment date |
| `source` | VYAPAR_POS_SYNC |

### `khata.csv`
| Column | Meaning |
|---|---|
| `entry_id` | KH-… |
| `customer_id` | FK → customers.csv |
| `timestamp` | IST |
| `type` | credit_given / payment_received |
| `amount` | INR |
| `txn_id` | FK → transactions.csv for repayments |
| `balance_after` | Outstanding store credit |
| `note` | Context |

### `inventory.csv`
| Column | Meaning |
|---|---|
| `sku` | SKU code |
| `name` | Product |
| `brand` | Brand |
| `category` | Category |
| `unit` | Selling unit |
| `cost_price` | INR |
| `selling_price` | INR |
| `mrp` | INR |
| `margin_pct` | (sell − cost) / sell |
| `stock_qty` | Units on hand (as of snapshot) |
| `reorder_point` | Reorder threshold |
| `below_reorder` | stock_qty < reorder_point |
| `supplier` | Distributor |
| `weekend_stockout_count_6m` | Weekends it ran out in the last 6 months |

### `device_logs.csv`
| Column | Meaning |
|---|---|
| `ts` | Hourly, 1–18 Nov |
| `device_id` | SB-8821-01 |
| `device` | Model |
| `battery_pct` | Charge |
| `battery_health_pct` | Battery health (degrading from 10 Nov) |
| `network` | 4G / 2G / offline |
| `signal_dbm` | Signal strength |
| `heartbeat_ok` | Device reached Paytm servers |
| `announce_failures` | Payments it failed to announce that hour |
| `event` | Notable event |

### `support_history.csv`
| Column | Meaning |
|---|---|
| `ticket_id` | TKT-PAYTM-… |
| `opened_at` | IST |
| `intent` | Plan intent |
| `summary` | Issue |
| `channel` | voice / app_chat |
| `resolution` | What was done |
| `resolved_at` | IST |
| `outcome` | RESOLVED / WON / LOST / FRAUD_PREVENTED / OPEN |
| `csat` | 1–5 |

### `strategy_memory.json`
Past interventions with options considered, choice and verified outcome, plus learned policies the Merchant Buddy can cite.

### `scenarios.json`
One ready fixture per intent: Hinglish trigger, exact record IDs, story, expected root cause, intervention and verified outcome.
