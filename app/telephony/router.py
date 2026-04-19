"""Twilio telephony endpoints.

POST /voice        — TwiML webhook: answers the inbound call, plays a
                     brief greeting, then opens a Twilio Media Stream so
                     the STT→LLM→TTS pipeline can take over.

WS   /media-stream — Receives the Twilio Media Stream over WebSocket.
                     Each frame is a JSON envelope; the ``media`` event
                     carries base64-encoded mulaw 8 kHz audio. STT
                     integration lands in #38 — this handler logs
                     lifecycle events and proves the WebSocket
                     round-trip works end-to-end.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from twilio.twiml.voice_response import Connect, VoiceResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/voice")
async def voice(request: Request) -> Response:
    """Respond to Twilio's inbound call webhook with TwiML.

    Plays a short greeting, then instructs Twilio to open a bidirectional
    Media Stream back to /media-stream so the voice pipeline can receive
    raw caller audio.  The WebSocket URL is derived from the ``Host``
    header so the same code works under ngrok locally and Cloud Run in
    production without any config change.
    """
    host = request.headers.get("host", "localhost:8000")
    ws_url = f"wss://{host}/media-stream"

    twiml = VoiceResponse()
    twiml.say(
        "Thank you for calling. Please hold while we connect your call.",
        voice="alice",
    )
    connect = Connect()
    connect.stream(url=ws_url)
    twiml.append(connect)

    return Response(content=str(twiml), media_type="application/xml")


@router.websocket("/media-stream")
async def media_stream(websocket: WebSocket) -> None:
    """Receive Twilio Media Stream audio frames over WebSocket.

    Twilio sends JSON-enveloped messages with these event types:
      connected  — initial protocol handshake (no call state yet)
      start      — stream open; carries callSid, streamSid, track info
      media      — base64-encoded mulaw 8 kHz audio, 20 ms per chunk
      stop       — call ended; Twilio is closing the stream

    POC: logs lifecycle events; silently discards media frames until the
    Deepgram STT loop is wired in (#38).
    """
    await websocket.accept()
    call_sid: str | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            msg: dict = json.loads(raw)
            event = msg.get("event")

            if event == "connected":
                logger.info("media-stream connected protocol=%s", msg.get("protocol"))

            elif event == "start":
                start = msg.get("start", {})
                call_sid = start.get("callSid")
                stream_sid = start.get("streamSid")
                logger.info(
                    "media-stream start call_sid=%s stream_sid=%s",
                    call_sid,
                    stream_sid,
                )

            elif event == "media":
                # base64 mulaw 8 kHz; consumed by Deepgram STT in #38
                pass

            elif event == "stop":
                logger.info("media-stream stop call_sid=%s", call_sid)
                break

    except WebSocketDisconnect:
        logger.info("media-stream disconnected call_sid=%s", call_sid)
