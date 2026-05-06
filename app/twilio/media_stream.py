"""Twilio Media Stream WS protocol primitives — outgoing frames only.

Incoming frame parsing (start/media/mark/stop) stays inline in the
WS event-loop in app/telephony/router.py until a second telephony
provider forces a real shape difference.
"""

from __future__ import annotations

import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


async def send_clear(websocket: WebSocket, stream_sid: str | None) -> None:
    """Tell Twilio to flush its audio buffer and stop playback (#74).

    Cancelling the LLM/TTS task only stops generation — bytes already in
    Twilio's buffer keep playing for 1-3 seconds. Twilio's clear event
    drops the buffer in ~80ms. Used by barge-in and post-silence cleanup.
    """
    if not stream_sid:
        return
    try:
        await websocket.send_json({"event": "clear", "streamSid": stream_sid})
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception(
            "clear: failed to send Twilio clear event stream_sid=%s",
            stream_sid,
        )


async def send_mark(
    websocket: WebSocket,
    stream_sid: str | None,
    name: str,
) -> bool:
    """Append a named mark to Twilio's outgoing media stream (#78).

    Twilio echoes the mark back over the WebSocket once its audio buffer
    drains past it — i.e. once the caller has heard everything we sent.
    The auto-hangup path uses this as the precise trigger to begin its
    grace window. Returns True if the send succeeded.
    """
    if not stream_sid:
        return False
    try:
        await websocket.send_json(
            {
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {"name": name},
            }
        )
        return True
    except WebSocketDisconnect:
        return False
    except Exception:
        logger.exception(
            "mark: failed to send mark name=%s stream_sid=%s",
            name,
            stream_sid,
        )
        return False
