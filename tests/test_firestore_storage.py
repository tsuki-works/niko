"""Unit tests for the Firestore storage module.

All tests use a ``MagicMock`` in place of ``firestore.Client`` so the
suite runs offline with no GCP auth. Real Firestore behavior is
covered separately by an integration test (follow-up) against the
local Firestore emulator.
"""

from unittest.mock import MagicMock

import pytest

from app.orders.models import ItemCategory, LineItem, Order, OrderType
from app.storage import firestore as storage


@pytest.fixture(autouse=True)
def reset_client():
    """Ensure every test starts with a fresh mock; module-level state
    doesn't leak between tests."""

    yield
    storage.set_client(None)


def _fake_client() -> MagicMock:
    client = MagicMock()
    storage.set_client(client)
    return client


def _pepperoni() -> LineItem:
    return LineItem(
        name="Pepperoni",
        category=ItemCategory.PIZZA,
        size="medium",
        quantity=1,
        unit_price=17.99,
    )


def test_save_order_upserts_by_call_sid():
    client = _fake_client()
    order = Order(
        call_sid="CAsave1",
        items=[_pepperoni()],
        order_type=OrderType.PICKUP,
    )

    doc_id = storage.save_order(order)

    assert doc_id == "CAsave1"
    client.collection.assert_called_with("orders")
    client.collection.return_value.document.assert_called_with("CAsave1")

    set_call = client.collection.return_value.document.return_value.set
    set_call.assert_called_once()
    payload = set_call.call_args[0][0]
    assert payload["call_sid"] == "CAsave1"
    assert payload["order_type"] == "pickup"
    assert payload["items"][0]["name"] == "Pepperoni"


def test_get_order_returns_none_when_missing():
    client = _fake_client()
    client.collection.return_value.document.return_value.get.return_value.exists = False

    result = storage.get_order("CAmissing")

    assert result is None


def test_get_order_hydrates_pydantic_model():
    client = _fake_client()
    snapshot = client.collection.return_value.document.return_value.get.return_value
    snapshot.exists = True
    snapshot.to_dict.return_value = {
        "call_sid": "CAfetch",
        "restaurant_id": "niko-pizza-kitchen",
        "items": [
            {
                "name": "Coke",
                "category": "drink",
                "size": None,
                "quantity": 2,
                "unit_price": 2.99,
                "modifications": [],
            }
        ],
        "order_type": "pickup",
        "status": "confirmed",
    }

    result = storage.get_order("CAfetch")

    assert result is not None
    assert result.call_sid == "CAfetch"
    assert result.order_type is OrderType.PICKUP
    assert len(result.items) == 1
    # Computed fields re-derive from source fields on validate.
    assert result.subtotal == pytest.approx(5.98)
    assert result.items[0].line_total == pytest.approx(5.98)


def test_list_recent_orders_queries_ordered_and_limited():
    client = _fake_client()
    snap1 = MagicMock()
    snap1.to_dict.return_value = {"call_sid": "CA1", "items": []}
    snap2 = MagicMock()
    snap2.to_dict.return_value = {"call_sid": "CA2", "items": []}

    query = (
        client.collection.return_value
        .order_by.return_value
        .limit.return_value
    )
    query.stream.return_value = iter([snap1, snap2])

    result = storage.list_recent_orders(limit=5)

    client.collection.assert_called_with("orders")
    client.collection.return_value.order_by.assert_called_once()
    order_by_args = client.collection.return_value.order_by.call_args
    assert order_by_args[0][0] == "created_at"

    limit_call = client.collection.return_value.order_by.return_value.limit
    limit_call.assert_called_with(5)

    assert [o.call_sid for o in result] == ["CA1", "CA2"]


def test_computed_fields_dropped_on_read_even_if_present():
    """If an older stored document has stale computed fields, the
    freshly-validated Order recomputes them — stored totals can never
    drift from the source-of-truth."""

    client = _fake_client()
    snapshot = client.collection.return_value.document.return_value.get.return_value
    snapshot.exists = True
    snapshot.to_dict.return_value = {
        "call_sid": "CAstale",
        "items": [
            {
                "name": "Pepperoni",
                "category": "pizza",
                "size": "medium",
                "quantity": 1,
                "unit_price": 17.99,
                "modifications": [],
                "line_total": 999.99,  # stale / wrong
            }
        ],
        "subtotal": 999.99,  # stale / wrong
    }

    result = storage.get_order("CAstale")

    assert result is not None
    assert result.items[0].line_total == 17.99
    assert result.subtotal == 17.99
