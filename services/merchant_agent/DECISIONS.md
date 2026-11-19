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

## Phase 3: Team dataset integration + Person 1 compatibility

**Context:**
- The team agreed on a `dataset/` structure: `seed/*.json`, `intents/utterances.json`, `golden/golden_paths.json`, `test_files/pod_9981.png` and `fake_upi.png`, plus `generate_test_files.py` and a README.
- It isn't on any branch or anywhere on this machine yet. A teammate is building it.
- So the merchant agent **reads** it, and **no files were created outside `services/merchant_agent`**.
- Meanwhile Person 1's `sarvam_service` was merged to `main`, which made it possible to test against their real code.

| # | Decision | Why |
|---|---|---|
| D42 | **New `dataset_loader.py`.** It reads `<repo root>/dataset` (override with `DATASET_DIR`), and **each file falls back separately** to the built-in CONTRACT.md seed if it is missing, not valid JSON, or has no recognisable fields. | The service must never fail to start or crash mid-demo because a teammate's file is late or malformed. |
| D43 | **Field names are matched tolerantly**, ignoring case and separators and trying several likely names: `utr`/`utr_number`/`rrn`, `gross` or a summed `gross_mix`, deductions as a list or as `{label: amount}`, rates as `0.02` / `2` / `"2%"`. Partly usable files report `dataset (builtin for: <fields>)`. Optional fields (e.g. `loan.next_deduction`) default silently. | The schema isn't frozen. Being tolerant means fewer fixes at integration time, and the per-file status says exactly what to fix when something isn't recognised. |
| D44 | **`GET /health` → `dataset`** shows the folder, each file's status, the counts, and consistency checks: gross − net = variance = sum of deductions. **`POST /reset` reloads the dataset from disk.** | Integration hour: a teammate edits a JSON file, you hit Reset, and you see the change without a restart. |
| D45 | **The dataset now drives** the merchant order sheet; the mock Paytm answers (every UTR including the extra ones, refunds, chargebacks, the refund limit, loan and fees); the mock document fields; the reply templates (the settlement reply is itemised from the deductions list); order-id keywords and slot ids; and ITC entries (`gstin`, and `basis` from the GST rate and MDR). | One source of truth. A changed number in the dataset flows through without code changes. |
| D46 | **The mock Paytm keeps chargeback state.** It starts from `initial_state.json` (#9981 HELD). A PoD upload sets it to RELEASED until `/reset`. | Keeps the demo consistent: asking about the settlement after Step 2 shows the hold released, and drops the "send delivery proof" nudge. |
| D47 | **Utterance-bank routing:** an exact match takes a fast path that skips the LLM; otherwise the LLM runs with few-shot examples from the bank; if the LLM fails, a close match (≥ 70% word overlap) is used; keywords come last. `intent_source: "utterance_bank"`. Set `UTTERANCE_FAST_PATH=0` to always ask the LLM first. | Preset chips are the judges' demo path, so they should be instant and deterministic. This matches PLAN.md's "System-1 routing" story. **Trade-off:** preset chips show `utterance_bank`, not `llm`, in the event log. |
| D48 | **Hardware escalations** (Soundbox fault) send `issue_type: "HARDWARE_SOUNDBOX"` plus the Soundbox `device` from `merchant.json`. Nothing else gets device data. | A pre-filled L2 ticket (PLAN.md) while keeping data minimisation (D10). |
| D49 | **Added `GET /presets`**, an extra endpoint not in the contract: the preset chips flagged in `utterances.json`. The mock STT transcript is now the settlement preset. | Lets Person 4 build chips from the same dataset. Optional for them. |
| D50 | **Person 1 compatibility: `/doc-extract` returns `utr`, not `utr_number`.** Slots now read both. | **Demo Step 3 breaker.** With 8001 up, `fake_upi.png` lost its UTR, so the merchant heard "please tell me the UTR" instead of a fraud alert. |
| D51 | **Person 1's `source: "mock"` is honoured.** It's passed through as `*_source`, and **their mock `/llm` is ignored**, falling back to our routing and templates. | **Demo Step 2 breaker.** Their canned mock reply after a PoD upload said "upload your PoD within 48h", and it was mislabelled `llm`. |
| D52 | **`DOC_EXTRACT_TIMEOUT_S=30`** for `/doc-extract` only; every other call stays at 6s. | Person 1 lets Sarvam Vision run for up to 25s. A 6s cut-off threw away every real extraction in favour of our mock. **This deviates from the original 6s rule; set it to 6 to revert.** |
| D53 | **Added `audio_source`** (`live`/`mock`/`unavailable`) to the response. | Person 1's mock TTS is a placeholder tone, not speech, so the frontend can choose to show text only. |
| D54 | **`.env` is read inside `dataset_loader`.** | It's imported first and loads data immediately. Previously a `DATASET_DIR` set in `.env` was ignored until the first `/reset`. |

**Bugs found and fixed during verification:**
- The settlement reply said **"MDR ₹261"** for the GST line, because `GST_ON_MDR` contains "MDR" and MDR was matched first. The end-to-end run caught it, and a test now checks every line's label.
- A hardware fault with no device on file got the generic "your case" reply. It now names the Soundbox.
- The `.env` import-order issue (D54).

**Verification:**
- `pytest -q` → **52 passed, 5 skipped**. The 5 skipped are `test_real_*`, which switch on once `dataset/` exists. New tests cover:
  - two fixture datasets with **different schemas** normalising to identical values
  - a broken file and a partly usable file
  - dataset-driven mock answers, routing and ITC entries
  - `/presets`, reload on `/reset`, and chargeback state
  - five Person 1 compatibility tests using their exact response shapes
- The `test_real_*` tests were also run against a fixture dataset via `DATASET_DIR` → **5 passed** (golden paths, test files, utterances).
- **End to end with Person 1's actual service** (`services/sarvam_service`, `SARVAM_MODE=mock`, own venv) on 8001 and the merchant agent on 8003, with 8002 down. All of these behave correctly:
  - golden Step 1
  - free text
  - PoD → RELEASED
  - `fake_upi.png` → fraud (UTR `632184920555`)
  - voice
  - hardware escalation
  - consent 403

  Both ports were freed afterwards.

---

## Phase 4: V3 plan — All-in-One Merchant AI Buddy

### What was built
- **6-month historical memory.** Added `history` (`dataset/seed/merchant_history.json`, or a `historical_profile` block inside `merchant.json`) to `dataset_loader.py`, with a built-in seed. It covers:
  - the plan's headline numbers (₹32,000/day, 2.3x Fri–Sun, 96% EDI success, ₹4,500 payable tomorrow, Clix Capital)
  - 6 months of sales, the last 8 days of sales, the eNACH mandate, 5 recent customers, a duplicate payment, past disputes
  - connectors, bank account, Soundbox diagnostics, a growth offer, the cashflow forecast
- **`advisor.py`** implements the plan's closed loop on the merchant side:
  - `diagnose()` gives the root cause, a classification, evidence and a Hinglish tip for all 14 intents.
  - `evaluate()` scores options A/B/C.
  - `verify_and_learn()` writes to `strategy_memory`.
- **`pipeline.run()`** now runs: consent → intent → `ROOT_CAUSE_DIAGNOSED` → `INTERVENTIONS_EVALUATED` → dispatch (with `selected_intervention`) → `PAYTM_TO_MERCHANT` (with `agent_trace`) → ITC/fraud/khata → `OUTCOME_VERIFIED` → reply (resolution + tip, ≤35 words) → TTS.
- **New intents:**
  - from the plan: `MANDATE_TROUBLESHOOT`, `DUPLICATE_RECONCILE`, `GROWTH_ADVISORY`, `CASHFLOW_EDI_SWITCH`
  - from the brief: `SOUNDBOX_RETURN`, `LOAN_CLOSURE_NOC`, `BANK_KYC_UPDATE`, `SETTLEMENT_HOLD_BANK`
  - `REFUND_MANAGE` and `FEE_GST_LOAN` stay supported, for 14 intents in total
- **Routing:** keyword rules for all 14 intents, an updated LLM prompt, and built-in example utterances for intents the dataset doesn't cover yet.
- **`proactive.py`** adds:
  - `POST /merchant/proactive-shield` with scenarios `CHARGEBACK_INCOMING`, `CASHFLOW_EDI_SWITCH` and `MANDATE_FAILED`
  - `POST /merchant/confirm-dispute`
  - `POST /merchant/confirm-edi-pause`
- **`khata.py`:** `GET /merchant/khata-export` (JSON) and `?format=csv` (Tally journal).
- **Other endpoints:** `GET /merchant/profile` (for the insights banner) and `GET /merchant/strategy-memory`.
- **Mock 8002:** answers for all 14 intents, each with a 4-step `agent_trace` (Intelligence → RiskPolicy → Resolution → LedgerOps) and a `verified_outcome`. Also mock `/a2a/proactive-alert` and `/a2a/execute-edi-pause`, with a mock loan EDI state.

### Decisions and why
- **D55 — Old response fields kept, plan fields added.**
  - `hindi_reply` == `reply_text`.
  - New fields: `historical_insight`, `intervention_evaluation`, `verified_outcome`, `pending_action`, `paytm_agent_trace`, `proactive`.
  - Why: Person 1's tests and the existing frontend read `reply_text`, and the plan asks for `hindi_reply`. Supporting both breaks nobody.
- **D56 — Score = value × historical success rate**, where value = 0.4 policy + 0.3 cost + 0.3 UX.
  - Why: I first tried a weighted sum with history as one term. A test showed that 20 straight failures of the chosen strategy still didn't change the choice, because the static scores dominated. Multiplying by P(success) makes learning visible: the buddy switches after repeated failures.
  - The merchant's own verified outcomes count 2× against population priors (Laplace-smoothed).
- **D57 — Policy is a hard block, not a penalty.**
  - Examples: a KFS grace for a likely wilful default, a refund above ₹5,000, releasing goods on a screenshot, an EDI pause when the EDI is already paused or the loan isn't eligible.
  - A blocked option scores 0, shows `blocked_by_policy` with the reason, and is never selected.
  - Why: a soft penalty still let the grace option win for a wilful-default profile, which caught in a test.
- **D58 — Friction vs default.**
  - Friction: sales dip ≥ 25% vs the daily average, on days flagged rain/holiday/`dip`, combined with an EDI success rate ≥ 90%.
  - Wilful-default risk: success rate < 80% with no dip.
  - Anything else: `NEEDS_REVIEW`.
  - The seed has rain on 14–16 Nov (−40%), an eNACH bounce on 16 Nov, then ₹1,00,000 on 17 Nov. That ₹1,00,000 is the gross settled on 18 Nov, so the plan's Act 1 (rain dip) and the settlement story (₹1L sale) are consistent.
- **D59 — Only terminal outcomes are learned.**
  - Learned: success or failure, taken from 8002's `verified_outcome.resolved` if present, otherwise from the status.
  - Not learned: `HELD`, `PENDING`, `NEEDS_INFO` and `ALERT_RAISED`.
  - `/reset` clears learned outcomes; priors stay.
- **D60 — Asking to pause the EDI makes an offer; it does not pause.**
  - A query like "EDI ruk sakti hai?" runs the same eligibility check as the proactive flow (8002 `/a2a/proactive-alert` `HIGH_REFUND_CASHFLOW`). It returns `pending_action: CONFIRM_EDI_PAUSE`.
  - The pause happens only on `/merchant/confirm-edi-pause`.
  - Why: a KFS pause needs an explicit consent artifact. A question is not consent.
- **D61 — Proactive chargeback sends nothing to Paytm before sign-off.**
  - The PoD is pulled from `SHIPROCKET_SYNC`; the file is `dataset/test_files/pod_9981.png`, falling back to a built-in PoD.
  - The PoD is extracted (8001) and packed as `DISPUTE-9981`.
  - `MERCHANT_TO_PAYTM` happens only in `/merchant/confirm-dispute`, through the existing `/a2a/dispatch`. The `pod_source` there is `SHIPROCKET_SYNC`.
- **D62 — `MANDATE_FAILED` proactive scenario.** I added this because the plan names `MANDATE_FAILED_ALERT`.
  - It dispatches immediately, without a confirm step.
  - Why: a 1-tap UPI link is non-binding (the merchant still pays it themselves), and the merchant consented on the call.
- **D63 — Names for the brief's 4 new intents:** `SOUNDBOX_RETURN`, `LOAN_CLOSURE_NOC`, `BANK_KYC_UPDATE`, `SETTLEMENT_HOLD_BANK`.
  - The brief didn't name them, so 8002 may name them differently.
  - Safety net: if a live 8002 returns `UNSUPPORTED_INTENT` (or a similar status) or an HTTP error, 8003 answers from its mock, so the demo never breaks.
- **D64 — Routing order for the new intents.**
  - Soundbox return comes before hardware fault, and before refund (`wapas`).
  - "Loan settle" means NOC, not settlement.
  - Settlement hold/bank inactive comes before chargeback (`hold`) and before KYC.
  - "bill abhi bhi kat raha" (still being charged) is a return. "rental kitna kata" (how much was charged) stays `FEE_GST_LOAN`.
- **D65 — Khata is double-entry, with one voucher per row.**
  - Vouchers: Sales (gross), Journal per deduction (MDR, Input GST/ITC, refunds, rental, chargeback hold), and Receipt (bank credit).
  - The buddy's completed actions are added too: chargeback released, duplicate refunded, refund initiated, and the EDI pause as a Memorandum voucher (no cash moved).
  - The CSV has Tally-friendly `DD-MM-YYYY` dates and a UTF-8 BOM so ₹ and Hindi names survive Excel/Tally import.
  - `summary.reconciled` checks gross − deductions = bank credit.
  - `local_gst_itc_log` is unchanged, for compatibility.
- **D66 — Reply = resolution + tip, kept within 35 words.**
  - The template replies give the resolution, and `compose()` appends `historical_insight.tip_hi` only if the total stays ≤ 35 words. This is why the long settlement itemisation has no tip.
  - The fraud warning never gets a tip.
  - The LLM prompt asks for the same combination.
- **D67 — Hardware escalations carry the Soundbox diagnostics** (battery 9%, weak 2G, speaker self-test failed) in the A2A payload, so L2 asks "zero repeat questions" (plan scenario 8).

### Verification
- `pytest -q`: **89 passed, 5 skipped**. The 5 skipped are the real-dataset tests, which wait for `dataset/`.
- The new `test_buddy.py` (37 tests) covers:
  - routing
  - the full loop on one response
  - friction vs wilful-default choices
  - learning that changes a later choice
  - policy blocks
  - all new intents within the 35-word budget
  - proactive chargeback, cashflow and mandate flows, including 403, 404 and 409
  - live-8002 pass-through, and the mock fallback for unsupported intents
  - khata JSON and CSV
- Live run: real uvicorn on 8003 + Person 1's real service on 8001 (`SARVAM_MODE=mock`), with 8002 down:
  - 4 queries; proactive chargeback → confirm → RELEASED; cashflow offer → confirm → `PAUSED_2_DAYS`; khata CSV; CORS for :3000
  - Result: **E2E OK**.
  - Ports 8001 and 8003 were freed afterwards.

---

## Phase 5: Integration check against the pulled code (main @ fa6c7b4)

Pulled: Person 2's `services/paytm_agent` (8002), the team dataset at `data/seed/` (PR #7), and Person 1's V2 update (`use_sample_connector`). I ran all three real services together (8001 mock mode, 8002, 8003) and sent every scenario through 8003.

### What didn't match, and what I changed (8003 only)
- **D68 — The dataset is at `data/seed/` (CSV + JSON), not `dataset/seed/*.json`.** 8003 had been reading nothing.
  - New `seed_adapter.py` turns `merchant_profile.json`, `settlement_breakdown_2026-11-18.json`, `utr_ledger.csv`, `refunds.csv`, `chargebacks.csv`, `loan.json`, `scenarios.json`, `daily_sales_summary.csv`, `edi_schedule.csv`, `device_logs.csv` and `strategy_memory.json` into the sections the loader already normalises.
  - `data/` is now the default location, and `dataset/` still works.
  - All 10 sections load, the settlement checks pass, and the 8 scenario triggers become preset chips and golden steps.
- **D69 — The built-in seed now tells the dataset's story.**
  - The dip is a market closure on 14–16 Nov, not rain.
  - The bounce is on 17 Nov.
  - The duplicate is order 4489: ₹1,180 paid twice on PhonePe by Sunita Yadav.
  - Soundbox battery health is 18%, with 60 payments not announced.
  - The PoD shows Rohit Verma, Demo Express Logistics, AWB DEX7781203345.
- **D70 — The dip is measured against the same weekday.**
  - Two of the closure days were Sat/Sun, which normally run 2.3x. Against the flat ₹32,000 average the dip looked like 23%, so the diagnosis said "needs review".
  - Each day is now compared with the mean of the same weekday over the previous 4 ordinary weeks. That gives a 37% dip, so friction, not default.
- **D71 — Strategy priors from the dataset.** `strategy_memory.json` mandate memories are added to the population priors. Its other intents use different A/B/C letters, so they are not mapped.
- **D72 — Payload names 8002 reads.** 8002 answers 400 `BAD_PAYLOAD` without them, and 8003 then silently used its mock.
  - UTR: `utr`, `source`, `claimed_amount_inr`.
  - Escalation: `reason_code` (`MERCHANT_REQUESTED_HUMAN`), plus `reason_text` and `tried` carrying the Soundbox diagnostics.
  - Envelope: `session_id` (one per demo run) and `language_code`.
  - `merchant_said` is still not sent (data minimisation).
- **D73 — `upstream.interpret()` reads 8002's answers.** 8002 always returns `RESOLVED | ACTION_REQUIRED | ESCALATED` with the specifics in `data`, so this maps them to specific outcomes:
  - `lines` → itemised breakdown, so the ₹261 ITC is logged live
  - `lookup_status: NOT_FOUND` → fraud alert
  - `hold_status: RELEASED` → RELEASED
  - `refund_status` → REFUND_INITIATED
  - `remedies` → REMEDIES_OFFERED
  - `credit_offer` → OFFER_PREAPPROVED

  `paytm_response` is still 8002's raw body, plus `status_detail`. Replies, ITC, fraud, khata and learning use the interpreted view. Both intent names (`DUPLICATE_RECONCILE`/`DUPLICATE_PAYMENT_RECONCILE`, `GROWTH_ADVISORY`/`WORKING_CAPITAL_ADVISORY`) are read.
- **D74 — Mandate: 8002 offers remedies, it doesn't send a link.**
  - The reply no longer says "link भेजा है". It says "1-tap UPI link से आज भरिए… 2 दिन का KFS pause भी है".
  - 8002's pause remedy (`EDIOFFER-0001`) is registered, so `/merchant/confirm-edi-pause` accepts it.
  - The outcome is PENDING until something is resolved.
- **D75 — No invented credit pricing.** The growth offer is now ₹1,50,000 with "rate और tenure KFS में", matching 8002's `CreditOffer`, which deliberately quotes no rate. The old "₹50,000 at 21% APR" was made up.
- **D76 — Proactive chargeback uses Person 1's sample connector** (`/doc-extract use_sample_connector=true`, `samples/pod_9981.png`) when no local PoD file exists, so the real document is extracted.
- **D77 — Duplicate tip guard.** If Paytm matched a different order than the merchant's books (8002 says 4455, the dataset says 4489), the "X आपके repeat customer हैं" tip is dropped rather than naming the wrong person.

### Verification
- `pytest -q`: **103 passed, 0 skipped**.
  - The 5 real-dataset tests now run against `data/seed`.
  - The new `test_paytm_live.py` pins 8002's recorded response shapes and its 400 rules.
- Live run with 8001 + 8002 + 8003: settlement, UTR (good and fake), chargeback, duplicate, growth, mandate and escalation all show `paytm_source=live` with a 4-step trace.
  - Proactive chargeback → sign-off → 8002 hold `RELEASED`.
  - Cashflow offer → confirm → 8002 `loan_edi_status: PAUSED_2_DAYS`.
  - All three ports were freed afterwards.

---

## Phase 6: Shared .env + Vercel/Railway deployment prep (user request, 2026-11-19)
The user asked for one `.env` connecting all four apps, plus deploy prep. Files outside this folder are new files
only, at the repo root and in `deploy/`. No teammate's code was edited.

- **D78 — One root `.env`.**
  - 8001 and 8002 call `load_dotenv()` without a path, which in python-dotenv 1.2.4 searches upward from `app/config.py`, so they find `<repo>/.env` unchanged.
  - 8003 now loads its own `.env` first, then the root one (`upstream.py`, `dataset_loader.py`). `load_dotenv` never overrides, so a service `.env` or real env vars win.
  - Vite ignores it. `frontend/src/config.js` already defaults to localhost.
- **D79 — New root `.gitignore`.** There was none, and `frontend/.gitignore` only covers `.env.local`, so a root `.env` holding the Sarvam key would have been committed. `.env.example` (no secrets) stays tracked.
- **D80 — Railway via Dockerfiles in `deploy/`, built from the repo root.**
  - Selected with `RAILWAY_DOCKERFILE_PATH`, not `railway.json`: Railway's docs mark config as code deprecated for older services after 2026-12-01.
  - The repo root is the context because 8003 needs `data/seed`. Its image keeps the repo layout, so no `DATASET_DIR` is needed, and it copies Person 1's two sample PNGs.
  - `.dockerignore` keeps `.env` and venvs out of every image.
  - One replica each, because state is in memory.
- **D81 — CORS.** The browser calls only 8003 and 8002 (`frontend/src/api.js`). The Vercel origin goes in `CORS_EXTRA_ORIGINS` (8003) and `ALLOWED_ORIGINS` (8002). 8001 is reached only from 8003, so it needs no Vercel origin.

### Verification
- `pytest -q`: 103 passed, with the root `.env` present. The conftest env wins, so the key doesn't leak into the tests.
- All three services started like their containers (service folder as cwd, `--host 0.0.0.0 --port $PORT`), with no env passed in, so everything came from the root `.env`.
  - 8001 `/health`: `mode: live`, `api_key_configured: true`.
  - An off-script query to 8003 was classified by Sarvam's LLM (`intent_source=llm`, 4.9 s). 8002 answered live with the correct reply.
  - Sarvam TTS returned real audio (`source=sarvam`), and the Sarvam Vision samples finished.
- CORS preflight with deploy-style variables: a `*.vercel.app` origin is allowed on 8001, 8002 and 8003, and a foreign origin is rejected.
- Vercel build simulated in a scratch copy (`frontend/` + `data/seed`, `npm ci && npm run build` with `VITE_*` = Railway URLs). It built in 1 s, the Railway URLs are in the bundle, and no localhost URL remains.
- Docker isn't installed here, so the images themselves weren't built. Ports 8001–8003 were freed.

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
7. **When `dataset/` lands:**
   - Run `pytest -q`.
   - Check `GET /health` → `dataset.files`. Every file should say `dataset`.
   - If a file says `builtin (unusable…)` or `dataset (builtin for: …)`, add its field names to the key lists in `dataset_loader.py`.
8. **Dataset teammate:** make sure `transactions.json` does **not** contain `632184920555`. Person 1's mock reads `fake_upi.png` as that UTR, and if it is in the ledger the fraud demo shows "payment successful".
9. **Person 4:** `audio_source` (`mock` means a placeholder tone), the new `intent_source` value `utterance_bank`, and the optional `GET /presets`.
10. **Person 2 (V3):** confirm the following:
    - `/a2a/dispatch` accepts `selected_intervention: {option_id, action, label, score}`.
    - The names of the 4 new intents (D63).
    - `MANDATE_TROUBLESHOOT` reads `selected_intervention.action`: `SEND_REMINDER`, `UPI_LINK_48H_GRACE` or `ESCALATE_SPECIALIST`.
    - Statuses for the mock-only intents, and that `verified_outcome.resolved` is a boolean.
    - `/a2a/proactive-alert` supports `MANDATE_FAILED_ALERT`.
11. **Contract (CONTRACT.md V2 vs plan V3):**
    - The contract maps `CASHFLOW_EDI_SWITCH` to the intent `FEE_GST_LOAN`, but V3 makes it its own intent. 8003 uses `CASHFLOW_EDI_SWITCH`.
    - The contract has no `MANDATE_FAILED` scenario.
    - The contract doesn't list the 8 new intents or the new response fields.
    - Needs a V3 section, written only if the user asks.
12. **Data inconsistency:** the plan's scenario 7 says a "₹8,500 refund", but CONTRACT.md V2 says ₹3,500 (`ORDER #4490`). The payout of ₹1,200 is the same in both. 8003 uses the contract's ₹3,500, from the alert data when 8002 is live. Pick one for the pitch.
13. **Dataset teammate:** `seed/merchant_history.json` needs these fields:
    - the headline fields
    - `recent_daily_sales` with the rain-flagged dip days
    - `mandate`, `recent_customers`, `duplicate_payments` (order 7310 with 2 UTRs), `past_disputes`, `connectors`
    - `bank_account`, `soundbox_diagnostics`, `growth_offer`, `cashflow`

    Every field falls back to the built-in seed. `GET /health` → `dataset.files.history` shows what loaded.
