"""Live ElevenLabs integration test for speak().

Skipped when ELEVENLABS_API_KEY is absent so CI never calls the real API.
Run locally with your key in .env to verify the full round-trip.

Usage:
    pytest tests/test_tts_integration.py -v -s
    pytest tests/test_tts_integration.py -v -s --phrase "Hi, welcome to Niko's Pizza!"

Audio is saved to tts_test_output.wav — double-click to play in any media player.
"""
import array
import base64
import wave
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.tts.client import speak

pytestmark = pytest.mark.skipif(
    not settings.elevenlabs_api_key,
    reason="ELEVENLABS_API_KEY not set — skipping live ElevenLabs test",
)

OUTPUT_FILE = Path("tts_test_output.wav")


def _mulaw_to_pcm16(mulaw_data: bytes) -> bytes:
    """Decode mu-law bytes to 16-bit signed PCM (ITU-T G.711)."""
    samples = array.array("h")
    for byte in mulaw_data:
        byte = ~byte & 0xFF
        sign = byte & 0x80
        exponent = (byte >> 4) & 0x07
        mantissa = byte & 0x0F
        sample = (((mantissa << 3) + 0x84) << exponent) - 0x84
        samples.append(-sample if sign else sample)
    return samples.tobytes()


def _write_wav(mulaw_data: bytes, path: Path) -> None:
    pcm = _mulaw_to_pcm16(mulaw_data)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)   # 16-bit
        wf.setframerate(8000)
        wf.writeframes(pcm)


async def test_speak_returns_audio_chunks(tts_phrase):
    """Real ElevenLabs call — audio saved to tts_test_output.wav."""
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
    _write_wav(audio_bytes, OUTPUT_FILE)

    print(f"Chunks received : {len(received)}")
    print(f"Total audio     : {len(audio_bytes):,} bytes")
    print(f"Saved to        : {OUTPUT_FILE.resolve()}")
