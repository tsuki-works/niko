"""Live ElevenLabs integration test for speak().

Skipped when ELEVENLABS_API_KEY is absent so CI never calls the real API.
Run locally with your key in .env to verify the full round-trip.

Usage:
    pytest tests/test_tts_integration.py -v -s
    pytest tests/test_tts_integration.py -v -s --phrase "Hi, welcome to Niko's Pizza!"

Audio is saved to tts_test_output.wav (mulaw) or tts_test_output.mp3 (free tier).
"""
import base64
import struct
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.tts.client import speak

pytestmark = pytest.mark.skipif(
    not settings.elevenlabs_api_key,
    reason="ELEVENLABS_API_KEY not set — skipping live ElevenLabs test",
)

# G.711 mu-law decode table (ITU-T, matches CPython audioop implementation).
_EXP_LUT = [0, 132, 396, 924, 1980, 4092, 8316, 16764]


def _mulaw_to_pcm16(mulaw_data: bytes) -> bytes:
    out = bytearray(len(mulaw_data) * 2)
    for i, ulaw in enumerate(mulaw_data):
        ulaw = ~ulaw & 0xFF
        sign = ulaw & 0x80
        exp = (ulaw >> 4) & 0x07
        mant = ulaw & 0x0F
        sample = _EXP_LUT[exp] + (mant << (exp + 3))
        if sign:
            sample = -sample
        struct.pack_into("<h", out, i * 2, sample)
    return bytes(out)


def _save_audio(audio_bytes: bytes) -> Path:
    """Save audio to the right format based on what ElevenLabs actually returned."""
    if audio_bytes[:3] == b"ID3" or audio_bytes[:2] == b"\xff\xfb":
        # Free tier returns MP3 regardless of requested ulaw_8000 format
        path = Path("tts_test_output.mp3")
        path.write_bytes(audio_bytes)
        return path

    import wave
    path = Path("tts_test_output.wav")
    pcm = _mulaw_to_pcm16(audio_bytes)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(pcm)
    return path


async def test_speak_returns_audio_chunks(tts_phrase):
    """Real ElevenLabs call — audio saved to tts_test_output.wav or .mp3."""
    received: list[dict] = []

    ws = AsyncMock()
    ws.send_json = AsyncMock(side_effect=lambda msg: received.append(msg))

    print(f"\nPhrase: {tts_phrase!r}")

    await speak(tts_phrase, ws, stream_sid="TEST-STREAM-SID")

    assert len(received) > 0, "Expected at least one media event from ElevenLabs"

    for event in received:
        assert event["event"] == "media"
        assert event["streamSid"] == "TEST-STREAM-SID"
        assert len(base64.b64decode(event["media"]["payload"])) > 0

    audio_bytes = b"".join(
        base64.b64decode(e["media"]["payload"]) for e in received
    )
    output_path = _save_audio(audio_bytes)

    print(f"Chunks received : {len(received)}")
    print(f"Total audio     : {len(audio_bytes):,} bytes")
    print(f"Saved to        : {output_path.resolve()}")
