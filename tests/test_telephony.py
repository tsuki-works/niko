"""Tests for Twilio telephony endpoints.

Covers POST /voice (TwiML with Media Stream connect) and
WS /media-stream (Twilio Media Stream receiver).  Runs fully
in-process via TestClient — no Twilio, Deepgram, ElevenLabs, or
Anthropic credentials required.

The mock_pipeline fixture patches all three network-bound callables
(_open_deepgram_connection, speak, stream_reply) so every test is
offline and deterministic.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.llm.client import LLMResponse, StreamEvent
from app.orders.models import Order
from app.storage import restaurants as restaurants_storage
from app.telephony.router import _MIN_CHUNK_CHARS, _should_flush_chunk

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_restaurants_cache():
    """Each /voice request hits the restaurants storage; clear between
    tests so cache state doesn't leak."""
    yield
    restaurants_storage.clear_cache()


# Inbound test number — matches ``demo_restaurant_from_menu().twilio_phone``
# so /voice resolves to the demo via the MENU fallback (Firestore returns
# None under TestClient because GCP isn't reachable).
_DEMO_TO = "+16479058093"

_VOICE_FORM = {"CallSid": "CAtest", "From": "+10000000000", "To": _DEMO_TO}

_START_MSG = {
    "event": "start",
    "start": {
        "callSid": "CAtest123",
        "streamSid": "MZtest456",
        "accountSid": "ACtest",
        "tracks": ["inbound"],
        "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
        "customParameters": {"restaurant_id": "niko-pizza-kitchen"},
    },
}

_MEDIA_MSG = {
    "event": "media",
    "media": {
        "track": "inbound",
        "chunk": "1",
        "timestamp": "5",
        "payload": "AAEC",  # valid base64, 3 bytes of mulaw audio
    },
}

_STOP_MSG = {"event": "stop", "stop": {"accountSid": "ACtest", "callSid": "CAtest123"}}


def _make_fake_stream_reply(reply="Hi, welcome to Niko's Pizza Kitchen!"):
    async def fake_stream_reply(*, transcript, history, order, **kw):
        yield StreamEvent(text_delta=reply)
        yield StreamEvent(
            final=LLMResponse(reply_text=reply, order=order, history=history)
        )

    return fake_stream_reply


@pytest.fixture()
def mock_pipeline(monkeypatch):
    """Patch all four network-bound callables for offline testing."""
    fake_dg = AsyncMock()
    fake_dg.send = AsyncMock()
    fake_dg.finish = AsyncMock()

    async def fake_open_dg(call_sid, restaurant_id, on_final, **kwargs):
        return fake_dg

    async def fake_speak(text, websocket, stream_sid, **kw):
        pass

    # Stub out Firestore writes for the live call_sessions stream so the
    # router never tries to auth to GCP from a unit test (#70).
    from app.storage import call_sessions

    monkeypatch.setattr("app.telephony.router._open_deepgram_connection", fake_open_dg)
    monkeypatch.setattr("app.telephony.router.speak", fake_speak)
    monkeypatch.setattr(
        "app.telephony.router.stream_reply", _make_fake_stream_reply()
    )
    monkeypatch.setattr(call_sessions, "init_call_session", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "record_event", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "mark_call_ended", lambda *a, **kw: None)
    return fake_dg


# ---------------------------------------------------------------------------
# POST /voice
# ---------------------------------------------------------------------------


def test_voice_returns_xml(monkeypatch):
    monkeypatch.setattr(
        restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None
    )
    response = client.post("/voice", data=_VOICE_FORM)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")


def test_voice_twiml_contains_media_stream_no_say(monkeypatch):
    monkeypatch.setattr(
        restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None
    )
    response = client.post("/voice", data=_VOICE_FORM)
    body = response.text
    assert "<Response>" in body
    assert "<Say" not in body          # greeting is now via ElevenLabs on start event
    assert "<Connect" in body
    assert "<Stream" in body
    # TestClient sets Host: testserver
    assert "wss://testserver/media-stream" in body


def test_voice_passes_restaurant_id_as_stream_parameter(monkeypatch):
    """PR B (#79): /voice resolves the tenant by ``To`` and forwards the
    id to /media-stream via a Stream <Parameter>. Twilio echoes it back
    on the start event under ``customParameters.restaurant_id``."""
    monkeypatch.setattr(
        restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None
    )
    response = client.post("/voice", data=_VOICE_FORM)
    body = response.text
    assert "<Parameter" in body
    assert 'name="restaurant_id"' in body
    assert 'value="niko-pizza-kitchen"' in body


def test_voice_stream_omits_track_attribute(monkeypatch):
    """``<Connect><Stream>`` only supports the default ``inbound_track``.
    Passing ``track="both_tracks"`` (or any other non-default value)
    makes Twilio reject the TwiML and drop the call right after the
    trial-account interstitial. To get agent audio into the recording
    we capture TTS bytes inside ``speak()`` instead — see the WS
    handler in the same module."""
    monkeypatch.setattr(
        restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None
    )
    response = client.post("/voice", data=_VOICE_FORM)
    body = response.text
    assert "<Stream " in body
    # Regression guards for both spellings of the bug.
    assert 'track="both_tracks"' not in body
    assert 'tracks="both_tracks"' not in body


def test_voice_uses_firestore_lookup_when_present(monkeypatch):
    """When Firestore has a doc for the dialed number, ``/voice`` uses
    it directly without touching the MENU fallback."""
    from app.restaurants.models import Restaurant

    seeded = Restaurant(
        id="pizza-palace",
        name="Pizza Palace",
        display_phone="+14165550100",
        twilio_phone="+14165550101",
        address="456 Queen St W",
        hours="11am-11pm",
        menu={"pizzas": [], "sides": [], "drinks": []},
    )
    monkeypatch.setattr(
        restaurants_storage,
        "get_restaurant_by_twilio_phone",
        lambda e164: seeded if e164 == "+14165550101" else None,
    )
    response = client.post(
        "/voice",
        data={"CallSid": "CAtest", "From": "+10000000000", "To": "+14165550101"},
    )
    body = response.text
    assert 'value="pizza-palace"' in body


def test_voice_rejects_unmapped_number(monkeypatch):
    """Inbound to a number with no tenant mapping plays a brief hangup
    message instead of dead air."""
    monkeypatch.setattr(
        restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None
    )
    response = client.post(
        "/voice",
        data={"CallSid": "CAtest", "From": "+10000000000", "To": "+19999999999"},
    )
    assert response.status_code == 200
    body = response.text
    assert "<Say" in body
    assert "not currently configured" in body
    assert "<Hangup" in body
    # Crucially: no Connect/Stream — we never opened the media pipeline.
    assert "<Connect" not in body


# ---------------------------------------------------------------------------
# WS /media-stream — basic lifecycle
# ---------------------------------------------------------------------------


def test_media_stream_accepts_connection():
    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps({"event": "stop"}))


def test_media_stream_tolerates_unknown_events():
    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "mark", "mark": {"name": "my_mark"}}))
        ws.send_text(json.dumps({"event": "stop"}))


def test_media_stream_handles_full_call_lifecycle(mock_pipeline):
    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        ws.send_text(json.dumps(_MEDIA_MSG))
        ws.send_text(json.dumps(_STOP_MSG))
    # No exception = handler completed cleanly; Deepgram.finish was called
    mock_pipeline.finish.assert_called_once()


def test_media_stream_begins_recording_on_start(mock_pipeline, monkeypatch):
    """On WS start, after tenant resolution, begin_recording is called
    with the resolved restaurant id and the tenant's retention setting."""
    from app.storage import recordings as recordings_mod
    from app.restaurants.models import Restaurant

    seeded = Restaurant(
        id="niko-pizza-kitchen",
        name="Niko",
        display_phone="+1", twilio_phone=_DEMO_TO,
        address="a", hours="h",
        menu={"pizzas": [], "sides": [], "drinks": []},
        recording_retention_days=42,
    )
    monkeypatch.setattr(
        restaurants_storage, "get_restaurant", lambda _rid: seeded
    )
    monkeypatch.setattr(
        restaurants_storage, "load_or_fallback_demo", lambda _rid: seeded
    )

    captured: list[dict] = []

    def fake_begin(*, call_sid, restaurant_id, retention_days):
        captured.append({
            "call_sid": call_sid,
            "restaurant_id": restaurant_id,
            "retention_days": retention_days,
        })
        return MagicMock(broken=False)

    monkeypatch.setattr(recordings_mod, "begin_recording", fake_begin)
    monkeypatch.setattr(recordings_mod, "append_chunks", lambda *a, **kw: None)
    monkeypatch.setattr(recordings_mod, "finalize_recording", lambda _s: ("", 0))

    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        ws.send_text(json.dumps(_STOP_MSG))

    assert len(captured) == 1
    assert captured[0] == {
        "call_sid": "CAtest123",
        "restaurant_id": "niko-pizza-kitchen",
        "retention_days": 42,
    }


def test_media_stream_dispatches_audio_to_append_chunks(monkeypatch):
    """Each Twilio media event drives append_chunks with the right
    inbound/outbound payloads."""
    from base64 import b64encode
    from app.storage import recordings as recordings_mod

    fake_session = MagicMock(broken=False)
    captured: list[tuple[bytes, bytes]] = []

    monkeypatch.setattr(
        recordings_mod, "begin_recording",
        lambda *, call_sid, restaurant_id, retention_days: fake_session,
    )
    monkeypatch.setattr(
        recordings_mod, "append_chunks",
        lambda session, inbound_mu_law, outbound_mu_law:
            captured.append((inbound_mu_law, outbound_mu_law)),
    )
    monkeypatch.setattr(
        recordings_mod, "finalize_recording", lambda _s: ("", 0),
    )

    fake_dg = AsyncMock()
    fake_dg.send = AsyncMock()
    fake_dg.finish = AsyncMock()

    async def fake_open_dg(call_sid, restaurant_id, on_final, **kwargs):
        return fake_dg

    async def fake_speak(text, websocket, stream_sid, **kw):
        pass

    monkeypatch.setattr("app.telephony.router._open_deepgram_connection", fake_open_dg)
    monkeypatch.setattr("app.telephony.router.speak", fake_speak)
    monkeypatch.setattr(
        "app.telephony.router.stream_reply", _make_fake_stream_reply()
    )
    from app.storage import call_sessions
    monkeypatch.setattr(call_sessions, "init_call_session", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "record_event", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "mark_call_ended", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "mark_recording_ready", lambda *a, **kw: None)

    inbound_payload = b64encode(b"\xff" * 8).decode()
    outbound_payload = b64encode(b"\x00" * 8).decode()

    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        ws.send_text(json.dumps({
            "event": "media",
            "media": {"track": "inbound", "chunk": "1", "timestamp": "5", "payload": inbound_payload},
        }))
        ws.send_text(json.dumps({
            "event": "media",
            "media": {"track": "outbound", "chunk": "2", "timestamp": "10", "payload": outbound_payload},
        }))
        ws.send_text(json.dumps(_STOP_MSG))

    assert (b"\xff" * 8, b"") in captured
    assert (b"", b"\x00" * 8) in captured


def test_media_stream_finalizes_recording_on_stop(monkeypatch):
    """After the call ends, finalize_recording runs and mark_recording_ready
    writes the resulting gs:// URL to Firestore."""
    from app.storage import recordings as recordings_mod
    from app.storage import call_sessions

    fake_session = MagicMock(broken=False)
    monkeypatch.setattr(
        recordings_mod, "begin_recording",
        lambda *, call_sid, restaurant_id, retention_days: fake_session,
    )
    monkeypatch.setattr(recordings_mod, "append_chunks", lambda *a, **kw: None)
    monkeypatch.setattr(
        recordings_mod, "finalize_recording",
        lambda session: ("gs://niko-recordings/niko-pizza-kitchen/CAtest123.mp3", 12),
    )

    fake_dg = AsyncMock()
    fake_dg.send = AsyncMock()
    fake_dg.finish = AsyncMock()

    async def fake_open_dg(call_sid, restaurant_id, on_final, **kwargs):
        return fake_dg

    monkeypatch.setattr("app.telephony.router._open_deepgram_connection", fake_open_dg)
    monkeypatch.setattr("app.telephony.router.speak", AsyncMock())
    monkeypatch.setattr("app.telephony.router.stream_reply", _make_fake_stream_reply())

    monkeypatch.setattr(call_sessions, "init_call_session", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "record_event", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "mark_call_ended", lambda *a, **kw: None)

    captured: list[dict] = []
    monkeypatch.setattr(
        call_sessions, "mark_recording_ready",
        lambda call_sid, rid, **kw: captured.append({"call_sid": call_sid, "rid": rid, **kw}),
    )

    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        ws.send_text(json.dumps(_STOP_MSG))

    assert len(captured) == 1
    assert captured[0]["call_sid"] == "CAtest123"
    assert captured[0]["rid"] == "niko-pizza-kitchen"
    assert captured[0]["recording_url"] == "gs://niko-recordings/niko-pizza-kitchen/CAtest123.mp3"
    assert captured[0]["recording_sid"] == "CAtest123"
    assert captured[0]["duration_seconds"] == 12


# ---------------------------------------------------------------------------
# AI greeting
# ---------------------------------------------------------------------------


def test_ai_greeting_spawned_on_start(monkeypatch):
    """On start event, stream_reply is called with GREETING_TRANSCRIPT."""
    from app.telephony.router import GREETING_TRANSCRIPT

    calls: list[str] = []
    fake_dg = AsyncMock()
    fake_dg.send = AsyncMock()
    fake_dg.finish = AsyncMock()

    async def fake_open_dg(call_sid, restaurant_id, on_final, **kwargs):
        return fake_dg

    async def fake_speak(text, websocket, stream_sid, **kw):
        pass

    async def recording_stream_reply(*, transcript, history, order, **kw):
        calls.append(transcript)
        yield StreamEvent(text_delta="Hello!")
        yield StreamEvent(
            final=LLMResponse(reply_text="Hello!", order=order, history=history)
        )

    monkeypatch.setattr("app.telephony.router._open_deepgram_connection", fake_open_dg)
    monkeypatch.setattr("app.telephony.router.speak", fake_speak)
    monkeypatch.setattr("app.telephony.router.stream_reply", recording_stream_reply)

    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        ws.send_text(json.dumps(_STOP_MSG))

    assert GREETING_TRANSCRIPT in calls


# ---------------------------------------------------------------------------
# Order persistence on stop
# ---------------------------------------------------------------------------


def test_stop_event_persists_ready_order(monkeypatch):
    """persist_on_confirm is called at call end when order is_ready_to_confirm."""
    from app.orders.models import LineItem, ItemCategory, OrderType

    persisted: list = []

    fake_dg = AsyncMock()
    fake_dg.send = AsyncMock()
    fake_dg.finish = AsyncMock()

    async def fake_open_dg(call_sid, restaurant_id, on_final, **kwargs):
        return fake_dg

    async def fake_speak(text, websocket, stream_sid, **kw):
        pass

    ready_order = Order(
        call_sid="CAtest123",
        items=[LineItem(name="Pepperoni", category=ItemCategory.PIZZA, size="large", quantity=1, unit_price=21.99)],
        order_type=OrderType.PICKUP,
    )

    async def fake_stream_reply(*, transcript, history, order, **kw):
        yield StreamEvent(text_delta="Great!")
        yield StreamEvent(
            final=LLMResponse(reply_text="Great!", order=ready_order, history=history)
        )

    def fake_persist(order):
        persisted.append(order)
        return order

    monkeypatch.setattr("app.telephony.router._open_deepgram_connection", fake_open_dg)
    monkeypatch.setattr("app.telephony.router.speak", fake_speak)
    monkeypatch.setattr("app.telephony.router.stream_reply", fake_stream_reply)
    monkeypatch.setattr("app.telephony.router.persist_on_confirm", fake_persist)

    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        ws.send_text(json.dumps(_STOP_MSG))

    assert len(persisted) == 1
    assert persisted[0].call_sid == "CAtest123"


def test_stop_event_skips_persist_if_order_not_ready(monkeypatch):
    """persist_on_confirm is NOT called when order has no items."""
    persisted: list = []

    fake_dg = AsyncMock()
    fake_dg.send = AsyncMock()
    fake_dg.finish = AsyncMock()

    async def fake_open_dg(call_sid, restaurant_id, on_final, **kwargs):
        return fake_dg

    async def fake_speak(text, websocket, stream_sid, **kw):
        pass

    def fake_persist(order):
        persisted.append(order)
        return order

    monkeypatch.setattr("app.telephony.router._open_deepgram_connection", fake_open_dg)
    monkeypatch.setattr("app.telephony.router.speak", fake_speak)
    monkeypatch.setattr("app.telephony.router.stream_reply", _make_fake_stream_reply())
    monkeypatch.setattr("app.telephony.router.persist_on_confirm", fake_persist)

    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        ws.send_text(json.dumps(_STOP_MSG))

    assert persisted == []


# ---------------------------------------------------------------------------
# Barge-in: clear Twilio's audio buffer (#74)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_twilio_audio_sends_clear_event_with_stream_sid():
    """The helper emits the documented Twilio clear payload."""
    from app.telephony.router import clear_twilio_audio

    ws = AsyncMock()
    ws.send_json = AsyncMock()

    await clear_twilio_audio(ws, "MZtest456")

    ws.send_json.assert_awaited_once_with(
        {"event": "clear", "streamSid": "MZtest456"}
    )


@pytest.mark.asyncio
async def test_clear_twilio_audio_skips_when_stream_sid_missing():
    """No stream means we never opened the start frame — nothing to clear."""
    from app.telephony.router import clear_twilio_audio

    ws = AsyncMock()
    ws.send_json = AsyncMock()

    await clear_twilio_audio(ws, None)

    ws.send_json.assert_not_called()


def test_looks_like_goodbye_matches_terminal_phrases():
    from app.telephony.router import _looks_like_goodbye

    assert _looks_like_goodbye(
        "Great, your order is in — we'll have it ready for you soon!"
    )
    assert _looks_like_goodbye("Perfect, see you soon!")
    assert _looks_like_goodbye("Thanks for calling!")
    assert _looks_like_goodbye("Have a great day.")


def test_looks_like_goodbye_rejects_questions():
    """A reply that ends with '?' is still asking the caller something."""
    from app.telephony.router import _looks_like_goodbye

    assert not _looks_like_goodbye(
        "Got that. Anything else, or are you all set?"
    )
    # Even with goodbye-shaped phrasing earlier, trailing '?' = still asking.
    assert not _looks_like_goodbye(
        "Your order is in — does that all sound right?"
    )


def test_looks_like_goodbye_rejects_simple_acknowledgements():
    """Bot acknowledging an item mid-conversation must NOT trigger the
    auto-hangup fallback."""
    from app.telephony.router import _looks_like_goodbye

    assert not _looks_like_goodbye("One large margarita, got it.")
    assert not _looks_like_goodbye("Sure, what size would you like?")
    assert not _looks_like_goodbye("")
    assert not _looks_like_goodbye("   ")


@pytest.mark.asyncio
async def test_send_end_of_call_mark_emits_mark_payload():
    from app.telephony.router import END_OF_CALL_MARK, send_end_of_call_mark

    ws = AsyncMock()
    ws.send_json = AsyncMock()

    sent = await send_end_of_call_mark(ws, "MZtest456")

    assert sent is True
    ws.send_json.assert_awaited_once_with(
        {
            "event": "mark",
            "streamSid": "MZtest456",
            "mark": {"name": END_OF_CALL_MARK},
        }
    )


@pytest.mark.asyncio
async def test_send_end_of_call_mark_returns_false_when_stream_sid_missing():
    from app.telephony.router import send_end_of_call_mark

    ws = AsyncMock()
    sent = await send_end_of_call_mark(ws, None)
    assert sent is False
    ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_hang_up_after_grace_sets_should_hangup_event(monkeypatch):
    """After the grace window, _hang_up_after_grace sets the WS-loop's
    should_hangup event so the loop exits and the WebSocket closes —
    Twilio's <Connect> ends and the call hangs up. The REST update path
    is gone (it 404'd on <Connect>-state calls)."""
    from app.telephony.router import (
        HANGUP_GRACE_SECONDS,
        _CallState,
        _hang_up_after_grace,
    )

    monkeypatch.setattr("app.telephony.router.HANGUP_GRACE_SECONDS", 0.01)

    state = _CallState(call_sid="CAtest", pending_hangup=True)
    assert not state.should_hangup.is_set()

    await _hang_up_after_grace(state)

    assert state.should_hangup.is_set()
    assert HANGUP_GRACE_SECONDS == 5.0


@pytest.mark.asyncio
async def test_hang_up_after_grace_aborts_when_caller_speaks(monkeypatch):
    """If pending_hangup gets cleared during the grace window (caller
    spoke), the should_hangup event MUST NOT fire."""
    from app.telephony.router import _CallState, _hang_up_after_grace

    monkeypatch.setattr("app.telephony.router.HANGUP_GRACE_SECONDS", 0.01)

    state = _CallState(call_sid="CAtest", pending_hangup=True)
    # Simulate: caller spoke during the grace window — _handle_final_transcript
    # cleared the flag before the timer fired.
    state.pending_hangup = False

    await _hang_up_after_grace(state)

    assert not state.should_hangup.is_set()


def test_looks_like_goodbye_excludes_coming_right_up():
    """'coming right up' is mid-order, not a wrap-up — must NOT trigger fallback."""
    from app.telephony.router import _looks_like_goodbye
    assert _looks_like_goodbye("One large Margherita coming right up.") is False
    assert _looks_like_goodbye("Two Cokes coming right up!") is False


def test_looks_like_goodbye_remaining_patterns_still_match():
    """Positive coverage so a drive-by removal of a pattern is caught."""
    from app.telephony.router import _looks_like_goodbye
    assert _looks_like_goodbye("Thanks for ordering, see you soon!")
    assert _looks_like_goodbye("Your order is in — we'll have it ready shortly.")
    assert _looks_like_goodbye("Thanks for calling!")
    assert _looks_like_goodbye("Have a great day.")
    assert _looks_like_goodbye("Enjoy your meal!")


def test_hangup_grace_seconds_is_five():
    """Grace window must be 5s so callers can add late items."""
    from app.telephony.router import HANGUP_GRACE_SECONDS
    assert HANGUP_GRACE_SECONDS == 5.0


@pytest.mark.asyncio
async def test_mark_echo_timeout_fires_grace_window(monkeypatch):
    """If Twilio never echoes the end_of_call mark, the timeout fires
    the grace window anyway so the call terminates."""
    import asyncio
    from app.telephony import router as router_mod
    from app.telephony.router import (
        _CallState,
        _hang_up_after_mark_timeout,
    )

    monkeypatch.setattr(router_mod, "MARK_ECHO_TIMEOUT_SECONDS", 0.05)

    state = _CallState()
    state.call_sid = "CA_timeout_test"
    state.pending_hangup = True

    grace_started = {"flag": False}

    async def fake_grace(s):
        grace_started["flag"] = True

    monkeypatch.setattr(router_mod, "_hang_up_after_grace", fake_grace)

    await _hang_up_after_mark_timeout(state)

    assert grace_started["flag"] is True, (
        "mark echo timeout must trigger grace window when no echo arrives"
    )


@pytest.mark.asyncio
async def test_mark_echo_timeout_skips_grace_when_pending_hangup_cleared(monkeypatch):
    """If pending_hangup is cleared during the 8s sleep (caller spoke and
    _abort_pending_hangup raced), the timeout must NOT fire the grace window."""
    import asyncio
    from app.telephony import router as router_mod
    from app.telephony.router import _CallState, _hang_up_after_mark_timeout

    monkeypatch.setattr(router_mod, "MARK_ECHO_TIMEOUT_SECONDS", 0.05)

    state = _CallState()
    state.call_sid = "CA_abort_race"
    state.pending_hangup = False  # already cleared before timeout fires

    grace_started = {"flag": False}

    async def fake_grace(s):
        grace_started["flag"] = True

    monkeypatch.setattr(router_mod, "_hang_up_after_grace", fake_grace)

    await _hang_up_after_mark_timeout(state)

    assert grace_started["flag"] is False, (
        "timeout must not fire grace when pending_hangup was already cleared"
    )


@pytest.mark.asyncio
async def test_abort_pending_hangup_cancels_mark_timeout_task():
    """_abort_pending_hangup must cancel mark_timeout_task so the fallback
    timer doesn't fire after the caller speaks during the grace window."""
    import asyncio
    from app.telephony.router import _CallState, _abort_pending_hangup

    state = _CallState(call_sid="CAtest", pending_hangup=True)

    async def _noop():
        await asyncio.sleep(60)

    state.mark_timeout_task = asyncio.create_task(_noop())

    _abort_pending_hangup(state)

    assert state.mark_timeout_task is None
    assert state.pending_hangup is False


@pytest.mark.asyncio
async def test_clear_twilio_audio_swallows_websocket_disconnect():
    """If the caller already hung up, the clear send raises — but we
    must not let that exception escape into the call loop."""
    from starlette.websockets import WebSocketDisconnect

    from app.telephony.router import clear_twilio_audio

    ws = AsyncMock()
    ws.send_json = AsyncMock(side_effect=WebSocketDisconnect())

    # No exception escaping is the assertion.
    await clear_twilio_audio(ws, "MZtest456")


# ---------------------------------------------------------------------------
# _should_flush_chunk — TTS chunking logic
# ---------------------------------------------------------------------------


def test_flush_on_period_regardless_of_length():
    """Sentence terminators always flush, even on a very short buffer."""
    assert _should_flush_chunk(".", buffered_chars=3) is True
    assert _should_flush_chunk("up.", buffered_chars=3) is True


def test_flush_on_question_mark_and_exclamation():
    assert _should_flush_chunk("?", buffered_chars=5) is True
    assert _should_flush_chunk("!", buffered_chars=5) is True


def test_no_flush_on_comma_below_min_length():
    """Short comma-ended chunks (e.g. 'Got it,') keep buffering — we
    don't want a TTS round-trip for two-word fragments."""
    assert _should_flush_chunk(",", buffered_chars=7) is False
    assert _should_flush_chunk("it,", buffered_chars=7) is False


def test_flush_on_comma_at_or_above_min_length():
    """Once the buffer crosses _MIN_CHUNK_CHARS, a comma flushes so the
    caller hears the first half of a long sentence sooner."""
    assert _MIN_CHUNK_CHARS == 20
    assert _should_flush_chunk(",", buffered_chars=_MIN_CHUNK_CHARS) is True
    assert _should_flush_chunk("up,", buffered_chars=33) is True


def test_flush_on_other_soft_breaks():
    """Semicolons, colons, and em dashes are also natural prosody
    breaks — gated by the same min-length rule."""
    assert _should_flush_chunk(";", buffered_chars=25) is True
    assert _should_flush_chunk(":", buffered_chars=25) is True
    assert _should_flush_chunk("—", buffered_chars=25) is True
    assert _should_flush_chunk(";", buffered_chars=10) is False


def test_no_flush_on_plain_text_delta():
    """Mid-word deltas never flush, regardless of length."""
    assert _should_flush_chunk(" coming", buffered_chars=100) is False
    assert _should_flush_chunk("a", buffered_chars=5) is False


# ---------------------------------------------------------------------------
# _run_llm_tts_turn — comma-chunking integration (uses the WS pipeline)
# ---------------------------------------------------------------------------


def _make_fake_stream_reply_deltas(*deltas: str, final_text: str = ""):
    """Yield each delta string as a separate StreamEvent — lets us
    drive the chunking logic with realistic multi-event streams."""
    final = final_text or "".join(deltas)

    async def fake(*, transcript, history, order, **kw):
        for d in deltas:
            yield StreamEvent(text_delta=d)
        yield StreamEvent(
            final=LLMResponse(reply_text=final, order=order, history=history)
        )

    return fake


def test_run_llm_tts_turn_flushes_at_long_comma_clause(monkeypatch, mock_pipeline):
    """A delta sequence that builds up to 'One Chicken Fried Rice coming up,'
    should flush at the comma (≥20 chars buffered), then ship the rest at
    the period — total 2 chunks."""
    chunks_spoken: list[str] = []

    async def capture_speak(text, websocket, stream_sid, **kw):
        chunks_spoken.append(text)

    monkeypatch.setattr("app.telephony.router.speak", capture_speak)
    monkeypatch.setattr(
        "app.telephony.router.stream_reply",
        _make_fake_stream_reply_deltas(
            "One Chicken Fried Rice coming up,",
            " what size would you like?",
        ),
    )

    with client.websocket_connect("/media-stream") as ws:
        ws.send_json(_START_MSG)
        ws.send_json(_STOP_MSG)

    # Greeting turn ships once (single delta no terminators in the test
    # fake — flushed at end-of-stream as remainder). Caller turn here
    # produces 2 chunks: comma flush + period flush.
    assert "One Chicken Fried Rice coming up," in chunks_spoken
    assert "what size would you like?" in chunks_spoken


def test_run_llm_tts_turn_does_not_flush_at_short_comma(monkeypatch, mock_pipeline):
    """'Got it,' is below the 20-char threshold — it must keep buffering
    until the period and ship as a single chunk."""
    chunks_spoken: list[str] = []

    async def capture_speak(text, websocket, stream_sid, **kw):
        chunks_spoken.append(text)

    monkeypatch.setattr("app.telephony.router.speak", capture_speak)
    monkeypatch.setattr(
        "app.telephony.router.stream_reply",
        _make_fake_stream_reply_deltas("Got it,", " moving on."),
    )

    with client.websocket_connect("/media-stream") as ws:
        ws.send_json(_START_MSG)
        ws.send_json(_STOP_MSG)

    # Single chunk — comma did NOT flush, period did.
    combined = " ".join(chunks_spoken)
    assert "Got it, moving on." in combined
    # No chunk should be just "Got it,"
    assert "Got it," not in chunks_spoken


# ---------------------------------------------------------------------------
# first_tts_byte event (#152)
# ---------------------------------------------------------------------------


def test_first_tts_byte_event_emitted_on_turn(monkeypatch):
    """A first_tts_byte Firestore event with a latency_seconds field is
    emitted on the first speak() call of a turn. The existing first_audio
    event must still be present — we ADD, not replace."""
    from app.storage import call_sessions

    fake_dg = AsyncMock()
    fake_dg.send = AsyncMock()
    fake_dg.finish = AsyncMock()

    async def fake_open_dg(call_sid, restaurant_id, on_final, **kwargs):
        return fake_dg

    # A speak() stub that invokes on_first_byte so the callback fires
    # as it would with a real TTS stream delivering its first chunk.
    async def speak_with_callback(text, websocket, stream_sid, **kw):
        cb = kw.get("on_first_byte")
        if cb is not None:
            cb()

    recorded_events: list[dict] = []

    def capture_bg_event(call_sid, restaurant_id, **kwargs):
        recorded_events.append({"call_sid": call_sid, "rid": restaurant_id, **kwargs})

    monkeypatch.setattr("app.telephony.router._open_deepgram_connection", fake_open_dg)
    monkeypatch.setattr("app.telephony.router.speak", speak_with_callback)
    monkeypatch.setattr("app.telephony.router.stream_reply", _make_fake_stream_reply())
    monkeypatch.setattr("app.telephony.router._bg_call_event", capture_bg_event)
    monkeypatch.setattr(call_sessions, "init_call_session", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "record_event", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "mark_call_ended", lambda *a, **kw: None)

    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        ws.send_text(json.dumps(_STOP_MSG))

    first_tts_events = [e for e in recorded_events if e.get("kind") == "first_tts_byte"]
    assert len(first_tts_events) >= 1, (
        f"expected at least one first_tts_byte event; got events: "
        f"{[e.get('kind') for e in recorded_events]}"
    )
    evt = first_tts_events[0]
    assert "detail" in evt
    assert "latency_seconds" in evt["detail"], (
        f"first_tts_byte event missing latency_seconds: {evt}"
    )
    assert isinstance(evt["detail"]["latency_seconds"], float)

    # first_audio must still be emitted — backwards compatibility
    first_audio_events = [e for e in recorded_events if e.get("kind") == "first_audio"]
    assert len(first_audio_events) >= 1, "first_audio event must not be removed"


# ---------------------------------------------------------------------------
# Transfer trigger accumulation (#7 Sprint 2.4 Track 2)
# ---------------------------------------------------------------------------


def test_call_state_has_transfer_trigger_fields():
    """The new fields on _CallState are needed by the trigger detector."""
    from app.telephony.router import _CallState

    state = _CallState()
    assert state.consecutive_low_confidence_turns == 0
    assert state.last_caller_transcript == ""
    assert state.llm_error_occurred is False


def test_voice_twiml_includes_stream_ended_action():
    """The <Connect> in /voice TwiML must point its action callback at
    /voice/stream-ended so Phase C can dispatch transfer or hangup."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.main import app
    from app.restaurants.models import Restaurant
    from app.storage import restaurants as r_storage

    fake = Restaurant(
        id="r1",
        name="R",
        display_phone="+15551234567",
        twilio_phone="+16479058093",
        address="1 Main",
        hours="Mon-Sun 11-22",
        menu={},
    )

    with patch.object(
        r_storage,
        "get_restaurant_by_twilio_phone",
        return_value=fake,
    ):
        client = TestClient(app)
        resp = client.post(
            "/voice",
            data={"To": "+16479058093", "CallSid": "CAtest"},
            headers={"host": "test.example.com"},
        )

    assert resp.status_code == 200
    body = resp.text
    assert '<Connect' in body
    assert 'action="/voice/stream-ended"' in body
    assert 'method="POST"' in body


# ---------------------------------------------------------------------------
# on_transcript confidence handling (Fix 1 regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_transcript_increments_misheard_counter_on_low_confidence(monkeypatch):
    """Driving on_transcript with low-confidence finals must increment
    state.consecutive_low_confidence_turns. Reset on a clear final."""
    from unittest.mock import MagicMock

    from app.telephony.router import _CallState, _open_deepgram_connection
    import app.telephony.router as router_mod

    # Satisfy the API-key guard without a real credential.
    monkeypatch.setattr(router_mod.settings, "deepgram_api_key", "fake-key-for-test")
    # Prevent _bg_call_event from spawning background threads that attempt
    # real Firestore writes (no GCP in the test environment).
    monkeypatch.setattr(router_mod, "_bg_call_event", lambda *a, **kw: None)

    state = _CallState()
    captured: dict = {}

    class FakeDeepgramConn:
        def on(self, event_type, handler):
            captured.setdefault(str(event_type), handler)

        async def start(self, *_, **__):
            return True

        async def finish(self):
            pass

        async def send(self, *_):
            pass

        def keepalive(self):
            pass

    class FakeDeepgramClient:
        def __init__(self, *_):
            self.listen = MagicMock()
            self.listen.asynclive.v.return_value = FakeDeepgramConn()

    monkeypatch.setattr(router_mod, "DeepgramClient", FakeDeepgramClient)

    async def on_final(text):
        pass

    await _open_deepgram_connection(
        "CAtest",
        "r1",
        on_final,
        state=state,
    )

    # LiveTranscriptionEvents.Transcript stringifies to "Results" (Deepgram SDK).
    handler = captured["Results"]

    def fake_result(text, confidence, is_final=True):
        r = MagicMock()
        alt = MagicMock()
        alt.transcript = text
        alt.confidence = confidence
        r.channel.alternatives = [alt]
        r.is_final = is_final
        return r

    # Three consecutive low-confidence finals.
    await handler(None, fake_result("um", 0.2))
    await handler(None, fake_result("uhh", 0.1))
    # confidence=0.0 is the key regression: without Fix 1, `0.0 or 1.0`
    # yields 1.0 and the counter would not advance on this third call.
    await handler(None, fake_result("what", 0.0))

    assert state.consecutive_low_confidence_turns == 3

    # A clear final resets the counter.
    await handler(None, fake_result("a large pepperoni pizza", 0.95))
    assert state.consecutive_low_confidence_turns == 0
    assert state.last_caller_transcript == "a large pepperoni pizza"


# ---------------------------------------------------------------------------
# /voice/stream-ended — Phase C call-transfer dispatch (#7 Sprint 2.4 Track 2)
# ---------------------------------------------------------------------------


def test_stream_ended_returns_empty_twiml_when_no_transfer_requested(monkeypatch):
    """Normal end of call — no transfer_requested event → empty TwiML.
    Twilio's default behavior on empty TwiML is to hang up."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.storage import call_sessions

    monkeypatch.setattr(
        call_sessions,
        "get_session_by_call_sid",
        lambda sid: {"restaurant_id": "r1"},
    )
    monkeypatch.setattr(
        call_sessions,
        "get_session_events",
        lambda sid, rid: [
            {"kind": "transcript_final", "timestamp": None, "text": "hi"},
        ],
    )

    c = TestClient(app)
    resp = c.post("/voice/stream-ended", data={"CallSid": "CAtest"})
    assert resp.status_code == 200
    body = resp.text
    assert "<Dial" not in body
    assert "<Record" not in body


def test_stream_ended_returns_dial_when_transfer_requested(monkeypatch):
    """transfer_requested event + fallback_phone set → <Dial> TwiML."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.restaurants.models import Restaurant
    from app.storage import call_sessions, restaurants as r_storage

    monkeypatch.setattr(
        call_sessions,
        "get_session_by_call_sid",
        lambda sid: {"restaurant_id": "r1"},
    )
    monkeypatch.setattr(
        call_sessions,
        "get_session_events",
        lambda sid, rid: [
            {"kind": "transfer_requested", "timestamp": None, "text": "human_intent"},
        ],
    )
    monkeypatch.setattr(
        r_storage,
        "get_restaurant",
        lambda rid: Restaurant(
            id="r1",
            name="R",
            display_phone="+15551234567",
            twilio_phone="+16479058093",
            address="1 Main",
            hours="11-22",
            menu={},
            fallback_phone="+15559999999",
        ),
    )

    c = TestClient(app)
    resp = c.post("/voice/stream-ended", data={"CallSid": "CAtest"})
    assert resp.status_code == 200
    body = resp.text
    assert "<Dial" in body
    assert "+15559999999" in body
    assert "/voice/transfer-result" in body


def test_stream_ended_skips_to_voicemail_when_no_fallback(monkeypatch):
    """transfer_requested but no fallback_phone configured → mark
    transfer as skipped + return voicemail TwiML directly."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.restaurants.models import Restaurant
    from app.storage import call_sessions, restaurants as r_storage

    monkeypatch.setattr(
        call_sessions,
        "get_session_by_call_sid",
        lambda sid: {"restaurant_id": "r1"},
    )
    monkeypatch.setattr(
        call_sessions,
        "get_session_events",
        lambda sid, rid: [
            {"kind": "transfer_requested", "timestamp": None, "text": "llm_error"},
        ],
    )
    monkeypatch.setattr(
        r_storage,
        "get_restaurant",
        lambda rid: Restaurant(
            id="r1",
            name="R",
            display_phone="+15551234567",
            twilio_phone="+16479058093",
            address="1 Main",
            hours="11-22",
            menu={},
            fallback_phone=None,
        ),
    )

    mark_calls = []
    monkeypatch.setattr(
        call_sessions,
        "mark_transfer_attempted",
        lambda *a, **kw: mark_calls.append(kw),
    )

    c = TestClient(app)
    resp = c.post("/voice/stream-ended", data={"CallSid": "CAtest"})
    assert resp.status_code == 200
    assert "<Dial" not in resp.text
    assert "<Record" in resp.text
    assert mark_calls and mark_calls[0]["status"] == "skipped"


def test_stream_ended_handles_missing_call_sid_gracefully(monkeypatch):
    """Defensive — if Twilio's CallSid form field is missing, return
    empty TwiML rather than 500."""
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    resp = c.post("/voice/stream-ended", data={})
    assert resp.status_code == 200
    assert "<Dial" not in resp.text


# ---------------------------------------------------------------------------
# /voice/transfer-result — Phase C cascade on no-answer (#7 Sprint 2.4 Track 2)
# ---------------------------------------------------------------------------


def test_transfer_result_completed_returns_empty(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.storage import call_sessions

    mark_calls = []
    monkeypatch.setattr(
        call_sessions,
        "mark_transfer_attempted",
        lambda *a, **kw: mark_calls.append(kw),
    )

    c = TestClient(app)
    resp = c.post(
        "/voice/transfer-result",
        params={"call_sid": "CAtest", "rid": "r1"},
        data={"DialCallStatus": "completed"},
    )
    assert resp.status_code == 200
    assert "<Record" not in resp.text
    assert mark_calls and mark_calls[0]["status"] == "answered"


def test_transfer_result_no_answer_drops_to_voicemail(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.storage import call_sessions

    monkeypatch.setattr(
        call_sessions,
        "mark_transfer_attempted",
        lambda *a, **kw: None,
    )

    c = TestClient(app)
    resp = c.post(
        "/voice/transfer-result",
        params={"call_sid": "CAtest", "rid": "r1"},
        data={"DialCallStatus": "no-answer"},
    )
    assert resp.status_code == 200
    assert "<Record" in resp.text


def test_transfer_result_busy_drops_to_voicemail(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.storage import call_sessions

    monkeypatch.setattr(
        call_sessions,
        "mark_transfer_attempted",
        lambda *a, **kw: None,
    )

    c = TestClient(app)
    resp = c.post(
        "/voice/transfer-result",
        params={"call_sid": "CAtest", "rid": "r1"},
        data={"DialCallStatus": "busy"},
    )
    assert resp.status_code == 200
    assert "<Record" in resp.text


def test_transfer_result_failed_status_marks_internal_failed(monkeypatch):
    """Verify the Twilio-status → internal-status mapping."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.storage import call_sessions

    mark_calls = []
    monkeypatch.setattr(
        call_sessions,
        "mark_transfer_attempted",
        lambda *a, **kw: mark_calls.append(kw),
    )

    c = TestClient(app)
    resp = c.post(
        "/voice/transfer-result",
        params={"call_sid": "CAtest", "rid": "r1"},
        data={"DialCallStatus": "failed"},
    )
    assert resp.status_code == 200
    assert mark_calls and mark_calls[0]["status"] == "failed"


# ---------------------------------------------------------------------------
# Phase D: voicemail recording + transcription webhooks + after-hours routing
# ---------------------------------------------------------------------------


def test_voicemail_recorded_uploads_and_marks_session(monkeypatch):
    """Twilio recording URL → GCS upload → call_sessions.mark_voicemail_left."""
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app
    from app.storage import call_sessions, recordings

    upload_calls: list[dict] = []
    def fake_upload(**kwargs):
        upload_calls.append(kwargs)
        return f"gs://test/voicemail/{kwargs['restaurant_id']}/{kwargs['call_sid']}.mp3"

    monkeypatch.setattr(
        recordings, "upload_voicemail_from_twilio", fake_upload,
    )
    monkeypatch.setattr(settings, "twilio_account_sid", "ACfake")
    monkeypatch.setattr(settings, "twilio_auth_token", "tokenfake")

    mark_calls: list[dict] = []
    monkeypatch.setattr(
        call_sessions,
        "mark_voicemail_left",
        lambda *a, **kw: mark_calls.append(kw),
    )

    client = TestClient(app)
    resp = client.post(
        "/voice/voicemail-recorded",
        params={"call_sid": "CAtest", "rid": "r1"},
        data={
            "RecordingUrl": "https://api.twilio.com/2010-04-01/Recordings/REabc",
            "RecordingSid": "REabc",
            "RecordingDuration": "42",
        },
    )

    assert resp.status_code == 200
    assert len(upload_calls) == 1
    assert upload_calls[0]["call_sid"] == "CAtest"
    assert upload_calls[0]["restaurant_id"] == "r1"
    assert len(mark_calls) == 1
    assert mark_calls[0]["recording_url"].startswith("gs://test/voicemail/")
    assert mark_calls[0]["duration_seconds"] == 42


def test_voicemail_recorded_handles_missing_twilio_creds_gracefully(monkeypatch):
    """If TWILIO creds aren't set, log + return empty TwiML rather than 500."""
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app
    from app.storage import recordings

    upload_calls = []
    monkeypatch.setattr(
        recordings,
        "upload_voicemail_from_twilio",
        lambda **kw: upload_calls.append(kw) or "gs://x/y",
    )
    monkeypatch.setattr(settings, "twilio_account_sid", None)
    monkeypatch.setattr(settings, "twilio_auth_token", None)

    client = TestClient(app)
    resp = client.post(
        "/voice/voicemail-recorded",
        params={"call_sid": "CAtest", "rid": "r1"},
        data={
            "RecordingUrl": "https://api.twilio.com/2010-04-01/Recordings/REabc",
            "RecordingSid": "REabc",
            "RecordingDuration": "42",
        },
    )

    assert resp.status_code == 200
    assert upload_calls == []  # Skipped


def test_voicemail_recorded_handles_upload_failure_gracefully(monkeypatch):
    """Twilio download or GCS upload failure → log + empty TwiML."""
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app
    from app.storage import call_sessions, recordings

    def boom(**kw):
        raise RuntimeError("gcs is angry")
    monkeypatch.setattr(recordings, "upload_voicemail_from_twilio", boom)
    monkeypatch.setattr(settings, "twilio_account_sid", "AC")
    monkeypatch.setattr(settings, "twilio_auth_token", "tok")

    mark_calls = []
    monkeypatch.setattr(
        call_sessions, "mark_voicemail_left", lambda *a, **kw: mark_calls.append(kw),
    )

    client = TestClient(app)
    resp = client.post(
        "/voice/voicemail-recorded",
        params={"call_sid": "CAtest", "rid": "r1"},
        data={
            "RecordingUrl": "https://api.twilio.com/2010-04-01/Recordings/REabc",
            "RecordingSid": "REabc",
            "RecordingDuration": "42",
        },
    )

    assert resp.status_code == 200
    # Upload failed → no mark call
    assert mark_calls == []


def test_voicemail_transcription_patches_call_session(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.storage import call_sessions

    patches: list[dict] = []
    monkeypatch.setattr(
        call_sessions,
        "update_voicemail_transcript",
        lambda *a, **kw: patches.append(kw),
    )

    client = TestClient(app)
    resp = client.post(
        "/voice/voicemail-transcription",
        params={"call_sid": "CAtest", "rid": "r1"},
        data={"TranscriptionText": "Hi, please call me back."},
    )

    assert resp.status_code == 200
    assert patches == [{"transcript": "Hi, please call me back."}]


def test_voicemail_transcription_skips_when_empty(monkeypatch):
    """Twilio sometimes posts empty TranscriptionText (transcription
    failed or audio too quiet). Skip the patch silently."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.storage import call_sessions

    patches: list[dict] = []
    monkeypatch.setattr(
        call_sessions,
        "update_voicemail_transcript",
        lambda *a, **kw: patches.append(kw),
    )

    client = TestClient(app)
    resp = client.post(
        "/voice/voicemail-transcription",
        params={"call_sid": "CAtest", "rid": "r1"},
        data={"TranscriptionText": ""},
    )

    assert resp.status_code == 200
    assert patches == []


def test_voice_routes_to_voicemail_when_after_hours(monkeypatch):
    """When the restaurant's hours_structured says it's closed,
    /voice returns voicemail TwiML directly instead of opening a
    media stream."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.restaurants import open_check
    from app.restaurants.models import (
        DayHours, HoursStructured, Restaurant,
    )
    from app.storage import restaurants as r_storage, call_sessions

    closed_day = DayHours(open="00:00", close="00:00", closed=True)
    h = HoursStructured(
        mon=closed_day, tue=closed_day, wed=closed_day, thu=closed_day,
        fri=closed_day, sat=closed_day, sun=closed_day,
    )
    fake = Restaurant(
        id="r1",
        name="R",
        display_phone="+15551234567",
        twilio_phone="+16479058093",
        address="1 Main",
        hours="closed",
        menu={},
        hours_structured=h,
    )

    monkeypatch.setattr(
        r_storage,
        "get_restaurant_by_twilio_phone",
        lambda phone: fake,
    )
    # Force is_open_now to return False regardless of clock state
    monkeypatch.setattr(open_check, "is_open_now", lambda r, now=None: False)
    monkeypatch.setattr(
        call_sessions,
        "init_call_session",
        lambda *a, **kw: None,
    )

    client = TestClient(app)
    resp = client.post(
        "/voice",
        data={"To": "+16479058093", "CallSid": "CAtest"},
        headers={"host": "test.example.com"},
    )

    assert resp.status_code == 200
    assert "<Record" in resp.text
    assert "<Connect" not in resp.text


def test_voice_opens_stream_when_open(monkeypatch):
    """When is_open_now returns True (default for None hours_structured),
    /voice still opens the AI media stream as before."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.restaurants.models import Restaurant
    from app.storage import restaurants as r_storage

    fake = Restaurant(
        id="r1",
        name="R",
        display_phone="+15551234567",
        twilio_phone="+16479058093",
        address="1 Main",
        hours="11-22",
        menu={},
    )
    monkeypatch.setattr(
        r_storage,
        "get_restaurant_by_twilio_phone",
        lambda phone: fake,
    )

    client = TestClient(app)
    resp = client.post(
        "/voice",
        data={"To": "+16479058093", "CallSid": "CAtest"},
        headers={"host": "test.example.com"},
    )

    assert resp.status_code == 200
    assert "<Connect" in resp.text
    assert "<Record" not in resp.text


def test_voicemail_recorded_is_idempotent_on_twilio_retry(monkeypatch):
    """Twilio retries the <Record> action callback on timeout. The
    second call must skip the upload + mark when the same RecordingSid
    is already on the call session."""
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app
    from app.storage import call_sessions, recordings

    monkeypatch.setattr(settings, "twilio_account_sid", "AC")
    monkeypatch.setattr(settings, "twilio_auth_token", "tok")

    # First call: no existing session record — upload runs.
    # Second call: session already has the same RecordingSid — skip.
    upload_calls = []
    monkeypatch.setattr(
        recordings,
        "upload_voicemail_from_twilio",
        lambda **kw: upload_calls.append(kw) or "gs://x/y",
    )

    mark_calls = []
    monkeypatch.setattr(
        call_sessions,
        "mark_voicemail_left",
        lambda *a, **kw: mark_calls.append(kw),
    )

    sessions = [
        None,                                          # 1st call: no session yet
        {"voicemail_recording_sid": "REabc"},          # 2nd call: already processed
    ]
    monkeypatch.setattr(
        call_sessions,
        "get_session",
        lambda sid, rid: sessions.pop(0) if sessions else None,
    )

    client = TestClient(app)
    payload = {
        "RecordingUrl": "https://api.twilio.com/2010-04-01/Recordings/REabc",
        "RecordingSid": "REabc",
        "RecordingDuration": "42",
    }
    # First post — should upload + mark
    r1 = client.post(
        "/voice/voicemail-recorded",
        params={"call_sid": "CAtest", "rid": "r1"},
        data=payload,
    )
    assert r1.status_code == 200
    # Second post (retry) — should skip
    r2 = client.post(
        "/voice/voicemail-recorded",
        params={"call_sid": "CAtest", "rid": "r1"},
        data=payload,
    )
    assert r2.status_code == 200

    assert len(upload_calls) == 1, "upload should run exactly once"
    assert len(mark_calls) == 1, "mark_voicemail_left should fire exactly once"


def test_voice_after_hours_without_call_sid_bails_with_hangup(monkeypatch):
    """Defensive — if CallSid is somehow missing on /voice (Twilio
    contract violation), don't write voicemail/{rid}/unknown.mp3. Hang
    up gracefully."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.restaurants import open_check
    from app.restaurants.models import Restaurant
    from app.storage import restaurants as r_storage
    import app.telephony.router as router_mod

    fake = Restaurant(
        id="r1",
        name="R",
        display_phone="+15551234567",
        twilio_phone="+16479058093",
        address="1 Main",
        hours="11-22",
        menu={},
    )
    monkeypatch.setattr(
        r_storage,
        "get_restaurant_by_twilio_phone",
        lambda phone: fake,
    )
    # Patch both the source module and the router's bound name so the
    # check fires regardless of import-time binding.
    monkeypatch.setattr(open_check, "is_open_now", lambda r, now=None: False)
    monkeypatch.setattr(router_mod, "is_open_now", lambda r, now=None: False)

    client = TestClient(app)
    resp = client.post(
        "/voice",
        data={"To": "+16479058093"},  # no CallSid
        headers={"host": "test.example.com"},
    )

    assert resp.status_code == 200
    body = resp.text
    assert "<Hangup" in body
    assert "<Record" not in body
    assert "unknown" not in body


# ---------------------------------------------------------------------------
# Barge-in transcript carry-forward (#170)
# ---------------------------------------------------------------------------


def test_call_state_has_in_flight_transcript_field():
    """#170 — _CallState carries the cancelled-turn transcript forward
    so the next turn can prepend it to the new utterance."""
    from app.telephony.router import _CallState

    state = _CallState()
    assert state.in_flight_transcript == ""


@pytest.mark.asyncio
async def test_cancelled_turn_transcript_carried_forward(monkeypatch):
    """#170 — when a final transcript arrives while an LLM turn is still
    in flight, the cancelled turn's transcript must be prepended to the
    new one so Haiku sees the complete caller intent.

    Real-world hit: call CAb1db16747ce2abb65d04c498e2b371ae lost a $12.25
    chicken fried rice because turn 1 was cancelled by turn 2 1s later
    and only "and a coke" reached the model.
    """
    import app.telephony.router as router_mod
    from app.telephony.router import _CallState, _handle_final_transcript

    captured: list[str] = []

    async def fake_run_llm_tts_turn(transcript, state, websocket):
        captured.append(transcript)
        # Stay in flight long enough to be cancelled by the next call.
        await asyncio.sleep(10.0)

    monkeypatch.setattr(router_mod, "_run_llm_tts_turn", fake_run_llm_tts_turn)
    # Suppress the silence watchdog — its done_callback would otherwise
    # arm a real watchdog that tries to call the real speak() later.
    monkeypatch.setattr(router_mod, "_arm_silence_watchdog", lambda *a, **kw: None)

    state = _CallState(call_sid="CAtest", stream_sid="MZtest")
    ws = AsyncMock()

    # T1 — caller's first utterance. Spawns turn 1.
    await _handle_final_transcript("i'll get one chicken fried rice", state, ws)
    # Yield so the task body actually starts and reaches its sleep.
    await asyncio.sleep(0)

    # T2 — caller's second utterance, while turn 1 is still in flight.
    await _handle_final_transcript("and a coke", state, ws)
    await asyncio.sleep(0)

    # Cleanup: cancel the second turn so the test exits cleanly.
    if state.llm_task and not state.llm_task.done():
        state.llm_task.cancel()
        try:
            await state.llm_task
        except (asyncio.CancelledError, BaseException):
            pass

    assert captured == [
        "i'll get one chicken fried rice",
        "i'll get one chicken fried rice and a coke",
    ]


@pytest.mark.asyncio
async def test_chained_cancels_accumulate_transcripts(monkeypatch):
    """#170 — a rapid burst of three finals should accumulate. Turn 3
    must see all three concatenated as one combined caller intent."""
    import app.telephony.router as router_mod
    from app.telephony.router import _CallState, _handle_final_transcript

    captured: list[str] = []

    async def fake_run_llm_tts_turn(transcript, state, websocket):
        captured.append(transcript)
        await asyncio.sleep(10.0)

    monkeypatch.setattr(router_mod, "_run_llm_tts_turn", fake_run_llm_tts_turn)
    monkeypatch.setattr(router_mod, "_arm_silence_watchdog", lambda *a, **kw: None)

    state = _CallState(call_sid="CAtest", stream_sid="MZtest")
    ws = AsyncMock()

    await _handle_final_transcript("chicken fried rice", state, ws)
    await asyncio.sleep(0)
    await _handle_final_transcript("and a coke", state, ws)
    await asyncio.sleep(0)
    await _handle_final_transcript("and fries", state, ws)
    await asyncio.sleep(0)

    if state.llm_task and not state.llm_task.done():
        state.llm_task.cancel()
        try:
            await state.llm_task
        except (asyncio.CancelledError, BaseException):
            pass

    assert captured == [
        "chicken fried rice",
        "chicken fried rice and a coke",
        "chicken fried rice and a coke and fries",
    ]


@pytest.mark.asyncio
async def test_run_llm_tts_turn_clears_in_flight_transcript_on_final(monkeypatch):
    """#170 — once a turn completes successfully (yields event.final),
    the carry-forward field must be cleared. The user message is now in
    state.history, so prepending it to the next turn would duplicate it."""
    import app.telephony.router as router_mod
    from app.telephony.router import _CallState, _run_llm_tts_turn

    async def fake_stream_reply(*, transcript, history, order, **kw):
        yield StreamEvent(
            final=LLMResponse(reply_text="ok", order=order, history=history)
        )

    async def fake_speak(*a, **kw):
        pass

    monkeypatch.setattr(router_mod, "stream_reply", fake_stream_reply)
    monkeypatch.setattr(router_mod, "speak", fake_speak)
    monkeypatch.setattr(router_mod, "_bg_call_event", lambda *a, **kw: None)

    state = _CallState(call_sid="CAtest", stream_sid="MZtest")
    state.in_flight_transcript = "chicken fried rice and a coke"

    ws = AsyncMock()
    await _run_llm_tts_turn("chicken fried rice and a coke", state, ws)

    assert state.in_flight_transcript == ""


@pytest.mark.asyncio
async def test_errored_turn_carries_transcript_forward(monkeypatch):
    """#170 — when a turn ends in an exception (e.g. Anthropic 5xx) the
    user's words also never reach history. The next final transcript
    must still pick up the carry-forward — same class of bug as cancel,
    different code path."""
    import app.telephony.router as router_mod
    from app.telephony.router import _CallState, _handle_final_transcript

    captured: list[str] = []

    async def erroring_run_llm_tts_turn(transcript, state, websocket):
        captured.append(transcript)
        # Simulate an LLM error after the transcript was already
        # assigned to state.in_flight_transcript by _handle_final_transcript.
        raise RuntimeError("simulated LLM error")

    async def normal_run_llm_tts_turn(transcript, state, websocket):
        captured.append(transcript)
        await asyncio.sleep(10.0)

    monkeypatch.setattr(router_mod, "_arm_silence_watchdog", lambda *a, **kw: None)

    state = _CallState(call_sid="CAtest", stream_sid="MZtest")
    ws = AsyncMock()

    # Turn 1 errors. in_flight_transcript should remain set.
    monkeypatch.setattr(router_mod, "_run_llm_tts_turn", erroring_run_llm_tts_turn)
    await _handle_final_transcript("i'll get one chicken fried rice", state, ws)
    # Wait for the error to propagate.
    if state.llm_task is not None:
        try:
            await state.llm_task
        except RuntimeError:
            pass
    assert state.in_flight_transcript == "i'll get one chicken fried rice"

    # Turn 2 with a fresh transcript — must still carry forward despite
    # state.llm_task.done() == True (errored, not running).
    monkeypatch.setattr(router_mod, "_run_llm_tts_turn", normal_run_llm_tts_turn)
    await _handle_final_transcript("and a coke", state, ws)
    await asyncio.sleep(0)

    if state.llm_task and not state.llm_task.done():
        state.llm_task.cancel()
        try:
            await state.llm_task
        except (asyncio.CancelledError, BaseException):
            pass

    assert captured == [
        "i'll get one chicken fried rice",
        "i'll get one chicken fried rice and a coke",
    ]


@pytest.mark.asyncio
async def test_whitespace_only_in_flight_transcript_is_not_prepended(monkeypatch):
    """#170 defense-in-depth — if some upstream change ever populates
    in_flight_transcript with whitespace, the prepend must be skipped
    so we don't inject leading spaces or trip Anthropic's empty-content
    rejection in `_append_user_transcript`."""
    import app.telephony.router as router_mod
    from app.telephony.router import _CallState, _handle_final_transcript

    captured: list[str] = []

    async def fake_run_llm_tts_turn(transcript, state, websocket):
        captured.append(transcript)
        await asyncio.sleep(10.0)

    monkeypatch.setattr(router_mod, "_run_llm_tts_turn", fake_run_llm_tts_turn)
    monkeypatch.setattr(router_mod, "_arm_silence_watchdog", lambda *a, **kw: None)

    state = _CallState(call_sid="CAtest", stream_sid="MZtest")
    state.in_flight_transcript = "   \t\n  "
    ws = AsyncMock()

    await _handle_final_transcript("and a coke", state, ws)
    await asyncio.sleep(0)

    if state.llm_task and not state.llm_task.done():
        state.llm_task.cancel()
        try:
            await state.llm_task
        except (asyncio.CancelledError, BaseException):
            pass

    assert captured == ["and a coke"]

