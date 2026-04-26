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

client = TestClient(app)

_START_MSG = {
    "event": "start",
    "start": {
        "callSid": "CAtest123",
        "streamSid": "MZtest456",
        "accountSid": "ACtest",
        "tracks": ["inbound"],
        "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
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

    async def fake_open_dg(call_sid, on_final):
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


def test_voice_returns_xml():
    response = client.post("/voice", data={"CallSid": "CAtest", "From": "+10000000000"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")


def test_voice_twiml_contains_media_stream_no_say():
    response = client.post("/voice", data={"CallSid": "CAtest", "From": "+10000000000"})
    body = response.text
    assert "<Response>" in body
    assert "<Say" not in body          # greeting is now via ElevenLabs on start event
    assert "<Connect>" in body
    assert "<Stream" in body
    # TestClient sets Host: testserver
    assert "wss://testserver/media-stream" in body


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

    async def fake_open_dg(call_sid, on_final):
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

    async def fake_open_dg(call_sid, on_final):
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

    async def fake_open_dg(call_sid, on_final):
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
