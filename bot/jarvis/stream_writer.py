"""Stream Anthropic text deltas into a Discord message.

Strategy: accumulate chunks in a string. After each chunk, check
whether enough time has passed since the last edit OR enough chars
have been buffered. If either, edit the placeholder. Always edit
once at the end so the final state is correct even if the burst
heuristics didn't trigger.

Edit cadence: every ~250ms is well within Discord's rate-limit
budget (5 edits / 5s per channel). The chunk-threshold flush is
there to keep latency low on big chunks (e.g. when Anthropic
emits a paragraph in one go).
"""

from __future__ import annotations

import time
from typing import AsyncIterator, Protocol

# Public knobs, exposed for tests and tuning.
EDIT_INTERVAL_S = 0.25
CHUNK_FLUSH_CHARS = 80


class _Editable(Protocol):
    async def edit(self, *, content: str) -> None: ...


async def stream_to_discord(
    placeholder: _Editable,
    chunks: AsyncIterator[str],
    *,
    edit_interval_s: float = EDIT_INTERVAL_S,
    chunk_flush_chars: int = CHUNK_FLUSH_CHARS,
) -> str:
    """Stream `chunks` into `placeholder.edit(content=...)`.

    Returns the final accumulated text. Always issues at least one
    edit even if the stream is empty (writes a placeholder so the
    caller isn't left looking at "thinking…").
    """
    accumulated = ""
    last_edit_at = time.monotonic()
    last_edit_len = 0

    async for chunk in chunks:
        accumulated += chunk
        now = time.monotonic()
        unflushed = len(accumulated) - last_edit_len
        time_elapsed = now - last_edit_at
        if time_elapsed >= edit_interval_s or unflushed >= chunk_flush_chars:
            await placeholder.edit(content=accumulated)
            last_edit_at = now
            last_edit_len = len(accumulated)

    if not accumulated:
        await placeholder.edit(content="(empty response)")
        return ""

    if last_edit_len < len(accumulated):
        await placeholder.edit(content=accumulated)

    return accumulated
