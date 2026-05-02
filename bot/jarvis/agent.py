"""Anthropic Claude streaming wrapper for Jarvis.

PR 2 is text-only — no tool-use loop yet (PR 3 adds it). The single
public function `respond(...)` takes the system prompt, prior turns,
and a new user message, and returns an async iterator of text deltas
that the Discord layer streams back into the thread.

The system prompt is passed with `cache_control: ephemeral` so the
prompt-cache hits across turns within the same thread (and across
threads as long as the prompt is unchanged). This is the same caching
pattern app/llm/client.py uses.

Model selection: claude-sonnet-4-6 — right speed/quality balance for
chat. Haiku is reserved for the telephony hot path. Mixing models
within one tool-use loop isn't supported, so when PR 3 adds tools the
whole loop runs on Sonnet too.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024


async def respond(
    *,
    anthropic_client: AsyncAnthropic,
    system_prompt: str,
    history: list[dict[str, Any]],
    user_message: str,
) -> AsyncIterator[str]:
    """Yield text deltas from a Claude response.

    `history` is the conversation history in Anthropic message format
    (a list of {"role": "user"|"assistant", "content": str}). The new
    `user_message` is appended internally; the caller's `history` list
    is not mutated.
    """
    messages = list(history) + [{"role": "user", "content": user_message}]
    async with anthropic_client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    ) as stream:
        async for delta in stream.text_stream:
            yield delta
