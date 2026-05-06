"""Tests for app/deepgram/stt.py — DeepgramSTT plugin.

The Deepgram SDK is the only thing mocked; everything else exercises
real plugin code (queue plumbing, callback wiring, options building).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.stt.base import TranscriptEvent


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """Every test needs the api key set so _api_key() doesn't raise."""
    from app.config import settings
    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")


@pytest.fixture
def fake_deepgram_client(monkeypatch):
    """Replace DeepgramClient inside app.deepgram.stt with a fake."""
    fake_conn = AsyncMock()
    fake_conn.send = AsyncMock()
    fake_conn.finish = AsyncMock()
    fake_conn.start = AsyncMock(return_value=True)
    fake_conn._handlers = {}

    def fake_on(event, handler):
        fake_conn._handlers[event] = handler

    fake_conn.on = MagicMock(side_effect=fake_on)

    fake_listen = MagicMock()
    fake_listen.asynclive.v = MagicMock(return_value=fake_conn)
    fake_client = MagicMock()
    fake_client.listen = fake_listen

    monkeypatch.setattr(
        "app.deepgram.stt.DeepgramClient",
        MagicMock(return_value=fake_client),
    )
    return fake_conn


@pytest.mark.asyncio
async def test_open_starts_connection_with_configured_options(
    fake_deepgram_client, monkeypatch,
):
    from app.config import settings
    from app.deepgram.stt import DeepgramSTT

    monkeypatch.setattr(settings, "stt_model", "nova-3")
    monkeypatch.setattr(settings, "stt_endpointing_ms", 600)
    monkeypatch.setattr(settings, "stt_utterance_end_ms", 1200)
    monkeypatch.setattr(settings, "stt_keyterms", "tikka,naan")

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()

    fake_deepgram_client.start.assert_awaited_once()
    options = fake_deepgram_client.start.await_args.args[0]
    assert options.model == "nova-3"
    assert options.endpointing == 600
    assert options.utterance_end_ms == 1200
    assert options.keyterm == ["tikka", "naan"]
    assert options.encoding == "mulaw"
    assert options.sample_rate == 8000


@pytest.mark.asyncio
async def test_keyterms_empty_string_yields_none(fake_deepgram_client, monkeypatch):
    from app.config import settings
    from app.deepgram.stt import DeepgramSTT

    monkeypatch.setattr(settings, "stt_keyterms", "")

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()

    options = fake_deepgram_client.start.await_args.args[0]
    assert options.keyterm is None


@pytest.mark.asyncio
async def test_open_raises_when_start_returns_false(fake_deepgram_client):
    from app.deepgram.stt import DeepgramSTT

    fake_deepgram_client.start = AsyncMock(return_value=False)
    stt = DeepgramSTT(call_sid="CAtest")
    with pytest.raises(RuntimeError, match="failed to start"):
        await stt.open()


@pytest.mark.asyncio
async def test_open_raises_when_api_key_missing(monkeypatch, fake_deepgram_client):
    from app.config import settings
    from app.deepgram.stt import DeepgramSTT

    monkeypatch.setattr(settings, "deepgram_api_key", None)
    stt = DeepgramSTT(call_sid="CAtest")
    with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY not set"):
        await stt.open()


@pytest.mark.asyncio
async def test_send_forwards_audio_to_sdk(fake_deepgram_client):
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    await stt.send(b"\x01\x02\x03")

    fake_deepgram_client.send.assert_awaited_once_with(b"\x01\x02\x03")


@pytest.mark.asyncio
async def test_send_swallows_sdk_exceptions(fake_deepgram_client, caplog):
    import logging
    from app.deepgram.stt import DeepgramSTT

    fake_deepgram_client.send = AsyncMock(side_effect=RuntimeError("dropped"))
    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()

    with caplog.at_level(logging.ERROR, logger="app.deepgram.stt"):
        await stt.send(b"x")

    assert any(
        "deepgram send failed" in rec.message for rec in caplog.records
    ), "expected the swallowed-error log line"


@pytest.mark.asyncio
async def test_transcript_callback_emits_events_in_order(fake_deepgram_client):
    from deepgram import LiveTranscriptionEvents
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()

    handler = fake_deepgram_client._handlers[LiveTranscriptionEvents.Transcript]

    def make_result(text: str, is_final: bool, confidence: float):
        alt = SimpleNamespace(transcript=text, confidence=confidence)
        channel = SimpleNamespace(alternatives=[alt])
        return SimpleNamespace(channel=channel, is_final=is_final)

    await handler(stt, make_result("hi", False, 0.7))
    await handler(stt, make_result("hello", True, 0.95))

    received = []
    async def consume():
        async for event in stt.events():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await stt.close()
    await task

    assert received == [
        TranscriptEvent("hi", False, 0.7),
        TranscriptEvent("hello", True, 0.95),
    ]


@pytest.mark.asyncio
async def test_transcript_callback_skips_empty_text(fake_deepgram_client):
    from deepgram import LiveTranscriptionEvents
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    handler = fake_deepgram_client._handlers[LiveTranscriptionEvents.Transcript]

    alt = SimpleNamespace(transcript="   ", confidence=0.9)
    result = SimpleNamespace(
        channel=SimpleNamespace(alternatives=[alt]),
        is_final=True,
    )
    await handler(stt, result)

    received = []
    async def consume():
        async for event in stt.events():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await stt.close()
    await task

    assert received == []


@pytest.mark.asyncio
async def test_transcript_callback_normalizes_none_confidence(fake_deepgram_client):
    """Deepgram occasionally returns confidence=None; we replace with 1.0
    rather than 0.0 (which would mask worst-case misheard turns)."""
    from deepgram import LiveTranscriptionEvents
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    handler = fake_deepgram_client._handlers[LiveTranscriptionEvents.Transcript]

    alt = SimpleNamespace(transcript="ok", confidence=None)
    result = SimpleNamespace(
        channel=SimpleNamespace(alternatives=[alt]),
        is_final=True,
    )
    await handler(stt, result)

    received = []
    async def consume():
        async for event in stt.events():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await stt.close()
    await task

    assert len(received) == 1
    assert received[0].confidence == 1.0


@pytest.mark.asyncio
async def test_error_callback_surfaces_as_exception_from_events(fake_deepgram_client):
    from deepgram import LiveTranscriptionEvents
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    handler = fake_deepgram_client._handlers[LiveTranscriptionEvents.Error]
    await handler(stt, "ws closed unexpectedly")

    with pytest.raises(RuntimeError, match="deepgram error"):
        async for _event in stt.events():
            pass


@pytest.mark.asyncio
async def test_close_terminates_events_iterator(fake_deepgram_client):
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    await stt.close()

    received = []
    async for event in stt.events():
        received.append(event)
    assert received == []
    fake_deepgram_client.finish.assert_awaited_once()


@pytest.mark.asyncio
async def test_speech_started_callback_emits_event(fake_deepgram_client):
    """Deepgram's SpeechStarted event becomes a SpeechStartedEvent on
    the queue.

    The live Deepgram SDK invokes the SpeechStarted callback with just
    the connection handle — NO second positional argument — unlike the
    Transcript and Error callbacks which both receive a payload. We
    invoke the handler the same way here (single positional arg) so a
    regression that removes the `= None` default on _event is caught
    by tests instead of by a real call (call CA061e6bf3 on 2026-05-06
    crashed for exactly this reason)."""
    from deepgram import LiveTranscriptionEvents
    from app.deepgram.stt import DeepgramSTT
    from app.stt.base import SpeechStartedEvent

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    handler = fake_deepgram_client._handlers[
        LiveTranscriptionEvents.SpeechStarted
    ]
    # Mirror the live SDK: single positional arg (the connection handle).
    await handler(stt)

    received = []

    async def consume():
        async for event in stt.events():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await stt.close()
    await task

    assert received == [SpeechStartedEvent()]
