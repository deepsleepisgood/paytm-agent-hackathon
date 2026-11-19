"""Small audio/text helpers for TTS (standard library only)."""
from __future__ import annotations

import base64
import io
import math
import re
import struct
import wave

TTS_CHAR_LIMIT = 2400  # Bulbul v3 accepts 2,500 characters; keep a safety margin


def chunk_text(text: str, limit: int = TTS_CHAR_LIMIT) -> list[str]:
    """Split long text on sentence boundaries (incl. Hindi danda) so each chunk fits one TTS call."""
    text = text.strip()
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?।])\s+", text)
    chunks, current = [], ""
    for sentence in sentences:
        while len(sentence) > limit:  # a single giant sentence: hard split
            chunks.append(sentence[:limit])
            sentence = sentence[limit:]
        if len(current) + len(sentence) + 1 > limit:
            if current:
                chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def merge_wav_base64(parts: list[str]) -> str:
    """Join several base64 WAV clips into one WAV (same format assumed, as Sarvam returns)."""
    if len(parts) == 1:
        return parts[0]
    frames, params = [], None
    for part in parts:
        with wave.open(io.BytesIO(base64.b64decode(part)), "rb") as w:
            params = params or w.getparams()
            frames.append(w.readframes(w.getnframes()))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setparams(params)
        for f in frames:
            out.writeframes(f)
    return base64.b64encode(buf.getvalue()).decode()


def tone_wav_base64(seconds: float = 0.6, freq: float = 660.0, rate: int = 22050) -> str:
    """A short soft beep. Used by mock TTS so the frontend audio player has something real to play."""
    n = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        fade = int(0.05 * rate)
        samples = bytearray()
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade)
            samples += struct.pack("<h", int(6000 * env * math.sin(2 * math.pi * freq * i / rate)))
        w.writeframes(bytes(samples))
    return base64.b64encode(buf.getvalue()).decode()
