"""Person 1 — Sarvam service (port 8001).

Endpoints (see contract.md):
  POST /stt          form-data audio                      -> {transcript, language_code}
  POST /tts          {text, language_code}                -> {audio_base64}
  POST /doc-extract  form-data file, doc_type             -> {doc_type, extracted_fields, confidence}
  POST /llm          {system_prompt, user_prompt, response_format} -> {reply}
  GET  /health       mode + which Sarvam features are live
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import mock, sarvam_client
from .audio import chunk_text, merge_wav_base64
from .confidence import missing_required, normalise, score
from .config import settings
from .doc_schemas import SCHEMAS
from .schemas import (
    SUPPORTED_LANGUAGES,
    DocExtractResponse,
    DocType,
    LLMRequest,
    LLMResponse,
    STTResponse,
    TTSRequest,
    TTSResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sarvam_service")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    await _prewarm_samples()
    yield
    for task in _sample_tasks.values():
        task.cancel()


app = FastAPI(title="Sarvam Service (Person 1)", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

T = TypeVar("T")

# Same file + doc_type -> same answer, without paying Sarvam twice or waiting on a
# second Doc AI job. Handy when the demo is re-run. In-memory only; cleared on restart.
_doc_cache: dict[str, DocExtractResponse] = {}


async def _live_or_mock(feature: str, live: Callable[[], Awaitable[T]], fallback: Callable[[], T],
                        budget: float | None = None) -> tuple[T, str]:
    """Run the live Sarvam call within a latency budget; on failure or timeout, fall back
    to mock if allowed. Returns (result, source)."""
    if not settings.use_live:
        return fallback(), "mock"
    budget = budget or settings.latency_budget
    try:
        return await asyncio.wait_for(live(), timeout=budget), "sarvam"
    except Exception as exc:  # noqa: BLE001 - any failure here is a Sarvam/network problem
        timed_out = isinstance(exc, asyncio.TimeoutError)
        reason = f"no answer within {budget:g}s" if timed_out else str(exc)
        log.error("%s: Sarvam call failed: %s", feature, reason)
        if settings.fallback_to_mock:
            log.warning("%s: answering from mock (SARVAM_FALLBACK_TO_MOCK=true)", feature)
            return fallback(), "mock"
        raise HTTPException(status_code=504 if timed_out else 502, detail=f"Sarvam {feature} failed: {reason}") from exc


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "mode": "live" if settings.use_live else "mock",
        "api_key_configured": bool(settings.api_key),
        "fallback_to_mock": settings.fallback_to_mock,
        "models": {
            "stt": settings.stt_model,
            "stt_mode": settings.stt_mode,
            "tts": f"{settings.tts_model} ({settings.tts_speaker or 'default voice'}), fallback {settings.tts_fallback_model}",
            "llm": settings.llm_model,
            "doc": "doc-ai extract (Sarvam Vision)",
            "samples_ready": {k: (t.done() and not t.cancelled() and t.exception() is None) for k, t in _sample_tasks.items()},
        },
    }


# ----------------------------------------------------------------------------- /stt
@app.post("/stt", response_model=STTResponse)
async def stt(
    audio: UploadFile = File(...),
    language_code: str = Form("unknown"),
    mock_transcript: str | None = Form(None),  # mock mode only: lets the demo script choose the line
) -> STTResponse:
    data = await audio.read()
    if not data:
        raise HTTPException(400, "Empty audio file")
    if len(data) > settings.max_audio_bytes:
        raise HTTPException(413, "Audio too large; keep voice notes under ~30 seconds")
    if language_code != "unknown" and language_code not in SUPPORTED_LANGUAGES:
        raise HTTPException(422, f"Unsupported language_code '{language_code}'")

    result, source = await _live_or_mock(
        "stt",
        lambda: sarvam_client.speech_to_text(data, audio.filename or "audio.webm", audio.content_type, language_code),
        lambda: mock.stt(mock_transcript),
    )
    return STTResponse(**result, source=source)


# ----------------------------------------------------------------------------- /tts
@app.post("/tts", response_model=TTSResponse)
async def tts(req: TTSRequest) -> TTSResponse:
    if req.language_code not in SUPPORTED_LANGUAGES:
        raise HTTPException(422, f"Unsupported language_code '{req.language_code}'. Use one of {SUPPORTED_LANGUAGES}")

    async def live() -> str:
        parts = [await sarvam_client.text_to_speech(c, req.language_code, req.speaker, req.pace) for c in chunk_text(req.text)]
        return merge_wav_base64(parts)

    audio_b64, source = await _live_or_mock("tts", live, mock.tts)
    return TTSResponse(audio_base64=audio_b64, source=source)


# ----------------------------------------------------------------------------- /doc-extract
# Sample connector documents (plan.md: use_sample_connector=true). Clearly marked demo
# images that match the seed data, so the "Shiprocket PoD for #9981" step works without
# anyone uploading a file.
SAMPLES_DIR = Path(__file__).parent / "samples"
SAMPLE_DOCS: dict[str, dict] = {
    "pod": {"file": "pod_9981.png", "connector": "SHIPROCKET_SYNC"},
    "upi_screenshot": {"file": "upi_632184920111.png", "connector": "SAMPLE_UPI_SCREENSHOT"},
}
_sample_tasks: dict[str, asyncio.Task] = {}


def _sample(doc_type: str) -> tuple[bytes, str, dict]:
    meta = SAMPLE_DOCS[doc_type]
    data = (SAMPLES_DIR / meta["file"]).read_bytes()
    return data, meta["file"], {"name": meta["connector"], "document": meta["file"], "sample": True,
                                "consent": "GRANTED"}


async def _extract(data: bytes, filename: str, content_type: str | None, doc_type: str,
                   connector: dict | None = None) -> DocExtractResponse:
    key = hashlib.sha256(data + doc_type.encode()).hexdigest()
    if key in _doc_cache:
        return _doc_cache[key]

    async def live() -> dict:
        return await sarvam_client.extract_document(data, filename, content_type, SCHEMAS[doc_type])

    result, source = await _live_or_mock(
        "doc-extract", live, lambda: {"fields": mock.doc_extract(doc_type, filename), "partial": False},
        budget=settings.doc_latency_budget,
    )

    fields, warnings = normalise(doc_type, result["fields"])
    if result.get("partial"):
        warnings.append("Sarvam processed the document only partially")
    missing = missing_required(doc_type, fields)
    if missing:
        warnings.append(f"Could not read: {', '.join(missing)}")

    response = DocExtractResponse(
        doc_type=doc_type,
        extracted_fields=fields,
        confidence=score(doc_type, fields, [w for w in warnings if not w.startswith("Could not read")]),
        warnings=warnings,
        connector=connector,
        source=source,
    )
    if source == "sarvam":
        _doc_cache[key] = response
    return response


@app.post("/doc-extract", response_model=DocExtractResponse)
async def doc_extract(
    doc_type: DocType = Form(...),
    file: UploadFile | None = File(None),
    use_sample_connector: bool = Form(False),
) -> DocExtractResponse:
    if use_sample_connector:
        task = _sample_tasks.get(doc_type)
        if task and not task.done():  # startup warm-up still running: wait for it instead of starting a 2nd job
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=settings.doc_latency_budget)
            except Exception:  # noqa: BLE001 - fall through to a normal extraction
                pass
        data, filename, connector = _sample(doc_type)
        return await _extract(data, filename, "image/png", doc_type, connector)

    if file is None:
        raise HTTPException(422, "Send a file, or use_sample_connector=true")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > settings.max_doc_bytes:
        raise HTTPException(413, "File too large (max 15 MB)")
    return await _extract(data, file.filename or "upload", file.content_type, doc_type)


async def _prewarm_samples() -> None:
    """In live mode, run both sample documents through Sarvam Vision once at startup, so the
    demo's connector step answers from cache instantly instead of waiting ~5 s on stage."""
    if not settings.use_live:
        return
    for doc_type in SAMPLE_DOCS:
        data, filename, connector = _sample(doc_type)
        _sample_tasks[doc_type] = asyncio.create_task(_extract(data, filename, "image/png", doc_type, connector))


# ----------------------------------------------------------------------------- /llm
def _parse_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Models sometimes wrap JSON in ```json fences or a sentence; pull out the outer object.
    match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


@app.post("/llm", response_model=LLMResponse)
async def llm(req: LLMRequest) -> LLMResponse:
    if req.json_schema and req.response_format != "json":
        raise HTTPException(422, "json_schema needs response_format='json'")

    result, source = await _live_or_mock(
        "llm",
        lambda: sarvam_client.chat(req.system_prompt, req.user_prompt, req.response_format,
                                   req.json_schema, req.temperature, req.max_tokens, req.reasoning_effort),
        lambda: {"reply": mock.llm(req.user_prompt, req.response_format, req.system_prompt), "model": "mock"},
    )

    parsed = None
    if req.response_format == "json":
        parsed = _parse_json(result["reply"])
        if parsed is None:
            raise HTTPException(502, "LLM did not return valid JSON")
        result["reply"] = json.dumps(parsed, ensure_ascii=False)

    return LLMResponse(reply=result["reply"], parsed=parsed, model=result.get("model"), source=source)
