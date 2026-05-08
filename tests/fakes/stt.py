"""FakeSTT — test double for app.stt.base.STTProvider.

Tests script events and assert on calls. The fake is intentionally
minimal: just enough plumbing to support the scenarios the real plugin
needs to handle (open, send, multi-event streams, close, error).

Usage:

    fake = FakeSTT(events=[TranscriptEvent("hi", True, 0.95)])
    await fake.open()
    async for event in fake.events():
        ...

    fake.feed(SpeechStartedEvent())             # inject mid-test
    fake.feed_error(RuntimeError("dropped"))    # surface error in events()
    await fake.close()

Note: events seeded via the constructor are visible from ``events()``
regardless of whether ``open()`` was called — chosen for test ergonomics.
Real STTProviders gate event emission on ``open()``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

from app.stt.base import STTEvent

_CLOSED = object()


@dataclass(frozen=True)
class _ErrorBox:
    exc: BaseException


class FakeSTT:
    """Implements STTProvider; lets tests feed scripted events."""

    def __init__(self, *, events: "list[STTEvent] | None" = None) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self.opened = False
        self.closed = False
        self.sent: list[bytes] = []
        for ev in events or []:
            self._queue.put_nowait(ev)

    async def open(self) -> None:
        self.opened = True

    async def send(self, audio: bytes) -> None:
        self.sent.append(audio)

    def events(self) -> AsyncIterator[STTEvent]:
        return self._events_impl()

    async def _events_impl(self) -> AsyncIterator[STTEvent]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            if isinstance(item, _ErrorBox):
                raise item.exc
            yield item

    async def close(self) -> None:
        self.closed = True
        self._queue.put_nowait(_CLOSED)

    # Test-side helpers ----------------------------------------------------
    def feed(self, event: STTEvent) -> None:
        """Inject one event into the live stream."""
        self._queue.put_nowait(event)

    def feed_error(self, exc: BaseException) -> None:
        """Cause the next ``events()`` pull to raise ``exc``."""
        self._queue.put_nowait(_ErrorBox(exc))
