"""Tests for _consume_transcripts in app/telephony/session.py.

The consumer is the session's bridge between the STT plugin and call
state. We feed scripted events into a FakeSTT and assert state changes,
Firestore emissions, and dispatch into _handle_final_transcript.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.stt.base import SpeechStartedEvent, TranscriptEvent
from app.telephony.session import _CallState, _consume_transcripts
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
        "app.telephony.session._handle_final_transcript", handler
    )
    bg = MagicMock()
    monkeypatch.setattr("app.telephony.session._bg_call_event", bg)

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
        "app.telephony.session._handle_final_transcript", handler
    )
    bg = MagicMock()
    monkeypatch.setattr("app.telephony.session._bg_call_event", bg)

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
        "app.telephony.session._handle_final_transcript", AsyncMock()
    )
    monkeypatch.setattr("app.telephony.session._bg_call_event", MagicMock())

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
        "app.telephony.session._handle_final_transcript", AsyncMock()
    )
    monkeypatch.setattr("app.telephony.session._bg_call_event", MagicMock())

    fake = FakeSTT(events=[TranscriptEvent("clear", True, 0.95)])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert state.consecutive_low_confidence_turns == 0


@pytest.mark.asyncio
async def test_speech_started_triggers_barge_in_when_llm_task_running(monkeypatch):
    """VAD speech-started while a turn is in flight fires _barge_in_now
    with trigger='vad'."""
    state = _make_state()

    async def long_turn():
        await asyncio.sleep(60)

    state.llm_task = asyncio.create_task(long_turn())

    barge_in_calls: list[str] = []

    async def fake_barge(state_, ws_, *, trigger):
        barge_in_calls.append(trigger)

    monkeypatch.setattr("app.telephony.session._barge_in_now", fake_barge)

    fake = FakeSTT(events=[SpeechStartedEvent()])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert barge_in_calls == ["vad"]

    # Cleanup
    state.llm_task.cancel()
    try:
        await state.llm_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_speech_started_no_op_when_no_llm_task(monkeypatch):
    """VAD with no in-flight turn does nothing — there's nothing to
    barge in on."""
    state = _make_state()
    state.llm_task = None

    barge_in_calls: list[str] = []

    async def fake_barge(state_, ws_, *, trigger):
        barge_in_calls.append(trigger)

    monkeypatch.setattr("app.telephony.session._barge_in_now", fake_barge)

    fake = FakeSTT(events=[SpeechStartedEvent()])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert barge_in_calls == []


@pytest.mark.asyncio
async def test_speech_started_disabled_by_setting(monkeypatch):
    """When STT_INSTANT_BARGE_IN is False, VAD events are ignored even
    with a turn in flight — caller falls back to final-transcript-driven
    barge-in."""
    from app.config import settings

    monkeypatch.setattr(settings, "stt_instant_barge_in", False)
    state = _make_state()

    async def long_turn():
        await asyncio.sleep(60)

    state.llm_task = asyncio.create_task(long_turn())

    barge_in_calls: list[str] = []

    async def fake_barge(state_, ws_, *, trigger):
        barge_in_calls.append(trigger)

    monkeypatch.setattr("app.telephony.session._barge_in_now", fake_barge)

    fake = FakeSTT(events=[SpeechStartedEvent()])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert barge_in_calls == []

    # Cleanup
    state.llm_task.cancel()
    try:
        await state.llm_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_consumer_logs_and_exits_on_stt_error(monkeypatch, caplog):
    import logging

    state = _make_state()
    monkeypatch.setattr(
        "app.telephony.session._handle_final_transcript", AsyncMock()
    )
    bg = MagicMock()
    monkeypatch.setattr("app.telephony.session._bg_call_event", bg)

    fake = FakeSTT()
    await fake.open()
    fake.feed_error(RuntimeError("dropped"))

    with caplog.at_level(logging.ERROR, logger="app.telephony.session"):
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
        "app.telephony.session._handle_final_transcript", AsyncMock()
    )

    fake = FakeSTT()
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_vad_then_final_transcript_creates_one_barge_in_then_new_turn(
    monkeypatch,
):
    """The realistic production interleaving: VAD fires (instant
    barge-in), then the caller's final transcript arrives. The consumer
    should call _barge_in_now exactly once for the VAD event and dispatch
    _handle_final_transcript exactly once for the final. Pins that the
    consumer keeps iterating after a VAD event (would catch a future
    refactor that turned `continue` into `return`)."""
    state = _make_state()

    async def long_turn():
        await asyncio.sleep(60)

    state.llm_task = asyncio.create_task(long_turn())

    barge_in_calls: list[str] = []

    async def fake_barge(state_, ws_, *, trigger):
        barge_in_calls.append(trigger)

    monkeypatch.setattr("app.telephony.session._barge_in_now", fake_barge)

    handler = AsyncMock()
    monkeypatch.setattr(
        "app.telephony.session._handle_final_transcript", handler
    )
    monkeypatch.setattr("app.telephony.session._bg_call_event", MagicMock())

    fake = FakeSTT(
        events=[
            SpeechStartedEvent(),
            TranscriptEvent("two pizzas", True, 0.95),
        ]
    )
    await fake.open()
    ws = AsyncMock()
    task = asyncio.create_task(_consume_transcripts(fake, state, ws))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert barge_in_calls == ["vad"]
    handler.assert_awaited_once_with("two pizzas", state, ws)

    # Cleanup
    state.llm_task.cancel()
    try:
        await state.llm_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_kill_switch_off_still_processes_final_transcripts(monkeypatch):
    """When STT_INSTANT_BARGE_IN is False, the consumer skips VAD events
    but must continue iterating to handle the final transcript that
    follows. Guards against a future refactor that turned the kill-switch
    `continue` into a `return`."""
    from app.config import settings

    monkeypatch.setattr(settings, "stt_instant_barge_in", False)
    state = _make_state()

    barge_in_calls: list[str] = []

    async def fake_barge(state_, ws_, *, trigger):
        barge_in_calls.append(trigger)

    monkeypatch.setattr("app.telephony.session._barge_in_now", fake_barge)

    handler = AsyncMock()
    monkeypatch.setattr(
        "app.telephony.session._handle_final_transcript", handler
    )
    monkeypatch.setattr("app.telephony.session._bg_call_event", MagicMock())

    fake = FakeSTT(
        events=[
            SpeechStartedEvent(),
            TranscriptEvent("hello", True, 0.95),
        ]
    )
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert barge_in_calls == []  # VAD ignored
    handler.assert_awaited_once()  # but final still flowed through
    assert handler.await_args.args[0] == "hello"


@pytest.mark.asyncio
async def test_early_turn_end_event_is_dropped(monkeypatch):
    """EarlyTurnEndEvent flows from the Flux provider; this PR does
    not consume it (speculative drafting is a future PR). The consumer
    must silently drop it — no barge-in, no Firestore, no LLM dispatch."""
    from app.stt.base import EarlyTurnEndEvent

    state = _make_state()
    monkeypatch.setattr("app.telephony.session._barge_in_now", AsyncMock())
    handler = AsyncMock()
    monkeypatch.setattr(
        "app.telephony.session._handle_final_transcript", handler
    )
    bg = MagicMock()
    monkeypatch.setattr("app.telephony.session._bg_call_event", bg)

    fake = FakeSTT(events=[EarlyTurnEndEvent()])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    handler.assert_not_called()
    bg.assert_not_called()


@pytest.mark.asyncio
async def test_turn_resumed_event_is_dropped(monkeypatch):
    """TurnResumedEvent is the cancel signal for the speculative
    draft. Until speculation lands the consumer drops it cleanly."""
    from app.stt.base import TurnResumedEvent

    state = _make_state()
    monkeypatch.setattr("app.telephony.session._barge_in_now", AsyncMock())
    handler = AsyncMock()
    monkeypatch.setattr(
        "app.telephony.session._handle_final_transcript", handler
    )
    bg = MagicMock()
    monkeypatch.setattr("app.telephony.session._bg_call_event", bg)

    fake = FakeSTT(events=[TurnResumedEvent()])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    handler.assert_not_called()
    bg.assert_not_called()


@pytest.mark.asyncio
async def test_speculation_events_interleaved_with_finals_pass_through(
    monkeypatch,
):
    """A real Flux call delivers EarlyTurnEnd and TurnResumed in
    between the SpeechStarted and final TranscriptEvent. The consumer
    must drop the speculative ones and still process the final."""
    from app.stt.base import EarlyTurnEndEvent, TurnResumedEvent

    state = _make_state()
    monkeypatch.setattr("app.telephony.session._barge_in_now", AsyncMock())
    handler = AsyncMock()
    monkeypatch.setattr(
        "app.telephony.session._handle_final_transcript", handler
    )
    monkeypatch.setattr("app.telephony.session._bg_call_event", MagicMock())

    fake = FakeSTT(
        events=[
            SpeechStartedEvent(),
            TranscriptEvent("hi the", False, 0.8),
            EarlyTurnEndEvent(),
            TurnResumedEvent(),
            TranscriptEvent("hi there", True, 0.9),
        ]
    )
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    handler.assert_awaited_once()
    assert handler.await_args.args[0] == "hi there"
