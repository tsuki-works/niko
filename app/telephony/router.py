"""Twilio telephony FastAPI surface.

Five HTTP webhook endpoints (`/voice`, `/voice/stream-ended`,
`/voice/transfer-result`, `/voice/voicemail-recorded`,
`/voice/voicemail-transcription`) and one WebSocket
(`/media-stream`) that runs Twilio's Media Stream loop. Endpoint
bodies parse Twilio's webhook form and delegate: TwiML construction
to app/twilio/twiml.py, REST credentials to app/twilio/__init__.py,
call orchestration (state, barge-in, hangup, LLM turn) to
app/telephony/session.py.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect

import app.twilio as app_twilio
from app.config import settings
from app.dev.audio_dump import open_caller_dump
from app.llm.prompts import build_system_prompt
from app.llm.warmup import prime_tenant_cache
from app.orders.lifecycle import OrderNotReadyError, persist_on_confirm
from app.orders.models import Order
from app.restaurants.keyterms import compute_keyterms
from app.restaurants.open_check import is_open_now
from app.storage import call_sessions, recordings
from app.storage import restaurants as restaurants_storage
from app.stt import get_stt
from app.telephony.session import (
    END_OF_CALL_MARK,
    _abort_pending_hangup,
    _bg_call_event,
    _CallState,
    _cancel_silence_task,
    _consume_transcripts,
    _hang_up_after_grace,
    _make_recording_chunk_handler,
    _play_greeting,
    _resolve_restaurant_for_voice,
    _state_rid,
)
from app.telephony.voicemail_twiml import voicemail_response
from app.tts import speak
from app.twilio.twiml import (
    closed_hangup_twiml,
    empty_twiml,
    transfer_twiml,
    unconfigured_hangup_twiml,
    voice_twiml,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_TRANSFER_STATUS_MAP = {
    "completed": "answered",
    "no-answer": "no_answer",
    "busy": "busy",
    "failed": "failed",
    "canceled": "failed",
}


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

    if restaurant is None:
        logger.warning("voice: no restaurant for To=%s — rejecting call", to_e164 or "(missing)")
        return Response(
            content=str(unconfigured_hangup_twiml()),
            media_type="application/xml",
        )

    # Anthropic cache primer (#192). Fire-and-forget — exploits the
    # ~300-500 ms TwiML → WS-connect window so T2's real LLM call reads
    # the system prompt from cache instead of paying cache_creation.
    # prime_tenant_cache swallows its own exceptions; the bare task is
    # never awaited and never observed for failure.
    logger.info("primer scheduled rid=%s call_sid=%s", restaurant.id, call_sid)
    asyncio.create_task(prime_tenant_cache(restaurant))

    if not is_open_now(restaurant):
        # After-hours: skip the AI flow, drop straight to voicemail.
        if not call_sid:
            # Defensive: Twilio always posts CallSid. Without it, we
            # can't key the recording or call_session — bail.
            return Response(
                content=str(closed_hangup_twiml()),
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
    return Response(
        content=str(voice_twiml(restaurant, host)),
        media_type="application/xml",
    )


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
        return Response(content=str(empty_twiml()), media_type="application/xml")

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
            content=str(empty_twiml()),
            media_type="application/xml",
        )

    events = call_sessions.get_session_events(call_sid, rid) or []
    last = events[-1] if events else {}
    transfer_requested = last.get("kind") == "transfer_requested"

    if not transfer_requested:
        return Response(
            content=str(empty_twiml()),
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

    return Response(
        content=str(transfer_twiml(restaurant.fallback_phone, call_sid, rid)),
        media_type="application/xml",
    )


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
            content=str(empty_twiml()),
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
            content=str(empty_twiml()),
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
            content=str(empty_twiml()),
            media_type="application/xml",
        )

    if app_twilio.twilio_basic_auth() is None:
        logger.error(
            "voicemail upload: twilio creds missing call_sid=%s",
            call_sid,
        )
        return Response(
            content=str(empty_twiml()),
            media_type="application/xml",
        )

    try:
        gs_url = app_twilio.upload_voicemail(
            call_sid=call_sid,
            restaurant_id=rid,
            twilio_recording_url=recording_url,
        )
    except Exception:
        logger.exception(
            "voicemail upload failed call_sid=%s sid=%s",
            call_sid,
            recording_sid,
        )
        return Response(
            content=str(empty_twiml()),
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

    return Response(content=str(empty_twiml()), media_type="application/xml")


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
    """Full call loop: Twilio Media Stream → STT → LLM → TTS.

    Twilio event types:
      connected  — protocol handshake
      start      — stream open; initialises Order, opens STT, fires AI greeting
      media      — base64 mulaw 8 kHz audio forwarded to the STT provider
      stop       — call ended; persists completed orders to Firestore
    """
    await websocket.accept()
    state = _CallState(websocket=websocket)

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
                # Local-dev caller-audio dump. Returns None in production
                # (env unset) and on any filesystem error — the call loop
                # never depends on this succeeding.
                if state.call_sid:
                    state.caller_dump = open_caller_dump(state.call_sid)
                if state.call_sid:
                    # init_call_session creates the parent doc; record_event
                    # (kind="start") then update()s it. Chain them in a single
                    # task so the start event never races init and 404s.
                    # Tracked on state.session_init_task so the WS finally
                    # block can await it — otherwise a fast hangup tears the
                    # loop down before the chained record_event lands.
                    init_sid = state.call_sid
                    init_rid = state.restaurant.id
                    init_stream_sid = state.stream_sid or ""

                    async def _init_then_start_event() -> None:
                        await asyncio.to_thread(call_sessions.init_call_session, init_sid, init_rid)
                        await asyncio.to_thread(
                            call_sessions.record_event,
                            init_sid,
                            init_rid,
                            kind="start",
                            detail={"stream_sid": init_stream_sid},
                        )

                    state.session_init_task = asyncio.create_task(_init_then_start_event())
                # Compute per-tenant keyterms from the loaded menu and
                # log them once so the call audit has a record of what
                # was biased. Empty list when the menu is unusably thin
                # — the heuristic always includes the restaurant name
                # at minimum, so the list is never literally empty.
                keyterms = compute_keyterms(state.restaurant.menu, state.restaurant.name)
                logger.info(
                    "keyterms call_sid=%s rid=%s n=%d preview=%r",
                    state.call_sid,
                    state.restaurant.id,
                    len(keyterms),
                    keyterms[:5],
                )
                state.stt, state.stt_provider = get_stt(call_sid=state.call_sid, keyterms=keyterms)
                try:
                    await state.stt.open()
                except Exception:
                    logger.exception("stt: failed to open call_sid=%s", state.call_sid)
                    _bg_call_event(
                        state.call_sid,
                        state.restaurant.id,
                        kind="error",
                        text="STT failed to open",
                        detail={"provider": state.stt_provider},
                    )
                    # Speak a brief audible fallback before bailing — without
                    # this the caller hears dead air until Twilio's idle
                    # timeout closes the WS. TTS uses a different vendor path,
                    # so a Deepgram-STT outage doesn't block this audio.
                    if state.stream_sid:
                        try:
                            await speak(
                                "Sorry, our service is briefly unavailable. Please call back in a moment.",
                                websocket,
                                state.stream_sid,
                                on_chunk=_make_recording_chunk_handler(state),
                            )
                        except Exception:
                            logger.exception(
                                "stt: fallback speak failed call_sid=%s",
                                state.call_sid,
                            )
                    return
                state.transcript_task = asyncio.create_task(
                    _consume_transcripts(state.stt, state, websocket)
                )
                if settings.testing_mode and settings.commit_sha and state.stream_sid:
                    await speak(
                        f"Test build {settings.commit_sha[:7]}.",
                        websocket,
                        state.stream_sid,
                        on_chunk=_make_recording_chunk_handler(state),
                    )
                # #192 — Greeting is hand-written text streamed straight
                # through Aura; no LLM round-trip on T1. ``_play_greeting``
                # also arms the silence watchdog before returning.
                await _play_greeting(state, websocket)

            elif event == "media":
                payload = base64.b64decode(msg["media"]["payload"])
                track = msg["media"].get("track")
                if track == "inbound":
                    inbound_chunk = payload
                    outbound_chunk = b""
                    if state.stt is not None:
                        await state.stt.send(payload)
                    if state.caller_dump is not None:
                        state.caller_dump.append(payload)
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
    except RuntimeError:
        # Server-initiated close (auto-hangup #78) flips Starlette's
        # application_state to DISCONNECTED before the next receive_text()
        # iteration; that guard then raises RuntimeError instead of the
        # WebSocketDisconnect we'd otherwise catch. Gate on should_hangup
        # so any other RuntimeError still surfaces as a real bug.
        if not state.should_hangup.is_set():
            raise
        logger.info(
            "media-stream disconnected (server-initiated close) call_sid=%s",
            state.call_sid,
        )
    finally:
        _cancel_silence_task(state)
        # Auto-hangup: stop any pending grace-window timer; the call is
        # already ending so we don't need to fire the REST close (#78).
        _abort_pending_hangup(state)
        # Quiesce the transcript consumer FIRST so it can't spawn a new
        # state.llm_task from a late final transcript while we're cleaning
        # up the in-flight one. Closing the STT connection here also
        # short-circuits any pending Deepgram callbacks. Order matters:
        # if we cancelled state.llm_task first, the consumer could create
        # a fresh task from a buffered transcript that we'd never await.
        if state.transcript_task and not state.transcript_task.done():
            state.transcript_task.cancel()
            try:
                await state.transcript_task
            except (asyncio.CancelledError, Exception):
                pass
        if state.stt is not None:
            try:
                await state.stt.close()
            except Exception:
                logger.exception("stt: close failed call_sid=%s", state.call_sid)
        if state.caller_dump is not None:
            try:
                state.caller_dump.close()
            except Exception:
                logger.exception(
                    "audio_dump: close failed call_sid=%s",
                    state.call_sid,
                )
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
