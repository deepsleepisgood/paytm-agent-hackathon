# All-in-One Merchant AI Buddy — Port 8003

Merchant-side agent for `PAYTM_MERCH_8821` (Sharma Electronics), built to PLAN.md V3. On every request it runs this closed loop:

1. **Understand and diagnose.** It reads the query against 6 months of history and names the root cause, e.g. a temporary rain dip is *payment friction*, not *default*.
2. **Evaluate options.** It scores options A, B and C on policy, cost, UX and past success, and picks the best one.
3. **Dispatch.** It mints a DPDP token and sends the chosen intervention to Paytm's 4-agent mesh (8002), capturing its `agent_trace`.
4. **Verify and learn.** It reads Paytm's verified outcome and records it in `strategy_memory`, so later choices improve.
5. **Reply.** It answers in Hinglish voice through Sarvam (8001): the resolution plus a historical business tip, in ≤35 words.

Along the way it keeps the GST ITC log, the khata (Tally export) and fraud alerts, and runs the proactive chargeback, cashflow and mandate flows.

## Run
```powershell
cd services/merchant_agent          # must be started from this folder (flat imports)
py -3.11 -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn main:app --port 8003 --reload
.\.venv\Scripts\python -m pytest -q        # offline tests (103), ~40s
```
Config is read from a `.env` file in this folder; copy `.env.example` to start. The settings are:
- `SARVAM_SERVICE_URL`, default `http://127.0.0.1:8001`. `SARVAM_URL` also works.
- `PAYTM_AGENT_URL`, default `http://127.0.0.1:8002`. `PAYTM_URL` also works.
- `UPSTREAM_TIMEOUT_S`, default 6.
- `DOC_EXTRACT_TIMEOUT_S`, default 30. Person 1 lets Sarvam Vision run for up to 25s.
- `UPSTREAM_CIRCUIT_COOLDOWN_S`, default 10.
- `CORS_EXTRA_ORIGINS`: comma-separated extra frontend origins, e.g. an ngrok or Vercel URL.
- `DATASET_DIR`, default `<repo root>/dataset`.
- `UTTERANCE_FAST_PATH`, default 1.

See `PLAN.md` for the team master plan and the demo script.

## Team dataset (`data/seed/` at the repo root)
The dataset as it landed (CSV + JSON, see `data/seed/README.md`) is read by `seed_adapter.py` and is the default. `GET /health` → `dataset.files` shows `dataset (data/seed: …)` for each section.

The older per-file layout below (`dataset/seed/*.json`) is still supported, and is used if `data/` is absent or `DATASET_DIR` points to it.
Seed data, utterances and golden paths come from the shared dataset, which a teammate is building. `dataset_loader.py` reads it by the file names agreed for the team:

| File | Used for |
|---|---|
| `seed/merchant.json` | Merchant name and MID. The GSTIN goes on every ITC log entry. The Soundbox device is attached to hardware-fault escalations. |
| `seed/settlement.json` | The merchant's books (`merchant_order_sheet`, `merchant_books` sent to Paytm), the mock Paytm breakdown, and the itemised settlement reply. |
| `seed/transactions.json` | The mock Paytm UTR ledger (SUCCESS, PENDING, FAILED, …). Unknown UTRs become `NOT_FOUND_SUSPECTED_FAKE`. |
| `seed/refunds_orders.json` | Mock refunds and chargebacks, the autonomous refund limit, and order-id keywords for routing. |
| `seed/loan.json`, `seed/fee_rules.json` | The FEE_GST_LOAN mock answer and reply. The GST rate is used in the ITC `basis` text. |
| `seed/initial_state.json` | Where `/reset` returns the mock chargeback status (e.g. `#9981 → HELD`). |
| `intents/utterances.json` | The utterance bank (see routing below), few-shot examples for the LLM, `GET /presets`, and the mock STT transcript. |
| `golden/golden_paths.json`, `test_files/` | `test_dataset.py` checks every golden step and both demo images. `test_files/pod_9981.png` is also the Shiprocket PoD for the proactive chargeback. |
| `seed/merchant_history.json` (or a `historical_profile` block in `merchant.json`) | 6-month memory: `daily_avg_sales`, `weekend_multiplier`, `past_edi_success_rate`, `supplier_payable_tomorrow`, `active_lender`, `kfs`, `monthly_sales`, `recent_daily_sales` (dip days flagged by `note: "rain"` or `dip: true`), `mandate`, `recent_customers`, `duplicate_payments`, `past_disputes`, `connectors`, `bank_account`, `soundbox_diagnostics`, `growth_offer`, `cashflow`, optional `strategy_priors`. Each field falls back to the built-in seed separately. |

**If a file is missing or unusable, that file alone falls back to the built-in CONTRACT.md seed.** The service never fails to start because of the dataset. The schema isn't frozen yet, so field names are matched tolerantly: e.g. `utr`, `utr_number` and `UTR No` are all accepted. `GET /health` → `dataset` shows, per file, `dataset`, `dataset (builtin for: …)` or `builtin (missing | unreadable | unusable: …)`, and checks that gross − net = variance = sum of deductions. `POST /reset` reloads the dataset from disk.

When the dataset lands, run `pytest -q`. The `test_real_*` tests switch on automatically and report:
- any file whose fields weren't recognised
- whether the settlement adds up
- whether every utterance routes correctly
- whether golden paths and test files behave as expected

## Intents (14)
- **PLAN.md V3:** `MANDATE_TROUBLESHOOT`, `SETTLEMENT_RECONCILE`, `CHARGEBACK_RESOLVE`, `UTR_VERIFY`, `DUPLICATE_RECONCILE`, `GROWTH_ADVISORY`, `CASHFLOW_EDI_SWITCH`, `ESCALATE_HUMAN`.
- **Original contract:** `REFUND_MANAGE`, `FEE_GST_LOAN`.
- **Service requests:**
  - `SOUNDBOX_RETURN` ("soundbox wapas / bill kat raha")
  - `LOAN_CLOSURE_NOC` ("loan settle / NOC")
  - `BANK_KYC_UPDATE` ("bank account / KYC change")
  - `SETTLEMENT_HOLD_BANK` ("settlement hold / bank inactive")

  These four names are 8003's choice and still need confirming with Person 2. If 8002 doesn't support one yet, 8003 answers from its mock.

## Intent routing
1. **Utterance bank, exact match.** If the text exactly matches a dataset utterance (e.g. a preset chip), that label is used instantly, with no LLM call. `intent_source: "utterance_bank"`.
2. **Sarvam LLM** (8001, JSON mode), prompted with few-shot examples from the bank.
3. **Utterance bank, close match** (≥ 70% word overlap), used if the LLM is unavailable.
4. **Keyword rules** (Hinglish and Devanagari) in `router.py`. `intent_source: "keyword_fallback"`.

## Resilience
Every call to 8001 or 8002 has a timeout and a deterministic fallback, so the service works with nothing else running:

| Upstream | Fallback |
|---|---|
| `/llm` classify | Utterance bank, then keyword rules |
| `/a2a/dispatch` | Mock 4-agent Paytm mesh built from the dataset (`upstream.mock_paytm`): all 14 intents, with `agent_trace` + `verified_outcome`. Also used when a live 8002 answers `UNSUPPORTED_INTENT` |
| `/a2a/proactive-alert`, `/a2a/execute-edi-pause` | `upstream.mock_alert` / `mock_execute_edi_pause`, with a mock loan EDI state (`/reset` sets it back to ACTIVE) |
| `/llm` reply | Status-aware Hindi templates (`pipeline.template_reply`) |
| `/tts` | `audio_base64: null` (text only) |
| `/stt` | The dataset's settlement preset chip, marked `transcript_source: "mock"` |
| `/doc-extract` | PoD for the chargeback order in the filename (default: first chargeback). For a UPI screenshot: a 12-digit UTR in the filename is used as-is, a name containing `fake`/`tamper` (e.g. `fake_upi.png`) gets an unknown UTR (the fraud path), and a name containing `pending` gets a PENDING UTR |

If a host refuses a connection, the service skips it for 10s and uses the fallback straight away. `POST /reset` re-probes.

**Person 2 (8002) compatibility:**
- **What 8003 sends.** 8002 needs `utr` for UTR checks and `reason_code` for escalations, and answers 400 without them. 8003 sends both, plus `session_id` and `language_code`.
- **How 8003 reads the answer.** 8002 answers `RESOLVED | ACTION_REQUIRED | ESCALATED` with the details in `data`. `upstream.interpret()` turns that into specific outcomes (RECONCILED, RELEASED, NOT_FOUND_SUSPECTED_FAKE, …). `paytm_response` is 8002's raw body, except that `status` holds the specific outcome (same as mock mode, and what the frontend reads); 8002's own status is in `mesh_status`.
- **Not supported by 8002.** The 4 service-request intents (`UNKNOWN_INTENT`) and `FEE_GST_LOAN` / `REFUND_MANAGE` (501) are answered by the 8003 mock.

**Person 1 (8001) compatibility:** their responses carry `source: "sarvam" | "mock"`, and we pass that through as `*_source: "live" | "mock"`. Their **mock `/llm` is deliberately ignored**: it keyword-matches canned replies and can't read Paytm's JSON (e.g. it would say "upload your PoD" right after a PoD was accepted). Our own routing and templates are used instead. Their `/doc-extract` field `utr` is read as `utr_number`.

## Response shape (every `/merchant/*` action endpoint)
```jsonc
{
  "request_id": "REQ_…", "mid": "PAYTM_MERCH_8821",
  "transcript": null, "transcript_source": null,          // "live" | "mock", set for audio
  "consent_token": "DPDP_VERIFIED_TS_1763…",
  "intent": "MANDATE_TROUBLESHOOT", "intent_source": "utterance_bank|llm|keyword_fallback|document|proactive",
  "slots": { "utr_number": null, "order_id": null, "amount": 500, "date": null },
  "doc_extract": null,                                    // set for upload-doc ("_source": "live|mock")
  "historical_insight": { "root_cause": "TEMPORARY_CASH_DIP", "classification": "PAYMENT_FRICTION",
                          "summary": "Friction, not default: sales fell 40% on 14–16 Nov (heavy rain)…",
                          "evidence": ["…"], "tip_hi": "…", "metrics": {}, "profile": { "daily_avg_sales": 32000, … } },
  "intervention_evaluation": {
    "options": [ { "id": "A", "action": "SEND_REMINDER", "label": "…", "scores": { "policy", "cost", "ux", "history" },
                   "history": { "success_rate": 0.375, "prior_trials": 6, "learned_trials": 0 }, "total": 0.28,
                   "blocked_by_policy": null, "selected": false }, … B (selected), C … ],
    "selected": "B", "selected_intervention": { "option_id": "B", "action": "UPI_LINK_48H_GRACE", "label": "…", "score": 0.77 },
    "rationale": "…", "scoring": { "total": "value × historical success rate", … } },
  "paytm_response": { "status": "UPI_LINK_SENT", "intent": "…", "data": {}, "agent_trace": [ … ],
                      "verified_outcome": { "resolved": true }, "action_required": {…} | null, "escalation_ticket": null },
  "paytm_source": "live|mock",
  "paytm_agent_trace": [ { "step": 1, "agent": "IntelligenceAgent", "output": "…" }, …RiskPolicyAgent, ResolutionAgent, LedgerOpsAgent ],
  "verified_outcome": { "outcome": "SUCCESS|FAILED|PENDING", "learned": true, "strategy_success_rate": 0.88, … },
  "pending_action": { "type": "PAY_VIA_UPI_LINK" | "UPLOAD_POD" | "CONFIRM_DISPUTE" | "CONFIRM_EDI_PAUSE" | …, "endpoint"?: "…" } | null,
  "proactive": null | { "scenario", "alert", "dispute_packet", "cashflow", "edi_pause_offer", "awaiting_confirmation" },
  "hindi_reply": "…Hinglish…", "reply_text": "(same as hindi_reply)", "reply_source": "llm|template",
  "audio_base64": "…", "audio_source": "live|mock|unavailable", "language_code": "hi-IN",
  "fraud_alert": null | { "alert_id", "priority": "HIGH", "utr_number", "recommended_action": "DO_NOT_RELEASE_GOODS" },
  "gst_itc_logged": null | { "amount": 261, "settlement_date": "2026-11-18", "gstin": "…", "basis": "18% GST on MDR ₹1,450 (ITC eligible)", … },
  "local_gst_itc_log": [ … ],
  "a2a_events": [ … ]
}
```
If `consent_granted` is false, the endpoints return HTTP 403 with `detail.error = "DPDP_CONSENT_REQUIRED"` and `detail.message_hi`.

`audio_source: "mock"` means Person 1 returned a placeholder tone, not speech. The frontend may want to show the text only in that case.

## Proactive flows (CONTRACT.md V2)
- **`POST /merchant/proactive-shield`** takes `{mid, scenario, consent_granted}`. 8003 fetches the alert from `8002/a2a/proactive-alert` (or uses its mock), then:
  - **`CHARGEBACK_INCOMING`:** pulls the PoD from `SHIPROCKET_SYNC`, extracts it (8001) and prepares `DISPUTE-9981`. Returns `pending_action.type = CONFIRM_DISPUTE`. Nothing goes to Paytm yet.
  - **`CASHFLOW_EDI_SWITCH`:** reads tomorrow's payable from `VYAPAR_POS_SYNC` and finds the gap (₹1,200 vs ₹4,500). Offers `EDIOFFER-0001`, a 2-day KFS pause, and returns `CONFIRM_EDI_PAUSE`.
  - **`MANDATE_FAILED`:** diagnoses friction and sends the 1-tap UPI link.
- **`POST /merchant/confirm-dispute`** takes `{mid, consent_granted, packet_id}`. It submits through `8002/a2a/dispatch`: `#9981` goes to RELEASED and the packet to `SUBMITTED`. Returns 404 `PACKET_NOT_FOUND` for an unknown packet.
- **`POST /merchant/confirm-edi-pause`** takes `{mid, consent_granted, offer_id, pause_days?}`. It calls `8002/a2a/execute-edi-pause` and the EDI becomes `PAUSED_2_DAYS`. Errors:
  - 404 `OFFER_NOT_FOUND`
  - 409 `EDI_PAUSE_NOT_ELIGIBLE` if `pause_days` is over 2 or the EDI is already paused. 8002's own 403 and 409 are passed through.
- A typed request to pause the EDI ("stock ke paise kam hain, EDI ruk sakti hai?") makes the same offer. The pause only happens on confirm, because a KFS pause needs explicit consent.

## Khata export
`GET /merchant/khata-export` returns JSON; `?format=csv` downloads a Tally-ready CSV (`khata_PAYTM_MERCH_8821_2026-11-18.csv`).
- **Vouchers:** one per row, with Date (DD-MM-YYYY), Voucher Type, Voucher No, Debit Ledger, Credit Ledger, Amount, GST ITC Eligible, Reference, Status and Narration.
- **From the settlement:** Sales (gross ₹1,00,000), a Journal entry for each deduction (MDR, Input GST/ITC ₹261, refunds, Soundbox rental, chargeback hold) and the Receipt (bank credit ₹95,840).
- **From the buddy's completed actions:** chargeback released, duplicate refunded, refund initiated, and EDI paused (a Memorandum voucher).
- **JSON extras:** `summary` (with `reconciled`, `gst_itc_claimable` and `gst_itc_logged`), `sales_register` (daily sales) and `gst_itc_register`.

## Other endpoints
- `GET /merchant/profile` returns the 6-month profile for the insights banner: averages, weekend multiplier, EDI record, connectors, monthly sales, recent customers and `loan_edi_status`.
- `GET /merchant/strategy-memory` returns `verified_outcomes_learned` (the plan's "Verified Outcomes Learned" counter), success rate per intent and action, and recent outcomes.
- `GET /events` returns `a2a_events`, `local_gst_itc_log`, `gst_itc_total`, `fraud_alerts`, `merchant_order_sheet` (which now includes `gstin`), `strategy_memory` and `pending_actions` (open dispute packets and EDI offers).
- `GET /presets` returns `{presets: [{text, intent, chip_label?}], source}`: the preset chips flagged in `utterances.json`. It's optional, for Person 4.
- `GET /health` returns the upstream URLs, circuit state and dataset status.
- `POST /reset` clears merchant state: events, the ITC log, learned strategy memory, khata entries, and dispute packets and EDI offers. It also reloads the dataset and puts the mock chargebacks (HELD) and mock EDI (ACTIVE) back to their initial state. Add `?cascade=true` to also call `POST 8002/ledger/reset`.

Each event has the form `{ seq, ts, unix, type, actor, request_id, summary, payload }`. `actor` is one of `MERCHANT_AGENT`, `PAYTM_AGENT` or `DPDP_GATE`.

Event types, in pipeline order:
1. `DPDP_CONSENT_VERIFIED` (payload `consent_status: "CONSENT_GRANTED"`) or `DPDP_CONSENT_DENIED`
2. `AUDIO_TRANSCRIBED` / `DOC_EXTRACTED`
3. `INTENT_CLASSIFIED`
4. `ROOT_CAUSE_DIAGNOSED`
5. `INTERVENTIONS_EVALUATED`
6. `MERCHANT_TO_PAYTM`
7. `PAYTM_TO_MERCHANT`
8. `GST_ITC_LOGGED`
9. `FRAUD_ALERT`
10. `KHATA_UPDATED`
11. `OUTCOME_VERIFIED`
12. `VOICE_REPLY_READY`

The proactive flows add `PROACTIVE_ALERT_RECEIVED`, `CONNECTOR_PULL`, `DISPUTE_PACKET_READY`, `CASHFLOW_GAP_DETECTED`, `EDI_PAUSE_OFFERED`, `MERCHANT_SIGNOFF`, `EDI_PAUSED` and `PAYTM_REJECTED`.

The same settlement's ITC is logged only once. For hardware escalations only, the A2A payload carries `issue_type: "HARDWARE_SOUNDBOX"` and the Soundbox `device`.
