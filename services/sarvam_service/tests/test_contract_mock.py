"""Mock mode: every endpoint returns exactly the shape contract.md promises."""
import base64
import json
import wave
import io


def test_health(mock_client):
    r = mock_client.get("/health")
    assert r.status_code == 200
    assert r.json()["mode"] == "mock"


def test_stt_contract(mock_client, wav_bytes):
    r = mock_client.post("/stt", files={"audio": ("note.wav", wav_bytes, "audio/wav")})
    assert r.status_code == 200
    body = r.json()
    assert set(["transcript", "language_code"]) <= body.keys()
    assert body["language_code"] == "hi-IN"
    assert body["source"] == "mock"


def test_stt_mock_transcript_override(mock_client, wav_bytes):
    r = mock_client.post("/stt", files={"audio": ("n.wav", wav_bytes, "audio/wav")},
                         data={"mock_transcript": "Is UTR 632184920111 real?"})
    assert r.json()["transcript"] == "Is UTR 632184920111 real?"
    assert r.json()["language_code"] == "en-IN"
    r = mock_client.post("/stt", files={"audio": ("n.wav", wav_bytes, "audio/wav")},
                         data={"mock_transcript": "Bhaiya ye payment aaya kya?"})
    assert r.json()["language_code"] == "hi-IN"  # romanised Hinglish is still Hindi


def test_stt_rejects_empty(mock_client):
    r = mock_client.post("/stt", files={"audio": ("n.wav", b"", "audio/wav")})
    assert r.status_code == 400


def test_tts_contract_returns_playable_wav(mock_client):
    r = mock_client.post("/tts", json={"text": "Aapka ₹95,840 kal credit hua", "language_code": "hi-IN"})
    assert r.status_code == 200
    audio = base64.b64decode(r.json()["audio_base64"])
    with wave.open(io.BytesIO(audio)) as w:
        assert w.getnframes() > 0


def test_tts_default_language_and_bad_language(mock_client):
    assert mock_client.post("/tts", json={"text": "hello"}).status_code == 200
    assert mock_client.post("/tts", json={"text": "hello", "language_code": "xx-YY"}).status_code == 422


def test_doc_extract_upi_matches_seed(mock_client, png_bytes):
    r = mock_client.post("/doc-extract", files={"file": ("upi.png", png_bytes, "image/png")},
                         data={"doc_type": "upi_screenshot"})
    body = r.json()
    assert r.status_code == 200
    assert body["doc_type"] == "upi_screenshot"
    assert body["extracted_fields"]["utr"] == "632184920111"
    assert body["extracted_fields"]["amount"] == 1250
    assert body["confidence"] == 1.0


def test_doc_extract_fake_and_pending_scenarios(mock_client, png_bytes):
    fake = mock_client.post("/doc-extract", files={"file": ("upi_fake.png", png_bytes, "image/png")},
                            data={"doc_type": "upi_screenshot"}).json()
    pending = mock_client.post("/doc-extract", files={"file": ("upi_pending.png", png_bytes, "image/png")},
                               data={"doc_type": "upi_screenshot"}).json()
    assert fake["extracted_fields"]["utr"] == "632184920555"  # unknown to the ledger -> suspected fake
    assert pending["extracted_fields"]["utr"] == "632184920999"


def test_doc_extract_pod(mock_client, png_bytes):
    body = mock_client.post("/doc-extract", files={"file": ("pod.jpg", png_bytes, "image/jpeg")},
                            data={"doc_type": "pod"}).json()
    assert body["extracted_fields"]["order_id"] == "9981"
    assert body["extracted_fields"]["signature_present"] is True


def test_doc_extract_bad_type(mock_client, png_bytes):
    r = mock_client.post("/doc-extract", files={"file": ("x.png", png_bytes, "image/png")}, data={"doc_type": "aadhaar"})
    assert r.status_code == 422


def test_llm_text_and_json(mock_client):
    t = mock_client.post("/llm", json={"system_prompt": "s", "user_prompt": "refund kab aayega", "response_format": "text"})
    assert t.status_code == 200 and isinstance(t.json()["reply"], str)

    j = mock_client.post("/llm", json={"system_prompt": "s", "user_prompt": "GST kyun kata?", "response_format": "json"})
    body = j.json()
    assert json.loads(body["reply"]) == body["parsed"]
    assert body["parsed"]["intent"] == "FEE_GST_LOAN"
