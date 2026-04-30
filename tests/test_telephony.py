"""Tests for Twilio telephony endpoints.

Covers POST /voice (TwiML with Media Stream connect) and
WS /media-stream (Twilio Media Stream receiver).  Runs fully
in-process via TestClient — no Twilio, Deepgram, ElevenLabs, or
Anthropic credentials required.

The mock_pipeline fixture patches all three network-bound callables
(_open_deepgram_connection, speak, stream_reply) so every test is
offline and deterministic.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.llm.client import LLMResponse, StreamEvent
from app.orders.models import Order
from app.storage import restaurants as restaurants_storage

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

    async def fake_open_dg(call_sid, restaurant_id, on_final):
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
    assert "<Connect>" in body
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


def test_voice_stream_requests_both_tracks(monkeypatch):
    """Twilio sends both inbound and outbound audio over the same WS
    only when we ask for ``tracks="both_tracks"`` on the <Stream>. This
    is the foundation for the WS-side recording pipeline (#82)."""
    monkeypatch.setattr(
        restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None
    )
    response = client.post("/voice", data=_VOICE_FORM)
    body = response.text
    assert 'tracks="both_tracks"' in body


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

    async def fake_open_dg(call_sid, restaurant_id, on_final):
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

    async def fake_open_dg(call_sid, restaurant_id, on_final):
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

    async def fake_open_dg(call_sid, restaurant_id, on_final):
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

    async def fake_open_dg(call_sid, restaurant_id, on_final):
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

    async def fake_open_dg(call_sid, restaurant_id, on_final):
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


