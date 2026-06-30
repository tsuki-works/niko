"""Unit tests for the greeting playback path (#192).

``_play_greeting`` replaces the cold T1 LLM call. It picks one of the
restaurant's hand-written greetings (or a hardcoded fallback template),
streams it via Aura, seeds conversation history so the caller's first
real turn (T2) has context, and arms the silence watchdog once Twilio
confirms the greeting audio has played out (#178).

These tests stub ``speak`` so the suite stays offline; the audio path
itself is exercised by ``tests/test_deepgram_tts.py``.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.restaurants.models import Restaurant
from app.telephony import session as session_module
from app.telephony.session import GREETING_TRANSCRIPT, _CallState, _play_greeting


def _restaurant_with(greetings: list[str]) -> Restaurant:
    return Restaurant(
        id="twilight",
        name="Twilight Family Restaurant",
        display_phone="+1",
        twilio_phone="+1",
        address="-",
        hours="-",
        greetings=greetings,
    )


@pytest.fixture
def fake_speak():
    with patch.object(session_module, "speak", new=AsyncMock()) as m:
        yield m


@pytest.fixture
async def state() -> _CallState:
    s = _CallState()
    s.call_sid = "CAtest"
    s.stream_sid = "MZtest"
    yield s
    # _play_greeting defers arming the silence watchdog behind a turn-end
    # mark echo (#178); cancel both the deferred-arm fallback and any armed
    # watchdog inside the event loop so neither dangles into "Task was
    # destroyed" warning territory.
    for task in (s.silence_arm_task, s.silence_task):
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.asyncio
async def test_play_greeting_speaks_from_greetings_list_when_populated(
    state, fake_speak, monkeypatch
):
    state.restaurant = _restaurant_with(["A", "B", "C"])
    monkeypatch.setattr(session_module.random, "choice", lambda seq: "B")
    await _play_greeting(state, websocket=AsyncMock())
    assert fake_speak.await_count == 1
    spoken_text = fake_speak.await_args.args[0]
    assert spoken_text == "B"


@pytest.mark.asyncio
async def test_play_greeting_uses_default_template_when_greetings_empty(state, fake_speak):
    state.restaurant = _restaurant_with([])
    await _play_greeting(state, websocket=AsyncMock())
    spoken_text = fake_speak.await_args.args[0]
    assert spoken_text == ("Hi, thanks for calling Twilight Family Restaurant. How can I help you?")


@pytest.mark.asyncio
async def test_play_greeting_seeds_history_for_t2_context(state, fake_speak, monkeypatch):
    """T2 fires with the caller's first real transcript. Without a seeded
    history Claude sees no prior turn and may behave like the call just
    started — confusing when the caller is already responding."""
    state.restaurant = _restaurant_with(["Hi there."])
    monkeypatch.setattr(session_module.random, "choice", lambda seq: "Hi there.")
    await _play_greeting(state, websocket=AsyncMock())
    assert state.history == [
        {"role": "user", "content": GREETING_TRANSCRIPT},
        {"role": "assistant", "content": [{"type": "text", "text": "Hi there."}]},
    ]


@pytest.mark.asyncio
async def test_play_greeting_swallows_speak_failure(state, caplog):
    state.restaurant = _restaurant_with([])
    failing = AsyncMock(side_effect=RuntimeError("aura down"))
    with patch.object(session_module, "speak", new=failing):
        with caplog.at_level("WARNING", logger="app.telephony.session"):
            await _play_greeting(state, websocket=AsyncMock())
    assert any("greeting: speak failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_play_greeting_defers_silence_watchdog_to_mark_echo(state, fake_speak):
    """If the caller stays silent after the greeting, the 'are you still
    there?' prompt must still fire — but the watchdog is armed only once
    Twilio echoes the turn-end mark (greeting audio played out), not at
    byte-send (#178). So right after _play_greeting it is deferred, and the
    mark echo arms it."""
    from app.telephony.session import TURN_END_MARK, _handle_mark_echo

    state.restaurant = _restaurant_with(["Hi there."])
    ws = AsyncMock()
    await _play_greeting(state, websocket=ws)

    # Deferred: not armed yet, but a turn-end mark was sent and we're waiting.
    assert state.silence_task is None
    assert state.silence_arm_pending is True
    sent = [c.args[0] for c in ws.send_json.call_args_list]
    assert any(
        m.get("event") == "mark" and m.get("mark", {}).get("name") == TURN_END_MARK for m in sent
    )

    # Twilio echoes the greeting's turn-end mark → watchdog arms.
    _handle_mark_echo(state, ws, TURN_END_MARK)
    assert state.silence_task is not None


@pytest.mark.asyncio
async def test_play_greeting_logs_source(state, fake_speak, caplog):
    state.restaurant = _restaurant_with([])
    with caplog.at_level("INFO", logger="app.telephony.session"):
        await _play_greeting(state, websocket=AsyncMock())
    msgs = " ".join(r.message for r in caplog.records)
    assert "greeting_played" in msgs
    assert "source=default_template" in msgs

    state.restaurant = _restaurant_with(["Hi there."])
    caplog.clear()
    with caplog.at_level("INFO", logger="app.telephony.session"):
        await _play_greeting(state, websocket=AsyncMock())
    msgs = " ".join(r.message for r in caplog.records)
    assert "source=greetings_list" in msgs
