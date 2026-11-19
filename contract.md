# A2A Merchant-Paytm Resolution Network — Multi-Intent Contract

## Ports & CORS (Allow http://localhost:3000)
- Person 1 (`services/sarvam_service`): Port `8001`
- Person 2 (`services/paytm_agent`): Port `8002`
- Person 3 (`services/merchant_agent`): Port `8003`
- Person 4 (`frontend`): Port `3000`

## Supported Intents
`SETTLEMENT_RECONCILE` | `UTR_VERIFY` | `CHARGEBACK_RESOLVE` | `REFUND_MANAGE` | `FEE_GST_LOAN` | `ESCALATE_HUMAN`

## Unified Seed Data (MID: `PAYTM_MERCH_8821` — "Sharma Electronics")
- **Settlement (2026-11-18):** Gross `₹1,00,000` | Net Bank Credit `₹95,840` | Variance `₹4,160`:
  - MDR Fee: `₹1,450` (2% Credit Card, 1.1% Wallet-on-UPI >₹2k, 0% Bank UPI)
  - 18% GST on MDR (ITC eligible): `₹261`
  - Customer Refund (`ORDER #4412`): `₹1,500` (Status: `PROCESSED`)
  - Soundbox Rental: `₹149`
  - Chargeback Hold (`TXNID #9981`, `ORDER #9981`): `₹800` (Status: `HELD`, PoD due in 48h)
- **Active Merchant Loan EDI:** `₹500/day` (Next deduction: tomorrow's settlement, Balance: `₹42,000`)
- **Recent UPI Transactions (for UTR_VERIFY):**
  - UTR `632184920111` | `₹1,250` | Payer App: GPay | Status: `SUCCESS` (Settled)
  - UTR `632184920999` | `₹2,400` | Payer App: PhonePe | Status: `PENDING` (NPCI T+1 auto-reversal)
  - Any unknown/tampered UTR -> Status: `NOT_FOUND_SUSPECTED_FAKE`

## Endpoints

### Person 1 (8001 — Sarvam)
- `POST /stt` (form-data `audio`) -> `{ "transcript", "language_code" }`
- `POST /tts` (`{ "text", "language_code": "hi-IN" }`) -> `{ "audio_base64" }`
- `POST /doc-extract` (form-data `file`, `doc_type`: `"pod" | "upi_screenshot"`) -> `{ "doc_type", "extracted_fields": {...}, "confidence": 0.96 }`
- `POST /llm` (`{ "system_prompt", "user_prompt", "response_format": "text" | "json" }`) -> `{ "reply" }`

### Person 2 (8002 — Paytm AI Teammate)
- `GET /ledger/{mid}` -> Full live state (settlement breakdown, transactions, loan EDI, chargeback status, tickets deflected, fraud blocked).
- `POST /a2a/dispatch` -> `{ "request_id", "mid", "intent", "payload": {...}, "consent_token" }` -> Returns `{ "status", "intent", "data": {...}, "action_required": {...} | null, "escalation_ticket": {...} | null }`.
- `POST /ledger/reset` -> Resets all in-memory state.

### Person 3 (8003 — Merchant AI Teammate)
- `POST /merchant/query` -> `{ "text", "mid", "consent_granted": true, "doc_context": {...} | null }`
- `POST /merchant/query-audio` -> form-data `audio`, `mid`, `consent_granted`
- `POST /merchant/upload-doc` -> form-data `file`, `doc_type` (`"pod" | "upi_screenshot"`), `mid`, `consent_granted`
- `GET /events` -> Chronological A2A + DPDP compliance log.
- `POST /reset` -> Clears events & local ITC log.

---

## V2 Upgrade Delta (Ideas 1 & 2 — Proactive Chargeback Shield + Cashflow/EDI Switch)

### Seeded Consented Connectors (Inside Paytm for Business App)
- `SHIPROCKET_SYNC`: `ACTIVE` (DPDP Consent: `GRANTED`, contains signed PoD for `ORDER #9981`)
- `VYAPAR_POS_SYNC`: `ACTIVE` (DPDP Consent: `GRANTED`, tracks daily stock payables: `₹4,500` due tomorrow)
- `ACTIVE_LOAN_KFS`: Partner NBFC `Clix Capital` | Daily EDI: `₹500/day` | `edi_holiday_eligible: true` (max 2-day pause under KFS clause 4.2)

- The connectors live on the **merchant side**, so 8003 holds their seed data. Paytm (8002) never reads them directly.
- The Shiprocket PoD document is `dataset/test_files/pod_9981.png`. If that file is missing, 8003 falls back to a built-in PoD.

### Demo flow (who calls whom)
There is no real webhook in the MVP. **The frontend "simulates" Paytm's webhook** by calling 8003, and **8003 then fetches the alert from 8002**:

```
Frontend --POST /merchant/proactive-shield--> 8003 --POST /a2a/proactive-alert--> 8002
Frontend <--offer + Hindi voice prompt------- 8003
Frontend --POST /merchant/confirm-dispute | /merchant/confirm-edi-pause--> 8003 --> 8002
```

Scenario names map 1:1 between the two services:

| 8003 `scenario` | 8002 `trigger_type` | Intent used in responses/events |
|---|---|---|
| `CHARGEBACK_INCOMING` | `CHARGEBACK_INCOMING` | `CHARGEBACK_RESOLVE` |
| `CASHFLOW_EDI_SWITCH` | `HIGH_REFUND_CASHFLOW` | `FEE_GST_LOAN` |

### New / Updated Endpoints

#### Person 2 (8002 — Paytm AI Teammate)
- `POST /a2a/proactive-alert` -> Input: `{ "mid": "PAYTM_MERCH_8821", "trigger_type": "CHARGEBACK_INCOMING" | "HIGH_REFUND_CASHFLOW" }`
  - If `CHARGEBACK_INCOMING`: Pushes incoming dispute alert for `TXNID #9981` (`₹800`, 48h deadline).
  - If `HIGH_REFUND_CASHFLOW`: Simulates a `₹3,500` customer refund request (`ORDER #4490`) + checks KFS eligibility, returning `projected_net_payout: 1200` and `edi_pause_offer: { "eligible": true, "nbfc": "Clix Capital", "pause_days": 2, "edi_saved_inr": 1000 }`.
  - Response (same envelope as `/a2a/dispatch`, plus `alert_id`):
    ```jsonc
    // CHARGEBACK_INCOMING
    { "alert_id": "ALERT-9981", "status": "ALERT_RAISED", "intent": "CHARGEBACK_RESOLVE",
      "trigger_type": "CHARGEBACK_INCOMING",
      "data": { "txn_id": "9981", "order_id": "9981", "amount": 800, "deadline_hours": 48 },
      "action_required": { "type": "SUBMIT_POD", "message": "Submit Proof of Delivery within 48h" },
      "escalation_ticket": null }

    // HIGH_REFUND_CASHFLOW
    { "alert_id": "ALERT-4490", "status": "ALERT_RAISED", "intent": "FEE_GST_LOAN",
      "trigger_type": "HIGH_REFUND_CASHFLOW",
      "data": { "refund_request": { "order_id": "4490", "amount": 3500 },
                "projected_net_payout": 1200,
                "edi_pause_offer": { "offer_id": "EDIOFFER-0001", "eligible": true, "nbfc": "Clix Capital",
                                     "pause_days": 2, "edi_saved_inr": 1000, "kfs_clause": "4.2" } },
      "action_required": { "type": "CONFIRM_EDI_PAUSE", "message": "Merchant consent needed to pause EDI" },
      "escalation_ticket": null }
    ```
  - It does **not** require a `consent_token`: it only *informs* the merchant and nothing is shared with Paytm yet.
- `POST /a2a/execute-edi-pause` -> Input: `{ "mid", "consent_token", "pause_days": 2, "offer_id" }` -> Mutates `loan_edi_status` from `ACTIVE (₹500/day)` to `PAUSED_2_DAYS (₹0 tomorrow)` and logs NBFC KFS consent artifact.
  - Response:
    ```jsonc
    { "status": "EDI_PAUSED", "intent": "FEE_GST_LOAN",
      "data": { "loan_edi_status": "PAUSED_2_DAYS", "nbfc": "Clix Capital", "pause_days": 2,
                "edi_saved_inr": 1000, "edi_tomorrow": 0, "resume_date": "2026-11-21",
                "kfs_consent_artifact": { "artifact_id": "KFS-ART-0001", "clause": "4.2",
                                          "consent_token": "DPDP_VERIFIED_TS_…", "ts": 1763… } },
      "action_required": null, "escalation_ticket": null }
    ```
  - Errors:
    - **403** for a missing or invalid `consent_token`. This is the existing DPDP guardrail.
    - **409** `EDI_PAUSE_NOT_ELIGIBLE` if `pause_days` is more than 2, the EDI is already paused, or there's no matching offer.
- `GET /ledger/{mid}` now also returns `loan_edi_status` and the `connectors` consent states.
- `POST /ledger/reset` sets the EDI back to `ACTIVE (₹500/day)`.

#### Person 3 (8003 — Merchant AI Teammate)
**DPDP:** every endpoint below takes `"consent_granted": true`, exactly like the existing merchant endpoints:
- If it's false, the endpoint returns **403** `DPDP_CONSENT_REQUIRED`, logs `DPDP_CONSENT_DENIED`, and calls neither 8002 nor any connector.
- If it's true, the endpoint mints `DPDP_VERIFIED_TS_<unix>` and sends it on every 8002 call.

**Response:** all three endpoints return the **same shape as `/merchant/query`**, with `intent_source: "proactive"` and an extra `proactive` block:
```jsonc
"proactive": {
  "scenario": "CHARGEBACK_INCOMING" | "CASHFLOW_EDI_SWITCH",
  "alert": { …8002 /a2a/proactive-alert response… } | null,
  "dispute_packet": { "packet_id": "DISPUTE-9981", "txn_id": "9981", "order_id": "9981", "amount": 800,
                      "pod_source": "SHIPROCKET_SYNC", "pod_fields": { …8001 extracted_fields… },
                      "doc_confidence": 0.96, "status": "READY_FOR_SIGNOFF" | "SUBMITTED" } | null,
  "cashflow": { "projected_net_payout": 1200, "tomorrow_stock_due": 4500, "shortfall": 3300,
                "payables_source": "VYAPAR_POS_SYNC" } | null,
  "edi_pause_offer": { …from the alert… } | null,
  "awaiting_confirmation": "CONFIRM_DISPUTE" | "CONFIRM_EDI_PAUSE" | null
}
```

- `POST /merchant/proactive-shield` -> Input: `{ "mid": "PAYTM_MERCH_8821", "scenario": "CHARGEBACK_INCOMING" | "CASHFLOW_EDI_SWITCH", "consent_granted": true }`
  - **Scenario A (`CHARGEBACK_INCOMING`):** Receives Paytm's webhook alert -> autonomously pulls PoD from consented `SHIPROCKET_SYNC` connector -> calls `8001/doc-extract` -> prepares dispute packet -> speaks Hindi prompt asking for 1-tap sign-off.
    - Nothing is sent to Paytm until the merchant signs off. The packet's `status` is `READY_FOR_SIGNOFF`, and `awaiting_confirmation` is `CONFIRM_DISPUTE`.
  - **Scenario B (`CASHFLOW_EDI_SWITCH`):** Detects `projected_net_payout (₹1,200) < tomorrow_stock_due (₹4,500)` -> negotiates via A2A with `8002` -> speaks Hindi offer to pause Clix Capital's ₹500/day EDI for 2 days.
    - If there's no shortfall, or `edi_pause_offer.eligible` is false, no offer is made and `awaiting_confirmation` is `null`.
- `POST /merchant/confirm-dispute` -> Input: `{ "mid", "consent_granted": true, "packet_id": "DISPUTE-9981" }` -> This is the merchant's 1-tap sign-off for Scenario A.
  - It submits the packet through the **existing** `8002/a2a/dispatch`, with `intent: "CHARGEBACK_RESOLVE"` and payload `{ order_id, txn_id, pod_submitted: true, pod_document, pod_source: "SHIPROCKET_SYNC" }`.
  - Paytm returns `RELEASED`. The endpoint then returns a Hindi voice confirmation, and the packet `status` becomes `SUBMITTED`.
  - There is no new 8002 endpoint for this.
  - Returns 404 `PACKET_NOT_FOUND` if `proactive-shield` hasn't prepared that packet.
- `POST /merchant/confirm-edi-pause` -> Input: `{ "mid", "consent_granted": true, "offer_id", "pause_days": 2 }` -> Calls `8002/a2a/execute-edi-pause` -> returns Hindi voice confirmation + updates `a2a_events`.
  - `pause_days` defaults to the offer's value and may not exceed 2 (KFS clause 4.2).
  - Returns 404 `OFFER_NOT_FOUND` if `proactive-shield` made no matching offer, and passes through 8002's 409.
- **New event types** in `GET /events`:
  - `PROACTIVE_ALERT_RECEIVED`
  - `CONNECTOR_PULL` (payload `{ connector, consent: "GRANTED" }`)
  - `DISPUTE_PACKET_READY`
  - `MERCHANT_SIGNOFF`
  - `CASHFLOW_GAP_DETECTED`
  - `EDI_PAUSE_OFFERED`
  - `EDI_PAUSED`

  These come on top of the existing `DPDP_CONSENT_VERIFIED`, `MERCHANT_TO_PAYTM`, `PAYTM_TO_MERCHANT` and `VOICE_REPLY_READY`.
- `POST /reset` also clears pending dispute packets and EDI-pause offers. Call it with `?cascade=true` to put the EDI back to `ACTIVE` on 8002.
