# DECISIONS — Merchant AI Teammate (Person 3, Port 8003)

**Owner:** Person 3 · **Scope:** `services/merchant_agent/` only · **Source of truth:** `CONTRACT.md` (root, frozen)
**Logged:** 2026-11-19, before 6:30 PM integration and the 9:00 PM MVP freeze

---

## Phase 1: Scaffold and standalone pipeline

### What was built
A FastAPI service on **port 8003** that acts as the merchant-side AI teammate and A2A orchestrator for `PAYTM_MERCH_8821` (Sharma Electronics).

| File | Responsibility |
|---|---|
| `main.py` | FastAPI app, CORS, endpoints: `POST /merchant/query`, `POST /merchant/query-audio`, `POST /merchant/upload-doc`, `GET /events`, `POST /reset`, `GET /health` |
| `router.py` | Intent and slot router: LLM first (8001 `/llm`, `response_format="json"`), deterministic keyword fallback, regex slot extraction |
| `pipeline.py` | Orchestration: DPDP consent gate → classify → A2A dispatch → local side-effects (GST ITC, fraud) → Hindi reply → TTS |
| `upstream.py` | HTTP clients for 8001 and 8002, each with a 6s timeout, a mock fallback and a circuit breaker |
| `schemas.py` | Pydantic models (request, response, events) |
| `state.py` | In-memory state: merchant order sheet, `a2a_events`, `local_gst_itc_log`, `fraud_alerts` |
| `test_merchant.py` | 27 offline pytest smoke tests |
| `README.md` | Run instructions, response shape, event types |
| `requirements.txt`, `.gitignore` | fastapi, uvicorn, httpx, python-multipart, pydantic, pytest; ignores `.venv/` |

**Seed state (merchant books):** `expected_gross = 100000`, `bank_credit_received = 95840`, `variance = 4160`, settlement date `2026-11-18`.

### Pipeline (per request)
1. **DPDP consent gate.** `consent_granted` must be `true`. The service mints `DPDP_VERIFIED_TS_<unix>` and logs `DPDP_CONSENT_VERIFIED`.
2. **(Audio only) STT.** Calls `8001/stt` and logs `AUDIO_TRANSCRIBED`.
   **(Doc only) Extract.** Calls `8001/doc-extract` and logs `DOC_EXTRACTED`.
3. **Intent and slots.** Calls `8001/llm`, falling back to keyword rules. Logs `INTENT_CLASSIFIED`.
4. **A2A dispatch.** Calls `8002/a2a/dispatch` with `{request_id, mid, intent, payload, consent_token}`. Logs `MERCHANT_TO_PAYTM` and `PAYTM_TO_MERCHANT`.
5. **Side-effects.**
   - If GST ITC is present: append it to `local_gst_itc_log` and log `GST_ITC_LOGGED`.
   - If the response contains `NOT_FOUND_SUSPECTED_FAKE`: raise a HIGH-priority alert and log `FRAUD_ALERT`.
6. **Reply.** Calls `8001/llm` for a 2–3 sentence Hindi reply (template fallback), then `8001/tts` for `audio_base64`. Logs `VOICE_REPLY_READY`.

---

## Decisions and why

### Contract gaps (CONTRACT.md doesn't specify these, so I defined them)
| # | Decision | Why |
|---|---|---|
| D1 | **Defined the response shape** for all three `/merchant/*` endpoints (see README). It includes `reply_text`, `audio_base64`, `paytm_response`, `fraud_alert`, `gst_itc_logged`, `local_gst_itc_log`, `a2a_events`, plus `*_source` fields. | The contract only defines inputs. Person 4 (frontend) needs one stable shape. **Person 4 must be told.** |
| D2 | **Consent event name: `DPDP_CONSENT_VERIFIED`**, with payload `consent_status: "CONSENT_GRANTED"`. | The two briefs used different names (`CONSENT_GRANTED` vs `DPDP_CONSENT_VERIFIED`). This keeps both names visible. |
| D3 | **Event schema:** `{seq, ts, unix, type, actor, request_id, summary, payload}`. `actor` is one of `MERCHANT_AGENT`, `PAYTM_AGENT` or `DPDP_GATE`. | Gives the frontend's centre-panel "live bus" a ready-made one-line `summary` and an `actor` to colour-code, without parsing payloads. |
| D4 | **Extra event types:** `DPDP_CONSENT_DENIED`, `AUDIO_TRANSCRIBED`, `DOC_EXTRACTED`, `GST_ITC_LOGGED`, `FRAUD_ALERT`, `VOICE_REPLY_READY`. | Makes the compliance trail and side-effects visible in the demo. |
| D5 | **`GET /events`** also returns `gst_itc_total`, `fraud_alerts` and `merchant_order_sheet`. | One call gives the frontend everything for the merchant panel. |
| D6 | **`POST /reset?cascade=true`** also calls `8002/ledger/reset`. Plain `/reset` only clears merchant state. | One-click clean demo reruns without coupling by default. |
| D7 | **Added `GET /health`.** It reports the upstream URLs and circuit state. | Quick integration check at 6:30. |

### DPDP / privacy
| # | Decision | Why |
|---|---|---|
| D8 | If consent is missing, return **HTTP 403** with `detail.error = "DPDP_CONSENT_REQUIRED"` and `detail.message_hi`, and log `DPDP_CONSENT_DENIED`. Nothing is sent to Paytm. | A hard gate is the honest DPDP story. The Hindi message lets the UI show the reason directly. |
| D9 | For audio, **consent is checked before STT** runs. | No processing of the merchant's voice without consent. |
| D10 | **Data minimisation.** Paytm receives structured slots only, never the raw utterance or audio. For settlement queries it also gets `merchant_books` (expected gross, bank credit, variance). | A strong pitch point that matches the "real-world data boundaries" theme. It is covered by a test. |

### Intent routing
| # | Decision | Why |
|---|---|---|
| D11 | **LLM first, keyword fallback.** The service uses the LLM's intent only if it is one of the 6 valid intents. Otherwise it uses the keyword rules. | Classification never fails, even if 8001 is slow or returns junk. |
| D12 | **Keyword rules are ordered (first match wins):** ESCALATE_HUMAN → UTR_VERIFY → CHARGEBACK_RESOLVE → REFUND_MANAGE → FEE_GST_LOAN → SETTLEMENT_RECONCILE. If nothing matches, the default is SETTLEMENT_RECONCILE. | Specific intents (a human request, a 12-digit UTR) beat generic money words like "kam" or "kaat". Settlement is the most common merchant pain point. |
| D13 | **Keywords cover Hinglish and Devanagari** (e.g. "paise kam", "कम", "रिफंड", "लोन", "इंसान"). | Merchants type and speak both scripts. |
| D14 | **Regex slots always run, and regex wins over the LLM** for `utr_number` (exactly 12 digits) and `order_id`. The LLM only fills gaps. | LLMs mangle long digit strings, and a wrong UTR would cause a false fraud alert. |
| D15 | **Date slot:** handles ISO dates and dd/mm/yyyy. "kal"/"कल" means yesterday and "aaj"/"आज" means today. | "kal ka settlement" is the canonical demo query (it resolves to 2026-11-18). |

### Side-effects
| # | Decision | Why |
|---|---|---|
| D16 | **GST ITC detection tolerates schema drift.** It checks, in priority order: keys containing `itc`, then breakdown lines whose label contains GST (e.g. `{"head": "GST_ON_MDR", "amount": 261}`), then generic `gst_*` numeric keys. Keys containing `rate`, `pct`, `percent` or `eligible` are skipped. | Person 2's exact field names were unknown. Skipping rate keys stops `gst_rate: 18` from being logged as ₹18 ITC. |
| D17 | **ITC is deduplicated by `(settlement_date, amount)`.** | Asking about settlement and then about GST would otherwise double-count ₹261, which is wrong accounting. |
| D18 | **The fraud check looks anywhere in the response** for the string `NOT_FOUND_SUSPECTED_FAKE`. The alert carries `priority: HIGH` and `recommended_action: DO_NOT_RELEASE_GOODS`. | Robust to where Person 2 puts the status. |
| D19 | **ITC amounts are stored as integers** when they are whole numbers. | The UI would otherwise show "₹261.0". |

### Replies
| # | Decision | Why |
|---|---|---|
| D20 | **Replies are in Hindi (Devanagari)**, with finance terms (UTR, GST, ITC, settlement, chargeback, MDR, EDI) kept in English. The LLM is told to use only numbers from the JSON. | Sarvam TTS (`hi-IN`) pronounces Devanagari better than Roman Hinglish. The number rule prevents invented amounts. |
| D21 | **Each intent and status has a Hindi template fallback** (including fraud, pending UTR, needs-UTR and chargeback reversed). | There is always a meaningful reply even with 8001 down. |
| D22 | **If TTS fails, `audio_base64` is `null`**, not silent audio. | The frontend can simply check for null and show text only. |

### Resilience
| # | Decision | Why |
|---|---|---|
| D23 | **Every upstream call has a 6s timeout and a 2s connect timeout, and wraps failures with a deterministic fallback.** | Ports 8001 and 8002 were still being built. All 6 intents can be tested standalone. |
| D24 | **Mock Paytm responses are built from CONTRACT.md seed data**: settlement breakdown, the UTR table (`632184920111` SUCCESS, `632184920999` PENDING, unknown → FAKE), chargeback `9981` (HELD, or REVERSED once PoD is submitted), refund `4412`, MDR/GST/loan, escalation ticket. | Demo behaviour without 8002 matches what 8002 should return. |
| D25 | **Circuit breaker.** If a host refuses a connection, it is skipped for 10s (`UPSTREAM_CIRCUIT_COOLDOWN_S`). `/reset` makes the service try it again. | On Windows each refused connection costs about 2s. Measured: the first offline call takes about 4.2s, later ones about 6ms. The test suite went from 59s to 14s. |
| D26 | **Default upstream URLs use `127.0.0.1`, not `localhost`.** They can be overridden with `SARVAM_URL` and `PAYTM_URL`. | On Windows, `localhost` tries IPv6 first, which adds delay. |
| D27 | **If STT fails, the service uses a canned transcript** ("मेरा कल का settlement ₹4,160 कम क्यों आया?"), labelled `transcript_source: "mock"`. | Keeps the voice flow demoable. It is labelled so it isn't mistaken for real STT. |
| D28 | **If doc-extract fails, the service uses mock fields.** For PoD that is order 9981. For a UPI screenshot it reads a 12-digit UTR from the filename. | Uploading `upi_123456789012.png` demos the fraud path offline. |
| D29 | **Every response reports `intent_source`, `paytm_source`, `reply_source` and `transcript_source`** (live or mock/fallback). Mock events are tagged `[mock]` in their summary. | At integration you can see instantly which services are really live. |
| D30 | **A global exception handler returns a structured 500 with a Hindi message.** Uploads are capped at 10MB, and empty files or audio get a 400. | Graceful degradation, so the demo never shows a stack trace. |

### Environment
| # | Decision | Why |
|---|---|---|
| D31 | **Python 3.11 venv** at `services/merchant_agent/.venv` (git-ignored). The machine default is Python 3.14. | 3.11 has the most reliable wheels for FastAPI and pydantic. |
| D32 | **Doc uploads are routed by type.** `pod` dispatches CHARGEBACK_RESOLVE (with `pod_submitted: true` and `pod_document`). `upi_screenshot` dispatches UTR_VERIFY (with `screenshot_fields`). | As specified in the brief. |

---

## Verification
- `python -m pytest -q` → **27 passed, 14s**, fully offline (8001 and 8002 pointed at a dead port). Coverage:
  - keyword intents in Hinglish and Devanagari, and slot extraction
  - all 6 intents end to end, including PENDING and SUCCESS UTRs
  - consent 403 on query and on upload
  - GST ITC logged once (deduplicated), and the fake-UTR fraud alert
  - PoD upload reversing the chargeback, and a fake screenshot upload
  - audio mock transcript, with consent checked before STT
  - `/reset`, and that the raw utterance is never sent to Paytm
- Live server run on 8003:
  - `/health` OK
  - `/merchant/query` → SETTLEMENT_RECONCILE / RECONCILED / ITC 261 logged
  - the second identical call does not re-log ITC
  - CORS preflight returns `Access-Control-Allow-Origin: http://localhost:3000`
  - `/events` shows the full event chain
- The server was stopped afterwards, and port 8003 was confirmed free.

---

## Phase 2: Aligning with the team master plan (`PLAN.md`)

`PLAN.md` was added to this folder as context. The code was then checked against it, and these mismatches were fixed.

| # | Mismatch found | Fix | Why it mattered |
|---|---|---|---|
| D33 | With 8001 offline, the demo's `fake_upi.png` was given the real UTR `632184920111` and came back **SUCCESS**. | A filename containing `fake`, `tamper` or `nakli` now gets an unknown UTR (`632184920777`), which takes the fraud path. | Demo Step 3 (fraud catch) would have shown "payment successful" to the judges. |
| D34 | The plan's chargeback lifecycle is `HELD` → **`RELEASED`**. The mock returned `CHARGEBACK_REVERSED`, and the reply template only recognised that status. | The mock now returns `RELEASED` (release `T+1`). The template accepts `RELEASED`, `CHARGEBACK_REVERSED`, `RESOLVED`, `WON` and `SUCCESS`. | A live `RELEASED` from Person 2 would have produced the "still on hold, upload PoD" reply in demo Step 2. |
| D35 | The plan says Soundbox **hardware** issues go to ESCALATE_HUMAN. "soundbox" was a FEE_GST_LOAN keyword. | Added a device + fault rule to ESCALATE_HUMAN (Hinglish and Devanagari, e.g. "soundbox kharab", "साउंडबॉक्स बंद") and a hint in the LLM prompt. Rental-fee questions still route to FEE_GST_LOAN. | Needed for the plan's Escalation Path check. |
| D36 | Escalation ticket format should be **`TKT-PAYTM-xxxx`**. | The mock ticket now uses `TKT-PAYTM-<4 digits>` with `queue: "L2"`. | Matches what the frontend and pitch show. |
| D37 | Refunds should be **≤ ₹5,000 autonomous, > ₹5,000 escalated to a human**. | The mock refund now returns `INITIATED` for orders other than 4412 up to ₹5,000, and `ESCALATED` with an L2 ticket above that. Templates were added for both. | Brings refund behaviour in line with the plan's intent definitions. |
| D38 | Reply budget is **≤ 35 words / 2 sentences**. The prompt said 2–3 sentences, and one template was 39 words. | The LLM prompt now says "at most 2 sentences, 35 words". LLM replies over 45 words fall back to the template. All templates were shortened, and a test enforces ≤ 35 words. | Snappier voice replies, and Person 3's tuning task in the plan. |
| D39 | The golden-path reply must **flag the ₹800 chargeback hold on #9981**. | The settlement template now names `#9981`, `₹800`, logs ITC, and asks for the delivery proof. This leads into demo Step 2. | Demo Step 1 → Step 2 handoff. |
| D40 | The plan configures URLs via **`.env`** using **`SARVAM_SERVICE_URL` / `PAYTM_AGENT_URL`**. | Added `python-dotenv`, which loads `services/merchant_agent/.env`. The plan's names are read first, and the old names still work. Added `.env.example`; `.env` is git-ignored. | Integration-hour setup on the demo laptop. |
| D41 | The plan exposes the frontend via **ngrok/Vercel** for Day 2 field testing. | Added the `CORS_EXTRA_ORIGINS` env (comma-separated). | Otherwise the browser would block calls from the tunnel URL. |

**Verification:** 36 tests pass, all offline. That includes 9 new tests:
- the golden-path utterance → SETTLEMENT_RECONCILE, ITC 261 logged, and a reply mentioning #9981 and ₹800
- `fake_upi.png` → fraud alert
- three Soundbox phrasings: two hardware faults → ESCALATE_HUMAN, and the rental fee → FEE_GST_LOAN
- the `TKT-PAYTM-` ticket format
- refund > ₹5,000 → ESCALATED and ≤ ₹5,000 → INITIATED
- every template reply ≤ 35 words

**For the plan's 5:30 "Contract Police" check (led by Person 3), confirm these with the team:**
- **Person 2** returns `RELEASED` (not some other word) after PoD.
- **Person 2** returns `TKT-PAYTM-xxxx` tickets and enforces the ₹5,000 refund limit itself.
- **Person 1**'s `/stt` accepts WebM from `MediaRecorder`. The merchant agent passes the browser's content-type through unchanged.

---

## Open items for integration (6:30 PM)
1. **Person 4:** share the response shape and event types (README + D1–D5). There is no frontend contract for these yet.
2. **Person 2:** confirm two things:
   - GST appears as a key containing `gst_itc`/`itc`, or as a breakdown line `{"head": "GST_ON_MDR", "amount": 261}`
   - fake UTRs return `status: "NOT_FOUND_SUSPECTED_FAKE"`

   Also confirm that `/a2a/dispatch` accepts `pod_submitted`, `pod_document` and `screenshot_fields` in the payload.
3. **Person 1:** confirm whether `/llm` with `response_format: "json"` returns a JSON string or an object. Both are handled, including fenced ```` ```json ```` blocks.
4. After going live, check that `*_source` fields read `live`/`llm`. If `intent_source` stays `keyword_fallback`, the LLM is timing out or returning an invalid intent.
5. Not yet committed. The `services/` folder is untracked. Per PLAN.md, push on branch **`feat/merchant-agent`**.
6. On the demo laptop:
   - `cd services/merchant_agent`
   - copy `.env.example` to `.env`
   - `pip install -r requirements.txt`
   - `uvicorn main:app --port 8003`

   The command must be run from inside this folder.
