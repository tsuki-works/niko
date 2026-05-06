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
