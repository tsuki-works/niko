"""Tests for app/tts and app/stt selector functions.

Confirms the configured provider is dispatched to and unknown providers
raise. STT-side selector tests are added when get_stt() lands.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings


@pytest.mark.asyncio
async def test_speak_dispatches_to_deepgram_when_provider_is_deepgram(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "deepgram")
    fake_speak = AsyncMock()
    monkeypatch.setattr("app.deepgram.tts.speak", fake_speak)

    from app.tts import speak

    ws = MagicMock()
    await speak("hi", ws, "MZ1")
    fake_speak.assert_awaited_once()


@pytest.mark.asyncio
async def test_speak_raises_for_unknown_tts_provider(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "elevenlabs-not-implemented")
    from app.tts import speak

    ws = MagicMock()
    with pytest.raises(ValueError, match="Unknown TTS provider"):
        await speak("hi", ws, "MZ1")


def test_get_stt_returns_deepgram_by_default(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "deepgram")
    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")

    from app.deepgram.stt import DeepgramSTT
    from app.stt import get_stt

    provider, name = get_stt(call_sid="CAtest")
    assert isinstance(provider, DeepgramSTT)
    assert name == "deepgram"


def test_get_stt_raises_for_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "whisper-not-implemented")
    from app.stt import get_stt

    with pytest.raises(ValueError, match="Unknown STT provider"):
        get_stt(call_sid="CAtest")


def test_get_stt_forwards_keyterms_to_deepgram_provider(monkeypatch):
    """The selector must thread ``keyterms`` into DeepgramSTT so the
    per-tenant heuristic output reaches Flux on connect. A regression
    here would silently drop the menu bias on every call."""
    monkeypatch.setattr(settings, "stt_provider", "deepgram")
    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")

    from app.stt import get_stt

    provider, _name = get_stt(
        call_sid="CAtest",
        keyterms=["Twilight Family Restaurant", "Pepper Shrimp"],
    )
    # DeepgramSTT exposes the resolved list via its private attribute;
    # the selector test pins that the constructor argument flowed
    # through unchanged.
    assert provider._keyterms_arg == [
        "Twilight Family Restaurant",
        "Pepper Shrimp",
    ]


def test_get_stt_default_keyterms_is_none(monkeypatch):
    """Callers who don't provide keyterms get a clean default — no
    accidental empty-list shenanigans, no global state."""
    monkeypatch.setattr(settings, "stt_provider", "deepgram")
    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")

    from app.stt import get_stt

    provider, _name = get_stt(call_sid="CAtest")
    assert provider._keyterms_arg is None
