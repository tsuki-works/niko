"""Smoke tests for the FastAPI surface.

Covers the three endpoints exposed today: the service banner, the
liveness probe, and the Twilio Voice webhook. Runs fully in-process via
``TestClient`` — no network, no Cloud Run.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_returns_service_banner():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"service": "niko", "status": "ok"}


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_voice_returns_twiml():
    response = client.post(
        "/voice",
        data={
            "CallSid": "CAtest",
            "From": "+16479058093",
            "To": "+16479058093",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    body = response.text
    assert "<Response>" in body
    assert "<Say" not in body  # greeting is delivered via Deepgram Aura on start event
