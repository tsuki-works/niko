"""STT provider contract.

The router talks to STT through this interface; concrete providers
(today: Deepgram) live under app/<vendor>/stt.py. Future providers
implement the same Protocol and become a one-line addition to the
selector in app/stt/__init__.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, Union


@dataclass(frozen=True)
class SpeechStartedEvent:
    """VAD detected the caller began speaking. Fires before any transcript
    is available — used for instant barge-in (~50ms vs ~800ms waiting on
    a final transcript)."""

    at: float = 0.0  # optional Deepgram timestamp; 0 if SDK omits it


@dataclass(frozen=True)
class TranscriptEvent:
    """One recognition result from the STT provider. Interim results
    (``is_final=False``) are rewritten by subsequent events; only finals
    should drive behavior."""

    text: str
    is_final: bool
    confidence: float


STTEvent = Union[TranscriptEvent, SpeechStartedEvent]


class STTProvider(Protocol):
    """Live streaming STT contract.

    Lifecycle: ``open()`` → many ``send(audio)`` + ``async for`` over
    ``events()`` → ``close()``. Errors mid-stream raise out of
    ``events()``; the consumer decides whether to recover or end the call.
    """

    async def open(self) -> None:
        """Open the live STT connection. Raises on failure."""

    async def send(self, audio: bytes) -> None:
        """Forward one chunk of caller audio (mulaw 8 kHz from Twilio).
        Connection-level errors are caught internally and logged; the call
        does not die on transient send failures."""

    def events(self) -> AsyncIterator[STTEvent]:
        """Yield STTEvents until close() is called. Raises on connection
        error — the consumer is responsible for catching and recovering."""

    async def close(self) -> None:
        """Tear down the connection and signal events() to terminate."""
