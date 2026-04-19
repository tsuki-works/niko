"""Unit tests for order Pydantic models."""

import pytest
from pydantic import ValidationError

from app.orders.models import (
    ItemCategory,
    LineItem,
    Order,
    OrderStatus,
    OrderType,
)


def _pepperoni(quantity: int = 1) -> LineItem:
    return LineItem(
        name="Pepperoni",
        category=ItemCategory.PIZZA,
        size="medium",
        quantity=quantity,
        unit_price=17.99,
    )


def test_line_item_computes_line_total():
    item = _pepperoni(quantity=2)
    assert item.line_total == 35.98


def test_line_item_rejects_zero_quantity():
    with pytest.raises(ValidationError):
        LineItem(
            name="Coke",
            category=ItemCategory.DRINK,
            quantity=0,
            unit_price=2.99,
        )


def test_line_item_rejects_negative_price():
    with pytest.raises(ValidationError):
        LineItem(
            name="Free pizza",
            category=ItemCategory.PIZZA,
            quantity=1,
            unit_price=-1.00,
        )


def test_empty_order_has_zero_subtotal():
    order = Order(call_sid="CAtest")
    assert order.subtotal == 0.0
    assert order.status is OrderStatus.IN_PROGRESS
    assert order.items == []


def test_order_subtotal_sums_line_items():
    order = Order(
        call_sid="CAtest",
        items=[
            _pepperoni(quantity=2),
            LineItem(
                name="Coke",
                category=ItemCategory.DRINK,
                quantity=1,
                unit_price=2.99,
            ),
        ],
    )
    assert order.subtotal == pytest.approx(38.97)


def test_is_ready_to_confirm_empty_order():
    order = Order(call_sid="CAtest")
    assert order.is_ready_to_confirm() is False


def test_is_ready_to_confirm_missing_order_type():
    order = Order(call_sid="CAtest", items=[_pepperoni()])
    assert order.is_ready_to_confirm() is False


def test_is_ready_to_confirm_pickup_ok():
    order = Order(
        call_sid="CAtest",
        items=[_pepperoni()],
        order_type=OrderType.PICKUP,
    )
    assert order.is_ready_to_confirm() is True


def test_is_ready_to_confirm_delivery_without_address():
    order = Order(
        call_sid="CAtest",
        items=[_pepperoni()],
        order_type=OrderType.DELIVERY,
    )
    assert order.is_ready_to_confirm() is False


def test_is_ready_to_confirm_delivery_with_address():
    order = Order(
        call_sid="CAtest",
        items=[_pepperoni()],
        order_type=OrderType.DELIVERY,
        delivery_address="123 Main St",
    )
    assert order.is_ready_to_confirm() is True


def test_order_json_roundtrip_includes_computed_fields():
    order = Order(
        call_sid="CAtest",
        items=[_pepperoni(quantity=2)],
        order_type=OrderType.PICKUP,
    )
    dumped = order.model_dump(mode="json")
    assert dumped["subtotal"] == 35.98
    assert dumped["items"][0]["line_total"] == 35.98
    assert dumped["order_type"] == "pickup"
    assert dumped["status"] == "in_progress"
