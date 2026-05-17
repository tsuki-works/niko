"""Provider-neutral order-update domain logic.

Helpers shared across every LLM provider for the atomic order tools
(#305 Part B):

- ``apply_tool_call`` — dispatch one atomic tool_use block to the right
  per-operation handler; returns the mutated ``Order`` plus rejection
  notes the provider should append to its tool_result so the model knows
  to re-ask the caller.
- ``summarize_order_for_tool_result`` — render a server-verified
  subtotal + item_id-prefixed item list as the string body of a
  tool_result, closing the accuracy hole where the model otherwise
  fabricates totals and surfacing item_ids the model uses for
  subsequent remove_item / update_item calls.
- ``should_skip_followup`` — decide whether the post-tool-use
  follow-up call can be skipped (terminal set_status turn where the
  main call already spoke).

These functions take and return plain dicts / domain objects so any
provider can call them without leaking wire-format concerns.
"""

from __future__ import annotations

from typing import Any, Callable

from app.orders.models import LineItem, Order, OrderStatus, OrderType
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

    Each line is prefixed with its ``item_id`` (e.g. ``[i_a3f4c1]``)
    so the model can reference it in subsequent ``remove_item`` /
    ``update_item`` calls (#305 Part B). The IDs live in the model's
    message history as plain tool_result text — that's where the model
    reads them from when constructing later tool calls.
    """
    if not order.items:
        return "Order updated. Subtotal: $0.00. (no items yet)"
    items_summary = ", ".join(
        f"[{item.item_id}] {item.quantity}× {item.name}"
        + (f" ({', '.join(item.modifications)})" if item.modifications else "")
        for item in order.items
    )
    return f"Order updated. Subtotal: ${order.subtotal:.2f}. Items: {items_summary}."


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

    ``tool_uses`` items must have ``name`` and ``input`` fields. The
    function recognizes ``set_status`` (atomic-tool path, #305 Part B)
    as the terminal signal.
    """
    if not main_emitted_text:
        return False
    return any(
        tu.get("name") == "set_status"
        and tu.get("input", {}).get("status") in TERMINAL_STATUSES
        for tu in tool_uses
    )


# ---------------------------------------------------------------------------
# Atomic tool dispatch (#305 Part B)
# ---------------------------------------------------------------------------
#
# Replaces the single snapshot ``update_order`` tool with six narrow
# operations dispatched by ``apply_tool_call``. The model picks an
# operation per turn and the provider routes the tool_use block here.
# Each handler returns ``(new_order, rejection_notes)`` so the provider
# can append notes to the tool_result alongside the order summary.
#
# Item identity: ``add_item`` mints a new ``item_id`` on the resulting
# LineItem (default factory on the model). The provider surfaces that
# ID via the tool_result summary; the model uses it in subsequent
# ``remove_item`` / ``update_item`` calls.


_ADD_ITEM_REQUIRED = ("name", "category", "quantity", "unit_price")
_UPDATE_ITEM_FIELDS = ("name", "category", "size", "quantity", "unit_price", "modifications")
_VALID_ORDER_TYPES = ("pickup", "delivery")
_VALID_LLM_STATUSES = ("confirmed", "cancelled")


def _apply_add_item(order: Order, payload: dict[str, Any]) -> tuple[Order, list[str]]:
    missing = [k for k in _ADD_ITEM_REQUIRED if k not in payload]
    if missing:
        return order, [
            f"add_item rejected: missing required field(s) {missing}. "
            "Re-ask the caller for the missing info."
        ]
    try:
        new_item = LineItem(
            name=payload["name"],
            category=payload["category"],
            size=payload.get("size"),
            quantity=payload["quantity"],
            unit_price=payload["unit_price"],
            modifications=payload.get("modifications", []),
        )
    except (ValueError, TypeError) as exc:
        return order, [f"add_item rejected: {exc}"]
    return order.model_copy(update={"items": [*order.items, new_item]}), []


def _apply_remove_item(order: Order, payload: dict[str, Any]) -> tuple[Order, list[str]]:
    item_id = payload.get("item_id")
    if not item_id:
        return order, ["remove_item rejected: missing item_id."]
    remaining = [i for i in order.items if i.item_id != item_id]
    if len(remaining) == len(order.items):
        return order, [
            f"remove_item rejected: no item with item_id {item_id!r} in the order."
        ]
    return order.model_copy(update={"items": remaining}), []


def _apply_update_item(order: Order, payload: dict[str, Any]) -> tuple[Order, list[str]]:
    item_id = payload.get("item_id")
    if not item_id:
        return order, ["update_item rejected: missing item_id."]
    updates = {k: payload[k] for k in _UPDATE_ITEM_FIELDS if k in payload}
    if not updates:
        return order, ["update_item rejected: no fields to update."]
    new_items: list[LineItem] = []
    found = False
    for item in order.items:
        if item.item_id == item_id:
            found = True
            try:
                new_items.append(item.model_copy(update=updates))
            except (ValueError, TypeError) as exc:
                return order, [f"update_item rejected: {exc}"]
        else:
            new_items.append(item)
    if not found:
        return order, [
            f"update_item rejected: no item with item_id {item_id!r} in the order."
        ]
    # Re-validate to catch constraint violations not caught by model_copy
    # (Pydantic's model_copy(update=...) is a shallow assignment that
    # bypasses field validators — round-trip through model_validate to
    # actually enforce ge=1 quantity, ge=0 unit_price, etc.).
    try:
        validated = [LineItem.model_validate(i.model_dump()) for i in new_items]
    except (ValueError, TypeError) as exc:
        return order, [f"update_item rejected: {exc}"]
    return order.model_copy(update={"items": validated}), []


def _apply_set_order_type(order: Order, payload: dict[str, Any]) -> tuple[Order, list[str]]:
    value = payload.get("order_type")
    if value not in _VALID_ORDER_TYPES:
        return order, [
            f"set_order_type rejected: {value!r} is not one of {list(_VALID_ORDER_TYPES)}."
        ]
    updates: dict[str, Any] = {"order_type": OrderType(value)}
    if value == "pickup":
        updates["delivery_address"] = None  # see _CORRECTIONS prompt
    return order.model_copy(update=updates), []


def _apply_set_delivery_address(
    order: Order, payload: dict[str, Any]
) -> tuple[Order, list[str]]:
    value = payload.get("delivery_address")
    if value is None or (isinstance(value, str) and not value.strip()):
        return order.model_copy(update={"delivery_address": None}), []
    if not validate_delivery_address(value):
        return order, [INVALID_ADDRESS_NOTE]
    return order.model_copy(update={"delivery_address": value}), []


def _apply_set_status(order: Order, payload: dict[str, Any]) -> tuple[Order, list[str]]:
    value = payload.get("status")
    if value not in _VALID_LLM_STATUSES:
        return order, [
            f"set_status rejected: {value!r} is not one of {list(_VALID_LLM_STATUSES)}. "
            "Kitchen states are set by the dashboard, not the model."
        ]
    return order.model_copy(update={"status": OrderStatus(value)}), []


_TOOL_DISPATCH: dict[str, Callable[[Order, dict[str, Any]], tuple[Order, list[str]]]] = {
    "add_item": _apply_add_item,
    "remove_item": _apply_remove_item,
    "update_item": _apply_update_item,
    "set_order_type": _apply_set_order_type,
    "set_delivery_address": _apply_set_delivery_address,
    "set_status": _apply_set_status,
}


def apply_tool_call(
    order: Order, tool_name: str, payload: dict[str, Any]
) -> tuple[Order, list[str]]:
    """Dispatch one atomic tool_use call. Returns ``(new_order, notes)``.

    ``notes`` are human-readable strings the provider appends to the
    tool_result so the model knows what went wrong and can recover by
    re-asking the caller. Empty list on success.

    Unknown tool names return the order unchanged with a one-line note
    — defensive against model output drift (e.g. Haiku hallucinating a
    tool that doesn't exist).
    """
    handler = _TOOL_DISPATCH.get(tool_name)
    if handler is None:
        return order, [f"unknown tool: {tool_name!r}"]
    return handler(order, payload)


__all__ = [
    "INVALID_ADDRESS_NOTE",
    "TERMINAL_STATUSES",
    "apply_tool_call",
    "should_skip_followup",
    "summarize_order_for_tool_result",
]
