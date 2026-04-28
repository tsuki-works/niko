"""Unit tests for ``app.orders.lifecycle.persist_on_confirm``.

Uses the same ``MagicMock`` pattern as ``test_firestore_storage.py`` —
no real Firestore, no GCP auth. After PR C of #79 the storage module
addresses the nested ``restaurants/{rid}/orders/{call_sid}`` path, so
the helpers below traverse one extra ``.collection().document()``.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.orders.lifecycle import OrderNotReadyError, persist_on_confirm
from app.orders.models import (
    ItemCategory,
    LineItem,
    Order,
    OrderStatus,
    OrderType,
)
from app.storage import firestore as storage


@pytest.fixture(autouse=True)
def reset_client():
    yield
    storage.set_client(None)


def _fake_client() -> MagicMock:
    client = MagicMock()
    storage.set_client(client)
    return client


def _order_doc(client: MagicMock):
    """Address the same ``restaurants/{rid}/orders/{call_sid}`` doc the
    storage module addresses."""
    return (
        client.collection.return_value
        .document.return_value
        .collection.return_value
        .document.return_value
    )


def _pepperoni() -> LineItem:
    return LineItem(
        name="Pepperoni",
        category=ItemCategory.PIZZA,
        size="medium",
        quantity=1,
        unit_price=17.99,
    )


def _ready_pickup_order(**overrides) -> Order:
    base = dict(
        call_sid="CAconfirm",
        items=[_pepperoni()],
        order_type=OrderType.PICKUP,
    )
    base.update(overrides)
    return Order(**base)


def _ready_delivery_order(**overrides) -> Order:
    base = dict(
        call_sid="CAdelivery",
        items=[_pepperoni()],
        order_type=OrderType.DELIVERY,
        delivery_address="123 Main Street",
    )
    base.update(overrides)
    return Order(**base)


def test_persist_on_confirm_stamps_status_and_timestamp():
    client = _fake_client()
    order = _ready_pickup_order()
    assert order.status is OrderStatus.IN_PROGRESS
    assert order.confirmed_at is None

    confirmed = persist_on_confirm(order)

    assert confirmed.status is OrderStatus.CONFIRMED
    assert confirmed.confirmed_at is not None
    # timestamp is recent (within last few seconds — generous to avoid flakes)
    age = datetime.now(timezone.utc) - confirmed.confirmed_at
    assert timedelta(seconds=0) <= age < timedelta(seconds=5)
    _order_doc(client).set.assert_called_once()


def test_persist_on_confirm_does_not_mutate_input_order():
    """The caller's Order instance stays untouched — we return a new one."""

    _fake_client()
    order = _ready_pickup_order()

    persist_on_confirm(order)

    assert order.status is OrderStatus.IN_PROGRESS
    assert order.confirmed_at is None


def test_persist_on_confirm_writes_payload_with_confirmed_status():
    """Whatever lands in Firestore reflects the confirmed state, not
    the pre-confirmation snapshot."""

    client = _fake_client()
    order = _ready_pickup_order()

    persist_on_confirm(order)

    set_call = _order_doc(client).set
    payload = set_call.call_args[0][0]
    assert payload["status"] == "confirmed"
    assert payload["confirmed_at"] is not None
    assert payload["call_sid"] == "CAconfirm"


def test_persist_on_confirm_handles_delivery_order():
    _fake_client()
    order = _ready_delivery_order()

    confirmed = persist_on_confirm(order)

    assert confirmed.status is OrderStatus.CONFIRMED
    assert confirmed.delivery_address == "123 Main Street"


def test_persist_on_confirm_is_idempotent_on_already_confirmed_order():
    """Re-running on a confirmed order keeps the original confirmed_at
    rather than re-stamping. Save still runs (recovery from a partial
    failure where the stamp landed but the write didn't)."""

    client = _fake_client()
    original_ts = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
    order = _ready_pickup_order(
        status=OrderStatus.CONFIRMED, confirmed_at=original_ts
    )

    confirmed = persist_on_confirm(order)

    assert confirmed.confirmed_at == original_ts
    _order_doc(client).set.assert_called_once()


def test_persist_on_confirm_refuses_empty_order():
    _fake_client()
    order = Order(call_sid="CAempty", order_type=OrderType.PICKUP)

    with pytest.raises(OrderNotReadyError, match="not ready"):
        persist_on_confirm(order)


def test_persist_on_confirm_refuses_missing_order_type():
    _fake_client()
    order = Order(call_sid="CAtype", items=[_pepperoni()])  # no order_type

    with pytest.raises(OrderNotReadyError, match="not ready"):
        persist_on_confirm(order)


def test_persist_on_confirm_refuses_delivery_without_address():
    _fake_client()
    order = Order(
        call_sid="CAdelivery-no-addr",
        items=[_pepperoni()],
        order_type=OrderType.DELIVERY,
    )

    with pytest.raises(OrderNotReadyError, match="not ready"):
        persist_on_confirm(order)


def test_persist_on_confirm_refuses_cancelled_order():
    _fake_client()
    order = _ready_pickup_order(status=OrderStatus.CANCELLED)

    with pytest.raises(OrderNotReadyError, match="cancelled"):
        persist_on_confirm(order)


def test_persist_on_confirm_does_not_save_when_refusing():
    """Failed validation must not produce a Firestore write — it'd be
    weird for a half-baked order to land in the dashboard."""

    client = _fake_client()
    order = Order(call_sid="CAbad", order_type=OrderType.PICKUP)

    with pytest.raises(OrderNotReadyError):
        persist_on_confirm(order)

    _order_doc(client).set.assert_not_called()


def test_order_supports_new_lifecycle_statuses_and_timestamps():
    """Sprint 2.2 #107 — OrderStatus must include preparing/ready/completed,
    and Order must accept the per-transition timestamps without complaint."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    order = Order(
        call_sid="CAlife",
        items=[_pepperoni()],
        order_type=OrderType.PICKUP,
        status=OrderStatus.READY,
        confirmed_at=now,
        preparing_at=now,
        ready_at=now,
    )

    assert order.status is OrderStatus.READY
    assert order.preparing_at == now
    assert order.ready_at == now
    assert order.completed_at is None  # not yet completed
    assert order.cancelled_at is None

    # All four enum values exist
    assert OrderStatus.PREPARING.value == "preparing"
    assert OrderStatus.READY.value == "ready"
    assert OrderStatus.COMPLETED.value == "completed"
