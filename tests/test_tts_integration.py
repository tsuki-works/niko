"""Live ElevenLabs integration test for speak().

Skipped when ELEVENLABS_API_KEY is absent so CI never calls the real API.
Run locally with your key in .env to verify the full round-trip.

Usage:
    pytest tests/test_tts_integration.py -v -s
"""
import base64
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.tts.client import speak

pytestmark = pytest.mark.skipif(
    not settings.elevenlabs_api_key,
    reason="ELEVENLABS_API_KEY not set — skipping live ElevenLabs test",
)


@pytest.mark.asyncio
async def test_speak_returns_audio_chunks():
    """Real ElevenLabs call produces at least one valid base64 mulaw chunk."""
    received: list[dict] = []

    ws = AsyncMock()
    ws.send_json = AsyncMock(side_effect=lambda msg: received.append(msg))

    await speak(
        "Your order is one large pepperoni pizza for pickup. Does that sound right?",
        ws,
        stream_sid="TEST-STREAM-SID",
    )

    assert len(received) > 0, "Expected at least one media event from ElevenLabs"

    for event in received:
        assert event["event"] == "media"
        assert event["streamSid"] == "TEST-STREAM-SID"
        payload = event["media"]["payload"]
        # Valid base64 decodes without error
        decoded = base64.b64decode(payload)
        assert len(decoded) > 0
