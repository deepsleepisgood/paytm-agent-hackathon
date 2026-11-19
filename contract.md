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
