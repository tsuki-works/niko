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


UPDATE_ORDER_TOOL_SPEC: ToolSpec = ToolSpec(
    name="update_order",
    description=(
        "Record the caller's current order state. Call this whenever "
        "the order changes — items added, removed, or modified; order "
        "type decided; delivery address given; or the caller confirms "
        "or cancels. Emit the FULL current order state each time, not "
        "a diff."
    ),
    parameters={
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
                            "description": ("Customizations like 'extra cheese' or 'no onions'."),
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
)


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
    "LLMProvider",
    "LLMResponse",
    "StreamEvent",
    "ToolSpec",
    "UPDATE_ORDER_TOOL_SPEC",
]
