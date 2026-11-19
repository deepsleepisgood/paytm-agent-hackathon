# Sarvam Service — Person 1 (port 8001)

Speech, voice, document reading and LLM for the A2A Merchant–Paytm Resolution Network,
all on Sarvam AI's Indic models. Implements the Person 1 section of `contract.md`.

| Endpoint | Sarvam API used | Model |
|---|---|---|
| `POST /stt` | Speech-to-Text (`/speech-to-text`) | Saaras v3 (auto language detect) |
| `POST /tts` | Text-to-Speech (`/text-to-speech`) | Bulbul v3, voice `priya` |
| `POST /doc-extract` | Document AI Extract (`/doc-ai/v1/job/extract`) | Sarvam Vision |
| `POST /llm` | Chat Completions (`/v1/chat/completions`) | Sarvam-105B |
| `GET /health` | — | shows live/mock mode |

## Run it

```bash
cd services/sarvam_service
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # paste your key into SARVAM_API_KEY
uvicorn app.main:app --port 8001 --reload
```

Interactive docs: http://localhost:8001/docs

**No key yet?** Leave `SARVAM_API_KEY` empty. The service runs in **mock mode** and returns
contract-shaped answers that match the seed data (MID `PAYTM_MERCH_8821`), so Persons 2–4
can integrate today. Every response has `"source": "sarvam"` or `"source": "mock"`.

Get a key at https://dashboard.sarvam.ai, then check the live integration end-to-end:

```bash
python scripts/smoke_live.py      # TTS -> STT round trip, LLM intent, doc extraction
pytest -q                         # 44 tests, no key or network needed
```

## For Person 3 (merchant agent, :8003): read this first

| Call | Use this client timeout | Why |
|---|---|---|
| `/stt`, `/tts`, `/llm` | **6 s** is fine | We answer within **5 s**, guaranteed. If Sarvam is slower, we stop waiting and return a mock answer (`"source": "mock"`), so you never hit your timeout. |
| `/doc-extract` | **30 s**, not 6 s | Sarvam Doc AI is a job (submit → wait → fetch), so it takes longer. Our budget is 25 s. The same file a second time comes back instantly from cache. |

- **Intent JSON from `/llm`:** read `parsed`. Mock mode returns `intent`, `utr_number`, `order_id` and
  `amount` both flat and under `slots`. Live mode returns whatever shape your system prompt asks for.
  To force the shape, pass `json_schema` (example below).
- **Spoken reply from `/llm` (text):** in mock mode it is a proper Hindi sentence built from the seed
  numbers, never debug text. Mock replies always use the seed values, so check `source` if you need live data.
- **`/stt` `language_code`:** Hindi and Hinglish (including romanised "payment aaya kya") come back as `hi-IN`.
- Keep your own keyword fallback for when :8001 is completely down (connection refused). This service
  covers slow or failing Sarvam calls, but it can't cover itself being down.

Recommended intent schema (live mode guarantees this exact shape):
```json
{"type": "object", "required": ["intent", "utr_number", "order_id", "amount"],
 "properties": {
   "intent": {"type": "string", "enum": ["SETTLEMENT_RECONCILE","UTR_VERIFY","CHARGEBACK_RESOLVE","REFUND_MANAGE","FEE_GST_LOAN","ESCALATE_HUMAN"]},
   "utr_number": {"type": ["string","null"]}, "order_id": {"type": ["string","null"]}, "amount": {"type": ["number","null"]}}}
```

## API (for Persons 2, 3, 4)

Fields marked ★ are the contract. Others are additive: ignore them if you don't need them.

### `POST /stt` — form-data
| field | |
|---|---|
| `audio` ★ | wav/mp3/webm/ogg/m4a… under ~30 s (browser MediaRecorder webm is fine) |
| `language_code` | optional, default `unknown` = auto-detect |
| `mock_transcript` | mock mode only: choose what the "merchant said" for a demo step |

```json
{"transcript": "मेरा कल का settlement ₹4,160 कम आया है", "language_code": "hi-IN", "language_probability": 0.97, "source": "sarvam"}
```

### `POST /tts` — JSON
```json
{"text": "आपका ₹95,840 कल बैंक में आ गया है", "language_code": "hi-IN"}
```
→ `{"audio_base64": "<WAV>", "mime_type": "audio/wav", "source": "sarvam"}`

Play in the browser: `new Audio("data:audio/wav;base64," + res.audio_base64).play()`

Languages: `hi-IN en-IN bn-IN gu-IN kn-IN ml-IN mr-IN od-IN pa-IN ta-IN te-IN`.
Optional: `speaker`, `pace` (0.5–2.0). Long text is split and joined automatically.
Write amounts with commas (`₹95,840`): Bulbul reads them correctly that way.

### `POST /doc-extract` — form-data `file`, `doc_type` = `pod` | `upi_screenshot`
PNG/JPG screenshots or PDFs. Images are wrapped into a 1-page PDF for Sarvam Doc AI.

```json
{
  "doc_type": "upi_screenshot",
  "extracted_fields": {"utr": "632184920111", "amount": 1250, "payer_app": "GPay", "status": "SUCCESS",
                       "transaction_datetime": "18 Nov 2026, 11:03 am", "payee_name": "Sharma Electronics"},
  "confidence": 1.0,
  "warnings": [],
  "source": "sarvam"
}
```
`pod` fields: `order_id`, `awb_or_tracking_id`, `courier_name`, `delivery_date`, `recipient_name`,
`delivery_address`, `amount`, `signature_present`.

**How `confidence` is computed** (Sarvam returns values, not per-field scores): the share of
required fields that were read (UPI: utr, amount, status; PoD: order_id, delivery_date,
recipient_name, signature_present), minus 0.1 per validation warning (e.g. a UTR that isn't
12 digits). It is deterministic and explainable. **Person 2:** treat `< 0.7` as "ask the
merchant for a clearer photo", not as fraud.

Mock demo scenarios, chosen by **file name**: `*fake*` → unknown UTR `632184920555`
(→ `NOT_FOUND_SUSPECTED_FAKE`), `*pending*` → UTR `632184920999`, anything else → UTR `632184920111`.

### `POST /llm` — JSON
```json
{"system_prompt": "...", "user_prompt": "...", "response_format": "json"}
```
→ `{"reply": "<string>", "parsed": {...} | null, "model": "sarvam-105b", "source": "sarvam"}`

- `reply` is always a string (contract). With `response_format: "json"` it is valid JSON text, and
  `parsed` already holds the object, so you don't need `json.loads`.
- Optional `json_schema` (with `"json"`) forces an exact shape, e.g. for intent routing.
- If the model doesn't return valid JSON → HTTP 502, so your agent can retry or escalate.

## Design decisions (and why)

- **Mock mode + automatic fallback.** The team isn't blocked on a key, and a Sarvam outage during
  judging doesn't kill the demo. Answers are always labelled with `source`, so it's never hidden.
- **Latency budgets on our side.** Callers have short timeouts, so we enforce our own deadline
  just under theirs and degrade to a labelled mock answer instead of letting the whole chain time out.
  The reasoning setting defaults to `none`: classifying an intent and rephrasing a reply don't need it, and it is much faster.
- **Raw `httpx`, not the SDK.** Every request is visible in `app/sarvam_client.py`, which makes
  debugging faster. One retry on 429/5xx, then fail fast. A slow retry loop hurts a live demo more than an error.
- **Validation is deterministic.** The vision model reads the screenshot, then Python checks it (UTR
  format, amount parsing, status normalisation). The model isn't trusted to police itself.
- **Doc results cached by file hash.** Re-running the demo doesn't wait for a new Doc AI job.
- **DPDP.** No audio, document or prompt content is logged, only endpoint, status code and latency.
  Consent is checked by Person 3 before anything reaches this service.

## Files
```
app/main.py            routes + live/mock switch
app/sarvam_client.py   the four Sarvam API calls (retry, PDF wrapping, job polling)
app/mock.py            seed-aligned offline answers + keyword intent router
app/doc_schemas.py     what to extract from a PoD / UPI screenshot
app/confidence.py      field cleaning, validation, confidence score
app/audio.py           TTS chunking, WAV merging
scripts/smoke_live.py  live end-to-end check with your key
tests/                 44 tests (mock contract, faked Sarvam HTTP, Person 3 call flow)
```
