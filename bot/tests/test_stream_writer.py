"""Tests for jarvis.stream_writer.stream_to_discord."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from jarvis.stream_writer import stream_to_discord


class FakeMessage:
    def __init__(self) -> None:
        self.edits: list[str] = []
        self.edit = self._record_edit  # bind as method-style

    async def _record_edit(self, *, content: str) -> None:
        self.edits.append(content)


async def _gen(chunks: list[str], sleep_ms: float = 0.0):
    for c in chunks:
        if sleep_ms:
            await asyncio.sleep(sleep_ms / 1000.0)
        yield c


async def test_stream_to_discord_does_at_least_one_edit():
    msg = FakeMessage()
    await stream_to_discord(msg, _gen(["hello"]))
    assert msg.edits, "expected at least one edit"
    assert msg.edits[-1] == "hello"


async def test_stream_to_discord_final_content_is_full_concatenation():
    msg = FakeMessage()
    await stream_to_discord(msg, _gen(["hel", "lo ", "world"]))
    assert msg.edits[-1] == "hello world"


async def test_stream_to_discord_handles_empty_stream():
    msg = FakeMessage()
    await stream_to_discord(msg, _gen([]))
    # Falls back to a single placeholder edit so the user isn't left
    # staring at "thinking…".
    assert msg.edits == ["(empty response)"]


async def test_stream_to_discord_does_not_edit_per_token():
    """Many small tokens should NOT mean many small edits — burst protection."""
    msg = FakeMessage()
    chunks = [chr(ord("a") + i % 26) for i in range(200)]  # 200 tiny chunks
    await stream_to_discord(msg, _gen(chunks))
    # Should be MUCH fewer than 200 edits — at most ~10 given default thresholds.
    assert len(msg.edits) < 30, f"too many edits: {len(msg.edits)}"
    assert msg.edits[-1] == "".join(chunks)


async def test_stream_to_discord_flushes_on_chunk_threshold():
    """A single big chunk should produce at least one edit."""
    msg = FakeMessage()
    big = "x" * 500
    await stream_to_discord(msg, _gen([big]))
    assert any(e == big for e in msg.edits)
