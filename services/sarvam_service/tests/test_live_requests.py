"""Live mode against a faked api.sarvam.ai: checks the exact requests we send and how we
handle Sarvam's responses and failures. No real key or network needed."""
import json

import httpx
import respx

from app.audio import tone_wav_base64

BASE = "https://api.sarvam.ai"


@respx.mock
def test_stt_sends_key_model_and_autodetect(live_client, wav_bytes):
    route = respx.post(f"{BASE}/speech-to-text").mock(return_value=httpx.Response(
        200, json={"request_id": "r1", "transcript": "मेरा पैसा कहाँ है", "language_code": "hi-IN", "language_probability": 0.97}))
    r = live_client.post("/stt", files={"audio": ("v.webm", wav_bytes, "audio/webm")})
    assert r.status_code == 200
    assert r.json() == {"transcript": "मेरा पैसा कहाँ है", "language_code": "hi-IN", "language_probability": 0.97, "source": "sarvam"}
    req = route.calls.last.request
    assert req.headers["api-subscription-key"] == "sk_test"
    body = req.content.decode(errors="ignore")
    assert 'name="model"' in body and "saaras:v3" in body
    assert 'name="language_code"' in body and "unknown" in body
    assert 'name="mode"' in body and "codemix" in body


@respx.mock
def test_tts_uses_v3_priya_with_language_code_first(live_client):
    clip = tone_wav_base64(0.1)
    route = respx.post(f"{BASE}/text-to-speech").mock(return_value=httpx.Response(200, json={"audios": [clip]}))
    r = live_client.post("/tts", json={"text": "नमस्ते", "language_code": "hi-IN"})
    assert r.status_code == 200 and r.json()["audio_base64"] == clip
    sent = json.loads(route.calls.last.request.content)
    assert len(route.calls) == 1  # no wasted round trip
    assert sent["model"] == "bulbul:v3" and sent["language_code"] == "hi-IN"
    assert sent["speaker"] == "priya"


@respx.mock
def test_v4_model_drops_v3_voice_name(monkeypatch):
    from conftest import _use_settings
    from fastapi.testclient import TestClient
    from app import main

    _use_settings(monkeypatch, SARVAM_MODE="live", SARVAM_API_KEY="sk_test", SARVAM_FALLBACK_TO_MOCK="false",
                  SARVAM_TTS_MODEL="bulbul:v4-flash", SARVAM_TTS_SPEAKER="priya")
    route = respx.post(f"{BASE}/text-to-speech").mock(return_value=httpx.Response(200, json={"audios": [tone_wav_base64(0.1)]}))
    TestClient(main.app).post("/tts", json={"text": "नमस्ते", "language_code": "hi-IN"})
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "bulbul:v4-flash" and "speaker" not in sent  # 'priya' would be a 400 on v4


@respx.mock
def test_tts_falls_back_to_v3_then_old_field_and_remembers(monkeypatch):
    from conftest import _use_settings
    from fastapi.testclient import TestClient
    from app import main

    _use_settings(monkeypatch, SARVAM_MODE="live", SARVAM_API_KEY="sk_test", SARVAM_FALLBACK_TO_MOCK="false",
                  SARVAM_TTS_MODEL="bulbul:v4-flash")
    live_client = TestClient(main.app)
    clip = tone_wav_base64(0.1)
    route = respx.post(f"{BASE}/text-to-speech").mock(side_effect=[
        httpx.Response(400, json={"error": {"message": "model not available"}}),   # v4 rejected
        httpx.Response(422, json={"error": {"message": "language_code not allowed"}}),  # v3 + new field rejected
        httpx.Response(200, json={"audios": [clip]}),                                # v3 + old field works
        httpx.Response(200, json={"audios": [clip]}),                                # next call
    ])
    assert live_client.post("/tts", json={"text": "नमस्ते", "language_code": "hi-IN"}).status_code == 200
    a, b, c = (json.loads(x.request.content) for x in route.calls)
    assert a["model"] == "bulbul:v4-flash"
    assert b["model"] == "bulbul:v3" and b["speaker"] == "priya" and "language_code" in b
    assert c["model"] == "bulbul:v3" and c["target_language_code"] == "hi-IN"
    # the working combination is remembered: the next call goes straight to it
    live_client.post("/tts", json={"text": "फिर से", "language_code": "hi-IN"})
    assert len(route.calls) == 4
    assert json.loads(route.calls[3].request.content)["target_language_code"] == "hi-IN"


@respx.mock
def test_tts_long_text_is_chunked_and_merged(live_client):
    route = respx.post(f"{BASE}/text-to-speech").mock(
        return_value=httpx.Response(200, json={"audios": [tone_wav_base64(0.1)]}))
    long_text = "यह एक लंबा वाक्य है। " * 300  # ~6,000 chars -> 3 chunks
    r = live_client.post("/tts", json={"text": long_text, "language_code": "hi-IN"})
    assert r.status_code == 200
    assert len(route.calls) == 3
    assert all(len(json.loads(c.request.content)["text"]) <= 2500 for c in route.calls)


@respx.mock
def test_llm_json_mode_and_think_stripping(live_client):
    route = respx.post(f"{BASE}/v1/chat/completions").mock(return_value=httpx.Response(200, json={
        "model": "sarvam-105b",
        "choices": [{"message": {"role": "assistant",
                                 "content": "<think>reasoning</think>```json\n{\"intent\": \"REFUND_MANAGE\"}\n```"}}]}))
    r = live_client.post("/llm", json={"system_prompt": "Classify", "user_prompt": "refund?", "response_format": "json"})
    assert r.status_code == 200
    assert r.json()["parsed"] == {"intent": "REFUND_MANAGE"}
    req = route.calls.last.request
    sent = json.loads(req.content)
    assert req.headers["authorization"] == "Bearer sk_test"
    assert sent["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" in sent and sent["reasoning_effort"] is None  # reasoning off = fast
    assert sent["messages"][0] == {"role": "system", "content": "Classify"}


@respx.mock
def test_llm_retries_once_on_429_then_succeeds(live_client):
    route = respx.post(f"{BASE}/v1/chat/completions").mock(side_effect=[
        httpx.Response(429, json={"error": {"message": "slow down"}}),
        httpx.Response(200, json={"choices": [{"message": {"content": "theek hai"}}]}),
    ])
    r = live_client.post("/llm", json={"user_prompt": "hi", "response_format": "text"})
    assert r.status_code == 200 and r.json()["reply"] == "theek hai"
    assert len(route.calls) == 2


@respx.mock
def test_llm_strict_schema_falls_back_to_json_object(live_client):
    route = respx.post(f"{BASE}/v1/chat/completions").mock(side_effect=[
        httpx.Response(400, json={"error": {"message": "schema not supported"}}),
        httpx.Response(200, json={"choices": [{"message": {"content": "{\"intent\": \"UTR_VERIFY\"}"}}]}),
    ])
    schema = {"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]}
    r = live_client.post("/llm", json={"user_prompt": "x", "response_format": "json", "json_schema": schema})
    assert r.json()["parsed"] == {"intent": "UTR_VERIFY"}
    first, second = (json.loads(c.request.content) for c in route.calls)
    assert first["response_format"]["type"] == "json_schema"
    assert second["response_format"] == {"type": "json_object"}


@respx.mock
def test_doc_extract_full_job_flow_with_image(live_client, png_bytes):
    submit = respx.post(f"{BASE}/doc-ai/v1/job/extract").mock(
        return_value=httpx.Response(200, json={"job_id": "job1", "status": "pending"}))
    respx.get(f"{BASE}/doc-ai/v1/job/job1/status").mock(side_effect=[
        httpx.Response(200, json={"status": "running"}),
        httpx.Response(200, json={"status": "completed"}),
    ])
    respx.get(f"{BASE}/doc-ai/v1/job/job1/results").mock(return_value=httpx.Response(200, json={
        "result": {"utr": "6321 8492 0111", "amount": "₹1,250.00", "status": "Successful", "payer_app": "GPay"}}))

    r = live_client.post("/doc-extract", files={"file": ("shot.png", png_bytes, "image/png")},
                         data={"doc_type": "upi_screenshot"})
    body = r.json()
    assert r.status_code == 200
    assert body["extracted_fields"] == {"utr": "632184920111", "amount": 1250, "status": "SUCCESS", "payer_app": "GPay"}
    assert body["confidence"] == 1.0 and body["source"] == "sarvam"

    sent = submit.calls.last.request.content
    assert b"%PDF-" in sent  # PNG was wrapped into a PDF
    assert b'name="schema"' in sent and b"utr" in sent

    # second identical upload is served from cache: no new job
    live_client.post("/doc-extract", files={"file": ("shot.png", png_bytes, "image/png")}, data={"doc_type": "upi_screenshot"})
    assert submit.call_count == 1


@respx.mock
def test_doc_extract_flags_bad_utr_and_missing_fields(live_client, png_bytes):
    respx.post(f"{BASE}/doc-ai/v1/job/extract").mock(return_value=httpx.Response(200, json={"job_id": "j2"}))
    respx.get(f"{BASE}/doc-ai/v1/job/j2/status").mock(return_value=httpx.Response(200, json={"status": "completed"}))
    respx.get(f"{BASE}/doc-ai/v1/job/j2/results").mock(return_value=httpx.Response(200, json={"result": {"utr": "12345", "amount": 500}}))
    body = live_client.post("/doc-extract", files={"file": ("s.png", png_bytes, "image/png")},
                            data={"doc_type": "upi_screenshot"}).json()
    assert any("not 12 digits" in w for w in body["warnings"])
    assert any("Could not read: status" in w for w in body["warnings"])
    assert body["confidence"] < 0.7


@respx.mock
def test_failed_job_returns_502_without_fallback(live_client, png_bytes):
    respx.post(f"{BASE}/doc-ai/v1/job/extract").mock(return_value=httpx.Response(200, json={"job_id": "j3"}))
    respx.get(f"{BASE}/doc-ai/v1/job/j3/status").mock(return_value=httpx.Response(200, json={"status": "failed"}))
    r = live_client.post("/doc-extract", files={"file": ("s.png", png_bytes, "image/png")}, data={"doc_type": "pod"})
    assert r.status_code == 502


@respx.mock
def test_outage_falls_back_to_mock_when_enabled(live_fallback_client, wav_bytes):
    respx.post(f"{BASE}/speech-to-text").mock(return_value=httpx.Response(503))
    r = live_fallback_client.post("/stt", files={"audio": ("v.wav", wav_bytes, "audio/wav")})
    assert r.status_code == 200 and r.json()["source"] == "mock"
