"""Request/response models. Field names marked CONTRACT match contract.md exactly.

Extra fields (source, warnings, parsed, ...) are additive: a client that only reads the
contract fields keeps working, and a client that wants more detail can use them.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Source = Literal["sarvam", "mock"]

SUPPORTED_LANGUAGES = (
    "hi-IN", "en-IN", "bn-IN", "gu-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN",
)


class STTResponse(BaseModel):
    transcript: str  # CONTRACT
    language_code: Optional[str]  # CONTRACT (BCP-47, e.g. "hi-IN"; null if undetected)
    language_probability: Optional[float] = None
    source: Source


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000)  # CONTRACT
    language_code: str = "hi-IN"  # CONTRACT
    speaker: Optional[str] = None  # optional override of the default voice
    pace: Optional[float] = Field(None, ge=0.5, le=2.0)


class TTSResponse(BaseModel):
    audio_base64: str  # CONTRACT (a complete WAV file, base64-encoded)
    mime_type: str = "audio/wav"
    source: Source


DocType = Literal["pod", "upi_screenshot"]


class DocExtractResponse(BaseModel):
    doc_type: DocType  # CONTRACT
    extracted_fields: dict[str, Any]  # CONTRACT
    confidence: float  # CONTRACT (0..1, see confidence.py for how it is computed)
    warnings: list[str] = []
    source: Source


class LLMRequest(BaseModel):
    system_prompt: str = ""  # CONTRACT
    user_prompt: str = Field(..., min_length=1)  # CONTRACT
    response_format: Literal["text", "json"] = "text"  # CONTRACT
    # Optional, additive knobs:
    json_schema: Optional[dict[str, Any]] = None  # enforce an exact JSON shape (needs response_format="json")
    temperature: Optional[float] = Field(None, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, ge=1, le=8000)


class LLMResponse(BaseModel):
    reply: str  # CONTRACT (always a string; for json it is the JSON text)
    parsed: Optional[Any] = None  # for response_format="json": the reply already parsed
    model: Optional[str] = None
    source: Source
