"""Live ElevenLabs integration test for speak().

Skipped when ELEVENLABS_API_KEY is absent so CI never calls the real API.
Run locally with your key in .env to verify the full round-trip.

Usage:
    pytest tests/test_tts_integration.py -v -s
    pytest tests/test_tts_integration.py -v -s --phrase "Hi, welcome to Niko's Pizza!"

Audio is saved to tts_test_output.wav — double-click to play in any media player.
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

OUTPUT_FILE = Path("tts_test_output.wav")


def _write_mulaw_wav(data: bytes, path: Path) -> None:
    """Wrap raw mulaw 8 kHz mono audio in a WAV container.

    Uses WAVE_FORMAT_MULAW (7) so the file plays in any media player
    without transcoding. No third-party libraries needed.
    """
    sample_rate = 8000
    num_channels = 1
    bits_per_sample = 8
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8

    # fmt chunk: 18 bytes (MULAW requires the cbSize extension field)
    fmt = struct.pack(
        "<HHIIHH",
        7,              # wFormatTag: WAVE_FORMAT_MULAW
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
    ) + struct.pack("<H", 0)  # cbSize

    # fact chunk: number of samples (required for compressed formats)
    fact = struct.pack("<I", len(data))

    riff_size = 4 + (8 + len(fmt)) + (8 + 4) + (8 + len(data))

    with path.open("wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", riff_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", len(fmt)))
        f.write(fmt)
        f.write(b"fact")
        f.write(struct.pack("<I", 4))
        f.write(fact)
        f.write(b"data")
        f.write(struct.pack("<I", len(data)))
        f.write(data)


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
    _write_mulaw_wav(audio_bytes, OUTPUT_FILE)

    print(f"Chunks received : {len(received)}")
    print(f"Total audio     : {len(audio_bytes):,} bytes")
    print(f"Saved to        : {OUTPUT_FILE.resolve()}")
