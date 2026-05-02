"""Anthropic Claude streaming wrapper for Jarvis with tool-use loop.

Public API stays the same (yields text deltas) but the function now
accepts an optional ToolRegistry + ToolContext. When both are present
and the registry has tools, the loop hands `tools=...` to Anthropic on
each turn and processes any `tool_use` blocks it returns by dispatching
through the registry and feeding back `tool_result` blocks. Loops at
most MAX_TOOL_STEPS times; if the model keeps asking for tools beyond
that, the loop aborts with a brief safety message so the user isn't
left empty-handed.

Streaming-with-tools nuance: each loop iteration is a fresh streaming
call. Text deltas yielded mid-iteration arrive in real time. After a
tool round-trip, the next iteration's text continues seamlessly to the
caller (the events handler edits the same Discord placeholder).
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

from anthropic import AsyncAnthropic

from jarvis.tools import ToolContext, ToolRegistry

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024
MAX_TOOL_STEPS = 6


async def respond(
    *,
    anthropic_client: AsyncAnthropic,
    system_prompt: str,
    history: list[dict[str, Any]],
    user_message: str,
    tool_registry: Optional[ToolRegistry],
    tool_context: ToolContext,
) -> AsyncIterator[str]:
    """Yield text deltas from Claude, running tools as needed.

    `history` is the prior conversation in Anthropic message format
    (list of {"role": "user"|"assistant", "content": str}). `user_message`
    is appended internally; the caller's `history` is never mutated.

    If `tool_registry` is None or empty, this is a no-tools call (PR 2
    behavior).
    """
    messages: list[dict[str, Any]] = list(history) + [
        {"role": "user", "content": user_message}
    ]

    tools_payload: Optional[list[dict[str, Any]]] = None
    if tool_registry is not None and tool_registry.names():
        tools_payload = tool_registry.as_anthropic_tools()

    for step in range(MAX_TOOL_STEPS):
        stream_kwargs: dict[str, Any] = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": messages,
        }
        if tools_payload is not None:
            stream_kwargs["tools"] = tools_payload

        async with anthropic_client.messages.stream(**stream_kwargs) as stream:
            async for delta in stream.text_stream:
                yield delta
            final = await stream.get_final_message()

        tool_uses = [
            b for b in final.content if getattr(b, "type", None) == "tool_use"
        ]
        if not tool_uses:
            return  # done

        # Append the assistant's full turn (text + tool_use blocks) and
        # then a user-role message carrying the tool_result blocks.
        assistant_blocks: list[dict[str, Any]] = []
        for b in final.content:
            btype = getattr(b, "type", None)
            if btype == "text":
                assistant_blocks.append({"type": "text", "text": b.text})
            elif btype == "tool_use":
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": b.id,
                        "name": b.name,
                        "input": b.input,
                    }
                )
        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_result_blocks: list[dict[str, Any]] = []
        if tool_registry is None:
            # Defensive: model asked for a tool but we have no registry.
            for tu in tool_uses:
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(
                            {"error": "no tools available"}
                        ),
                    }
                )
        else:
            for tu in tool_uses:
                content_str = await tool_registry.dispatch(
                    name=tu.name,
                    tool_input=tu.input or {},
                    context=tool_context,
                )
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": content_str,
                    }
                )
        messages.append({"role": "user", "content": tool_result_blocks})

    # Reached MAX_TOOL_STEPS without a non-tool turn. Yield a safety
    # message so the user sees something.
    yield (
        "(I hit my max tool-use step count and didn't finish — "
        "could you try a more specific question?)"
    )
