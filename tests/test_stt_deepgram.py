"""Tests for app/deepgram/stt.py — DeepgramSTT plugin (Flux v2).

The Deepgram SDK is the only thing mocked; everything else exercises
real plugin code (queue plumbing, event translation, lifecycle).
Tests stub the v2 connect path so we never hit a network — translation
correctness is the contract this file pins.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.stt.base import (
    EarlyTurnEndEvent,
    SpeechStartedEvent,
    TranscriptEvent,
    TurnResumedEvent,
)


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """Every test needs the api key set so _api_key() doesn't raise."""
    from app.config import settings

    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")


def _make_turn_info(*, event: str, transcript: str = "", confidence: float = 0.95):
    """Build a real ListenV2TurnInfo. Constructing the SDK's pydantic
    model rather than ducking it with a MagicMock makes isinstance
    checks inside the translator behave like production."""
    from deepgram.listen.v2.types import (
        ListenV2TurnInfo,
        ListenV2TurnInfoWordsItem,
    )

    words = (
        [
            ListenV2TurnInfoWordsItem(word=w, confidence=confidence)
            for w in transcript.split()
        ]
        if transcript
        else []
    )
    return ListenV2TurnInfo(
        request_id="req-test",
        sequence_id=0,
        event=event,
        turn_index=0,
        audio_window_start=0.0,
        audio_window_end=1.0,
        transcript=transcript,
        words=words,
        end_of_turn_confidence=confidence,
    )


@pytest.fixture
def fake_v2_connection(monkeypatch):
    """Replace AsyncDeepgramClient inside app.deepgram.stt with a fake
    whose listen.v2.connect(...) returns an async-context-manager that
    yields a connection mock with controllable recv()/send_media()."""
    fake_conn = AsyncMock()
    fake_conn.send_media = AsyncMock()
    fake_conn.send_close_stream = AsyncMock()
    fake_conn._recv_queue: asyncio.Queue = asyncio.Queue()

    async def fake_recv():
        return await fake_conn._recv_queue.get()

    fake_conn.recv = fake_recv

    fake_cm = AsyncMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_cm.__aexit__ = AsyncMock(return_value=None)

    fake_v2 = MagicMock()
    fake_v2.connect = MagicMock(return_value=fake_cm)
    fake_listen = MagicMock()
    fake_listen.v2 = fake_v2
    fake_client = MagicMock()
    fake_client.listen = fake_listen

    monkeypatch.setattr(
        "app.deepgram.stt.AsyncDeepgramClient",
        MagicMock(return_value=fake_client),
    )
    # Expose the connect mock so tests can introspect call args.
    fake_conn._connect_mock = fake_v2.connect
    return fake_conn


@pytest.mark.asyncio
async def test_open_calls_v2_connect_with_configured_options(
    fake_v2_connection, monkeypatch
):
    from app.config import settings
    from app.deepgram.stt import DeepgramSTT

    monkeypatch.setattr(settings, "stt_model", "flux-general-en")
    monkeypatch.setattr(settings, "stt_keyterms", "")  # no env override

    stt = DeepgramSTT(
        call_sid="CAtest",
        keyterms=["Twilight Family Restaurant", "Pepper Shrimp"],
    )
    await stt.open()
    try:
        connect_call = fake_v2_connection._connect_mock.call_args
        assert connect_call.kwargs["model"] == "flux-general-en"
        assert connect_call.kwargs["encoding"] == "mulaw"
        assert connect_call.kwargs["sample_rate"] == 8000
        assert connect_call.kwargs["keyterm"] == [
            "Twilight Family Restaurant",
            "Pepper Shrimp",
        ]
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_env_keyterms_override_replaces_constructor_list(
    fake_v2_connection, monkeypatch
):
    from app.config import settings
    from app.deepgram.stt import DeepgramSTT

    monkeypatch.setattr(settings, "stt_keyterms", "alpha, beta , gamma")

    stt = DeepgramSTT(
        call_sid="CAtest", keyterms=["Twilight", "Pepper Shrimp"]
    )
    await stt.open()
    try:
        kwargs = fake_v2_connection._connect_mock.call_args.kwargs
        assert kwargs["keyterm"] == ["alpha", "beta", "gamma"]
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_no_keyterms_passes_none(fake_v2_connection, monkeypatch):
    from app.config import settings
    from app.deepgram.stt import DeepgramSTT

    monkeypatch.setattr(settings, "stt_keyterms", "")

    stt = DeepgramSTT(call_sid="CAtest")  # no keyterms arg
    await stt.open()
    try:
        kwargs = fake_v2_connection._connect_mock.call_args.kwargs
        assert kwargs["keyterm"] is None
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_open_raises_when_api_key_missing(monkeypatch, fake_v2_connection):
    from app.config import settings
    from app.deepgram.stt import DeepgramSTT

    monkeypatch.setattr(settings, "deepgram_api_key", None)
    stt = DeepgramSTT(call_sid="CAtest")
    with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY not set"):
        await stt.open()


@pytest.mark.asyncio
async def test_send_forwards_audio_to_send_media(fake_v2_connection):
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    try:
        await stt.send(b"\x01\x02\x03")
        fake_v2_connection.send_media.assert_awaited_once_with(b"\x01\x02\x03")
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_send_swallows_sdk_exceptions(fake_v2_connection, caplog):
    import logging

    from app.deepgram.stt import DeepgramSTT

    fake_v2_connection.send_media = AsyncMock(
        side_effect=RuntimeError("dropped")
    )
    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    try:
        with caplog.at_level(logging.ERROR, logger="app.deepgram.stt"):
            await stt.send(b"x")
        assert any(
            "deepgram send failed" in rec.message for rec in caplog.records
        ), "expected the swallowed-error log line"
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_translates_start_of_turn_to_speech_started(
    fake_v2_connection
):
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    try:
        fake_v2_connection._recv_queue.put_nowait(
            _make_turn_info(event="StartOfTurn")
        )
        # Drain one event then close.
        ev = await _next_event(stt)
        assert isinstance(ev, SpeechStartedEvent)
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_translates_update_to_interim_transcript(
    fake_v2_connection
):
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    try:
        fake_v2_connection._recv_queue.put_nowait(
            _make_turn_info(event="Update", transcript="hi there", confidence=0.8)
        )
        ev = await _next_event(stt)
        assert isinstance(ev, TranscriptEvent)
        assert ev.text == "hi there"
        assert ev.is_final is False
        assert ev.confidence == pytest.approx(0.8)
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_translates_eager_end_of_turn(fake_v2_connection):
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    try:
        fake_v2_connection._recv_queue.put_nowait(
            _make_turn_info(event="EagerEndOfTurn")
        )
        ev = await _next_event(stt)
        assert isinstance(ev, EarlyTurnEndEvent)
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_translates_turn_resumed(fake_v2_connection):
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    try:
        fake_v2_connection._recv_queue.put_nowait(
            _make_turn_info(event="TurnResumed")
        )
        ev = await _next_event(stt)
        assert isinstance(ev, TurnResumedEvent)
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_translates_end_of_turn_to_final_transcript(
    fake_v2_connection
):
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    try:
        fake_v2_connection._recv_queue.put_nowait(
            _make_turn_info(
                event="EndOfTurn", transcript="hello world", confidence=0.92
            )
        )
        ev = await _next_event(stt)
        assert isinstance(ev, TranscriptEvent)
        assert ev.text == "hello world"
        assert ev.is_final is True
        assert ev.confidence == pytest.approx(0.92)
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_update_with_empty_transcript_is_dropped(
    fake_v2_connection
):
    """Flux occasionally sends 'Update' with an empty transcript on
    barge-in or noise — translator drops them so downstream interim
    handling doesn't see phantom ''."""
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    try:
        fake_v2_connection._recv_queue.put_nowait(
            _make_turn_info(event="Update", transcript="")
        )
        # Followed by something we DO expect, so the consumer wakes up.
        fake_v2_connection._recv_queue.put_nowait(
            _make_turn_info(event="StartOfTurn")
        )
        ev = await _next_event(stt)
        assert isinstance(ev, SpeechStartedEvent)
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_unknown_turn_info_event_is_ignored(
    fake_v2_connection
):
    """A future Flux release adding a new event type must not crash
    a live call. Translator drops unknowns and continues."""
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    try:
        fake_v2_connection._recv_queue.put_nowait(
            _make_turn_info(event="SomeFutureEvent")
        )
        fake_v2_connection._recv_queue.put_nowait(
            _make_turn_info(event="StartOfTurn")
        )
        ev = await _next_event(stt)
        assert isinstance(ev, SpeechStartedEvent)
    finally:
        await stt.close()


@pytest.mark.asyncio
async def test_close_terminates_events_iterator(fake_v2_connection):
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    await stt.close()

    received = []
    async for event in stt.events():
        received.append(event)
    assert received == []
    fake_v2_connection.send_close_stream.assert_awaited()


@pytest.mark.asyncio
async def test_recv_exception_surfaces_as_runtime_error(fake_v2_connection):
    """If the SDK's recv() raises (e.g. WS dropped mid-call), the
    error should surface from events() so the consumer can react.
    Errors aren't silently swallowed — that would feel like dead air
    to whoever's debugging the call."""
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    fake_v2_connection.recv = AsyncMock(side_effect=RuntimeError("ws dropped"))

    await stt.open()
    try:
        with pytest.raises(RuntimeError, match="deepgram error"):
            async for _ev in stt.events():
                pass
    finally:
        await stt.close()


# Helpers ----------------------------------------------------------------


async def _next_event(stt: Any):
    """Drain a single event from stt.events() without leaving the
    iterator open. Tests use this to assert one-event-per-input."""
    event_iter = stt.events()
    # asyncio.wait_for guards against the consumer hanging when a test
    # has misconfigured the recv queue.
    return await asyncio.wait_for(event_iter.__anext__(), timeout=1.0)
