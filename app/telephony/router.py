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
from typing import Any, Callable

from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from twilio.twiml.voice_response import Connect, Dial, VoiceResponse

from app.config import settings
from app.llm.client import stream_reply
from app.llm.prompts import build_system_prompt
from app.orders.lifecycle import OrderNotReadyError, persist_on_confirm
from app.orders.models import Order, OrderStatus
from app.restaurants.models import Restaurant
from app.restaurants.open_check import is_open_now
from app.storage import call_sessions, recordings
from app.storage import restaurants as restaurants_storage
from app.storage.recordings import RecordingUploadSession  # noqa: F401  (typing only)
from app.telephony.voicemail_twiml import voicemail_response
from app.tts import speak

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
HANGUP_GRACE_SECONDS = 5.0
# Fallback if Twilio never echoes the end_of_call mark back to us
# (WebSocket dropped, mark lost in transit). After this many seconds
# we trigger the grace window anyway so the call still terminates
# instead of hanging open. Picked > typical mark round-trip (1-3s).
MARK_ECHO_TIMEOUT_SECONDS = 8.0

# Chunking thresholds for TTS handoff (#151). Sentence terminators
# always flush; soft breaks (commas, semicolons, colons, em dashes)
# only flush once the buffered chunk is ≥ _MIN_CHUNK_CHARS so that
# fragments like "Got it," don't become their own Aura round-trip.
# 20 chars ≈ "One Chicken Fried Rice coming up," length when the
# 4/26 Twilight call's longest "over budget" turn would have hit.
_HARD_BREAKS = (".", "?", "!")
_SOFT_BREAKS = (",", ";", ":", "—")
_MIN_CHUNK_CHARS = 20


def _should_flush_chunk(delta: str, buffered_chars: int) -> bool:
    """True if the current text-delta should close a TTS chunk.

    ``delta`` is the latest streamed text fragment from Anthropic;
    ``buffered_chars`` is the total length of all deltas accumulated
    since the last flush (i.e. the chunk we'd ship if we flushed now).
    """
    if delta.endswith(_HARD_BREAKS):
        return True
    if delta.endswith(_SOFT_BREAKS) and buffered_chars >= _MIN_CHUNK_CHARS:
        return True
    return False


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


def _bg_call_event(call_sid: str | None, restaurant_id: str | None, **kwargs) -> None:
    """Fire-and-forget Firestore write so the audio loop never blocks on it.

    The storage module catches its own exceptions, so failures here just
    drop the event from the live dashboard — the call continues normally.
    Both ``call_sid`` and ``restaurant_id`` must be set; if either is
    missing (early-lifecycle event before ``start`` resolved the tenant),
    we silently skip rather than guess at the path.
    """
    if not call_sid or not restaurant_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        asyncio.to_thread(call_sessions.record_event, call_sid, restaurant_id, **kwargs)
    )


async def send_end_of_call_mark(websocket: WebSocket, stream_sid: str | None) -> bool:
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
        logger.exception("mark: failed to send end_of_call mark stream_sid=%s", stream_sid)
        return False


async def _hang_up_after_grace(state: _CallState) -> None:
    """Wait HANGUP_GRACE_SECONDS, then close the WebSocket to end the
    call.

    Closing our /media-stream WebSocket ends Twilio's <Connect>; with no
    further TwiML the inbound call hangs up. This avoids the Twilio REST
    Calls.update endpoint, which returns 404 on calls in <Connect> state
    (same root cause as the recording 404). The grace window lets a
    caller squeeze in a late follow-up like *"how long does that
    take?"* — a final transcript clears ``state.pending_hangup`` and
    we abort.

    ``state.should_hangup`` is also set as a fallback signal in case
    the WS close doesn't immediately unblock ``receive_text()`` (rare,
    but harmless to set both).
    """
    try:
        await asyncio.sleep(HANGUP_GRACE_SECONDS)
    except asyncio.CancelledError:
        return
    if not state.pending_hangup or not state.call_sid:
        return
    state.should_hangup.set()
    if state.websocket is not None:
        try:
            await state.websocket.close(code=1000)
            logger.info(
                "call ended by server (WS-close path) call_sid=%s",
                state.call_sid,
            )
        except Exception:
            logger.exception("auto-hangup: WS close failed call_sid=%s", state.call_sid)


async def _hang_up_after_mark_timeout(state: _CallState) -> None:
    """Fallback for when Twilio never echoes the end_of_call mark.

    The primary path is: send mark → Twilio echoes when audio drains →
    start grace timer. If the echo never arrives, this timer fires
    after ``MARK_ECHO_TIMEOUT_SECONDS`` and starts the grace window
    anyway, so the call still ends instead of hanging open.

    Cancelled by the echo handler when the echo arrives, or by
    ``_abort_pending_hangup`` when the caller speaks.
    """
    try:
        await asyncio.sleep(MARK_ECHO_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        return
    if not state.pending_hangup or not state.call_sid:
        return
    logger.warning(
        "auto-hangup: mark echo timed out after %.1fs, falling back to grace window call_sid=%s",
        MARK_ECHO_TIMEOUT_SECONDS,
        state.call_sid,
    )
    if state.hangup_task and not state.hangup_task.done():
        state.hangup_task.cancel()
    state.hangup_task = None
    await _hang_up_after_grace(state)


def _abort_pending_hangup(state: _CallState) -> None:
    """Cancel a pending auto-hangup because the caller spoke during
    the grace window. Safe to call when no hangup is pending."""
    state.pending_hangup = False
    if state.hangup_task and not state.hangup_task.done():
        state.hangup_task.cancel()
    state.hangup_task = None
    if state.mark_timeout_task and not state.mark_timeout_task.done():
        state.mark_timeout_task.cancel()
    state.mark_timeout_task = None


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


async def _barge_in_now(
    state: "_CallState",
    websocket: WebSocket,
    *,
    trigger: str,
) -> None:
    """Stop the bot mid-utterance.

    Three mechanical steps:
      1. Cancel the in-flight LLM/TTS task → halt audio generation.
      2. Cancel the silence watchdog → caller is speaking; "are you still
         there?" would be wrong.
      3. Send Twilio 'clear' → flush already-buffered audio playback (#74).

    The barge_in Firestore event is NOT emitted here. It's emitted by
    _run_llm_tts_turn's existing CancelledError handler when the task we
    just cancelled actually receives the cancellation. Trigger
    information flows via state.barge_in_trigger, which is set ONLY when
    there is actually a task to cancel — preventing stale triggers from
    leaking into the next turn's barge-in event, and preventing phantom
    barge_in events on cleanup-path cancellations (WS shutdown).
    """
    if state.llm_task and not state.llm_task.done():
        state.barge_in_trigger = trigger
        state.llm_task.cancel()
    _cancel_silence_task(state)
    await clear_twilio_audio(websocket, state.stream_sid)


@dataclass
class _CallState:
    call_sid: str | None = None
    stream_sid: str | None = None
    order: Order | None = None
    history: list[dict] = field(default_factory=list)
    restaurant: Restaurant | None = None  # tenant for this call (#79)
    system_prompt: str = ""  # built from restaurant on start
    llm_task: asyncio.Task | None = None  # current LLM→TTS turn
    silence_task: asyncio.Task | None = None  # silence watchdog
    hangup_task: asyncio.Task | None = None  # pending auto-hangup (#78)
    mark_timeout_task: asyncio.Task | None = None  # mark-echo fallback (#114)
    pending_hangup: bool = False  # set when goodbye mark sent (#78)
    recording_session: "RecordingUploadSession | None" = None
    should_hangup: asyncio.Event = field(default_factory=asyncio.Event)
    # WS reference so _hang_up_after_grace can close the connection
    # server-side. Closing the WS ends Twilio's <Connect>; with no
    # further TwiML the call hangs up. Avoids the Twilio REST
    # Calls.update endpoint which 404s on <Connect>-state calls.
    websocket: "WebSocket | None" = None
    # Transfer trigger accumulators (#7 Sprint 2.4 Track 2). Set by
    # transcript / LLM-error handlers; read in the finally block to
    # decide whether to write a transfer flag to the call session.
    consecutive_low_confidence_turns: int = 0
    last_caller_transcript: str = ""
    llm_error_occurred: bool = False
    # Carry-forward of the most recent transcript fed to an LLM turn
    # that has not yet been persisted to ``history``. When a new final
    # transcript arrives mid-turn, ``_handle_final_transcript`` cancels
    # the in-flight task and prepends this string so the cancelled
    # turn's user words aren't lost (#170). Cleared by ``_run_llm_tts_turn``
    # the moment ``event.final`` writes ``state.history``.
    in_flight_transcript: str = ""
    # Set by _barge_in_now() before cancelling state.llm_task; read and
    # cleared by _run_llm_tts_turn's CancelledError handler when emitting
    # the barge_in Firestore event. None at all other times.
    barge_in_trigger: str | None = None


async def _open_deepgram_connection(
    call_sid: str | None,
    restaurant_id: str | None,
    on_final: Callable,
    state: "_CallState | None" = None,
):
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
            # Track confidence for transfer-trigger detection (#7).
            # Explicit None check — `or 1.0` would replace 0.0 (falsy)
            # with 1.0, masking a legitimate worst-case misheard signal.
            raw_confidence = getattr(alt, "confidence", 1.0)
            confidence = 1.0 if raw_confidence is None else raw_confidence
            if state is not None:
                state.last_caller_transcript = text
                if confidence < 0.5:
                    state.consecutive_low_confidence_turns += 1
                else:
                    state.consecutive_low_confidence_turns = 0
            _bg_call_event(
                call_sid,
                restaurant_id,
                kind="transcript_final",
                text=text,
                detail={"text": text, "confidence": confidence},
            )
            asyncio.get_event_loop().create_task(on_final(text))

    async def on_error(self, error, **kwargs):
        logger.error("deepgram error call_sid=%s error=%s", call_sid, error)

    conn.on(LiveTranscriptionEvents.Transcript, on_transcript)
    conn.on(LiveTranscriptionEvents.Error, on_error)

    # endpointing + utterance_end_ms together control how aggressively
    # Deepgram closes a turn. We picked 800/1000 after a 2026-04-26
    # Twilight test call where endpointing=300 fired ~7 false barge-ins
    # in 3 minutes — every micro-pause mid-sentence ("i would like to"
    # <breath> "have") was treated as a turn ending, and the AI kept
    # saying "take your time" because it thought the caller had spoken.
    # 800ms is Deepgram's recommended value for conversational flow;
    # utterance_end_ms=1000 layers a prosody-aware end-of-utterance
    # signal on top so we wait for "actually finished" instead of just
    # "stopped making noise".
    options = LiveOptions(
        model="nova-2",
        encoding="mulaw",
        sample_rate=8000,
        channels=1,
        interim_results=True,
        endpointing=800,
        utterance_end_ms=1000,
        vad_events=True,
    )
    started = await conn.start(options)
    if not started:
        raise RuntimeError(f"Deepgram connection failed to start call_sid={call_sid}")
    return conn


def _make_recording_chunk_handler(state: "_CallState") -> Callable[[bytes], None] | None:
    """Return a chunk handler that appends outbound TTS audio to the
    recording session, or None when no session is active.

    Returning None means ``speak()`` won't fire ``on_chunk`` at all,
    which is the desired behaviour when ``RECORDINGS_BUCKET`` is unset
    and ``state.recording_session`` therefore stays None.
    """
    if state.recording_session is None:
        return None
    rs = state.recording_session

    def _handle(chunk: bytes) -> None:
        try:
            recordings.append_chunks(rs, b"", chunk)
        except Exception:
            logger.exception(
                "tts: recording append failed call_sid=%s", state.call_sid
            )

    return _handle


def _state_rid(state: _CallState) -> str | None:
    """Restaurant id from state, or None if start hasn't resolved a tenant
    yet (early-lifecycle defense)."""
    return state.restaurant.id if state.restaurant else None


async def _silence_watchdog(state: _CallState, websocket: WebSocket) -> None:
    try:
        await asyncio.sleep(SILENCE_TIMEOUT_SECONDS)
        logger.info("silence timeout call_sid=%s", state.call_sid)
        _bg_call_event(state.call_sid, _state_rid(state), kind="silence_timeout")
        if state.stream_sid:
            await speak(
                SILENCE_PROMPT,
                websocket,
                state.stream_sid,
                on_chunk=_make_recording_chunk_handler(state),
            )
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
    state.silence_task = asyncio.get_event_loop().create_task(_silence_watchdog(state, websocket))


async def _run_llm_tts_turn(transcript: str, state: _CallState, websocket: WebSocket) -> None:
    turn_start = time.monotonic()
    logger.info("llm_turn start call_sid=%s transcript=%r", state.call_sid, transcript)
    _bg_call_event(
        state.call_sid,
        _state_rid(state),
        kind="llm_turn_start",
        text=transcript,
        detail={"transcript": transcript},
    )
    text_buffer: list[str] = []
    first_speak = True
    full_reply_parts: list[str] = []
    # #146 — instrumentation. ``stream_reply`` yields one timing snapshot
    # the moment the first text content block opens; we stash it and
    # fold the breakdown into the first_audio Firestore event so the
    # dashboard can show ttft/tool_prefix/cache without anyone needing
    # GCP log access.
    timing_snapshot: dict[str, Any] | None = None
    first_text_at: float | None = None

    def _record_first_audio() -> None:
        latency = time.monotonic() - turn_start
        logger.info(
            "llm_turn first_audio latency=%.3fs call_sid=%s",
            latency,
            state.call_sid,
        )
        detail: dict[str, Any] = {"latency_seconds": round(latency, 3)}
        if first_text_at is not None:
            detail["first_text_seconds"] = round(first_text_at - turn_start, 3)
        if timing_snapshot is not None:
            detail.update(timing_snapshot)
        _bg_call_event(
            state.call_sid,
            _state_rid(state),
            kind="first_audio",
            detail=detail,
        )

    def _record_first_tts_byte() -> None:
        # #152 — captures the actual moment the first audio byte arrives
        # from Deepgram Aura, closing the gap that first_audio misses
        # (first_audio fires before await speak(), hiding TTS network time).
        latency = time.monotonic() - turn_start
        logger.info(
            "llm_turn first_tts_byte latency=%.3fs call_sid=%s",
            latency,
            state.call_sid,
        )
        _bg_call_event(
            state.call_sid,
            _state_rid(state),
            kind="first_tts_byte",
            detail={"latency_seconds": round(latency, 3)},
        )

    try:
        async for event in stream_reply(
            transcript=transcript,
            history=state.history,
            order=state.order,
            system_prompt=state.system_prompt,
        ):
            if asyncio.current_task().cancelled():
                return

            if event.timing is not None:
                timing_snapshot = event.timing
                continue

            if event.text_delta is not None:
                if first_text_at is None:
                    first_text_at = time.monotonic()
                text_buffer.append(event.text_delta)
                full_reply_parts.append(event.text_delta)
                buffered_chars = sum(len(p) for p in text_buffer)
                if _should_flush_chunk(event.text_delta, buffered_chars):
                    chunk = "".join(text_buffer).strip()
                    text_buffer.clear()
                    if chunk and state.stream_sid:
                        if first_speak:
                            _record_first_audio()
                            first_speak = False
                            on_first_byte = _record_first_tts_byte
                        else:
                            on_first_byte = None
                        await speak(
                            chunk,
                            websocket,
                            state.stream_sid,
                            on_chunk=_make_recording_chunk_handler(state),
                            on_first_byte=on_first_byte,
                        )

            elif event.final is not None:
                remainder = "".join(text_buffer).strip()
                text_buffer.clear()
                if remainder and state.stream_sid:
                    if first_speak:
                        _record_first_audio()
                        first_speak = False
                        on_first_byte = _record_first_tts_byte
                    else:
                        on_first_byte = None
                    await speak(
                        remainder,
                        websocket,
                        state.stream_sid,
                        on_chunk=_make_recording_chunk_handler(state),
                        on_first_byte=on_first_byte,
                    )
                state.history = event.final.history
                state.order = event.final.order
                # Transcript is now durably in history — no need to carry
                # it forward if a future turn is cancelled (#170).
                state.in_flight_transcript = ""
                full_reply = "".join(full_reply_parts).strip()
                if full_reply:
                    logger.info(
                        "agent_reply call_sid=%s text=%r",
                        state.call_sid,
                        full_reply,
                    )
                    _bg_call_event(
                        state.call_sid,
                        _state_rid(state),
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
                    explicitly_confirmed = state.order.status == OrderStatus.CONFIRMED
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
                        sent = await send_end_of_call_mark(websocket, state.stream_sid)
                        if sent:
                            state.pending_hangup = True
                            if state.mark_timeout_task and not state.mark_timeout_task.done():
                                state.mark_timeout_task.cancel()
                            state.mark_timeout_task = asyncio.create_task(
                                _hang_up_after_mark_timeout(state)
                            )

    except asyncio.CancelledError:
        trigger = state.barge_in_trigger
        state.barge_in_trigger = None
        if trigger is not None:
            # User-driven barge-in: trigger was set by _barge_in_now
            # before cancelling the task. Emit the timeline event.
            logger.info(
                "llm_turn cancelled (barge-in trigger=%s) call_sid=%s",
                trigger,
                state.call_sid,
            )
            _bg_call_event(
                state.call_sid,
                _state_rid(state),
                kind="barge_in",
                detail={"trigger": trigger},
            )
        else:
            # Cleanup-path cancellation: WS handler's finally block
            # cancels the task during call teardown. No barge_in event.
            logger.info(
                "llm_turn cancelled (cleanup) call_sid=%s", state.call_sid
            )
        raise
    except Exception as exc:
        logger.exception("llm_turn errored call_sid=%s", state.call_sid)
        # #7: signal the trigger detector at end-of-stream
        state.llm_error_occurred = True
        _bg_call_event(
            state.call_sid,
            _state_rid(state),
            kind="error",
            text=str(exc)[:500],
            detail={"exception": type(exc).__name__},
        )
        raise


async def _handle_final_transcript(text: str, state: _CallState, websocket: WebSocket) -> None:
    interrupted = bool(state.llm_task and not state.llm_task.done())
    # Carry forward — if any prior turn (cancelled or errored) left a
    # transcript on state without persisting it to history, prepend it
    # so Haiku sees the full caller intent in this turn (#170). The
    # field is cleared by ``_run_llm_tts_turn`` only on ``event.final``,
    # so a non-empty value here always means "user words from a prior
    # turn that never made it into history."
    if state.in_flight_transcript.strip():
        text = f"{state.in_flight_transcript} {text}".strip()
    silence_was_active = bool(state.silence_task and not state.silence_task.done())
    # Caller spoke — abort any pending auto-hangup (#78). Even if they
    # spoke during the grace window after a confirmation, we want to
    # keep the call alive and process this transcript.
    _abort_pending_hangup(state)

    if interrupted:
        # True barge-in: a turn is running and we're interrupting it.
        # The barge_in Firestore event fires from _run_llm_tts_turn's
        # CancelledError handler.
        await _barge_in_now(state, websocket, trigger="final_transcript")
    elif silence_was_active:
        # Caller resumed after a silence prompt — flush any leftover
        # prompt audio still buffered, but this isn't a barge-in (no
        # task to cancel, no event to emit).
        _cancel_silence_task(state)
        await clear_twilio_audio(websocket, state.stream_sid)

    state.in_flight_transcript = text
    state.llm_task = asyncio.create_task(_run_llm_tts_turn(text, state, websocket))
    state.llm_task.add_done_callback(lambda _t: _arm_silence_watchdog(state, websocket))


_UNCONFIGURED_TWIML_MESSAGE = "Sorry, this number is not currently configured. Goodbye."


def _resolve_restaurant_for_voice(
    to_e164: str,
) -> Restaurant | None:
    """Find the tenant for an inbound Twilio call (PR B of #79).

    Looks up by the ``To`` field — Twilio's name for the dialed number,
    which equals the per-restaurant ``twilio_phone`` we provisioned. If
    Firestore returns nothing AND the dialed number matches the
    demo's hardcoded ``twilio_phone``, falls back to building the demo
    restaurant from ``app.menu.MENU``. The fallback is removed in PR F
    once the seed is canonical.
    """
    restaurant = restaurants_storage.get_restaurant_by_twilio_phone(to_e164)
    if restaurant is not None:
        return restaurant
    demo = restaurants_storage.demo_restaurant_from_menu()
    if to_e164 == demo.twilio_phone:
        logger.warning(
            "voice: demo Twilio number %s not in Firestore — falling back to MENU",
            to_e164,
        )
        return demo
    return None


@router.post("/voice")
async def voice(request: Request) -> Response:
    """Respond to Twilio's inbound call webhook with TwiML.

    Looks up the tenant by Twilio's ``To`` field, opens a bidirectional
    Media Stream back to /media-stream, and forwards the resolved
    restaurant id to the WebSocket handler via a ``<Parameter>`` on the
    stream — Twilio echoes it back on the ``start`` event so the WS
    can load the right restaurant without re-querying.

    If the dialed number isn't mapped to any tenant, returns a brief
    TwiML hangup so callers don't sit through dead air.

    The WebSocket URL is derived from the ``Host`` header so the same
    code works under ngrok locally and on Cloud Run in production.
    """
    form = await request.form()
    to_e164 = (form.get("To") or "").strip()
    call_sid = (form.get("CallSid") or "").strip()
    restaurant = _resolve_restaurant_for_voice(to_e164)

    twiml = VoiceResponse()
    if restaurant is None:
        logger.warning("voice: no restaurant for To=%s — rejecting call", to_e164 or "(missing)")
        twiml.say(_UNCONFIGURED_TWIML_MESSAGE)
        twiml.hangup()
        return Response(content=str(twiml), media_type="application/xml")

    if restaurant is not None and not is_open_now(restaurant):
        # After-hours: skip the AI flow, drop straight to voicemail.
        if not call_sid:
            # Defensive: Twilio always posts CallSid. Without it, we
            # can't key the recording or call_session — bail.
            twiml = VoiceResponse()
            twiml.say("Sorry, we're closed. Please call back during business hours.")
            twiml.hangup()
            return Response(
                content=str(twiml),
                media_type="application/xml",
            )
        try:
            call_sessions.init_call_session(call_sid, restaurant.id)
        except Exception:
            logger.exception(
                "voice: init_call_session failed call_sid=%s rid=%s",
                call_sid,
                restaurant.id,
            )
        return Response(
            content=str(voicemail_response(call_sid, restaurant.id)),
            media_type="application/xml",
        )

    host = request.headers.get("host", "localhost:8000")
    connect = Connect(action="/voice/stream-ended", method="POST")
    # NOTE: <Connect><Stream> only supports the default ``inbound_track``;
    # passing ``track="both_tracks"`` makes Twilio reject the TwiML and
    # the call drops the moment the caller dismisses the trial-account
    # interstitial. To capture the agent's voice in the recording, the
    # /media-stream WS handler intercepts the TTS bytes we send out via
    # ``speak()`` and feeds them directly into the recording session.
    stream = connect.stream(url=f"wss://{host}/media-stream")
    stream.parameter(name="restaurant_id", value=restaurant.id)
    twiml.append(connect)
    return Response(content=str(twiml), media_type="application/xml")


_TRANSFER_STATUS_MAP = {
    "completed": "answered",
    "no-answer": "no_answer",
    "busy": "busy",
    "failed": "failed",
    "canceled": "failed",
}


@router.post("/voice/stream-ended")
async def stream_ended(request: Request) -> Response:
    """Twilio's <Connect> action callback. Decides what happens after
    the AI flow ends: empty TwiML (hang up), transfer to fallback, or
    drop to voicemail directly.

    Reads the latest call_session events to see if a `transfer_requested`
    was written by the WebSocket finally block (Phase B). If so, looks
    up the tenant's `fallback_phone` and returns <Dial> TwiML; if no
    fallback is configured, drops to voicemail with status='skipped'.
    """
    form = await request.form()
    call_sid = form.get("CallSid")

    if not call_sid:
        # Twilio always sends CallSid; missing → defensive hangup.
        return Response(content=str(VoiceResponse()), media_type="application/xml")

    # Resolve the tenant by reading the call_session doc. Uses the legacy
    # flat path because this action callback only receives CallSid — the
    # rid isn't known until we look it up here.
    try:
        session_doc = call_sessions.get_session_by_call_sid(call_sid)
        rid: str | None = (session_doc or {}).get("restaurant_id")
    except Exception:
        logger.exception("stream_ended: session lookup failed call_sid=%s", call_sid)
        rid = None

    if rid is None:
        return Response(
            content=str(VoiceResponse()),
            media_type="application/xml",
        )

    events = call_sessions.get_session_events(call_sid, rid) or []
    last = events[-1] if events else {}
    transfer_requested = last.get("kind") == "transfer_requested"

    if not transfer_requested:
        return Response(
            content=str(VoiceResponse()),
            media_type="application/xml",
        )

    restaurant = restaurants_storage.get_restaurant(rid)
    if restaurant is None or not restaurant.fallback_phone:
        # Transfer requested but no number to dial → mark + voicemail.
        try:
            call_sessions.mark_transfer_attempted(
                call_sid,
                rid,
                status="skipped",
                fallback_phone=None,
            )
        except Exception:
            logger.exception(
                "stream_ended: mark_transfer_attempted skipped call_sid=%s",
                call_sid,
            )
        return Response(
            content=str(voicemail_response(call_sid, rid)),
            media_type="application/xml",
        )

    twiml = VoiceResponse()
    dial = Dial(
        action=f"/voice/transfer-result?call_sid={call_sid}&rid={rid}",
        method="POST",
        timeout=20,
    )
    dial.number(restaurant.fallback_phone)
    twiml.append(dial)
    return Response(content=str(twiml), media_type="application/xml")


@router.post("/voice/transfer-result")
async def transfer_result(
    request: Request,
    call_sid: str,
    rid: str,
) -> Response:
    """<Dial>'s action callback. Maps Twilio DialCallStatus to internal
    status, marks the call session, and either returns empty (answered)
    or cascades to voicemail (no-answer/busy/failed)."""
    form = await request.form()
    status = form.get("DialCallStatus", "failed")
    internal_status = _TRANSFER_STATUS_MAP.get(status, "failed")

    try:
        call_sessions.mark_transfer_attempted(
            call_sid,
            rid,
            status=internal_status,
            fallback_phone=None,
        )
    except Exception:
        logger.exception(
            "transfer_result: mark_transfer_attempted failed call_sid=%s",
            call_sid,
        )

    if internal_status == "answered":
        return Response(
            content=str(VoiceResponse()),
            media_type="application/xml",
        )

    return Response(
        content=str(voicemail_response(call_sid, rid)),
        media_type="application/xml",
    )


@router.post("/voice/voicemail-recorded")
async def voicemail_recorded(
    request: Request,
    call_sid: str,
    rid: str,
) -> Response:
    """Twilio's <Record> action callback. Downloads the recording from
    Twilio's REST and uploads to GCS, then writes metadata to the call
    session. Returns empty TwiML — Twilio already hung up after <Record>.
    """
    form = await request.form()
    recording_url = form.get("RecordingUrl", "")
    recording_sid = form.get("RecordingSid", "")
    duration_raw = form.get("RecordingDuration", "0")
    try:
        duration = int(duration_raw)
    except (TypeError, ValueError):
        duration = 0

    if not recording_url or not recording_sid:
        return Response(
            content=str(VoiceResponse()),
            media_type="application/xml",
        )

    # Idempotency: Twilio retries this callback on timeout. If we've
    # already processed this RecordingSid for this call, short-circuit.
    try:
        existing = call_sessions.get_session(call_sid, rid) or {}
    except Exception:
        existing = {}
    if existing.get("voicemail_recording_sid") == recording_sid:
        logger.info(
            "voicemail-recorded: idempotent retry for call_sid=%s sid=%s — skipping",
            call_sid,
            recording_sid,
        )
        return Response(
            content=str(VoiceResponse()),
            media_type="application/xml",
        )

    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        logger.error(
            "voicemail upload: twilio creds missing call_sid=%s",
            call_sid,
        )
        return Response(
            content=str(VoiceResponse()),
            media_type="application/xml",
        )

    try:
        gs_url = recordings.upload_voicemail_from_twilio(
            call_sid=call_sid,
            restaurant_id=rid,
            twilio_recording_url=recording_url,
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        )
    except Exception:
        logger.exception(
            "voicemail upload failed call_sid=%s sid=%s",
            call_sid,
            recording_sid,
        )
        return Response(
            content=str(VoiceResponse()),
            media_type="application/xml",
        )

    try:
        call_sessions.mark_voicemail_left(
            call_sid,
            rid,
            recording_url=gs_url,
            recording_sid=recording_sid,
            duration_seconds=duration,
            transcript=None,  # Filled in by /voice/voicemail-transcription
        )
    except Exception:
        logger.exception(
            "voicemail mark_voicemail_left failed call_sid=%s",
            call_sid,
        )

    return Response(content=str(VoiceResponse()), media_type="application/xml")


@router.post("/voice/voicemail-transcription")
async def voicemail_transcription(
    request: Request,
    call_sid: str,
    rid: str,
) -> Response:
    """Twilio's transcribeCallback. Patches the voicemail transcript on
    the call session. Empty transcript (Twilio sometimes posts ""
    when transcription fails) is silently skipped."""
    form = await request.form()
    transcript = form.get("TranscriptionText", "")
    if transcript:
        try:
            call_sessions.update_voicemail_transcript(
                call_sid,
                rid,
                transcript=transcript,
            )
        except Exception:
            logger.exception(
                "voicemail transcript patch failed call_sid=%s",
                call_sid,
            )
    return Response(content="", media_type="text/plain")


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
    state = _CallState(websocket=websocket)
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
                # PR B: /voice looks up the restaurant by ``To`` and
                # forwards the id via Stream <Parameter>; Twilio echoes
                # it back on the start event under customParameters.
                # When the parameter is missing (older clients, manual
                # WS connects in tests), fall back to the demo path.
                custom_params = start.get("customParameters", {}) or {}
                rid = custom_params.get("restaurant_id")
                if rid:
                    state.restaurant = restaurants_storage.get_restaurant(rid)
                if state.restaurant is None:
                    state.restaurant = restaurants_storage.load_or_fallback_demo(
                        rid or restaurants_storage.DEMO_RID
                    )
                state.system_prompt = build_system_prompt(state.restaurant)
                try:
                    state.recording_session = recordings.begin_recording(
                        call_sid=state.call_sid or "unknown",
                        restaurant_id=state.restaurant.id,
                        retention_days=state.restaurant.recording_retention_days,
                    )
                except Exception:
                    logger.exception(
                        "recording: begin_recording failed call_sid=%s — call continues without recording",
                        state.call_sid,
                    )
                    state.recording_session = None
                state.order = Order(
                    call_sid=state.call_sid or "unknown",
                    restaurant_id=state.restaurant.id,
                )
                logger.info(
                    "media-stream start call_sid=%s stream_sid=%s restaurant=%s",
                    state.call_sid,
                    state.stream_sid,
                    state.restaurant.id,
                )
                if state.call_sid:
                    asyncio.get_running_loop().create_task(
                        asyncio.to_thread(
                            call_sessions.init_call_session,
                            state.call_sid,
                            state.restaurant.id,
                        )
                    )
                    _bg_call_event(
                        state.call_sid,
                        state.restaurant.id,
                        kind="start",
                        detail={"stream_sid": state.stream_sid or ""},
                    )
                dg_conn = await _open_deepgram_connection(
                    state.call_sid, state.restaurant.id, on_final, state=state
                )
                if settings.testing_mode and settings.commit_sha and state.stream_sid:
                    await speak(
                        f"Test build {settings.commit_sha[:7]}.",
                        websocket,
                        state.stream_sid,
                        on_chunk=_make_recording_chunk_handler(state),
                    )
                state.llm_task = asyncio.create_task(
                    _run_llm_tts_turn(GREETING_TRANSCRIPT, state, websocket)
                )
                state.llm_task.add_done_callback(lambda _t: _arm_silence_watchdog(state, websocket))

            elif event == "media":
                payload = base64.b64decode(msg["media"]["payload"])
                track = msg["media"].get("track")
                if track == "inbound":
                    inbound_chunk = payload
                    outbound_chunk = b""
                    if dg_conn is not None:
                        await dg_conn.send(payload)
                elif track == "outbound":
                    inbound_chunk = b""
                    outbound_chunk = payload
                else:
                    inbound_chunk = b""
                    outbound_chunk = b""
                if state.recording_session is not None:
                    recordings.append_chunks(state.recording_session, inbound_chunk, outbound_chunk)

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
                    if state.mark_timeout_task and not state.mark_timeout_task.done():
                        state.mark_timeout_task.cancel()
                    state.mark_timeout_task = None
                    if state.hangup_task and not state.hangup_task.done():
                        state.hangup_task.cancel()
                    state.hangup_task = asyncio.create_task(_hang_up_after_grace(state))

            elif event == "stop":
                logger.info("media-stream stop call_sid=%s", state.call_sid)
                _bg_call_event(state.call_sid, _state_rid(state), kind="stop")
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
                _bg_call_event(state.call_sid, _state_rid(state), kind="order_confirmed")
                order_confirmed = True
            except (OrderNotReadyError, Exception) as exc:
                logger.error("order persist failed call_sid=%s: %s", state.call_sid, exc)
        rid_for_close = _state_rid(state)
        if state.call_sid and rid_for_close:
            try:
                call_sessions.mark_call_ended(
                    state.call_sid,
                    rid_for_close,
                    confirmed=order_confirmed,
                )
            except Exception:
                logger.exception(
                    "call_sessions: mark_call_ended scheduling failed call_sid=%s",
                    state.call_sid,
                )
        # Sprint 2.4 Track 2: decide whether to flag this call for
        # transfer in the /voice/stream-ended callback. Reads accumulated
        # signals on _CallState; persists the verdict as a call_session
        # event so the action callback can branch on it.
        if state.call_sid and rid_for_close:
            from app.telephony.transfer_triggers import should_trigger_transfer

            transfer_reason = should_trigger_transfer(
                consecutive_low_confidence_turns=state.consecutive_low_confidence_turns,
                last_transcript=state.last_caller_transcript,
                llm_error_occurred=state.llm_error_occurred,
            )
            if transfer_reason is not None:
                logger.info(
                    "transfer_requested call_sid=%s reason=%s",
                    state.call_sid,
                    transfer_reason.value,
                )
                try:
                    call_sessions.record_event(
                        state.call_sid,
                        rid_for_close,
                        kind="transfer_requested",
                        text=transfer_reason.value,
                    )
                except Exception:
                    logger.exception(
                        "call_sessions: transfer_requested write failed call_sid=%s",
                        state.call_sid,
                    )
        if state.recording_session is not None and rid_for_close:
            try:
                gs_url, duration = recordings.finalize_recording(state.recording_session)
                if gs_url:
                    call_sessions.mark_recording_ready(
                        state.call_sid,
                        rid_for_close,
                        recording_url=gs_url,
                        recording_sid=state.call_sid,
                        duration_seconds=duration,
                    )
            except Exception:
                logger.exception(
                    "recording: finalize/mark failed call_sid=%s",
                    state.call_sid,
                )
        if dg_conn is not None:
            await dg_conn.finish()
