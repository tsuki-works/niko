"""Anthropic Claude Haiku 4.5 client for the voice ordering agent.

Takes a caller transcript plus conversation history and the current
order state, returns the assistant's spoken reply along with any
updates to the order (produced via the ``update_order`` tool).

The tool schema mirrors ``app.orders.models.Order`` so Haiku can emit
partial order state incrementally. The model can both speak to the
caller and call ``update_order`` in the same turn — we process both
and advance the conversation.

Not streamed yet. #40 adds streaming to hit the <1s first-audio
latency budget; today we just prove the synchronous round-trip works.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from anthropic import Anthropic

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


def _client() -> Anthropic:
    key = settings.anthropic_api_key
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set — cannot call the LLM. "
            "Populate it in your .env (fetch via /shared-creds)."
        )
    return Anthropic(api_key=key)


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
