"""Smoke tests for the FastAPI surface.

Covers the three endpoints exposed today: the service banner, the
liveness probe, and the Twilio Voice webhook. Runs fully in-process via
``TestClient`` — no network, no Cloud Run.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import restaurants as restaurants_storage

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_restaurants_cache():
    """The /voice tests resolve the demo via the MENU fallback. Clearing
    the cache between tests keeps each test self-contained."""
    yield
    restaurants_storage.clear_cache()


def test_root_returns_service_banner():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"service": "niko", "status": "ok"}


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_voice_returns_twiml(monkeypatch):
    """Inbound to the demo Twilio number resolves via the MENU fallback
    (Firestore returns None in unit tests) and opens a Media Stream."""
    monkeypatch.setattr(
        restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None
    )
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
