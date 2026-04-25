"""Deepgram Aura TTS client for the niko voice agent.

Streams LLM reply text through Deepgram Aura and pipes mulaw 8 kHz audio
back to the caller via the active Twilio Media Streams WebSocket.

Why Deepgram Aura (over ElevenLabs):
  - Server-to-server design — no abuse detector that blocks Cloud Run egress.
  - Native ``mulaw`` 8 kHz output — drop-in for Twilio Media Streams.
  - Reuses the Deepgram API key already in use for STT.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import httpx
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.config import settings

logger = logging.getLogger(__name__)

_DEEPGRAM_BASE = "https://api.deepgram.com/v1"


def _api_key() -> str:
    key = settings.deepgram_api_key
    if not key:
        raise RuntimeError(
            "DEEPGRAM_API_KEY not set — cannot call TTS. "
            "Fetch credentials via /shared-creds."
        )
    return key


async def speak(
    text: str,
    websocket: WebSocket,
    stream_sid: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> None:
    """Stream Deepgram Aura TTS audio back into the Twilio call.

    Requests ``encoding=mulaw`` at 8 kHz with no container — raw mulaw
    bytes that Twilio's Media Streams accepts directly. Each binary chunk
    is base64-encoded and sent as a Twilio ``media`` WebSocket event
    immediately, keeping latency low.

    Args:
        text:       LLM reply text to synthesize.
        websocket:  Active Twilio Media Streams WebSocket.
        stream_sid: Twilio streamSid from the ``start`` event.
        client:     Optional injected httpx.AsyncClient (for unit tests).
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

    created_client = client is None
    _client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    )

    try:
        async with _client.stream(
            "POST", url, headers=headers, params=params, json=body
        ) as response:
            if response.status_code != 200:
                error_body = await response.aread()
                logger.error(
                    "tts: Deepgram returned %d stream_sid=%s body=%s",
                    response.status_code,
                    stream_sid,
                    error_body.decode(errors="replace")[:200],
                )
                raise RuntimeError(
                    f"Deepgram returned {response.status_code}: "
                    f"{error_body.decode(errors='replace')}"
                )

            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
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
    finally:
        if created_client:
            await _client.aclose()
