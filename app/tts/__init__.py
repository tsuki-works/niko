"""Public entry point for the TTS abstraction layer.

Dispatches to the configured provider. Today only Deepgram is wired in;
adding ElevenLabs or another HTTP-streaming TTS is a one-clause addition
to ``speak()`` plus a new ``app/<vendor>/tts.py`` matching the SpeakFunc
contract from ``app/tts/base.py``.
"""

from __future__ import annotations

from typing import Callable, Optional

import httpx
from fastapi import WebSocket

from app.config import settings
from app.tts.base import SpeakFunc

__all__ = ["SpeakFunc", "speak"]


async def speak(
    text: str,
    websocket: WebSocket,
    stream_sid: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    on_chunk: Optional[Callable[[bytes], None]] = None,
    on_first_byte: Optional[Callable[[], None]] = None,
) -> None:
    """Synthesize ``text`` through the configured TTS provider and stream
    audio into the Twilio call via ``websocket``."""
    provider = settings.tts_provider
    if provider == "deepgram":
        from app.deepgram.tts import speak as _speak

        return await _speak(
            text,
            websocket,
            stream_sid,
            client=client,
            on_chunk=on_chunk,
            on_first_byte=on_first_byte,
        )
    raise ValueError(f"Unknown TTS provider: {provider}")
