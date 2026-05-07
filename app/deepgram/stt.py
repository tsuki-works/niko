"""Deepgram Flux live STT implementation.

Implements the STTProvider contract from app/stt/base.py. Uses
``AsyncDeepgramClient.listen.v2.connect`` (Flux v2 API) and translates
Flux's wire messages into the vendor-neutral common-named events the
consumer expects.

Translation map (Flux ``TurnInfo.event`` → common-named event):

    | TurnInfo.event   | Common-named             |
    |------------------|--------------------------|
    | "Update"         | TranscriptEvent(is_final=False)
    | "StartOfTurn"    | SpeechStartedEvent
    | "EagerEndOfTurn" | EarlyTurnEndEvent
    | "TurnResumed"    | TurnResumedEvent
    | "EndOfTurn"      | TranscriptEvent(is_final=True)

``EarlyTurnEndEvent`` and ``TurnResumedEvent`` are emitted but the
session-loop consumer drops them in this PR. They exist on the wire
so a follow-up speculative-drafting PR can wire them in without
changing the protocol.

A note on the SDK's wire format: ``deepgram-sdk`` 7.1's
``recv()`` returns Union-typed messages by passing the JSON to
``construct_type(Union[...], ...)``, which does NOT pick a Union
discriminator and falls through to the raw dict. So in practice every
message arrives as a ``dict`` with a ``type`` field. ``_translate``
routes on that field for dicts, and keeps an ``isinstance``
fallback in case a future SDK revision starts returning concrete
Pydantic models.

Lifecycle: ``open()`` enters the v2 connect context and starts a
background reader task that drains ``recv()`` into an internal queue.
``send()`` forwards Twilio mulaw bytes via ``send_media``.
``events()`` is an async generator yielding STTEvents until
``close()``. ``close()`` cancels the reader, sends close-stream, and
exits the context manager.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, Sequence

from deepgram import AsyncDeepgramClient
from deepgram.listen.v2.types import (
    ListenV2ConfigureFailure,
    ListenV2Connected,
    ListenV2FatalError,
    ListenV2TurnInfo,
)

from app.config import settings
from app.deepgram import _api_key
from app.stt.base import (
    EarlyTurnEndEvent,
    SpeechStartedEvent,
    STTEvent,
    TranscriptEvent,
    TurnResumedEvent,
)

logger = logging.getLogger(__name__)


_CLOSED = object()


@dataclass(frozen=True)
class _ErrorBox:
    error: Any


def _resolve_keyterms(
    constructor_keyterms: Optional[Sequence[str]],
    call_sid: Optional[str] = None,
) -> Optional[list[str]]:
    """Return the keyterm list to send to Flux, or None.

    Precedence:
      1. STT_KEYTERMS env var (when non-empty) — debug override that
         REPLACES the heuristic output entirely. Used to A/B specific
         lists without redeploying.
      2. The list passed by the caller (computed per-tenant by
         app.restaurants.keyterms.compute_keyterms).
      3. None — Flux runs in pure open-domain mode.
    """
    env_override = settings.stt_keyterms.strip()
    if env_override:
        items = [t.strip() for t in env_override.split(",") if t.strip()]
        # The override is process-wide and silently replaces every
        # tenant's per-call biasing. Log loudly so a misconfigured
        # deploy is visible in #ci-alerts rather than degrading every
        # call's keyterms in silence.
        logger.warning(
            "stt: STT_KEYTERMS env override active — per-tenant keyterms "
            "REPLACED for this call (call_sid=%s, n=%d). Unset STT_KEYTERMS "
            "in non-debug environments.",
            call_sid,
            len(items),
        )
        return items or None
    if constructor_keyterms:
        items = [t for t in constructor_keyterms if t and t.strip()]
        return items or None
    return None


def _confidence_from_words_payload(words: Any) -> float:
    """Average word-level confidence as a single transcript confidence.

    Accepts either a list of pydantic ``ListenV2TurnInfoWordsItem``
    instances (attribute access) or a list of plain dicts (key access),
    which is what Flux's ``recv()`` returns when ``construct_type``
    falls through to the raw JSON path. Returns 1.0 as the
    worst-case-visible default when no per-word confidence is
    available — picking 0.0 would mask genuine low-confidence turns.
    """
    if not words:
        return 1.0
    try:
        confs: list[float] = []
        for w in words:
            if isinstance(w, dict):
                c = w.get("confidence")
            else:
                c = getattr(w, "confidence", None)
            if c is None:
                continue
            confs.append(float(c))
        if confs:
            return sum(confs) / len(confs)
    except (TypeError, ValueError):
        pass
    return 1.0


class DeepgramSTT:
    """Live Deepgram Flux STT provider.

    Constructor accepts an optional ``keyterms`` list — typically the
    output of ``app.restaurants.keyterms.compute_keyterms`` for the
    active tenant. When the ``STT_KEYTERMS`` env var is non-empty it
    REPLACES this list (debug override).
    """

    def __init__(
        self,
        *,
        call_sid: Optional[str] = None,
        keyterms: Optional[Sequence[str]] = None,
    ) -> None:
        self._call_sid = call_sid
        self._keyterms_arg: Optional[list[str]] = (
            list(keyterms) if keyterms else None
        )
        self._client: Any = None
        self._cm: Any = None
        self._conn: Any = None
        self._reader: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue = asyncio.Queue()

    async def open(self) -> None:
        # Eager api-key check so the call fails before we hand off to
        # the SDK with a confusing error message.
        api_key = _api_key()

        keyterms = _resolve_keyterms(self._keyterms_arg, call_sid=self._call_sid)

        self._client = AsyncDeepgramClient(api_key=api_key)
        self._cm = self._client.listen.v2.connect(
            model=settings.stt_model,
            encoding="mulaw",
            sample_rate=8000,
            keyterm=keyterms,
        )
        try:
            self._conn = await self._cm.__aenter__()
        except Exception:
            # Connect itself failed (network, auth, malformed args).
            # Re-raise so the caller can decide whether to fall back to
            # voicemail or end the call cleanly.
            self._cm = None
            raise

        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Drain Flux messages into the internal queue.

        ``recv()`` blocks until the next message; the background task
        translates each one into a common-named event and enqueues it
        for the consumer. The task ends when the connection closes
        (``recv`` raises) or when ``close()`` cancels it. The
        ``msg_count`` in the cancelled/crashed logs gives the postmortem
        a quick read on how many wire messages were actually delivered.
        """
        msg_count = 0
        try:
            while True:
                msg = await self._conn.recv()
                msg_count += 1
                self._translate(msg)
        except asyncio.CancelledError:
            logger.info(
                "deepgram reader cancelled call_sid=%s msg_count=%d",
                self._call_sid,
                msg_count,
            )
            raise
        except Exception as exc:
            logger.exception(
                "deepgram reader crashed call_sid=%s msg_count=%d",
                self._call_sid,
                msg_count,
            )
            self._queue.put_nowait(_ErrorBox(exc))

    def _translate(self, msg: Any) -> None:
        """Translate one Flux wire message into a common-named event.

        The SDK's ``recv()`` returns ``dict`` for typed messages because
        ``construct_type`` on a Union doesn't pick a discriminator and
        falls through to returning the raw JSON dict. We route on the
        ``type`` field of the dict and keep the Pydantic-class
        ``isinstance`` branches as a safety net for any future SDK
        version that does parse Union members into concrete classes.
        """
        # Normalize: extract a ``type`` discriminator from either a
        # dict or a typed model.
        if isinstance(msg, dict):
            msg_type = msg.get("type")
            getter = msg.get
        elif isinstance(
            msg,
            (
                ListenV2Connected,
                ListenV2TurnInfo,
                ListenV2ConfigureFailure,
                ListenV2FatalError,
            ),
        ):
            msg_type = getattr(msg, "type", None) or type(msg).__name__.replace(
                "ListenV2", ""
            )

            def getter(key, default=None, _msg=msg):
                return getattr(_msg, key, default)
        else:
            logger.debug(
                "deepgram unknown message type=%s call_sid=%s",
                type(msg).__name__,
                self._call_sid,
            )
            return

        if msg_type == "Connected":
            logger.info(
                "deepgram connected call_sid=%s request_id=%s",
                self._call_sid,
                getter("request_id", "?"),
            )
            return

        if msg_type == "TurnInfo":
            event = getter("event", "")
            text = (getter("transcript", "") or "").strip()

            if event == "StartOfTurn":
                logger.info(
                    "speech_started call_sid=%s turn=%s",
                    self._call_sid,
                    getter("turn_index", "?"),
                )
                self._queue.put_nowait(SpeechStartedEvent())
                return

            if event == "Update":
                # Interim transcript. Skip empty payloads — Flux
                # streams an "Update" event every ~250ms with a
                # rolling end_of_turn_confidence even when there's
                # no speech yet, and an empty transcript downstream
                # confuses logging and the low-confidence counter.
                if not text:
                    return
                confidence = _confidence_from_words_payload(getter("words", []))
                logger.info(
                    "transcript [interim] call_sid=%s text=%r",
                    self._call_sid,
                    text,
                )
                self._queue.put_nowait(
                    TranscriptEvent(text=text, is_final=False, confidence=confidence)
                )
                return

            if event == "EagerEndOfTurn":
                logger.info(
                    "eager_eot call_sid=%s turn=%s",
                    self._call_sid,
                    getter("turn_index", "?"),
                )
                self._queue.put_nowait(EarlyTurnEndEvent())
                return

            if event == "TurnResumed":
                logger.info(
                    "turn_resumed call_sid=%s turn=%s",
                    self._call_sid,
                    getter("turn_index", "?"),
                )
                self._queue.put_nowait(TurnResumedEvent())
                return

            if event == "EndOfTurn":
                if not text:
                    # Confirmed turn-end with no transcript — caller
                    # said nothing recognizable. Drop; the consumer
                    # has nothing to act on.
                    return
                confidence = _confidence_from_words_payload(getter("words", []))
                logger.info(
                    "transcript [final] call_sid=%s text=%r",
                    self._call_sid,
                    text,
                )
                self._queue.put_nowait(
                    TranscriptEvent(text=text, is_final=True, confidence=confidence)
                )
                return

            # Unknown event — log and drop. New Flux versions may add
            # event types we haven't taught the translator about; we'd
            # rather no-op than crash the call.
            logger.debug(
                "deepgram unknown turn_info event=%r call_sid=%s",
                event,
                self._call_sid,
            )
            return

        if msg_type in ("ConfigureFailure", "FatalError"):
            logger.error(
                "deepgram error call_sid=%s msg_type=%s msg=%s",
                self._call_sid,
                msg_type,
                msg,
            )
            self._queue.put_nowait(
                _ErrorBox(RuntimeError(f"deepgram error: {msg}"))
            )
            return

        logger.debug(
            "deepgram unknown message type=%r call_sid=%s",
            msg_type,
            self._call_sid,
        )

    async def send(self, audio: bytes) -> None:
        if self._conn is None:
            return
        try:
            await self._conn.send_media(audio)
        except Exception:
            # Connection-level send failure: log and continue. The
            # next transcript will be incomplete; the silence
            # watchdog absorbs the resulting gap.
            logger.exception(
                "deepgram send failed call_sid=%s — call continues",
                self._call_sid,
            )

    def events(self) -> AsyncIterator[STTEvent]:
        return self._events_impl()

    async def _events_impl(self) -> AsyncIterator[STTEvent]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            if isinstance(item, _ErrorBox):
                cause = (
                    item.error if isinstance(item.error, BaseException) else None
                )
                raise RuntimeError(f"deepgram error: {item.error}") from cause
            yield item

    async def close(self) -> None:
        # Stop the reader first so it doesn't see the close-stream
        # turn-around as a crash and enqueue a spurious _ErrorBox.
        if self._reader and not self._reader.done():
            self._reader.cancel()
            try:
                await self._reader
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(
                    "deepgram reader cleanup failed call_sid=%s",
                    self._call_sid,
                )

        if self._conn is not None:
            try:
                await self._conn.send_close_stream()
            except Exception:
                # Socket already gone — exit the context manager
                # anyway so resources are released.
                logger.debug(
                    "deepgram send_close_stream failed (likely already closed) call_sid=%s",
                    self._call_sid,
                )

        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                logger.exception(
                    "deepgram finish failed call_sid=%s", self._call_sid
                )

        self._queue.put_nowait(_CLOSED)
