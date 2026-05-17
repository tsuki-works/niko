"""LLM provider contract.

The router talks to the LLM through this interface; concrete providers
(today: Anthropic) live under ``app/llm/<vendor>.py``. Future providers
implement the same Protocol and become a one-line addition to
``get_llm()`` in ``app/llm/__init__.py``.

Tool definitions are kept provider-neutral via ``ToolSpec``; each
provider renders the spec into its own native wire shape (Anthropic
``input_schema``; OpenAI ``function``; Gemini function declaration).

Two known leaks documented below:

- ``StreamEvent.timing`` payload — ``ttft_seconds`` and
  ``tool_prefix_seconds`` are neutral; the four other fields
  (``network_prefill_seconds``, ``decode_seconds``,
  ``cache_read_tokens``, ``cache_creation_tokens``) map cleanly to
  Anthropic concepts only. Other providers should report ``0`` for
  fields they cannot derive. TODO: revisit timing schema when adding a
  second provider.
- ``LLMResponse.history`` — opaque to the router, but the *inner*
  shape is **provider-private**. History returned by a provider must
  only be passed back to the same provider on subsequent turns.
  Provider hot-swap within a call is not supported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, Protocol

from app.orders.models import Order


@dataclass
class ToolSpec:
    """Provider-neutral tool definition.

    ``parameters`` is a JSON Schema dict — the same shape Anthropic
    expects under ``input_schema`` and OpenAI expects under
    ``function.parameters``. Each provider wraps this into its native
    request shape at the edge.
    """

    name: str
    description: str
    parameters: dict[str, Any]


# ---------------------------------------------------------------------------
# Atomic tool specs (#305 Part B)
# ---------------------------------------------------------------------------
#
# Six narrow operations replacing the single snapshot ``update_order``
# tool. Discrimination between tools depends on the descriptions below —
# the model picks a tool by matching caller intent against
# ``name`` + ``description``, so each description has to be intent-keyed
# and non-overlapping. The provider's atomic dispatch
# (``orchestration.apply_tool_call``) keys off ``name``.


_ADD_ITEM_SPEC: ToolSpec = ToolSpec(
    name="add_item",
    description=(
        "Add a new line item to the order. Call this when the caller "
        "asks for something not already in the order, or asks for a "
        "different size or variant of an existing item — different "
        "sizes are SEPARATE line items, not in-place size changes. "
        "For changing the size or quantity of an item already in the "
        "order, use update_item instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Menu item name."},
            "category": {
                "type": "string",
                "description": (
                    "Free-form category from the menu (appetizer, main, "
                    "soup, drink, dessert, etc.). Use whatever category "
                    "key the menu lists — not validated against a fixed enum."
                ),
            },
            "size": {
                "type": ["string", "null"],
                "description": (
                    "Required when the menu item is multi-size "
                    "(small/medium/large, half/whole, etc.) — use the "
                    "size key the menu shows. Null for single-priced items."
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
                "description": "Customizations like 'extra cheese' or 'no onions'.",
            },
        },
        "required": ["name", "category", "quantity", "unit_price"],
    },
)


_REMOVE_ITEM_SPEC: ToolSpec = ToolSpec(
    name="remove_item",
    description=(
        "Remove a line item from the order, identified by item_id. The "
        "item_id was surfaced in the tool_result when the item was "
        "added — read it from your prior tool_result blocks rather than "
        "inventing one. Call this when the caller takes something back "
        "('scratch the wings', 'no actually skip the coke')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
                "description": (
                    "The 'i_xxxxxx' ID surfaced in a prior tool_result "
                    "for the item you want to remove."
                ),
            },
        },
        "required": ["item_id"],
    },
)


_UPDATE_ITEM_SPEC: ToolSpec = ToolSpec(
    name="update_item",
    description=(
        "Modify an existing line item identified by item_id. Use for: "
        "quantity changes ('make that two'), size changes on the same "
        "line ('change to large' — also update unit_price to match the "
        "menu's price for the new size), and modification edits ('add "
        "no onions', 'remove extra cheese'). The item_id was surfaced "
        "in a prior tool_result — read it from there rather than "
        "inventing one. If the caller is adding a DIFFERENT size or "
        "variant alongside the existing item, use add_item instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
                "description": (
                    "The 'i_xxxxxx' ID surfaced in a prior tool_result "
                    "for the item you want to modify."
                ),
            },
            "name": {"type": "string"},
            "category": {"type": "string"},
            "size": {"type": ["string", "null"]},
            "quantity": {"type": "integer", "minimum": 1},
            "unit_price": {"type": "number"},
            "modifications": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Full new list of modifications — replaces the existing list, does not append."
                ),
            },
        },
        "required": ["item_id"],
    },
)


_SET_ORDER_TYPE_SPEC: ToolSpec = ToolSpec(
    name="set_order_type",
    description=(
        "Set the order as pickup or delivery. Call when the caller "
        "decides. Switching to pickup automatically clears any "
        "previously captured delivery address — no need to call "
        "set_delivery_address(null) afterward."
    ),
    parameters={
        "type": "object",
        "properties": {
            "order_type": {
                "type": "string",
                "enum": ["pickup", "delivery"],
            },
        },
        "required": ["order_type"],
    },
)


_SET_DELIVERY_ADDRESS_SPEC: ToolSpec = ToolSpec(
    name="set_delivery_address",
    description=(
        "Capture the caller's delivery address. Only meaningful when "
        "order_type is delivery. Pass null or an empty string to clear "
        "an existing address (e.g., the caller wants to change it)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "delivery_address": {
                "type": ["string", "null"],
                "description": (
                    "Full street address as the caller stated it. "
                    "Null or empty string clears the field."
                ),
            },
        },
        "required": ["delivery_address"],
    },
)


_SET_STATUS_SPEC: ToolSpec = ToolSpec(
    name="set_status",
    description=(
        "Mark the order as confirmed (caller explicitly confirmed "
        "after the read-back) or cancelled (caller cancelled the "
        "order). Do NOT call confirmed on a vague 'uh huh' mid-call — "
        "only on an explicit yes after you've read the full order "
        "back. Kitchen workflow states (preparing/ready/completed) "
        "are not available here; the dashboard owns those."
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["confirmed", "cancelled"],
            },
        },
        "required": ["status"],
    },
)


ATOMIC_TOOL_SPECS: list[ToolSpec] = [
    _ADD_ITEM_SPEC,
    _REMOVE_ITEM_SPEC,
    _UPDATE_ITEM_SPEC,
    _SET_ORDER_TYPE_SPEC,
    _SET_DELIVERY_ADDRESS_SPEC,
    _SET_STATUS_SPEC,
]


@dataclass
class LLMResponse:
    """Terminal value returned by a provider after a complete turn.

    ``history`` is opaque to the router but **provider-private** in
    shape — see module docstring. Pass it back to the same provider
    only.
    """

    reply_text: str
    order: Order
    history: list[dict[str, Any]]


@dataclass
class StreamEvent:
    """One event yielded by ``LLMProvider.stream_reply``.

    At most one of ``text_delta``, ``timing``, or ``final`` is set on
    any given event; ``flush_now`` is a boolean signal that can be set
    on its own event (no payload) or alongside a ``text_delta``. Text
    deltas arrive incrementally as the model produces output; a
    ``timing`` event lands the moment the first text block opens (so
    the router can fold the latency breakdown into its ``first_audio``
    Firestore event before TTS starts); ``flush_now`` fires at content
    block boundaries (#305) so the caller can drain any buffered TTS
    text before the next block starts — critical on text-then-tool
    turns where the buffered text would otherwise sit idle until the
    tool round-trip completes. The terminal ``final`` event carries
    the assembled ``LLMResponse`` so the caller can persist state for
    the next turn.

    The ``timing`` payload has the shape::

        {
            "ttft_seconds": float,             # request → first SDK event (neutral)
            "tool_prefix_seconds": float,      # first event → first text block (neutral)
            "network_prefill_seconds": float,  # Anthropic-specific; 0 for others
            "decode_seconds": float,           # Anthropic-specific; 0 for others
            "cache_read_tokens": int,          # Anthropic-specific; 0 for others
            "cache_creation_tokens": int,      # Anthropic-specific; 0 for others
        }

    Tool-use turns emit a second timing event for the follow-up call so
    each network round-trip is measured independently.
    """

    text_delta: Optional[str] = None
    final: Optional[LLMResponse] = None
    timing: Optional[dict[str, Any]] = None
    flush_now: bool = False


class LLMProvider(Protocol):
    """Streaming + sync LLM contract.

    Providers expose two entry points:

    - ``stream_reply`` — async generator yielding ``StreamEvent``s.
      Used by the call-flow orchestrator to start TTS before the full
      reply lands and hit the first-audio latency budget.
    - ``generate_reply`` — synchronous round-trip used by tests, the
      offline replay harness, and any non-streaming consumer.

    ``history`` is threaded turn-to-turn verbatim — the provider owns
    its message shape and returns the updated history in
    ``LLMResponse.history``. Callers must not introspect or mutate it.
    """

    async def stream_reply(
        self,
        *,
        transcript: str,
        history: list[dict[str, Any]],
        order: Order,
        system_prompt: str,
    ) -> AsyncIterator[StreamEvent]: ...

    def generate_reply(
        self,
        *,
        transcript: str,
        history: list[dict[str, Any]],
        order: Order,
        system_prompt: str,
    ) -> LLMResponse: ...


__all__ = [
    "ATOMIC_TOOL_SPECS",
    "LLMProvider",
    "LLMResponse",
    "StreamEvent",
    "ToolSpec",
]
