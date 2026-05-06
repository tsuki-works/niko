"""Tests for _barge_in_now() — the helper that stops the bot mid-utterance.

The helper itself does not emit a Firestore event; the event is emitted
by _run_llm_tts_turn's CancelledError handler when the cancellation we
trigger here actually propagates. These tests verify the mechanical
steps (task cancel, watchdog cancel, Twilio clear, trigger field set).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.telephony.router import _CallState, _barge_in_now


@pytest.mark.asyncio
async def test_cancels_running_llm_task():
    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZ1"
    async def long_task():
        await asyncio.sleep(60)
    state.llm_task = asyncio.create_task(long_task())

    ws = AsyncMock()
    await _barge_in_now(state, ws, trigger="vad")
    await asyncio.sleep(0)  # let cancellation propagate

    assert state.llm_task.cancelled()


@pytest.mark.asyncio
async def test_skips_task_cancel_when_no_llm_task():
    """Without a running task, the helper still cancels the silence
    watchdog and flushes Twilio's buffer — but does NOT set
    barge_in_trigger (preventing stale trigger from leaking into a
    later real barge-in's CancelledError handler)."""
    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZ1"
    state.llm_task = None
    state.barge_in_trigger = None
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    await _barge_in_now(state, ws, trigger="vad")

    ws.send_json.assert_awaited_once_with({"event": "clear", "streamSid": "MZ1"})
    assert state.barge_in_trigger is None  # NOT set — no task to cancel


@pytest.mark.asyncio
async def test_cancels_silence_task():
    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZ1"
    async def long_silence():
        await asyncio.sleep(60)
    state.silence_task = asyncio.create_task(long_silence())

    ws = AsyncMock()
    ws.send_json = AsyncMock()
    await _barge_in_now(state, ws, trigger="vad")
    await asyncio.sleep(0)
    assert state.silence_task is None


@pytest.mark.asyncio
async def test_sends_twilio_clear_event():
    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZabc"
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    await _barge_in_now(state, ws, trigger="vad")
    ws.send_json.assert_awaited_once_with(
        {"event": "clear", "streamSid": "MZabc"}
    )


@pytest.mark.asyncio
async def test_sets_barge_in_trigger_on_state_when_task_running():
    """Trigger is set when there's actually a task to cancel."""
    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZ1"

    async def long_task():
        await asyncio.sleep(60)

    state.llm_task = asyncio.create_task(long_task())
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    await _barge_in_now(state, ws, trigger="final_transcript")
    assert state.barge_in_trigger == "final_transcript"

    # Let the cancellation propagate so the task is collected cleanly.
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_does_not_set_trigger_when_no_task_to_cancel():
    """If _barge_in_now is called repeatedly with no task in flight, the
    trigger field stays None — preventing stale values from leaking into
    a future real barge-in's CancelledError handler."""
    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZ1"
    state.llm_task = None
    state.barge_in_trigger = None
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    await _barge_in_now(state, ws, trigger="vad")
    assert state.barge_in_trigger is None

    await _barge_in_now(state, ws, trigger="final_transcript")
    assert state.barge_in_trigger is None


@pytest.mark.asyncio
async def test_swallows_websocket_disconnect_during_clear():
    """If the caller already hung up, sending clear raises but we must
    not let that exception escape into the call loop."""
    from starlette.websockets import WebSocketDisconnect

    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZ1"
    ws = AsyncMock()
    ws.send_json = AsyncMock(side_effect=WebSocketDisconnect())
    # No exception escapes is the assertion.
    await _barge_in_now(state, ws, trigger="vad")
