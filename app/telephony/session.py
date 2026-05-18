"""Call orchestration — vendor-neutral.

Owns _CallState and every helper that runs during the lifetime of an
active call: barge-in, hangup, silence, the LLM/TTS turn loop, and the
STT transcript consumer. The module knows about the abstract STT/TTS
provider interfaces in app/stt and app/tts but nothing about Twilio
specifics — those live in app/twilio/.

The FastAPI endpoints + WS event-loop dispatch live in
app/telephony/router.py. router.py imports from this module; this
module does not import from router.py.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import WebSocket

from app.config import settings
from app.dev.audio_dump import CallerAudioDump  # noqa: F401  (typing only)
from app.llm import get_llm
from app.orders.models import Order, OrderStatus
from app.restaurants.models import Restaurant
from app.storage import call_sessions, recordings
from app.storage import restaurants as restaurants_storage
from app.storage.recordings import RecordingUploadSession  # noqa: F401  (typing only)
from app.stt import (
    EarlyTurnEndEvent,
    SpeechStartedEvent,
    STTProvider,
    TranscriptEvent,
    TurnResumedEvent,
)
from app.tts import speak
from app.twilio.media_stream import send_clear, send_mark

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
    # STT plugin lifecycle. Set on "start"; consumer task drains
    # stt.events() and is cancelled in the WS handler's finally block.
    stt: "STTProvider | None" = None
    stt_provider: str | None = None
    transcript_task: asyncio.Task | None = None
    # Chained init_call_session + record_event(kind="start"). Held on
    # state so a strong reference exists for the task's lifetime;
    # serialising the two writes ensures the start event never races
    # init's parent-doc set() and 404s on Firestore.
    session_init_task: asyncio.Task | None = None
    # Local-dev caller-audio dump (#TBD). Set on "start" when
    # NIKO_LOCAL_AUDIO_DUMP_DIR is configured; otherwise stays None and
    # the media-event branch and finally-block close are no-ops.
    caller_dump: "CallerAudioDump | None" = None


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
            logger.exception("tts: recording append failed call_sid=%s", state.call_sid)

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
    state.silence_task = asyncio.create_task(_silence_watchdog(state, websocket))


async def _play_greeting(state: _CallState, websocket: WebSocket) -> None:
    """Speak the call's opening greeting via Aura — no LLM round-trip (#192).

    Picks a random entry from ``restaurant.greetings`` when populated,
    else falls back to a deterministic template against ``name``. Seeds
    ``state.history`` with a synthetic prior turn so the caller's first
    real reply (T2) lands with conversational context Claude expects.

    Exceptions from ``speak`` are caught and logged — dead air on the
    greeting is handled the same way as today's LLM-greet path, via the
    silence watchdog armed at the end of this function.
    """
    restaurant = state.restaurant
    if restaurant is None:
        return

    if restaurant.greetings:
        text = random.choice(restaurant.greetings)
        source = "greetings_list"
    else:
        text = f"Hi, thanks for calling {restaurant.name}. How can I help you?"
        source = "default_template"
    logger.info(
        "greeting_played rid=%s source=%s call_sid=%s",
        restaurant.id,
        source,
        state.call_sid,
    )

    if state.stream_sid:
        try:
            await speak(
                text,
                websocket,
                state.stream_sid,
                on_chunk=_make_recording_chunk_handler(state),
            )
        except Exception:
            logger.warning(
                "greeting: speak failed call_sid=%s rid=%s — silence watchdog will handle",
                state.call_sid,
                restaurant.id,
            )

    state.history = [
        {"role": "user", "content": GREETING_TRANSCRIPT},
        {"role": "assistant", "content": [{"type": "text", "text": text}]},
    ]
    _arm_silence_watchdog(state, websocket)


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
    await send_clear(websocket, state.stream_sid)


async def _consume_transcripts(
    stt: STTProvider,
    state: _CallState,
    websocket: WebSocket,
) -> None:
    """Background task consuming events from the STT plugin.

    All state mutation, Firestore emission, and dispatch into
    _handle_final_transcript happens here — the plugin is pure and
    knows nothing about call state. SpeechStartedEvent triggers an
    instant barge-in via _barge_in_now (gated on STT_INSTANT_BARGE_IN).
    """
    try:
        async for event in stt.events():
            if isinstance(event, SpeechStartedEvent):
                # Instant barge-in: fire as soon as the STT provider
                # reports the caller began speaking (Flux:
                # TurnInfo.event="StartOfTurn") instead of waiting for
                # the confirmed final transcript. The final-transcript
                # path in _handle_final_transcript still runs as a
                # fallback for short utterances or missed VAD signals.
                if not settings.stt_instant_barge_in:
                    continue
                if state.llm_task and not state.llm_task.done():
                    await _barge_in_now(state, websocket, trigger="vad")
                continue

            if isinstance(event, (EarlyTurnEndEvent, TurnResumedEvent)):
                # Speculative end-of-turn signals from Flux. The
                # speculative-drafting work that consumes them lives
                # in a separate follow-up PR; for now we drop them
                # to keep behavior identical to today.
                continue

            if isinstance(event, TranscriptEvent):
                if not event.is_final:
                    continue  # interim: captured in plugin logs only

                state.last_caller_transcript = event.text
                if event.confidence < 0.5:
                    state.consecutive_low_confidence_turns += 1
                else:
                    state.consecutive_low_confidence_turns = 0

                _bg_call_event(
                    state.call_sid,
                    _state_rid(state),
                    kind="transcript_final",
                    text=event.text,
                    detail={
                        "text": event.text,
                        "confidence": event.confidence,
                    },
                )
                await _handle_final_transcript(event.text, state, websocket)
                continue

            # Unknown event type — providers may extend the event union
            # in the future. Log once and keep going rather than crash
            # the call.
            logger.debug(
                "stt: unknown event type=%s call_sid=%s",
                type(event).__name__,
                state.call_sid,
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("transcript consumer crashed call_sid=%s", state.call_sid)
        # Mark the call as errored so the transfer-trigger logic in
        # finally has a signal to act on, and surface the failure to the
        # dashboard so it doesn't look like dead air to whoever's watching.
        state.llm_error_occurred = True
        _bg_call_event(
            state.call_sid,
            _state_rid(state),
            kind="error",
            text=f"transcript consumer crashed: {exc}"[:500],
            detail={"exception": type(exc).__name__},
        )


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
        async for event in get_llm().stream_reply(
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

            if event.flush_now:
                # Block-boundary drain (#305 Part A). The provider has
                # finished a text content block; ship whatever is buffered
                # to TTS now instead of waiting for ``_should_flush_chunk``
                # to fire on a future delta or for ``event.final`` to run
                # its remainder path. On text-then-tool turns this drains
                # the short ack ("Okay,") before the tool round-trip
                # starts, removing dead air during the tool call.
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
                        sent = await send_mark(websocket, state.stream_sid, name=END_OF_CALL_MARK)
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
            logger.info("llm_turn cancelled (cleanup) call_sid=%s", state.call_sid)
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
        await send_clear(websocket, state.stream_sid)

    state.in_flight_transcript = text
    state.llm_task = asyncio.create_task(_run_llm_tts_turn(text, state, websocket))

    def _llm_task_done(task: asyncio.Task) -> None:
        _arm_silence_watchdog(state, websocket)
        # Swallow the exception so asyncio doesn't log it a second time
        # (it was already logged inside _run_llm_tts_turn).
        if not task.cancelled():
            task.exception()  # consume without re-raising

    state.llm_task.add_done_callback(_llm_task_done)


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
