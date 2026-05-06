"""Deepgram Aura TTS implementation.

Streams Aura audio through Twilio Media Streams. Implements the SpeakFunc
contract from app/tts/base.py.

Why Deepgram Aura (over ElevenLabs):
  - Server-to-server design — no abuse detector that blocks Cloud Run egress.
  - Native ``mulaw`` 8 kHz output — drop-in for Twilio Media Streams.
  - Reuses the Deepgram API key already in use for STT.
"""

from __future__ import annotations

import base64
import logging
from typing import Callable, Optional

import httpx
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.deepgram import _DEEPGRAM_BASE, _api_key

logger = logging.getLogger(__name__)


# Process-wide reusable client (#151). Constructing an httpx.AsyncClient
# costs a TLS handshake on every speak() call; reusing one across the
# whole process keeps the connection pool warm so subsequent sentence
# chunks skip the handshake. Lazy-initialised so importing this module
# never spins up sockets at startup. Tests reset this between cases via
# a fixture; the real process never needs to.
_default_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _default_client
    if _default_client is None:
        _default_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        )
    return _default_client


async def speak(
    text: str,
    websocket: WebSocket,
    stream_sid: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    on_chunk: Optional[Callable[[bytes], None]] = None,
    on_first_byte: Optional[Callable[[], None]] = None,
) -> None:
    """Stream Deepgram Aura TTS audio back into the Twilio call.

    Requests ``encoding=mulaw`` at 8 kHz with no container — raw mulaw
    bytes that Twilio's Media Streams accepts directly. Each binary chunk
    is base64-encoded and sent as a Twilio ``media`` WebSocket event
    immediately, keeping latency low.
    """
    if not text.strip():
        return

    key = _api_key()
    model = settings.deepgram_tts_model
    url = f"{_DEEPGRAM_BASE}/speak"
    params = {
        "model": model,
        "encoding": "mulaw",
        "sample_rate": "8000",
        "container": "none",
    }

    headers = {
        "Authorization": f"Token {key}",
        "Content-Type": "application/json",
    }
    body = {"text": text}

    _client = client if client is not None else _get_client()
    first_byte_fired = False

    async with _client.stream("POST", url, headers=headers, params=params, json=body) as response:
        if response.status_code != 200:
            error_body = await response.aread()
            logger.error(
                "tts: Deepgram returned %d stream_sid=%s body=%s",
                response.status_code,
                stream_sid,
                error_body.decode(errors="replace")[:200],
            )
            raise RuntimeError(
                f"Deepgram returned {response.status_code}: {error_body.decode(errors='replace')}"
            )

        async for chunk in response.aiter_bytes():
            if not chunk:
                continue
            if not first_byte_fired and on_first_byte is not None:
                first_byte_fired = True
                try:
                    on_first_byte()
                except Exception:
                    logger.exception("tts: on_first_byte callback raised stream_sid=%s", stream_sid)
            payload = base64.b64encode(chunk).decode()
            try:
                await websocket.send_json(
                    {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": payload},
                    }
                )
            except WebSocketDisconnect:
                logger.info("tts: websocket disconnected mid-stream stream_sid=%s", stream_sid)
                return
            if on_chunk is not None:
                try:
                    on_chunk(chunk)
                except Exception:
                    logger.exception("tts: on_chunk callback raised stream_sid=%s", stream_sid)
