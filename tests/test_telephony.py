"""Tests for Twilio telephony endpoints.

Covers POST /voice (TwiML with Media Stream connect) and
WS /media-stream (Twilio Media Stream receiver).  Runs fully
in-process via TestClient — no Twilio account or network required.
"""

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# POST /voice
# ---------------------------------------------------------------------------


def test_voice_returns_xml():
    response = client.post("/voice", data={"CallSid": "CAtest", "From": "+10000000000"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")


def test_voice_twiml_contains_greeting_and_media_stream():
    response = client.post("/voice", data={"CallSid": "CAtest", "From": "+10000000000"})
    body = response.text
    assert "<Response>" in body
    assert "<Say" in body
    assert "<Connect>" in body
    assert "<Stream" in body
    # TestClient sets Host: testserver
    assert "wss://testserver/media-stream" in body


# ---------------------------------------------------------------------------
# WS /media-stream
# ---------------------------------------------------------------------------


def test_media_stream_accepts_connection():
    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps({"event": "stop"}))


def test_media_stream_handles_full_call_lifecycle():
    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({
            "event": "connected",
            "protocol": "Call",
            "version": "1.0.0",
        }))
        ws.send_text(json.dumps({
            "event": "start",
            "start": {
                "callSid": "CAtest123",
                "streamSid": "MZtest456",
                "accountSid": "ACtest",
                "tracks": ["inbound"],
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            },
        }))
        ws.send_text(json.dumps({
            "event": "media",
            "media": {
                "track": "inbound",
                "chunk": "1",
                "timestamp": "5",
                "payload": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz012345678=",
            },
        }))
        ws.send_text(json.dumps({
            "event": "stop",
            "stop": {"accountSid": "ACtest", "callSid": "CAtest123"},
        }))
        # No exception raised = handler completed cleanly


def test_media_stream_tolerates_unknown_events():
    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "mark", "mark": {"name": "my_mark"}}))
        ws.send_text(json.dumps({"event": "stop"}))
