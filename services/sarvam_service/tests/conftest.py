import base64
import io
import os

import pytest
from fastapi.testclient import TestClient

from app import config, main, sarvam_client
from app.audio import tone_wav_base64


def _use_settings(monkeypatch, **env):
    for k in ["SARVAM_API_KEY", "SARVAM_MODE", "SARVAM_FALLBACK_TO_MOCK", "SARVAM_DOC_POLL_INTERVAL", "SARVAM_LATENCY_BUDGET",
              "MOCK_MODE", "SARVAM_STT_MODE", "SARVAM_TTS_MODEL", "SARVAM_TTS_SPEAKER"]:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    s = config.Settings()
    for mod in (config, main, sarvam_client):
        monkeypatch.setattr(mod, "settings", s)
    main._doc_cache.clear()
    main._sample_tasks.clear()
    monkeypatch.setattr(sarvam_client, "_tts_variant", None)
    return s


@pytest.fixture
def mock_client(monkeypatch):
    _use_settings(monkeypatch, SARVAM_MODE="mock")
    return TestClient(main.app)


@pytest.fixture
def live_client(monkeypatch):
    _use_settings(monkeypatch, SARVAM_MODE="live", SARVAM_API_KEY="sk_test", SARVAM_FALLBACK_TO_MOCK="false",
                  SARVAM_DOC_POLL_INTERVAL="0")
    monkeypatch.setattr(sarvam_client.asyncio, "sleep", _no_sleep)
    return TestClient(main.app)


@pytest.fixture
def live_fallback_client(monkeypatch):
    _use_settings(monkeypatch, SARVAM_MODE="live", SARVAM_API_KEY="sk_test", SARVAM_FALLBACK_TO_MOCK="true")
    monkeypatch.setattr(sarvam_client.asyncio, "sleep", _no_sleep)
    return TestClient(main.app)


async def _no_sleep(_):
    return None


@pytest.fixture
def wav_bytes():
    return base64.b64decode(tone_wav_base64(0.2))


@pytest.fixture
def png_bytes():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (40, 80), (255, 255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()
