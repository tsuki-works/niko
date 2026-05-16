"""Smoke tests for the FastAPI surface.

Covers the three endpoints exposed today: the service banner, the
liveness probe, and the Twilio Voice webhook. Runs fully in-process via
``TestClient`` — no network, no Cloud Run.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import restaurants as restaurants_storage
from app.telephony import router as telephony_router

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
    monkeypatch.setattr(restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None)
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


def test_voice_schedules_cache_primer_for_resolved_tenant(monkeypatch):
    """The /voice handler exploits the ~300-500 ms TwiML → WS-connect
    window by firing a max_tokens=1 primer to warm the Anthropic prompt
    cache for this tenant before T2 needs it (#192)."""
    monkeypatch.setattr(restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None)
    primer_mock = AsyncMock()
    monkeypatch.setattr(telephony_router, "prime_tenant_cache", primer_mock)

    response = client.post(
        "/voice",
        data={"CallSid": "CAtest", "From": "+16479058093", "To": "+16479058093"},
    )

    assert response.status_code == 200
    # The primer was scheduled (called) for the resolved tenant. We don't
    # await the task inside /voice — TestClient drains pending tasks on
    # response, so by the time we assert, the AsyncMock has been awaited.
    assert primer_mock.await_count == 1
    rid = primer_mock.await_args.args[0].id
    assert rid == restaurants_storage.DEMO_RID


def test_voice_does_not_schedule_primer_when_tenant_unknown(monkeypatch):
    """Unknown Twilio number → 'unconfigured' hangup TwiML. No primer
    because there's no system prompt to prime against."""
    monkeypatch.setattr(restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None)
    # Make demo fallback fail so the resolver returns None.
    monkeypatch.setattr(
        telephony_router,
        "_resolve_restaurant_for_voice",
        lambda _e164: None,
    )
    primer_mock = AsyncMock()
    monkeypatch.setattr(telephony_router, "prime_tenant_cache", primer_mock)

    response = client.post(
        "/voice",
        data={"CallSid": "CAtest", "From": "+10000000000", "To": "+19999999999"},
    )

    assert response.status_code == 200
    assert primer_mock.await_count == 0


def test_voice_primer_does_not_block_response(monkeypatch):
    """Anthropic primer call must not be awaited inline — even a slow
    primer must not delay the TwiML response that Twilio is waiting for."""
    monkeypatch.setattr(restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None)

    started = asyncio.Event()
    block = asyncio.Event()

    async def _slow_primer(_restaurant):
        started.set()
        await block.wait()

    monkeypatch.setattr(telephony_router, "prime_tenant_cache", _slow_primer)
    try:
        response = client.post(
            "/voice",
            data={
                "CallSid": "CAtest",
                "From": "+16479058093",
                "To": "+16479058093",
            },
        )
        assert response.status_code == 200
        # If the handler awaited the primer, the request would hang forever
        # (block is never set). Reaching this line proves it didn't.
    finally:
        block.set()


def test_voice_primer_exception_does_not_propagate(monkeypatch):
    """Even if the primer task raises, the /voice TwiML response is
    untouched. ``prime_tenant_cache`` swallows internally; this guard
    is defense in depth in case a future refactor leaks an exception."""
    monkeypatch.setattr(restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None)

    async def _boom(_restaurant):
        raise RuntimeError("boom")

    monkeypatch.setattr(telephony_router, "prime_tenant_cache", _boom)

    response = client.post(
        "/voice",
        data={"CallSid": "CAtest", "From": "+16479058093", "To": "+16479058093"},
    )
    assert response.status_code == 200
