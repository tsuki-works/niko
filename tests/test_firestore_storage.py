"""Unit tests for the orders storage module (#79 PR C).

After PR C, orders live under ``restaurants/{rid}/orders/{call_sid}``.
The MagicMock fixture exposes the nested path so tests can assert
both the parent restaurant and the order doc were addressed.

All tests use a ``MagicMock`` in place of ``firestore.Client`` so the
suite runs offline with no GCP auth. Real Firestore behavior is
covered separately by an integration test (follow-up) against the
local Firestore emulator.
"""

from unittest.mock import MagicMock

import pytest

from app.orders.models import ItemCategory, LineItem, Order, OrderType
from app.storage import firestore as storage


_DEMO_RID = "niko-pizza-kitchen"


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


def _orders_doc(client: MagicMock, rid: str = _DEMO_RID, call_sid: str = "CAtest"):
    """Helper to address the same ``restaurants/{rid}/orders/{call_sid}`` doc
    we expect the storage module to address."""
    return (
        client.collection.return_value
        .document.return_value
        .collection.return_value
        .document.return_value
    )


def _orders_collection(client: MagicMock, rid: str = _DEMO_RID):
    return (
        client.collection.return_value
        .document.return_value
        .collection.return_value
    )


def _pepperoni() -> LineItem:
    return LineItem(
        name="Pepperoni",
        category=ItemCategory.PIZZA,
        size="medium",
        quantity=1,
        unit_price=17.99,
    )


def test_save_order_writes_to_nested_path():
    """``save_order`` addresses ``restaurants/{rid}/orders/{call_sid}``."""
    client = _fake_client()
    order = Order(
        call_sid="CAsave1",
        items=[_pepperoni()],
        order_type=OrderType.PICKUP,
    )

    doc_id = storage.save_order(order)

    assert doc_id == "CAsave1"
    # First .collection("restaurants"), then .document(rid),
    # then .collection("orders"), then .document(call_sid).
    client.collection.assert_called_with("restaurants")
    client.collection.return_value.document.assert_called_with(_DEMO_RID)
    (
        client.collection.return_value.document.return_value
        .collection.assert_called_with("orders")
    )
    (
        client.collection.return_value.document.return_value
        .collection.return_value.document.assert_called_with("CAsave1")
    )

    set_call = _orders_doc(client).set
    set_call.assert_called_once()
    payload = set_call.call_args[0][0]
    assert payload["call_sid"] == "CAsave1"
    assert payload["restaurant_id"] == _DEMO_RID
    assert payload["order_type"] == "pickup"
    assert payload["items"][0]["name"] == "Pepperoni"


def test_save_order_uses_orders_restaurant_id_for_path():
    """A non-demo tenant order writes under that tenant's path."""
    client = _fake_client()
    order = Order(
        call_sid="CApalace",
        restaurant_id="pizza-palace",
        items=[_pepperoni()],
        order_type=OrderType.PICKUP,
    )

    storage.save_order(order)

    client.collection.return_value.document.assert_called_with("pizza-palace")


def test_get_order_returns_none_when_missing():
    client = _fake_client()
    _orders_doc(client).get.return_value.exists = False

    result = storage.get_order("CAmissing", restaurant_id=_DEMO_RID)

    assert result is None


def test_get_order_hydrates_pydantic_model():
    client = _fake_client()
    snapshot = _orders_doc(client).get.return_value
    snapshot.exists = True
    snapshot.to_dict.return_value = {
        "call_sid": "CAfetch",
        "restaurant_id": _DEMO_RID,
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

    result = storage.get_order("CAfetch", restaurant_id=_DEMO_RID)

    assert result is not None
    assert result.call_sid == "CAfetch"
    assert result.order_type is OrderType.PICKUP
    assert len(result.items) == 1
    # Computed fields re-derive from source fields on validate.
    assert result.subtotal == pytest.approx(5.98)
    assert result.items[0].line_total == pytest.approx(5.98)


def test_list_recent_orders_queries_under_restaurant():
    client = _fake_client()
    snap1 = MagicMock()
    snap1.to_dict.return_value = {"call_sid": "CA1", "items": []}
    snap2 = MagicMock()
    snap2.to_dict.return_value = {"call_sid": "CA2", "items": []}

    query = (
        _orders_collection(client)
        .order_by.return_value
        .limit.return_value
    )
    query.stream.return_value = iter([snap1, snap2])

    result = storage.list_recent_orders(restaurant_id=_DEMO_RID, limit=5)

    client.collection.assert_called_with("restaurants")
    client.collection.return_value.document.assert_called_with(_DEMO_RID)
    _orders_collection(client).order_by.assert_called_once()
    order_by_args = _orders_collection(client).order_by.call_args
    assert order_by_args[0][0] == "created_at"

    limit_call = _orders_collection(client).order_by.return_value.limit
    limit_call.assert_called_with(5)

    assert [o.call_sid for o in result] == ["CA1", "CA2"]


def test_computed_fields_dropped_on_read_even_if_present():
    """If an older stored document has stale computed fields, the
    freshly-validated Order recomputes them — stored totals can never
    drift from the source-of-truth."""

    client = _fake_client()
    snapshot = _orders_doc(client).get.return_value
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

    result = storage.get_order("CAstale", restaurant_id=_DEMO_RID)

    assert result is not None
    assert result.items[0].line_total == 17.99
    assert result.subtotal == 17.99
