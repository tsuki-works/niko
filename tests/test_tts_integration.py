"""Live ElevenLabs integration test for speak().

Skipped when ELEVENLABS_API_KEY is absent so CI never calls the real API.
Run locally with your key in .env to verify the full round-trip.

Usage:
    pytest tests/test_tts_integration.py -v -s
    pytest tests/test_tts_integration.py -v -s --phrase "Hi, welcome to Niko's Pizza!"

Audio is saved to tts_test_output.raw after each run.
Play it back with:
    ffplay -f mulaw -ar 8000 -ac 1 tts_test_output.raw
"""
import base64
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.tts.client import speak

pytestmark = pytest.mark.skipif(
    not settings.elevenlabs_api_key,
    reason="ELEVENLABS_API_KEY not set — skipping live ElevenLabs test",
)

OUTPUT_FILE = Path("tts_test_output.raw")


async def test_speak_returns_audio_chunks(tts_phrase):
    """Real ElevenLabs call produces audio saved to tts_test_output.raw."""
    received: list[dict] = []

    ws = AsyncMock()
    ws.send_json = AsyncMock(side_effect=lambda msg: received.append(msg))

    print(f"\nPhrase: {tts_phrase!r}")

    await speak(tts_phrase, ws, stream_sid="TEST-STREAM-SID")

    assert len(received) > 0, "Expected at least one media event from ElevenLabs"

    for event in received:
        assert event["event"] == "media"
        assert event["streamSid"] == "TEST-STREAM-SID"
        decoded = base64.b64decode(event["media"]["payload"])
        assert len(decoded) > 0

    audio_bytes = b"".join(
        base64.b64decode(e["media"]["payload"]) for e in received
    )
    OUTPUT_FILE.write_bytes(audio_bytes)

    print(f"Chunks received: {len(received)}")
    print(f"Total audio: {len(audio_bytes):,} bytes")
    print(f"Saved to: {OUTPUT_FILE.resolve()}")
    print(f"Play with: ffplay -f mulaw -ar 8000 -ac 1 {OUTPUT_FILE}")
