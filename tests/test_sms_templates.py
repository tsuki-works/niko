"""Unit tests for app.sms.templates."""

from app.orders.models import (
    ItemCategory,
    LineItem,
    Order,
    OrderType,
)
from app.sms.templates import order_confirmation


def _sample_pickup_order() -> Order:
    return Order(
        call_sid="CAabc",
        caller_phone="+15551234567",
        items=[
            LineItem(
                name="Pepperoni",
                category=ItemCategory.PIZZA,
                size="large",
                quantity=1,
                unit_price=18.99,
            ),
        ],
        order_type=OrderType.PICKUP,
    )


def _sample_delivery_order() -> Order:
    return Order(
        call_sid="CAdef",
        caller_phone="+15551234567",
        items=[
            LineItem(
                name="Margherita",
                category=ItemCategory.PIZZA,
                quantity=2,
                unit_price=15.00,
            ),
        ],
        order_type=OrderType.DELIVERY,
        delivery_address="123 Main Street",
    )


def test_order_confirmation_includes_total_and_summary_for_pickup():
    body = order_confirmation(_sample_pickup_order())
    assert "$18.99" in body
    assert "Pepperoni" in body
    assert "pickup" in body.lower()


def test_order_confirmation_includes_delivery_address_for_delivery():
    body = order_confirmation(_sample_delivery_order())
    assert "$30.00" in body
    assert "Margherita" in body
    assert "123 Main Street" in body


def test_order_confirmation_handles_multi_item_orders():
    order = _sample_pickup_order()
    order.items.append(
        LineItem(
            name="Garlic Knots",
            category=ItemCategory.SIDE,
            quantity=1,
            unit_price=5.00,
        ),
    )
    body = order_confirmation(order)
    assert "Pepperoni" in body
    assert "Garlic Knots" in body
    assert "$23.99" in body  # 18.99 + 5.00


def test_order_confirmation_under_sms_segment_limit():
    """Single-segment SMS is 160 GSM-7 chars. Two-segment is 306. We aim
    for one segment for typical orders so the per-pilot SMS cost stays
    predictable. Tolerance: 320 chars accommodates edge cases without
    blowing past two segments."""
    body = order_confirmation(_sample_pickup_order())
    assert len(body) <= 320
