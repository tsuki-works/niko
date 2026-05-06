"""Tests for _consume_transcripts in app/telephony/router.py.

The consumer is the router's bridge between the STT plugin and call
state. We feed scripted events into a FakeSTT and assert state changes,
Firestore emissions, and dispatch into _handle_final_transcript.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.stt.base import SpeechStartedEvent, TranscriptEvent
from app.telephony.router import _CallState, _consume_transcripts
from tests.fakes.stt import FakeSTT


def _make_state() -> _CallState:
    state = _CallState(websocket=AsyncMock())
    state.call_sid = "CAtest"
    state.stream_sid = "MZ1"
    return state


@pytest.mark.asyncio
async def test_interim_transcripts_ignored(monkeypatch):
    """Interims arrive on the queue but cause no state mutation, no
    Firestore call, no _handle_final_transcript dispatch."""
    state = _make_state()
    handler = AsyncMock()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", handler
    )
    bg = MagicMock()
    monkeypatch.setattr("app.telephony.router._bg_call_event", bg)

    fake = FakeSTT(events=[TranscriptEvent("partial", False, 0.7)])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    handler.assert_not_called()
    bg.assert_not_called()
    assert state.last_caller_transcript == ""


@pytest.mark.asyncio
async def test_final_transcript_mutates_state_and_dispatches(monkeypatch):
    state = _make_state()
    handler = AsyncMock()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", handler
    )
    bg = MagicMock()
    monkeypatch.setattr("app.telephony.router._bg_call_event", bg)

    ws = AsyncMock()
    fake = FakeSTT(events=[TranscriptEvent("two pizzas", True, 0.9)])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, ws))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert state.last_caller_transcript == "two pizzas"
    handler.assert_awaited_once_with("two pizzas", state, ws)
    bg.assert_called_once()
    args, kwargs = bg.call_args
    assert kwargs["kind"] == "transcript_final"


@pytest.mark.asyncio
async def test_low_confidence_increments_counter(monkeypatch):
    state = _make_state()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", AsyncMock()
    )
    monkeypatch.setattr("app.telephony.router._bg_call_event", MagicMock())

    fake = FakeSTT(events=[
        TranscriptEvent("muffled", True, 0.3),
        TranscriptEvent("still muffled", True, 0.4),
        # 0.0 boundary case — guards against any future "or 1.0" regression
        # in the confidence-handling path.
        TranscriptEvent("zero confidence", True, 0.0),
    ])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert state.consecutive_low_confidence_turns == 3


@pytest.mark.asyncio
async def test_high_confidence_resets_counter(monkeypatch):
    state = _make_state()
    state.consecutive_low_confidence_turns = 3
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", AsyncMock()
    )
    monkeypatch.setattr("app.telephony.router._bg_call_event", MagicMock())

    fake = FakeSTT(events=[TranscriptEvent("clear", True, 0.95)])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert state.consecutive_low_confidence_turns == 0


@pytest.mark.asyncio
async def test_speech_started_currently_ignored(monkeypatch):
    """Until α-7 wires VAD-triggered barge-in, SpeechStartedEvents are
    silently dropped by the consumer."""
    state = _make_state()
    handler = AsyncMock()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", handler
    )

    fake = FakeSTT(events=[SpeechStartedEvent()])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    handler.assert_not_called()


@pytest.mark.asyncio
async def test_consumer_logs_and_exits_on_stt_error(monkeypatch, caplog):
    import logging

    state = _make_state()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", AsyncMock()
    )
    bg = MagicMock()
    monkeypatch.setattr("app.telephony.router._bg_call_event", bg)

    fake = FakeSTT()
    await fake.open()
    fake.feed_error(RuntimeError("dropped"))

    with caplog.at_level(logging.ERROR, logger="app.telephony.router"):
        # Consumer catches the exception and exits cleanly.
        await _consume_transcripts(fake, state, AsyncMock())

    assert any(
        "transcript consumer crashed" in rec.message for rec in caplog.records
    ), "expected the consumer's crash log line"
    # Mid-call STT crash should also surface as a transfer signal and a
    # dashboard event, so it isn't invisible.
    assert state.llm_error_occurred is True
    error_calls = [c for c in bg.call_args_list if c.kwargs.get("kind") == "error"]
    assert error_calls, "expected an error Firestore event on consumer crash"


@pytest.mark.asyncio
async def test_consumer_propagates_cancellation(monkeypatch):
    state = _make_state()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", AsyncMock()
    )

    fake = FakeSTT()
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
