"""Live smoke test: run AFTER starting the service with a real SARVAM_API_KEY.

    python scripts/smoke_live.py            # talks to http://localhost:8001

It needs no audio or image files: it makes Sarvam speak a Hindi sentence (TTS), feeds
that audio back into STT (round trip), renders a plain test image for /doc-extract,
and asks the LLM to classify an intent. Each line prints PASS/FAIL, latency and source.
"""
from __future__ import annotations

import base64
import io
import sys
import time

import httpx
from PIL import Image, ImageDraw

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"
results: list[bool] = []


def check(name: str, ok: bool, detail: str, started: float) -> None:
    ms = int((time.perf_counter() - started) * 1000)
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name:<12} {ms:>6} ms  {detail}")


def test_image() -> bytes:
    img = Image.new("RGB", (720, 1000), "white")
    d = ImageDraw.Draw(img)
    lines = ["SAMPLE TEST IMAGE - NOT A REAL RECEIPT", "", "Payment Successful", "Rs 1,250",
             "Paid to Sharma Electronics", "UPI transaction ID: 632184920111", "18 Nov 2026, 11:03 am", "App: GPay"]
    for i, line in enumerate(lines):
        d.text((40, 60 + i * 60), line, fill="black", font_size=32)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


with httpx.Client(base_url=BASE, timeout=90) as c:
    health = c.get("/health").json()
    print(f"Service mode: {health['mode']}  key configured: {health['api_key_configured']}\n")
    if health["mode"] != "live":
        print("Service is in MOCK mode. Set SARVAM_API_KEY in .env and restart to test live.")

    t = time.perf_counter()
    r = c.post("/tts", json={"text": "नमस्ते, आपका कल का settlement पंचानवे हज़ार आठ सौ चालीस रुपये आपके बैंक में आ गया है।",
                             "language_code": "hi-IN"})
    tts = r.json() if r.status_code == 200 else {}
    check("/tts", r.status_code == 200 and tts.get("source") == "sarvam",
          f"source={tts.get('source')} bytes={len(base64.b64decode(tts.get('audio_base64', '')))}", t)

    if tts:
        t = time.perf_counter()
        r = c.post("/stt", files={"audio": ("roundtrip.wav", base64.b64decode(tts["audio_base64"]), "audio/wav")})
        stt = r.json() if r.status_code == 200 else {}
        check("/stt", r.status_code == 200 and stt.get("source") == "sarvam",
              f"lang={stt.get('language_code')} transcript={stt.get('transcript', r.text)[:70]!r}", t)

    t = time.perf_counter()
    r = c.post("/llm", json={
        "system_prompt": "Classify the merchant message into one intent: SETTLEMENT_RECONCILE, UTR_VERIFY, "
                         "CHARGEBACK_RESOLVE, REFUND_MANAGE, FEE_GST_LOAN, ESCALATE_HUMAN. "
                         'Reply as JSON: {"intent": "...", "reason": "..."}',
        "user_prompt": "Bhaiya mere settlement mein 261 rupaye GST kyun kata?",
        "response_format": "json"})
    llm = r.json() if r.status_code == 200 else {}
    check("/llm", r.status_code == 200 and llm.get("source") == "sarvam",
          f"parsed={llm.get('parsed') or r.text[:120]}", t)

    t = time.perf_counter()
    r = c.post("/doc-extract", files={"file": ("sample_upi.png", test_image(), "image/png")},
               data={"doc_type": "upi_screenshot"})
    doc = r.json() if r.status_code == 200 else {}
    check("/doc-extract", r.status_code == 200 and doc.get("source") == "sarvam",
          f"fields={doc.get('extracted_fields') or r.text[:120]} conf={doc.get('confidence')} warnings={doc.get('warnings')}", t)

    t = time.perf_counter()
    r = c.post("/doc-extract", data={"doc_type": "pod", "use_sample_connector": "true"})
    pod = r.json() if r.status_code == 200 else {}
    f = pod.get("extracted_fields", {})
    check("/doc-extract", r.status_code == 200 and pod.get("source") == "sarvam" and f.get("order_id") == "9981",
          f"[sample PoD via {pod.get('connector', {}).get('name')}] order={f.get('order_id')} "
          f"amt={f.get('amount')} delivered={f.get('delivery_date')} to={f.get('recipient_name')} "
          f"signed={f.get('signature_present')} conf={pod.get('confidence')}", t)

print(f"\n{sum(results)}/{len(results)} live checks passed")
sys.exit(0 if all(results) else 1)
