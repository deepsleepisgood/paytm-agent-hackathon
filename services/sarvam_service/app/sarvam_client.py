"""Thin async client for the four Sarvam APIs we use.

Design choices:
- Raw httpx instead of the `sarvamai` SDK: one dependency fewer, and every request is
  visible here, which makes debugging during the hackathon much faster.
- One retry on 429/5xx/timeouts with a short backoff. More retries would only make a
  live demo hang longer; the fallback-to-mock in main.py covers the rest.
- We never log audio, documents or prompt text (DPDP: merchant data stays out of logs).
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
from typing import Any

import httpx

from .config import settings

log = logging.getLogger("sarvam")

RETRYABLE = {429, 500, 502, 503, 504}
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class SarvamError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _headers(json_body: bool = False) -> dict[str, str]:
    h = {"api-subscription-key": settings.api_key}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


async def _request(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
    url = f"{settings.base_url}{path}"
    last_exc: Exception | None = None
    for attempt in range(2):
        started = time.perf_counter()
        try:
            resp = await client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            log.warning("sarvam %s %s transport error (attempt %d): %s", method, path, attempt + 1, type(exc).__name__)
        else:
            ms = int((time.perf_counter() - started) * 1000)
            log.info("sarvam %s %s -> %d in %dms", method, path, resp.status_code, ms)
            if resp.status_code < 400:
                return resp
            if resp.status_code not in RETRYABLE or attempt == 1:
                raise SarvamError(f"Sarvam {path} returned {resp.status_code}: {resp.text[:300]}", resp.status_code)
        await asyncio.sleep(1.0 + attempt)
    raise SarvamError(f"Sarvam {path} unreachable: {last_exc}")


# ---------------------------------------------------------------- Speech to text
async def speech_to_text(audio: bytes, filename: str, content_type: str | None, language_code: str = "unknown") -> dict:
    data = {"model": settings.stt_model, "language_code": language_code}
    if settings.stt_model.startswith("saaras"):
        data["mode"] = settings.stt_mode
    files = {"file": (filename or "audio.webm", audio, content_type or "application/octet-stream")}
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        resp = await _request(client, "POST", "/speech-to-text", headers=_headers(), data=data, files=files)
    body = resp.json()
    return {
        "transcript": body.get("transcript", ""),
        "language_code": body.get("language_code"),
        "language_probability": body.get("language_probability"),
    }


# ---------------------------------------------------------------- Text to speech
def _speaker_for(model: str, speaker: str | None) -> str | None:
    """Voices are model-specific: v4 voices look like 'shubh_enhi_ads', v3/v2 like 'priya'.
    Sending a voice from the wrong family is a 400, so drop it and use the model's default."""
    if not speaker:
        return None
    is_v4_voice = "_" in speaker
    return speaker if is_v4_voice == model.startswith("bulbul:v4") else None


# (model, speaker, language field) that last worked. Saves a failed round trip on every call.
_tts_variant: tuple[str, str | None, str] | None = None


async def text_to_speech(text: str, language_code: str, speaker: str | None, pace: float | None) -> str:
    """Returns base64 WAV for one chunk of text (<= 2,500 chars).

    Tries, in order: primary model (v4-flash) -> fallback model (v3) -> v3 with the older
    `target_language_code` field. A 400/422 moves to the next variant; anything else
    (timeouts, 5xx) is a real outage and is raised.
    """
    global _tts_variant
    wanted = speaker or settings.tts_speaker
    variants = [
        (settings.tts_model, _speaker_for(settings.tts_model, wanted), "language_code"),
        (settings.tts_fallback_model,
         _speaker_for(settings.tts_fallback_model, speaker) or settings.tts_fallback_speaker, "language_code"),
        (settings.tts_fallback_model, settings.tts_fallback_speaker, "target_language_code"),
    ]
    if _tts_variant in variants:
        variants.remove(_tts_variant)
        variants.insert(0, _tts_variant)

    last_exc: SarvamError | None = None
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        for model, voice, lang_field in variants:
            payload: dict[str, Any] = {"text": text, lang_field: language_code, "model": model,
                                       "speech_sample_rate": settings.tts_sample_rate}
            if voice:
                payload["speaker"] = voice
            if pace is not None:
                payload["pace"] = pace
            try:
                resp = await _request(client, "POST", "/text-to-speech", headers=_headers(True), json=payload)
            except SarvamError as exc:
                if exc.status_code not in (400, 422):
                    raise
                log.warning("tts: %s/%s/%s rejected (%s), trying next", model, voice, lang_field, exc.status_code)
                last_exc = exc
                continue
            audios = resp.json().get("audios") or []
            if not audios:
                raise SarvamError("Sarvam TTS returned no audio")
            _tts_variant = (model, voice, lang_field)
            return audios[0]
    raise last_exc or SarvamError("Sarvam TTS failed")


# ---------------------------------------------------------------- Chat / LLM
async def chat(system_prompt: str, user_prompt: str, response_format: str,
               json_schema: dict | None, temperature: float | None, max_tokens: int | None,
               reasoning_effort: str | None = None) -> dict:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "max_tokens": max_tokens or settings.llm_max_tokens,
    }
    # Per-request override: e.g. Person 3's Option A/B/C evaluation can ask for "low".
    effort = reasoning_effort or settings.llm_reasoning_effort
    if settings.llm_model == "sarvam-105b":  # the -conversations model ignores this anyway
        payload["reasoning_effort"] = None if effort == "none" else effort
    if temperature is not None:
        payload["temperature"] = temperature
    if response_format == "json":
        if json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "agent_output", "schema": json_schema, "strict": True},
            }
        else:
            payload["response_format"] = {"type": "json_object"}

    headers = _headers(True) | {"Authorization": f"Bearer {settings.api_key}"}
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        try:
            resp = await _request(client, "POST", "/v1/chat/completions", headers=headers, json=payload)
        except SarvamError as exc:
            # A strict schema the API can't honour is rejected with 400/422. Fall back to
            # plain JSON mode: still valid JSON, the caller validates the shape.
            if not (json_schema and exc.status_code in (400, 422)):
                raise
            payload["response_format"] = {"type": "json_object"}
            resp = await _request(client, "POST", "/v1/chat/completions", headers=headers, json=payload)
    body = resp.json()
    content = (body["choices"][0]["message"].get("content") or "").strip()
    content = _THINK_RE.sub("", content).strip()  # defensive: strip any inline reasoning
    return {"reply": content, "model": body.get("model", settings.llm_model)}


# ---------------------------------------------------------------- Document AI (Extract)
def _ensure_pdf(data: bytes, filename: str, content_type: str | None) -> tuple[bytes, str, str]:
    """Doc AI documents PDF/ZIP input. Phone screenshots are PNG/JPG, so wrap images in a 1-page PDF."""
    is_pdf = data[:5] == b"%PDF-" or (content_type or "").endswith("pdf") or filename.lower().endswith(".pdf")
    if is_pdf:
        return data, filename or "document.pdf", "application/pdf"
    from PIL import Image  # imported lazily: only needed for images

    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150)
    stem = (filename or "upload").rsplit(".", 1)[0]
    return buf.getvalue(), f"{stem}.pdf", "application/pdf"


async def extract_document(data: bytes, filename: str, content_type: str | None, schema: dict) -> dict:
    pdf, name, mime = _ensure_pdf(data, filename, content_type)
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        resp = await _request(
            client, "POST", "/doc-ai/v1/job/extract",
            headers=_headers(),
            data={"schema": json.dumps(schema), "language": "en-IN", "output_format": "json"},
            files={"file": (name, pdf, mime)},
        )
        job_id = resp.json().get("job_id")
        if not job_id:
            raise SarvamError("Doc AI did not return a job_id")

        deadline = time.monotonic() + settings.doc_job_timeout
        status = "pending"
        while time.monotonic() < deadline:
            await asyncio.sleep(settings.doc_poll_interval)
            st = await _request(client, "GET", f"/doc-ai/v1/job/{job_id}/status", headers=_headers())
            status = st.json().get("status", "")
            if status in {"completed", "partially_completed", "failed", "rejected"}:
                break
        if status not in {"completed", "partially_completed"}:
            raise SarvamError(f"Doc AI job {job_id} ended as '{status}'")

        res = await _request(client, "GET", f"/doc-ai/v1/job/{job_id}/results", headers=_headers())
    body = res.json()
    result = body.get("result", body)
    if isinstance(result, list):  # one entry per document/page: take the first
        result = result[0] if result else {}
    return {"fields": result if isinstance(result, dict) else {}, "partial": status == "partially_completed"}
