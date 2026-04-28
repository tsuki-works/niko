"""Order lifecycle transitions — the rules layer above storage.

``app.storage.firestore`` handles raw Firestore reads and writes. This
module handles the *meaning* of state transitions: when an order
becomes confirmed it must actually be ready (items present,
``order_type`` set, delivery has an address), the ``confirmed_at``
timestamp is stamped at write time, and the operation is idempotent
across retries within a single call.

Today: ``persist_on_confirm`` only. Cancellation, reopen, and other
transitions land when their callers need them — this module stays
narrow to what the call-flow orchestrator (#40) actually needs for
the Phase 1 demo.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.orders.models import Order, OrderStatus
from app.storage import firestore as order_storage


class OrderNotReadyError(ValueError):
    """``persist_on_confirm`` was called with an order that isn't
    complete enough to confirm. Defense in depth — the orchestrator
    shouldn't reach this state, but the helper enforces the contract
    regardless of caller hygiene."""


def persist_on_confirm(order: Order) -> Order:
    """Stamp confirmation metadata and write the order to Firestore.

    Returns a new ``Order`` with ``status=CONFIRMED`` and
    ``confirmed_at`` set. The Firestore write is a deterministic upsert
    keyed by ``call_sid``, so re-running is safe.

    Idempotent. If the order already has ``status == CONFIRMED`` and
    ``confirmed_at`` set (e.g., a retry after a successful write whose
    response got dropped), the original ``confirmed_at`` is preserved
    rather than re-stamped. The Firestore write still runs — that's the
    cheapest way to recover from a partial failure where the stamp
    landed in memory but the network round-trip didn't.

    Raises ``OrderNotReadyError`` if the order is cancelled or fails
    ``Order.is_ready_to_confirm()``.
    """

    if order.status is OrderStatus.CANCELLED:
        raise OrderNotReadyError(
            f"Cannot confirm order {order.call_sid!r}: status is cancelled"
        )

    if not order.is_ready_to_confirm():
        raise OrderNotReadyError(
            f"Cannot confirm order {order.call_sid!r}: not ready "
            "(missing items, order_type, or delivery_address)"
        )

    confirmed_at = order.confirmed_at or datetime.now(timezone.utc)
    confirmed_order = order.model_copy(
        update={"status": OrderStatus.CONFIRMED, "confirmed_at": confirmed_at}
    )

    order_storage.save_order(confirmed_order)
    return confirmed_order


class OrderTransitionError(ValueError):
    """A transition function was called from an invalid source state.
    Mirrors ``OrderNotReadyError``'s shape but specific to the
    confirmed → preparing → ready → completed kitchen workflow."""


def _transition(
    order: Order,
    *,
    allowed_sources: list[OrderStatus],
    target: OrderStatus,
    timestamp_field: str,
) -> Order:
    """Generic state-machine transition helper.

    Idempotent: if the order is already in the target state, save
    again (recovery from partial failure where the in-memory transition
    landed but the Firestore write didn't) and preserve the original
    timestamp.

    Validates source state: raises ``OrderTransitionError`` if the
    order's current status isn't in ``allowed_sources`` and isn't
    already the target.
    """
    if order.status is target:
        order_storage.save_order(order)
        return order

    if order.status not in allowed_sources:
        raise OrderTransitionError(
            f"Cannot transition order {order.call_sid!r} to "
            f"{target.value!r}: current status is {order.status.value!r}, "
            f"expected one of {[s.value for s in allowed_sources]}"
        )

    now = datetime.now(timezone.utc)
    updated = order.model_copy(
        update={"status": target, timestamp_field: now}
    )
    order_storage.save_order(updated)
    return updated


def mark_preparing(order: Order) -> Order:
    """Confirmed → Preparing. Kitchen has accepted the order and started
    cooking. Stamps ``preparing_at``."""
    return _transition(
        order,
        allowed_sources=[OrderStatus.CONFIRMED],
        target=OrderStatus.PREPARING,
        timestamp_field="preparing_at",
    )


def mark_ready(order: Order) -> Order:
    """Preparing → Ready. Food is done and waiting for handoff (counter
    pickup or restaurant's own driver). Stamps ``ready_at``."""
    return _transition(
        order,
        allowed_sources=[OrderStatus.PREPARING],
        target=OrderStatus.READY,
        timestamp_field="ready_at",
    )


def mark_completed(order: Order) -> Order:
    """Ready → Completed. Food has left the kitchen. Terminal state for
    successful orders. Stamps ``completed_at``."""
    return _transition(
        order,
        allowed_sources=[OrderStatus.READY],
        target=OrderStatus.COMPLETED,
        timestamp_field="completed_at",
    )


def cancel_order(order: Order) -> Order:
    """Any pre-completed state → Cancelled. Off-ramp from the workflow
    (caller-cancel, kitchen-reject, staff-cancel via dashboard).
    Stamps ``cancelled_at``."""
    return _transition(
        order,
        allowed_sources=[
            OrderStatus.IN_PROGRESS,
            OrderStatus.CONFIRMED,
            OrderStatus.PREPARING,
            OrderStatus.READY,
        ],
        target=OrderStatus.CANCELLED,
        timestamp_field="cancelled_at",
    )
