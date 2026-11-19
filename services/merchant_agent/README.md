# Merchant AI Teammate — Port 8003

Merchant-side agent for `PAYTM_MERCH_8821` (Sharma Electronics). It runs the DPDP consent gate, routes intents for Hindi and Hinglish queries, handles A2A dispatch to Paytm (8002), keeps the GST ITC log and fraud alerts, and returns a Hindi voice reply through Sarvam (8001).

## Run
```powershell
cd services/merchant_agent
py -3.11 -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn main:app --port 8003 --reload
.\.venv\Scripts\python -m pytest -q        # offline smoke tests, ~15s
```
Config is read from a `.env` file in this folder; copy `.env.example` to start. The settings are:
- `SARVAM_SERVICE_URL`, default `http://127.0.0.1:8001`. `SARVAM_URL` also works.
- `PAYTM_AGENT_URL`, default `http://127.0.0.1:8002`. `PAYTM_URL` also works.
- `UPSTREAM_TIMEOUT_S`, default 6.
- `UPSTREAM_CIRCUIT_COOLDOWN_S`, default 10.
- `CORS_EXTRA_ORIGINS`: comma-separated extra frontend origins, e.g. an ngrok or Vercel URL.

See `PLAN.md` for the team master plan and the demo script.

## Resilience
Every call to 8001 or 8002 has a 6s timeout and a deterministic fallback, so the service works with nothing else running:

| Upstream | Fallback |
|---|---|
| `/llm` classify | Keyword rules (Hinglish + Devanagari) in `router.py` |
| `/a2a/dispatch` | Seed-data answers from CONTRACT.md (`upstream.mock_paytm`) |
| `/llm` reply | Hindi templates per intent (`pipeline.template_reply`) |
| `/tts` | `audio_base64: null` (text only) |
| `/stt` | Canned settlement question, marked `transcript_source: "mock"` |
| `/doc-extract` | Seed PoD for order 9981. For a UPI screenshot, a 12-digit UTR in the filename is used, and a filename containing `fake` (e.g. `fake_upi.png`) gets an unknown UTR. Either way the fraud path shows |

If a host refuses a connection, the service skips it for 10s and uses the fallback straight away. `POST /reset` re-probes. Each response reports where its data came from in `intent_source`, `paytm_source`, `reply_source` and `transcript_source`.

## Response shape (`/merchant/query`, `/query-audio`, `/upload-doc`)
```jsonc
{
  "request_id": "REQ_…", "mid": "PAYTM_MERCH_8821",
  "transcript": null, "transcript_source": null,          // set for audio
  "consent_token": "DPDP_VERIFIED_TS_1763…",
  "intent": "SETTLEMENT_RECONCILE", "intent_source": "llm|keyword_fallback|document",
  "slots": { "utr_number": null, "order_id": null, "amount": 4160, "date": "2026-11-18" },
  "doc_extract": null,                                    // set for upload-doc
  "paytm_response": { "status": "…", "intent": "…", "data": {}, "action_required": null, "escalation_ticket": null },
  "paytm_source": "live|mock",
  "reply_text": "…Hindi…", "reply_source": "llm|template",
  "audio_base64": "…" , "language_code": "hi-IN",
  "fraud_alert": null | { "alert_id", "priority": "HIGH", "utr_number", "recommended_action": "DO_NOT_RELEASE_GOODS" },
  "gst_itc_logged": null | { "amount": 261, "settlement_date": "2026-11-18", … },
  "local_gst_itc_log": [ … ],
  "a2a_events": [ … ]
}
```
If `consent_granted` is false, the endpoints return HTTP 403 with `detail.error = "DPDP_CONSENT_REQUIRED"` and `detail.message_hi`.

## Events (`GET /events` → `a2a_events`, `local_gst_itc_log`, `gst_itc_total`, `fraud_alerts`, `merchant_order_sheet`)
Each event has the form `{ seq, ts, unix, type, actor, request_id, summary, payload }`. `actor` is one of `MERCHANT_AGENT`, `PAYTM_AGENT` or `DPDP_GATE`.

Event types, in pipeline order: `DPDP_CONSENT_VERIFIED` (payload `consent_status: "CONSENT_GRANTED"`) or `DPDP_CONSENT_DENIED` → `AUDIO_TRANSCRIBED` / `DOC_EXTRACTED` → `INTENT_CLASSIFIED` → `MERCHANT_TO_PAYTM` → `PAYTM_TO_MERCHANT` → `GST_ITC_LOGGED` → `FRAUD_ALERT` → `VOICE_REPLY_READY`.

The same settlement's ITC is logged only once.

`POST /reset` clears merchant state. Add `?cascade=true` to also call `POST 8002/ledger/reset`.
