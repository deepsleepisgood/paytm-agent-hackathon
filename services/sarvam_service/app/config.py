"""Runtime configuration, read once from environment variables (or a .env file).

Why env vars: the same code runs on every teammate's laptop and in the demo. Nobody
edits Python to switch from mock to live Sarvam; they change one line in .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default_factory=lambda: os.getenv("SARVAM_API_KEY", "").strip())
    base_url: str = field(default_factory=lambda: os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai").rstrip("/"))

    # mode: "live" = always call Sarvam, "mock" = never call Sarvam,
    # "auto" = live when a key is present, otherwise mock.
    # MOCK_MODE=true (the name plan.md uses) is a shortcut for SARVAM_MODE=mock.
    mode: str = field(default_factory=lambda: "mock" if _bool("MOCK_MODE", False)
                      else os.getenv("SARVAM_MODE", "auto").strip().lower())
    # In live mode, if Sarvam errors/times out, answer from mock instead of failing.
    # Keep this ON for the demo, OFF while you are debugging the live integration.
    fallback_to_mock: bool = field(default_factory=lambda: _bool("SARVAM_FALLBACK_TO_MOCK", True))

    # Models (all overridable so a Sarvam model rename never needs a code change)
    stt_model: str = field(default_factory=lambda: os.getenv("SARVAM_STT_MODEL", "saaras:v3"))
    # codemix keeps English words ("settlement", "UPI") in Latin script inside Hindi text,
    # which is how merchants actually talk (plan.md: Saaras v3 codemix).
    stt_mode: str = field(default_factory=lambda: os.getenv("SARVAM_STT_MODE", "codemix"))
    # Bulbul v3 + "priya": picked by ear in testing. v4-flash's default voice
    # (shubh_enhi_ads) is an advertising style that sounded wrong for a support assistant.
    # v4 voices are named <name>_<lang>_<style> if you want to try one again.
    tts_model: str = field(default_factory=lambda: os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"))
    tts_speaker: str = field(default_factory=lambda: os.getenv("SARVAM_TTS_SPEAKER", "priya").strip())
    # If the primary voice model is rejected, retry once with this known-good pair.
    tts_fallback_model: str = field(default_factory=lambda: os.getenv("SARVAM_TTS_FALLBACK_MODEL", "bulbul:v3"))
    tts_fallback_speaker: str = field(default_factory=lambda: os.getenv("SARVAM_TTS_FALLBACK_SPEAKER", "priya"))
    tts_sample_rate: int = field(default_factory=lambda: int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "22050")))
    llm_model: str = field(default_factory=lambda: os.getenv("SARVAM_LLM_MODEL", "sarvam-105b"))
    # "none" turns reasoning off (fastest). Intent classification and rephrasing don't need
    # reasoning, and callers (Person 3) give us ~6 s, so speed wins by default.
    llm_reasoning_effort: str = field(default_factory=lambda: os.getenv("SARVAM_LLM_REASONING_EFFORT", "none"))
    llm_max_tokens: int = field(default_factory=lambda: int(os.getenv("SARVAM_LLM_MAX_TOKENS", "800")))

    # Latency budgets (seconds). If Sarvam hasn't answered by then we stop waiting and
    # (with fallback on) answer from mock, so the CALLER never hits its own timeout.
    # Person 3 calls us with a 6 s timeout, so stt/tts/llm must answer in < 6 s.
    latency_budget: float = field(default_factory=lambda: float(os.getenv("SARVAM_LATENCY_BUDGET", "5.0")))
    # Doc AI is an async job (submit -> poll -> fetch) and is slower; callers must use a longer timeout.
    doc_latency_budget: float = field(default_factory=lambda: float(os.getenv("SARVAM_DOC_LATENCY_BUDGET", "25")))

    # Timeouts (seconds)
    http_timeout: float = field(default_factory=lambda: float(os.getenv("SARVAM_HTTP_TIMEOUT", "30")))
    doc_job_timeout: float = field(default_factory=lambda: float(os.getenv("SARVAM_DOC_JOB_TIMEOUT", "60")))
    doc_poll_interval: float = field(default_factory=lambda: float(os.getenv("SARVAM_DOC_POLL_INTERVAL", "2")))

    # Upload limits
    max_audio_bytes: int = 10 * 1024 * 1024
    max_doc_bytes: int = 15 * 1024 * 1024

    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()
        )
    )

    @property
    def use_live(self) -> bool:
        if self.mode == "mock":
            return False
        if self.mode == "live":
            return True
        return bool(self.api_key)  # auto


settings = Settings()
