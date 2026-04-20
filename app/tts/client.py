"""ElevenLabs TTS client for the niko voice agent.

Streams LLM reply text through ElevenLabs and pipes mulaw 8 kHz audio
back to the caller via the active Twilio Media Streams WebSocket.

Upgrade path: this module uses the ElevenLabs HTTP streaming API (Option A).
When #40 adds LLM token streaming, upgrade to the ElevenLabs WebSocket API
(Option B) for lower first-audio latency — the speak() signature stays the same.
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

_ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"


def _api_key() -> str:
    key = settings.elevenlabs_api_key
    if not key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY not set — cannot call TTS. "
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
    """Stream ElevenLabs TTS audio back into the Twilio call.

    Requests ulaw_8000 output from ElevenLabs (native mulaw 8 kHz — no
    transcoding needed). Each binary chunk is base64-encoded and sent as
    a Twilio ``media`` WebSocket event immediately, keeping latency low.

    Args:
        text:       LLM reply text to synthesize.
        websocket:  Active Twilio Media Streams WebSocket.
        stream_sid: Twilio streamSid from the ``start`` event.
        client:     Optional injected httpx.AsyncClient (for unit tests).
    """
    if not text.strip():
        return

    key = _api_key()
    voice_id = settings.elevenlabs_voice_id
    model_id = settings.elevenlabs_model_id
    url = f"{_ELEVENLABS_BASE}/text-to-speech/{voice_id}/stream"

    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
    }
    body = {
        "text": text,
        "model_id": model_id,
        "output_format": "ulaw_8000",
    }

    created_client = client is None
    _client = client or httpx.AsyncClient()

    try:
        async with _client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                error_body = await response.aread()
                raise RuntimeError(
                    f"ElevenLabs returned {response.status_code}: "
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
