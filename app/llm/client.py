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
from app.orders.models import Order
from app.orders.validation import validate_delivery_address

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
                            "description": (
                                "Free-form category from the menu (e.g. "
                                "appetizer, main, soup, drink, dessert). "
                                "Used for grouping in the dashboard — not "
                                "validated against a fixed enum, since "
                                "tenants pick their own category names."
                            ),
                        },
                        "size": {
                            "type": ["string", "null"],
                            "description": (
                                "Required when the menu item is multi-size "
                                "(small/medium/large, half/whole, etc.) — "
                                "use whichever size keys the menu shows. "
                                "Null for single-priced items."
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


def _serialize_block(block: Any) -> dict[str, Any]:
    """Convert an SDK content block to the dict shape the Messages API accepts.

    The Anthropic SDK's streaming blocks carry extra attributes like
    ``parsed_output`` that ``model_dump()`` faithfully serializes — but the
    Messages API rejects unknown fields, so any subsequent turn that threads
    that history 400s. We rebuild the API-valid shape by hand instead.
    """
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    raise ValueError(f"Unsupported content block type: {block.type!r}")


def _summarize_order(order: Order) -> str:
    """Server-side summary fed back to the LLM as a ``tool_result``.

    Returning the post-apply subtotal + item list closes the
    accuracy hole observed on the 2026-04-26 Twilight call where
    Haiku quoted a $50.50 total for an order that actually summed to
    $49.25 — without a server-verified number in the tool_result, the
    model fabricates totals from its memory of unit prices. Now it
    has a ground-truth subtotal to read back instead.
    """
    if not order.items:
        return "Order updated. Subtotal: $0.00. (no items yet)"
    items_summary = ", ".join(
        f"{item.quantity}× {item.name}"
        + (f" ({', '.join(item.modifications)})" if item.modifications else "")
        for item in order.items
    )
    return f"Order updated. Subtotal: ${order.subtotal:.2f}. Items: {items_summary}."


def _tool_result_block(tool_use_id: str, content: str = "Order updated.") -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }


def _system_cache_block(system_prompt: str) -> list[dict[str, Any]]:
    """Wrap the system prompt for Anthropic prompt caching.

    Passing system as a list with cache_control=ephemeral tells Anthropic
    to cache the block server-side for up to 5 minutes. Cache hits reduce
    system-prompt token cost by ~90% and shave first-token latency on
    turns 2+ of the same call — near-certain for any call lasting > 20s.
    """
    return [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _append_user_transcript(
    history: list[dict[str, Any]], transcript: str
) -> list[dict[str, Any]]:
    """Append the caller's transcript to history with valid alternation.

    Anthropic requires strict user/assistant alternation. After a turn
    that produced both text and a ``tool_use``, history ends in a synthetic
    ``user: [tool_result]`` message. Appending another ``user`` message
    would error, so we merge the new transcript into that pending
    ``tool_result`` message instead.
    """
    if (
        history
        and history[-1]["role"] == "user"
        and isinstance(history[-1]["content"], list)
        and history[-1]["content"]
        and history[-1]["content"][0].get("type") == "tool_result"
    ):
        merged = [
            *history[-1]["content"],
            {"type": "text", "text": transcript},
        ]
        return [*history[:-1], {"role": "user", "content": merged}]
    return [*history, {"role": "user", "content": transcript}]


_INVALID_ADDRESS_NOTE = (
    "Delivery address incomplete — please ask the caller for the full "
    "street address."
)


def _apply_validation(patch: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Filter an update_order patch through server-side validators.

    Returns a (cleaned_patch, rejection_notes) tuple:
    - cleaned_patch is a copy of patch with any field that failed
      validation removed (so the previous Order value stays put when
      the patch is applied).
    - rejection_notes is a list of human-readable strings to append to
      the tool_result so Haiku knows to re-ask the caller. Empty when
      every field passed validation.

    Today only delivery_address has a validator (Sprint 2.2 #105). New
    field validators slot in here so _apply_update stays a dumb
    dict-merger and orchestration stays in one place.

    Note on explicit-clear intents: when Haiku ships
    delivery_address=None or "" (e.g. swapping order_type from
    delivery to pickup), that's a legitimate clear, not a rejection.
    The validator returns False for both, so we only invoke it when
    there's actual non-empty content to validate.
    """
    cleaned = dict(patch)
    notes: list[str] = []
    if "delivery_address" in cleaned:
        value = cleaned["delivery_address"]
        # None / empty / whitespace-only is an explicit clear — pass through.
        # Only validate when the caller actually provided content.
        if value is not None and isinstance(value, str) and value.strip():
            if not validate_delivery_address(value):
                del cleaned["delivery_address"]
                notes.append(_INVALID_ADDRESS_NOTE)
    return cleaned, notes


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
    system_prompt: str,
    client: Optional[Anthropic] = None,
) -> LLMResponse:
    """Send the caller's latest transcript to Haiku and return a reply.

    ``system_prompt`` is rendered per call from the inbound restaurant's
    config (#79); the previously-cached module-level prompt is gone.

    ``history`` is Anthropic's Messages format: a list of
    ``{"role": "user"|"assistant", "content": ...}`` dicts. The updated
    history (with the new user turn and the assistant turn appended) is
    returned in ``LLMResponse.history`` so the caller can thread it
    into the next turn verbatim — including any tool_use blocks, which
    Anthropic requires to stay in context.
    """

    api = client or _client()

    new_history = _append_user_transcript(history, transcript)

    response = api.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_system_cache_block(system_prompt),
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
    tool_results: list[dict[str, Any]] = []
    for tu in tool_uses:
        cleaned_input, rejection_notes = _apply_validation(tu["input"])
        updated_order = _apply_update(updated_order, cleaned_input)
        summary = _summarize_order(updated_order)
        if rejection_notes:
            summary = summary + " " + " ".join(rejection_notes)
        tool_results.append(_tool_result_block(tu["id"], summary))

    assistant_content = [_serialize_block(block) for block in response.content]
    new_history = [
        *new_history,
        {"role": "assistant", "content": assistant_content},
    ]

    if tool_uses:
        new_history = [
            *new_history,
            {"role": "user", "content": tool_results},
        ]

    if not reply_text_parts and tool_uses:
        followup = api.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_system_cache_block(system_prompt),
            tools=[UPDATE_ORDER_TOOL],
            messages=new_history,
        )
        for block in followup.content:
            if block.type == "text":
                reply_text_parts.append(block.text)
        followup_content = [_serialize_block(block) for block in followup.content]
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
    system_prompt: str,
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

    new_history = _append_user_transcript(history, transcript)

    text_parts: list[str] = []
    tool_uses: list[dict[str, Any]] = []

    async with api.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_system_cache_block(system_prompt),
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
    tool_results: list[dict[str, Any]] = []
    for tu in tool_uses:
        cleaned_input, rejection_notes = _apply_validation(tu["input"])
        updated_order = _apply_update(updated_order, cleaned_input)
        summary = _summarize_order(updated_order)
        if rejection_notes:
            summary = summary + " " + " ".join(rejection_notes)
        tool_results.append(_tool_result_block(tu["id"], summary))

    assistant_content = [_serialize_block(block) for block in first_message.content]
    new_history = [
        *new_history,
        {"role": "assistant", "content": assistant_content},
    ]

    if tool_uses:
        new_history = [
            *new_history,
            {"role": "user", "content": tool_results},
        ]

    text_emitted = bool(text_parts)
    if not text_emitted and tool_uses:
        async with api.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_system_cache_block(system_prompt),
            tools=[UPDATE_ORDER_TOOL],
            messages=new_history,
        ) as followup_stream:
            async for delta in followup_stream.text_stream:
                text_parts.append(delta)
                yield StreamEvent(text_delta=delta)
            followup_message = await followup_stream.get_final_message()
        followup_content = [_serialize_block(b) for b in followup_message.content]
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
