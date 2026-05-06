"""TTS provider contract.

TTS is per-utterance and stateless across calls (an HTTP request that
streams audio bytes back). The contract is therefore a callable signature
rather than a class — same shape works for Deepgram Aura, ElevenLabs,
OpenAI TTS, and similar HTTP-streaming providers.
"""

from __future__ import annotations

from typing import Callable, Optional, Protocol

import httpx
from fastapi import WebSocket


class SpeakFunc(Protocol):
    """Signature any TTS provider implementation must match.

    Args:
        text: LLM reply text to synthesize.
        websocket: Active Twilio Media Streams WebSocket.
        stream_sid: Twilio streamSid from the ``start`` event.
        client: Optional injected httpx.AsyncClient for tests.
        on_chunk: Optional zero-arg sync callable fired with each raw
            audio chunk (mulaw bytes) as it streams in. Used by callers
            that want a copy of the outbound audio (e.g., for recording).
            Exceptions are swallowed by the implementation.
        on_first_byte: Optional zero-arg sync callable fired exactly once
            when the first non-empty chunk arrives. Used to measure TTS
            network latency. Exceptions are swallowed.
    """

    async def __call__(
        self,
        text: str,
        websocket: WebSocket,
        stream_sid: str,
        *,
        client: Optional[httpx.AsyncClient] = None,
        on_chunk: Optional[Callable[[bytes], None]] = None,
        on_first_byte: Optional[Callable[[], None]] = None,
    ) -> None: ...
