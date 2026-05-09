"""Provider-neutral order-update domain logic.

Helpers shared across every LLM provider for the ``update_order`` tool
flow:

- ``apply_order_patch`` — merge a tool-call payload into the current
  ``Order``, preserving server-owned identifiers.
- ``validate_order_patch`` — filter a patch through server-side
  validators (today: delivery address). Returns the cleaned patch plus
  rejection notes the provider should append to its tool_result so the
  model knows to re-ask the caller.
- ``summarize_order_for_tool_result`` — render a server-verified
  subtotal + item list as the string body of a tool_result, closing
  the accuracy hole where the model otherwise fabricates totals.
- ``should_skip_followup`` — decide whether the post-tool-use
  follow-up call can be skipped (terminal-status turn where the main
  call already spoke).

These functions take and return plain dicts / domain objects so any
provider can call them without leaking wire-format concerns.
"""

from __future__ import annotations

from typing import Any

from app.orders.models import Order
from app.orders.validation import validate_delivery_address

INVALID_ADDRESS_NOTE = (
    "Delivery address incomplete — please ask the caller for the full street address."
)

TERMINAL_STATUSES = frozenset({"confirmed", "cancelled"})


def summarize_order_for_tool_result(order: Order) -> str:
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


def validate_order_patch(patch: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Filter an update_order patch through server-side validators.

    Returns a (cleaned_patch, rejection_notes) tuple:
    - cleaned_patch is a copy of patch with any field that failed
      validation removed (so the previous Order value stays put when
      the patch is applied).
    - rejection_notes is a list of human-readable strings to append to
      the tool_result so the model knows to re-ask the caller. Empty
      when every field passed validation.

    Today only delivery_address has a validator (Sprint 2.2 #105). New
    field validators slot in here so ``apply_order_patch`` stays a dumb
    dict-merger and orchestration stays in one place.

    Note on explicit-clear intents: when the model ships
    ``delivery_address=None`` or ``""`` (e.g. swapping order_type from
    delivery to pickup), that's a legitimate clear, not a rejection.
    The validator returns False for both, so we only invoke it when
    there's actual non-empty content to validate.
    """
    cleaned = dict(patch)
    notes: list[str] = []
    if "delivery_address" in cleaned:
        value = cleaned["delivery_address"]
        if value is not None and isinstance(value, str) and value.strip():
            if not validate_delivery_address(value):
                del cleaned["delivery_address"]
                notes.append(INVALID_ADDRESS_NOTE)
    return cleaned, notes


def should_skip_followup(tool_uses: list[dict[str, Any]], main_emitted_text: bool) -> bool:
    """Decide whether to skip the post-tool-use follow-up LLM call.

    The follow-up exists to give the model a chance to speak after
    seeing ``tool_result`` feedback. On terminal-status turns
    (confirmed or cancelled) the call is ending — there is no next
    caller turn for the model to react to — and if the main call
    already emitted text the caller has already heard the goodbye. In
    that case the follow-up is pure latency.

    The follow-up still runs when the main call was tool-only on a
    terminal turn (caller hasn't heard anything yet), or on any
    non-terminal turn (mid-order item adds need the server-verified
    subtotal in tool_result before the next "anything else?").

    ``tool_uses`` items must have an ``input`` dict; the function only
    reads ``input.status`` so any provider can map its native tool-use
    representation onto this shape.
    """
    if not main_emitted_text:
        return False
    return any(tu["input"].get("status") in TERMINAL_STATUSES for tu in tool_uses)


def apply_order_patch(order: Order, patch: dict[str, Any]) -> Order:
    """Merge a tool-call payload into the current ``Order``.

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


__all__ = [
    "INVALID_ADDRESS_NOTE",
    "TERMINAL_STATUSES",
    "apply_order_patch",
    "should_skip_followup",
    "summarize_order_for_tool_result",
    "validate_order_patch",
]
