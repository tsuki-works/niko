"""Twilio telephony endpoints.

POST /voice        — TwiML webhook: answers the inbound call, opens a
                     Twilio Media Stream so the STT→LLM→TTS pipeline can
                     take over.  The AI greeting is delivered via Deepgram
                     Aura on the 'start' event rather than a static TwiML
                     <Say>.

WS   /media-stream — Receives the Twilio Media Stream over WebSocket and
                     runs the full call loop:
                       Deepgram transcript → stream_reply() → speak()
                     Supports barge-in (new transcript cancels in-flight TTS)
                     and a 10-second silence watchdog.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.config import settings
from app.llm.client import stream_reply
from app.orders.lifecycle import OrderNotReadyError, persist_on_confirm
from app.orders.models import Order
from app.tts.client import speak

router = APIRouter()
logger = logging.getLogger(__name__)

SILENCE_TIMEOUT_SECONDS = 10.0
SILENCE_PROMPT = "Are you still there?"
GREETING_TRANSCRIPT = "[call started — greet the caller]"


@dataclass
class _CallState:
    call_sid:     str | None       = None
    stream_sid:   str | None       = None
    order:        Order | None     = None
    history:      list[dict]       = field(default_factory=list)
    llm_task:     asyncio.Task | None = None   # current LLM→TTS turn
    silence_task: asyncio.Task | None = None   # silence watchdog


async def _open_deepgram_connection(call_sid: str | None, on_final: Callable):
    assert settings.deepgram_api_key, "DEEPGRAM_API_KEY is not set"

    dg = DeepgramClient(settings.deepgram_api_key)
    conn = dg.listen.asynclive.v("1")

    async def on_transcript(self, result, **kwargs):
        alt = result.channel.alternatives[0]
        text = alt.transcript.strip()
        if not text:
            return
        label = "final" if result.is_final else "interim"
        logger.info("transcript [%s] call_sid=%s text=%r", label, call_sid, text)
        if result.is_final:
            asyncio.get_event_loop().create_task(on_final(text))

    async def on_error(self, error, **kwargs):
        logger.error("deepgram error call_sid=%s error=%s", call_sid, error)

    conn.on(LiveTranscriptionEvents.Transcript, on_transcript)
    conn.on(LiveTranscriptionEvents.Error, on_error)

    options = LiveOptions(
        model="nova-2",
        encoding="mulaw",
        sample_rate=8000,
        channels=1,
        interim_results=True,
        endpointing=300,
    )
    started = await conn.start(options)
    if not started:
        raise RuntimeError(f"Deepgram connection failed to start call_sid={call_sid}")
    return conn


async def _silence_watchdog(state: _CallState, websocket: WebSocket) -> None:
    try:
        await asyncio.sleep(SILENCE_TIMEOUT_SECONDS)
        logger.info("silence timeout call_sid=%s", state.call_sid)
        if state.stream_sid:
            await speak(SILENCE_PROMPT, websocket, state.stream_sid)
    except asyncio.CancelledError:
        pass


def _cancel_silence_task(state: _CallState) -> None:
    if state.silence_task and not state.silence_task.done():
        state.silence_task.cancel()
    state.silence_task = None


def _arm_silence_watchdog(state: _CallState, websocket: WebSocket) -> None:
    if state.llm_task and state.llm_task.cancelled():
        return  # barge-in — caller spoke again, no watchdog needed
    _cancel_silence_task(state)
    state.silence_task = asyncio.get_event_loop().create_task(
        _silence_watchdog(state, websocket)
    )


async def _run_llm_tts_turn(
    transcript: str, state: _CallState, websocket: WebSocket
) -> None:
    turn_start = time.monotonic()
    logger.info("llm_turn start call_sid=%s transcript=%r", state.call_sid, transcript)
    text_buffer: list[str] = []
    first_speak = True

    try:
        async for event in stream_reply(
            transcript=transcript, history=state.history, order=state.order
        ):
            if asyncio.current_task().cancelled():
                return

            if event.text_delta is not None:
                text_buffer.append(event.text_delta)
                if event.text_delta.endswith((".", "?", "!")):
                    chunk = "".join(text_buffer).strip()
                    text_buffer.clear()
                    if chunk and state.stream_sid:
                        if first_speak:
                            logger.info(
                                "llm_turn first_audio latency=%.3fs call_sid=%s",
                                time.monotonic() - turn_start,
                                state.call_sid,
                            )
                            first_speak = False
                        await speak(chunk, websocket, state.stream_sid)

            elif event.final is not None:
                remainder = "".join(text_buffer).strip()
                text_buffer.clear()
                if remainder and state.stream_sid:
                    if first_speak:
                        logger.info(
                            "llm_turn first_audio latency=%.3fs call_sid=%s",
                            time.monotonic() - turn_start,
                            state.call_sid,
                        )
                    await speak(remainder, websocket, state.stream_sid)
                state.history = event.final.history
                state.order = event.final.order

    except asyncio.CancelledError:
        logger.info("llm_turn cancelled (barge-in) call_sid=%s", state.call_sid)
        raise


async def _handle_final_transcript(
    text: str, state: _CallState, websocket: WebSocket
) -> None:
    if state.llm_task and not state.llm_task.done():
        state.llm_task.cancel()
    _cancel_silence_task(state)
    state.llm_task = asyncio.create_task(
        _run_llm_tts_turn(text, state, websocket)
    )
    state.llm_task.add_done_callback(
        lambda _t: _arm_silence_watchdog(state, websocket)
    )


@router.post("/voice")
async def voice(request: Request) -> Response:
    """Respond to Twilio's inbound call webhook with TwiML.

    Opens a bidirectional Media Stream back to /media-stream.  The AI
    greeting is delivered via Deepgram Aura on the 'start' WebSocket event
    rather than a static TwiML <Say>, so the caller hears the same voice
    for the entire call.

    The WebSocket URL is derived from the ``Host`` header so the same code
    works under ngrok locally and on Cloud Run in production.
    """
    host = request.headers.get("host", "localhost:8000")
    twiml = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{host}/media-stream")
    twiml.append(connect)
    return Response(content=str(twiml), media_type="application/xml")


@router.websocket("/media-stream")
async def media_stream(websocket: WebSocket) -> None:
    """Full call loop: Twilio Media Stream → Deepgram STT → LLM → Deepgram Aura TTS.

    Twilio event types:
      connected  — protocol handshake
      start      — stream open; initialises Order, opens Deepgram, fires AI greeting
      media      — base64 mulaw 8 kHz audio forwarded to Deepgram
      stop       — call ended; persists completed orders to Firestore
    """
    await websocket.accept()
    state = _CallState()
    dg_conn = None

    async def on_final(text: str) -> None:
        await _handle_final_transcript(text, state, websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            msg: dict = json.loads(raw)
            event = msg.get("event")

            if event == "connected":
                logger.info("media-stream connected protocol=%s", msg.get("protocol"))

            elif event == "start":
                start = msg.get("start", {})
                state.call_sid = start.get("callSid")
                state.stream_sid = start.get("streamSid")
                state.order = Order(call_sid=state.call_sid or "unknown")
                logger.info(
                    "media-stream start call_sid=%s stream_sid=%s",
                    state.call_sid,
                    state.stream_sid,
                )
                dg_conn = await _open_deepgram_connection(state.call_sid, on_final)
                state.llm_task = asyncio.create_task(
                    _run_llm_tts_turn(GREETING_TRANSCRIPT, state, websocket)
                )
                state.llm_task.add_done_callback(
                    lambda _t: _arm_silence_watchdog(state, websocket)
                )

            elif event == "media":
                if dg_conn is not None:
                    audio = base64.b64decode(msg["media"]["payload"])
                    await dg_conn.send(audio)

            elif event == "stop":
                logger.info("media-stream stop call_sid=%s", state.call_sid)
                # Let the in-flight LLM turn finish so we capture the final order state
                if state.llm_task and not state.llm_task.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(state.llm_task), timeout=10.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                        pass
                break

    except WebSocketDisconnect:
        logger.info("media-stream disconnected call_sid=%s", state.call_sid)
    finally:
        _cancel_silence_task(state)
        if state.llm_task and not state.llm_task.done():
            state.llm_task.cancel()
            try:
                await state.llm_task
            except (asyncio.CancelledError, Exception):
                pass
        if state.order and state.order.is_ready_to_confirm():
            try:
                persist_on_confirm(state.order)
                logger.info("order confirmed call_sid=%s", state.call_sid)
            except (OrderNotReadyError, Exception) as exc:
                logger.error(
                    "order persist failed call_sid=%s: %s", state.call_sid, exc
                )
        if dg_conn is not None:
            await dg_conn.finish()
