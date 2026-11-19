# Key Fact Statement (ILLUSTRATIVE)

> ILLUSTRATIVE: synthetic demo values, not actual Paytm pricing or policy. Not an actual Clix Capital or Paytm document.

| Item | Value |
|---|---|
| Borrower | Sharma Electronics (PAYTM_MERCH_8821) |
| Lender (Regulated Entity) | Clix Capital (NBFC) |
| Lending Service Provider | Paytm |
| Loan ID | CLX-ML-26-008821 |
| Sanctioned amount | ₹115,000 |
| Processing fee | ₹1,150 (deducted at disbursal) |
| Net disbursed | ₹113,850 on 2026-05-31 |
| Repayment | ₹500 per day (EDI) × 254 = ₹127,000 |
| Annual Percentage Rate (APR) | 31.89% (all-inclusive) |
| Collection | Daily eNACH auto-debit, mandate UMRN-DEMO-0000008821 |
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
