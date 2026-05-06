"""Deepgram Nova live STT implementation.

Implements the STTProvider contract from app/stt/base.py. Bridges
Deepgram SDK's callback-based API onto the async-iterator interface
the router consumer expects, via one internal asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents

from app.config import settings
from app.deepgram import _api_key
from app.stt.base import STTEvent, SpeechStartedEvent, TranscriptEvent

logger = logging.getLogger(__name__)


_CLOSED = object()


@dataclass(frozen=True)
class _ErrorBox:
    # Deepgram's SDK sometimes passes a plain str to the error callback
    # (e.g., for protocol-level WS closures) and sometimes an Exception;
    # we accept either and let the consumer's RuntimeError carry it.
    error: Any


def _parse_keyterms(raw: str) -> Optional[list[str]]:
    """Split STT_KEYTERMS env var into a list, or None when empty."""
    items = [t.strip() for t in raw.split(",") if t.strip()]
    return items or None


class DeepgramSTT:
    """Live Deepgram Nova STT provider.

    Lifecycle: ``open()`` opens the live WS and registers SDK callbacks
    that translate Deepgram events into STTEvents on an internal queue.
    ``send()`` forwards Twilio media-stream payloads. ``events()`` is an
    async generator that yields TranscriptEvent and SpeechStartedEvent
    objects until ``close()`` is called.
    """

    def __init__(self, *, call_sid: Optional[str] = None) -> None:
        self._call_sid = call_sid
        self._conn: Any = None
        self._queue: asyncio.Queue = asyncio.Queue()

    async def open(self) -> None:
        dg = DeepgramClient(_api_key())
        self._conn = dg.listen.asynclive.v("1")
        self._conn.on(LiveTranscriptionEvents.Transcript, self._on_transcript)
        self._conn.on(
            LiveTranscriptionEvents.SpeechStarted, self._on_speech_started
        )
        self._conn.on(LiveTranscriptionEvents.Error, self._on_error)

        keyterms = _parse_keyterms(settings.stt_keyterms)

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
            model=settings.stt_model,
            encoding="mulaw",
            sample_rate=8000,
            channels=1,
            interim_results=True,
            endpointing=settings.stt_endpointing_ms,
            utterance_end_ms=settings.stt_utterance_end_ms,
            vad_events=True,
            keyterm=keyterms,
        )
        started = await self._conn.start(options)
        if not started:
            raise RuntimeError(
                f"Deepgram connection failed to start call_sid={self._call_sid}"
            )

    async def send(self, audio: bytes) -> None:
        if self._conn is None:
            return
        try:
            await self._conn.send(audio)
        except Exception:
            # Connection-level send failure: log and continue. The next
            # transcript will be incomplete; the silence watchdog absorbs
            # the resulting gap.
            logger.exception(
                "deepgram send failed call_sid=%s — call continues",
                self._call_sid,
            )

    def events(self) -> AsyncIterator[STTEvent]:
        # Plain def: callers want to "async for" on the result, not "await"
        # it first. The actual generator lives in _events_impl below.
        return self._events_impl()

    async def _events_impl(self) -> AsyncIterator[STTEvent]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            if isinstance(item, _ErrorBox):
                # Preserve cause when the SDK passed an actual exception so
                # production tracebacks chain back to the original failure.
                # Tests sometimes pass a plain string — guard with isinstance.
                cause = item.error if isinstance(item.error, BaseException) else None
                raise RuntimeError(f"deepgram error: {item.error}") from cause
            yield item

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.finish()
            except Exception:
                logger.exception(
                    "deepgram finish failed call_sid=%s", self._call_sid
                )
        self._queue.put_nowait(_CLOSED)

    # SDK callbacks ---------------------------------------------------
    async def _on_transcript(self, _dg_handle: Any, result: Any, **_kwargs: Any) -> None:
        # Deepgram passes the connection handle as the first arg to bound
        # handlers in addition to self; we ignore it.
        alt = result.channel.alternatives[0]
        text = alt.transcript.strip()
        if not text:
            return
        # Replace None with 1.0 (not 0.0) so callers see worst-case
        # misheard turns explicitly when Deepgram does provide confidence.
        raw_confidence = getattr(alt, "confidence", 1.0)
        confidence = 1.0 if raw_confidence is None else raw_confidence

        is_final = bool(result.is_final)
        label = "final" if is_final else "interim"
        logger.info(
            "transcript [%s] call_sid=%s text=%r", label, self._call_sid, text
        )

        self._queue.put_nowait(
            TranscriptEvent(text=text, is_final=is_final, confidence=confidence)
        )

    async def _on_speech_started(
        self, _dg_handle: Any, _event: Any, **_kwargs: Any
    ) -> None:
        # Deepgram passes the connection handle as the first arg to bound
        # handlers in addition to self; we ignore it. The event payload
        # is also unused — we only need the signal that speech started.
        logger.info("speech_started call_sid=%s", self._call_sid)
        self._queue.put_nowait(SpeechStartedEvent())

    async def _on_error(self, _dg_handle: Any, error: Any, **_kwargs: Any) -> None:
        # Deepgram passes the connection handle as the first arg to bound
        # handlers in addition to self; we ignore it.
        logger.error("deepgram error call_sid=%s error=%s", self._call_sid, error)
        self._queue.put_nowait(_ErrorBox(error))
