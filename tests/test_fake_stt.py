"""Tests for tests/fakes/stt.py — the FakeSTT test double itself.

We test the fake because every other test in this push relies on it
behaving exactly like a real STTProvider should. A bug in the fake
would be a bug in dozens of consumer tests at once.
"""

from __future__ import annotations

import asyncio

import pytest

from app.stt.base import SpeechStartedEvent, TranscriptEvent
from tests.fakes.stt import FakeSTT


@pytest.mark.asyncio
async def test_open_marks_opened() -> None:
    fake = FakeSTT()
    await fake.open()
    assert fake.opened is True


@pytest.mark.asyncio
async def test_send_records_audio_chunks_in_order() -> None:
    fake = FakeSTT()
    await fake.send(b"chunk1")
    await fake.send(b"chunk2")
    assert fake.sent == [b"chunk1", b"chunk2"]


@pytest.mark.asyncio
async def test_events_yields_seeded_events_in_order() -> None:
    seeded = [
        TranscriptEvent("hi", False, 0.7),
        TranscriptEvent("hello", True, 0.95),
    ]
    fake = FakeSTT(events=seeded)
    await fake.open()

    received = []

    async def consume():
        async for event in fake.events():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let consumer drain seeded items
    await fake.close()
    await task

    assert received == seeded


@pytest.mark.asyncio
async def test_feed_injects_event_into_live_stream() -> None:
    fake = FakeSTT()
    await fake.open()

    received = []

    async def consume():
        async for event in fake.events():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    fake.feed(SpeechStartedEvent())
    fake.feed(TranscriptEvent("ok", True, 0.9))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert isinstance(received[0], SpeechStartedEvent)
    assert isinstance(received[1], TranscriptEvent)
    assert received[1].text == "ok"


@pytest.mark.asyncio
async def test_feed_error_raises_from_events() -> None:
    fake = FakeSTT()
    await fake.open()
    fake.feed_error(RuntimeError("dropped"))

    with pytest.raises(RuntimeError, match="dropped"):
        async for _event in fake.events():
            pass


@pytest.mark.asyncio
async def test_close_terminates_events_iterator() -> None:
    fake = FakeSTT()
    await fake.open()
    await fake.close()

    received = []
    async for event in fake.events():
        received.append(event)

    assert received == []
    assert fake.closed is True


@pytest.mark.asyncio
async def test_send_before_open_records_chunks() -> None:
    """The fake doesn't enforce open() ordering — send() always records.
    Real providers may raise; the fake is permissive so tests can stub
    a partial flow without ceremony."""
    fake = FakeSTT()
    await fake.send(b"first")
    assert fake.sent == [b"first"]


@pytest.mark.asyncio
async def test_double_close_is_safe() -> None:
    """Closing twice doesn't raise. The second _CLOSED sits in the queue
    harmlessly; the iterator has already returned and won't read it."""
    fake = FakeSTT()
    await fake.open()
    await fake.close()
    await fake.close()  # should not raise
    assert fake.closed is True


@pytest.mark.asyncio
async def test_each_event_goes_to_exactly_one_consumer() -> None:
    """The fake's queue is single-consumer: each enqueued item is
    handed to exactly one waiting events() iterator. Two consumers
    blocked on an empty queue, then one event is fed — exactly one
    receives it."""
    fake = FakeSTT()
    await fake.open()

    a_received: list[TranscriptEvent] = []
    b_received: list[TranscriptEvent] = []

    async def drain(into: list[TranscriptEvent]) -> None:
        async for event in fake.events():
            into.append(event)

    task_a = asyncio.create_task(drain(a_received))
    task_b = asyncio.create_task(drain(b_received))
    # Let both consumers reach `await queue.get()` with the queue empty.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    fake.feed(TranscriptEvent("only", True, 0.9))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    await fake.close()
    await asyncio.sleep(0)
    if not task_a.done():
        task_a.cancel()
    if not task_b.done():
        task_b.cancel()

    assert len(a_received) + len(b_received) == 1
