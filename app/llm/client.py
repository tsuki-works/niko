"""Anthropic Claude Haiku 4.5 client for the voice ordering agent.

Takes a caller transcript plus conversation history and the current
order state, returns the assistant's spoken reply along with any
updates to the order (produced via the ``update_order`` tool).

The tool schema mirrors ``app.orders.models.Order`` so Haiku can emit
partial order state incrementally. The model can both speak to the
caller and call ``update_order`` in the same turn — we process both
and advance the conversation.

Two entry points:

- ``generate_reply`` — synchronous round-trip. Used by tests and any
  offline / batch path. Waits for Haiku to finish before returning.
- ``stream_reply`` — async generator that yields text deltas as Haiku
  produces them, then yields a terminal event with the final order
  and threaded history. Used by the call-flow orchestrator (#40) to
  start TTS before the full reply is ready and hit the <1s first-audio
  latency budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from anthropic import Anthropic, AsyncAnthropic

from app.config import settings
from app.llm.prompts import SYSTEM_PROMPT
from app.orders.models import Order

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 512

UPDATE_ORDER_TOOL: dict[str, Any] = {
    "name": "update_order",
    "description": (
        "Record the caller's current order state. Call this whenever "
        "the order changes — items added, removed, or modified; order "
        "type decided; delivery address given; or the caller confirms "
        "or cancels. Emit the FULL current order state each time, not "
        "a diff."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "Full list of line items currently in the order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ["pizza", "side", "drink"],
                        },
                        "size": {
                            "type": ["string", "null"],
                            "description": (
                                "For pizzas: small | medium | large. "
                                "Null for sides and drinks."
                            ),
                        },
                        "quantity": {"type": "integer", "minimum": 1},
                        "unit_price": {
                            "type": "number",
                            "description": "Per-unit price from the menu.",
                        },
                        "modifications": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Customizations like 'extra cheese' or "
                                "'no onions'."
                            ),
                        },
                    },
                    "required": ["name", "category", "quantity", "unit_price"],
                },
            },
            "order_type": {
                "type": ["string", "null"],
                "enum": ["pickup", "delivery", None],
            },
            "delivery_address": {"type": ["string", "null"]},
            "status": {
                "type": "string",
                "enum": ["in_progress", "confirmed", "cancelled"],
            },
        },
    },
}


@dataclass
class LLMResponse:
    reply_text: str
    order: Order
    history: list[dict[str, Any]]


@dataclass
class StreamEvent:
    """One event yielded by ``stream_reply``.

    Exactly one of ``text_delta`` or ``final`` is set on any given
    event. Text-delta events arrive incrementally as Haiku produces
    output; the terminal ``final`` event carries the assembled
    ``LLMResponse`` (full reply text, updated order, threaded history)
    so the caller can persist state and prepare for the next turn.
    """

    text_delta: Optional[str] = None
    final: Optional[LLMResponse] = None


def _missing_key_error() -> RuntimeError:
    return RuntimeError(
        "ANTHROPIC_API_KEY not set — cannot call the LLM. "
        "Populate it in your .env (fetch via /shared-creds)."
    )


def _client() -> Anthropic:
    key = settings.anthropic_api_key
    if not key:
        raise _missing_key_error()
    return Anthropic(api_key=key)


def _async_client() -> AsyncAnthropic:
    key = settings.anthropic_api_key
    if not key:
        raise _missing_key_error()
    return AsyncAnthropic(api_key=key)


def _apply_update(order: Order, patch: dict[str, Any]) -> Order:
    """Merge a tool-call payload into the current Order.

    Preserves call_sid, caller_phone, restaurant_id, and created_at
    from the existing order so the LLM cannot overwrite them. Every
    other field the LLM provided is accepted as the new authoritative
    value.
    """

    preserved = {
        "call_sid": order.call_sid,
        "caller_phone": order.caller_phone,
        "restaurant_id": order.restaurant_id,
        "created_at": order.created_at,
    }
    merged = {**order.model_dump(), **patch, **preserved}
    return Order.model_validate(merged)


def generate_reply(
    *,
    transcript: str,
    history: list[dict[str, Any]],
    order: Order,
    client: Optional[Anthropic] = None,
) -> LLMResponse:
    """Send the caller's latest transcript to Haiku and return a reply.

    ``history`` is Anthropic's Messages format: a list of
    ``{"role": "user"|"assistant", "content": ...}`` dicts. The updated
    history (with the new user turn and the assistant turn appended) is
    returned in ``LLMResponse.history`` so the caller can thread it
    into the next turn verbatim — including any tool_use blocks, which
    Anthropic requires to stay in context.
    """

    api = client or _client()

    new_history = [*history, {"role": "user", "content": transcript}]

    response = api.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[UPDATE_ORDER_TOOL],
        messages=new_history,
    )

    reply_text_parts: list[str] = []
    tool_uses: list[dict[str, Any]] = []
    for block in response.content:
        if block.type == "text":
            reply_text_parts.append(block.text)
        elif block.type == "tool_use" and block.name == "update_order":
            tool_uses.append({"id": block.id, "input": block.input})

    updated_order = order
    for tu in tool_uses:
        updated_order = _apply_update(updated_order, tu["input"])

    assistant_content = [block.model_dump() for block in response.content]
    new_history = [
        *new_history,
        {"role": "assistant", "content": assistant_content},
    ]

    if not reply_text_parts and tool_uses:
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": "Order updated.",
            }
            for tu in tool_uses
        ]
        new_history = [
            *new_history,
            {"role": "user", "content": tool_results},
        ]
        followup = api.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[UPDATE_ORDER_TOOL],
            messages=new_history,
        )
        for block in followup.content:
            if block.type == "text":
                reply_text_parts.append(block.text)
        followup_content = [block.model_dump() for block in followup.content]
        new_history = [
            *new_history,
            {"role": "assistant", "content": followup_content},
        ]

    return LLMResponse(
        reply_text="".join(reply_text_parts).strip(),
        order=updated_order,
        history=new_history,
    )


async def stream_reply(
    *,
    transcript: str,
    history: list[dict[str, Any]],
    order: Order,
    client: Optional[AsyncAnthropic] = None,
) -> AsyncIterator[StreamEvent]:
    """Stream Haiku's reply token-by-token for low-latency TTS handoff.

    Yields ``StreamEvent(text_delta=str)`` for each incremental chunk
    of the assistant's spoken reply, then a single terminal
    ``StreamEvent(final=LLMResponse)`` with the full reply text,
    updated order, and threaded history.

    The contract matches ``generate_reply`` for tool-use semantics:
    if the first turn emits only ``update_order`` blocks (no text),
    we send a ``tool_result`` and stream a follow-up call so the
    caller still gets a spoken reply. In practice this is the
    "I cancelled the order" path — the model often wants to confirm
    the side effect before talking back.
    """

    api = client or _async_client()

    new_history = [*history, {"role": "user", "content": transcript}]

    text_parts: list[str] = []
    tool_uses: list[dict[str, Any]] = []

    async with api.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[UPDATE_ORDER_TOOL],
        messages=new_history,
    ) as stream:
        async for delta in stream.text_stream:
            text_parts.append(delta)
            yield StreamEvent(text_delta=delta)
        first_message = await stream.get_final_message()

    for block in first_message.content:
        if block.type == "tool_use" and block.name == "update_order":
            tool_uses.append({"id": block.id, "input": block.input})

    updated_order = order
    for tu in tool_uses:
        updated_order = _apply_update(updated_order, tu["input"])

    assistant_content = [block.model_dump() for block in first_message.content]
    new_history = [
        *new_history,
        {"role": "assistant", "content": assistant_content},
    ]

    text_emitted = bool(text_parts)
    if not text_emitted and tool_uses:
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": "Order updated.",
            }
            for tu in tool_uses
        ]
        new_history = [
            *new_history,
            {"role": "user", "content": tool_results},
        ]
        async with api.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[UPDATE_ORDER_TOOL],
            messages=new_history,
        ) as followup_stream:
            async for delta in followup_stream.text_stream:
                text_parts.append(delta)
                yield StreamEvent(text_delta=delta)
            followup_message = await followup_stream.get_final_message()
        followup_content = [b.model_dump() for b in followup_message.content]
        new_history = [
            *new_history,
            {"role": "assistant", "content": followup_content},
        ]

    yield StreamEvent(
        final=LLMResponse(
            reply_text="".join(text_parts).strip(),
            order=updated_order,
            history=new_history,
        )
    )
