"""Tests for the Twilio request-signature validation dependency (#179).

All tests run in-process via TestClient. No real Twilio credentials
required — valid signatures are computed with a test auth token.
"""

import hashlib
import hmac
import base64
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.storage import restaurants as restaurants_storage

client = TestClient(app, raise_server_exceptions=False)

_TEST_TOKEN = "test_auth_token_12345"
_BASE_URL = "https://niko.example.com"
_VOICE_URL = f"{_BASE_URL}/voice"
_FORM = {"CallSid": "CAtest", "From": "+10000000000", "To": "+16479058093"}


def _twilio_signature(auth_token: str, url: str, params: dict) -> str:
    """Compute the expected X-Twilio-Signature for a webhook call."""
    s = url
    for key in sorted(params.keys()):
        s += key + params[key]
    mac = hmac.new(auth_token.encode("utf-8"), s.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode("utf-8")


@pytest.fixture(autouse=True)
def _reset_restaurants_cache():
    yield
    restaurants_storage.clear_cache()


@pytest.fixture(autouse=True)
def _reset_bypass_warning():
    import app.telephony.signature as sig_mod
    sig_mod._bypass_warned = False
    yield
    sig_mod._bypass_warned = False


@pytest.fixture()
def validation_enabled(monkeypatch):
    monkeypatch.setattr(settings, "testing_mode", False)
    monkeypatch.setattr(settings, "twilio_auth_token", _TEST_TOKEN)
    monkeypatch.setattr(settings, "public_base_url", _BASE_URL)


def test_valid_signature_passes(validation_enabled):
    sig = _twilio_signature(_TEST_TOKEN, _VOICE_URL, _FORM)
    resp = client.post("/voice", data=_FORM, headers={"X-Twilio-Signature": sig})
    assert resp.status_code != 403


def test_invalid_signature_returns_403(validation_enabled):
    resp = client.post(
        "/voice",
        data=_FORM,
        headers={"X-Twilio-Signature": "invalidsignature=="},
    )
    assert resp.status_code == 403


def test_missing_signature_returns_403(validation_enabled):
    resp = client.post("/voice", data=_FORM)
    assert resp.status_code == 403


def test_testing_mode_bypasses_validation(monkeypatch):
    monkeypatch.setattr(settings, "testing_mode", True)
    monkeypatch.setattr(settings, "twilio_auth_token", _TEST_TOKEN)
    monkeypatch.setattr(settings, "public_base_url", _BASE_URL)
    resp = client.post("/voice", data=_FORM)
    assert resp.status_code != 403
