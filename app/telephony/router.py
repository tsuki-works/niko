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
from app.orders.models import Order, OrderStatus
from app.storage import call_sessions
from app.tts.client import speak

router = APIRouter()
logger = logging.getLogger(__name__)

SILENCE_TIMEOUT_SECONDS = 10.0
SILENCE_PROMPT = "Are you still there?"
GREETING_TRANSCRIPT = "[call started — greet the caller]"

# Auto-hangup after order confirmation (#78). Twilio echoes back this
# named mark when its audio buffer drains, signalling the caller has
# heard the goodbye; we then hold for the grace window in case they
# squeeze in a late question before terminating the call.
END_OF_CALL_MARK = "end_of_call"
HANGUP_GRACE_SECONDS = 3.0

# Phrases the model uses when wrapping up. Used as a fallback signal
# for auto-hangup when Haiku says a goodbye but forgets to mark the
# order status as confirmed via update_order (#79). Matched
# case-insensitive against the full assembled reply.
_GOODBYE_PATTERNS = (
    "your order is in",
    "have it ready",
    "see you soon",
    "see you in a",
    "thanks for calling",
    "thanks for ordering",
    "have a great day",
    "have a good day",
    "enjoy your",
    "coming right up",
)


def _looks_like_goodbye(reply: str) -> bool:
    """True if ``reply`` reads as a terminal wrap-up rather than another
    follow-up question. Combined with ``Order.is_ready_to_confirm`` this
    is the fallback trigger for auto-hangup."""
    if not reply:
        return False
    stripped = reply.strip()
    if stripped.endswith("?"):
        return False
    lower = stripped.lower()
    return any(pat in lower for pat in _GOODBYE_PATTERNS)


def _bg_call_event(call_sid: str | None, **kwargs) -> None:
    """Fire-and-forget Firestore write so the audio loop never blocks on it.

    The storage module catches its own exceptions, so failures here just
    drop the event from the live dashboard — the call continues normally.
    """
    if not call_sid:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(asyncio.to_thread(call_sessions.record_event, call_sid, **kwargs))


def _twilio_end_call_sync(call_sid: str) -> None:
    """End a Twilio call via the REST API. Runs in a worker thread so the
    audio loop never blocks on network I/O."""
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    if not sid or not token:
        logger.warning(
            "twilio creds missing; cannot end call_sid=%s", call_sid
        )
        return
    from twilio.rest import Client as TwilioRestClient

    TwilioRestClient(sid, token).calls(call_sid).update(status="completed")


async def send_end_of_call_mark(
    websocket: WebSocket, stream_sid: str | None
) -> bool:
    """Append a named ``mark`` event to Twilio's outgoing media stream.

    Twilio echoes the same mark back over the WebSocket once its audio
    buffer drains past it — i.e. once the caller has heard everything
    we sent. We use that as the precise trigger for auto-hangup (#78).
    Returns True if the send succeeded.
    """
    if not stream_sid:
        return False
    try:
        await websocket.send_json(
            {
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {"name": END_OF_CALL_MARK},
            }
        )
        return True
    except WebSocketDisconnect:
        return False
    except Exception:
        logger.exception(
            "mark: failed to send end_of_call mark stream_sid=%s", stream_sid
        )
        return False


async def _hang_up_after_grace(state: _CallState) -> None:
    """Wait HANGUP_GRACE_SECONDS, then end the call IFF the caller
    didn't speak in the meantime.

    The grace window lets a caller squeeze in a late follow-up like
    *"how long does that take?"* — a final transcript clears
    ``state.pending_hangup`` and we abort.
    """
    try:
        await asyncio.sleep(HANGUP_GRACE_SECONDS)
    except asyncio.CancelledError:
        return
    if not state.pending_hangup or not state.call_sid:
        return
    try:
        await asyncio.to_thread(_twilio_end_call_sync, state.call_sid)
        logger.info("call ended by server call_sid=%s", state.call_sid)
    except Exception:
        logger.exception(
            "auto-hangup: REST end_call failed call_sid=%s", state.call_sid
        )


def _abort_pending_hangup(state: _CallState) -> None:
    """Cancel a pending auto-hangup because the caller spoke during
    the grace window. Safe to call when no hangup is pending."""
    state.pending_hangup = False
    if state.hangup_task and not state.hangup_task.done():
        state.hangup_task.cancel()
    state.hangup_task = None


async def clear_twilio_audio(websocket: WebSocket, stream_sid: str | None) -> None:
    """Tell Twilio to flush its audio buffer and stop playback.

    Cancelling the LLM task only stops *generation* of new audio — bytes
    already in Twilio's buffer keep playing for another 1–3 seconds, which
    is exactly what callers experience as "the bot doesn't pause when I
    interrupt." Twilio's Media Streams API has a dedicated ``clear`` event
    that drops the buffer in ~80ms; we fire it whenever we cancel an
    in-flight reply (#74).
    """
    if not stream_sid:
        return
    try:
        await websocket.send_json({"event": "clear", "streamSid": stream_sid})
    except WebSocketDisconnect:
        # Caller already hung up — nothing to clear.
        return
    except Exception:
        # Don't let a transient send failure break the call loop.
        logger.exception("clear: failed to send Twilio clear event stream_sid=%s", stream_sid)


@dataclass
class _CallState:
    call_sid:     str | None       = None
    stream_sid:   str | None       = None
    order:        Order | None     = None
    history:      list[dict]       = field(default_factory=list)
    llm_task:     asyncio.Task | None = None   # current LLM→TTS turn
    silence_task: asyncio.Task | None = None   # silence watchdog
    hangup_task:  asyncio.Task | None = None   # pending auto-hangup (#78)
    pending_hangup: bool           = False     # set when goodbye mark sent (#78)


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
            _bg_call_event(
                call_sid, kind="transcript_final", text=text, detail={"text": text}
            )
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
        _bg_call_event(state.call_sid, kind="silence_timeout")
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
    _bg_call_event(
        state.call_sid,
        kind="llm_turn_start",
        text=transcript,
        detail={"transcript": transcript},
    )
    text_buffer: list[str] = []
    first_speak = True
    full_reply_parts: list[str] = []

    def _record_first_audio() -> None:
        latency = time.monotonic() - turn_start
        logger.info(
            "llm_turn first_audio latency=%.3fs call_sid=%s",
            latency,
            state.call_sid,
        )
        _bg_call_event(
            state.call_sid,
            kind="first_audio",
            detail={"latency_seconds": round(latency, 3)},
        )

    try:
        async for event in stream_reply(
            transcript=transcript, history=state.history, order=state.order
        ):
            if asyncio.current_task().cancelled():
                return

            if event.text_delta is not None:
                text_buffer.append(event.text_delta)
                full_reply_parts.append(event.text_delta)
                if event.text_delta.endswith((".", "?", "!")):
                    chunk = "".join(text_buffer).strip()
                    text_buffer.clear()
                    if chunk and state.stream_sid:
                        if first_speak:
                            _record_first_audio()
                            first_speak = False
                        await speak(chunk, websocket, state.stream_sid)

            elif event.final is not None:
                remainder = "".join(text_buffer).strip()
                text_buffer.clear()
                if remainder and state.stream_sid:
                    if first_speak:
                        _record_first_audio()
                    await speak(remainder, websocket, state.stream_sid)
                state.history = event.final.history
                state.order = event.final.order
                full_reply = "".join(full_reply_parts).strip()
                if full_reply:
                    _bg_call_event(
                        state.call_sid,
                        kind="agent_reply",
                        text=full_reply,
                        detail={"text": full_reply},
                    )
                # Decide whether this turn is the wrap-up. Two signals:
                #  1. Haiku set status=confirmed via update_order (the
                #     primary path the prompt asks for).
                #  2. Fallback (#79) — Haiku emitted a goodbye-shaped
                #     reply ("your order is in", "see you soon", etc.)
                #     AND the order has the data to actually confirm.
                #     The model sometimes says the right closing line
                #     without remembering to flip status.
                if state.order is not None and state.stream_sid:
                    explicitly_confirmed = (
                        state.order.status == OrderStatus.CONFIRMED
                    )
                    fallback_confirmed = (
                        state.order.is_ready_to_confirm()
                        and state.order.status != OrderStatus.CANCELLED
                        and _looks_like_goodbye(full_reply)
                    )
                    if explicitly_confirmed or fallback_confirmed:
                        if fallback_confirmed and not explicitly_confirmed:
                            logger.info(
                                "auto-hangup: heuristic wrap-up detected "
                                "(LLM didn't set status=confirmed) call_sid=%s",
                                state.call_sid,
                            )
                            # Mirror the explicit-confirmation path locally
                            # so the finally-block persist sees it too.
                            state.order = state.order.model_copy(
                                update={"status": OrderStatus.CONFIRMED}
                            )
                        sent = await send_end_of_call_mark(
                            websocket, state.stream_sid
                        )
                        if sent:
                            state.pending_hangup = True

    except asyncio.CancelledError:
        logger.info("llm_turn cancelled (barge-in) call_sid=%s", state.call_sid)
        _bg_call_event(state.call_sid, kind="barge_in")
        raise
    except Exception as exc:
        logger.exception("llm_turn errored call_sid=%s", state.call_sid)
        _bg_call_event(
            state.call_sid,
            kind="error",
            text=str(exc)[:500],
            detail={"exception": type(exc).__name__},
        )
        raise


async def _handle_final_transcript(
    text: str, state: _CallState, websocket: WebSocket
) -> None:
    interrupted = bool(state.llm_task and not state.llm_task.done())
    if state.llm_task and not state.llm_task.done():
        state.llm_task.cancel()
    silence_was_active = bool(
        state.silence_task and not state.silence_task.done()
    )
    _cancel_silence_task(state)
    # Caller spoke — abort any pending auto-hangup (#78). Even if they
    # spoke during the grace window after a confirmation, we want to
    # keep the call alive and process this transcript.
    _abort_pending_hangup(state)
    if interrupted or silence_was_active:
        # Drop Twilio's pending audio buffer so the caller actually hears
        # us pause instead of getting talked over (#74).
        await clear_twilio_audio(websocket, state.stream_sid)
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
                if state.call_sid:
                    asyncio.get_running_loop().create_task(
                        asyncio.to_thread(
                            call_sessions.init_call_session, state.call_sid
                        )
                    )
                    _bg_call_event(
                        state.call_sid,
                        kind="start",
                        detail={"stream_sid": state.stream_sid or ""},
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

            elif event == "mark":
                # Twilio echoes our outgoing marks once the audio queued
                # before them has finished playing. We use it to drive
                # auto-hangup after order confirmation (#78).
                mark_name = msg.get("mark", {}).get("name")
                if mark_name == END_OF_CALL_MARK and state.pending_hangup:
                    logger.info(
                        "auto-hangup: end_of_call mark received call_sid=%s",
                        state.call_sid,
                    )
                    if state.hangup_task and not state.hangup_task.done():
                        state.hangup_task.cancel()
                    state.hangup_task = asyncio.create_task(
                        _hang_up_after_grace(state)
                    )

            elif event == "stop":
                logger.info("media-stream stop call_sid=%s", state.call_sid)
                _bg_call_event(state.call_sid, kind="stop")
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
        # Auto-hangup: stop any pending grace-window timer; the call is
        # already ending so we don't need to fire the REST close (#78).
        _abort_pending_hangup(state)
        if state.llm_task and not state.llm_task.done():
            state.llm_task.cancel()
            try:
                await state.llm_task
            except (asyncio.CancelledError, Exception):
                pass
        order_confirmed = False
        if state.order and state.order.is_ready_to_confirm():
            try:
                persist_on_confirm(state.order)
                logger.info("order confirmed call_sid=%s", state.call_sid)
                _bg_call_event(state.call_sid, kind="order_confirmed")
                order_confirmed = True
            except (OrderNotReadyError, Exception) as exc:
                logger.error(
                    "order persist failed call_sid=%s: %s", state.call_sid, exc
                )
        if state.call_sid:
            try:
                await asyncio.to_thread(
                    call_sessions.mark_call_ended,
                    state.call_sid,
                    confirmed=order_confirmed,
                )
            except Exception:
                logger.exception(
                    "call_sessions: mark_call_ended scheduling failed call_sid=%s",
                    state.call_sid,
                )
        if dg_conn is not None:
            await dg_conn.finish()
