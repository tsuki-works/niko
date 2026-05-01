"""Unit tests for app.storage.analytics aggregations."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.orders.models import (
    ItemCategory,
    LineItem,
    Order,
    OrderStatus,
    OrderType,
)
from app.storage import analytics, firestore as order_storage


@pytest.fixture(autouse=True)
def reset_storage():
    yield
    order_storage.set_client(None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _wire_orders(orders: list[Order]) -> None:
    fs = MagicMock()
    order_storage.set_client(fs)
    snapshots = []
    for o in orders:
        snap = MagicMock()
        snap.to_dict.return_value = o.model_dump(mode="python")
        snapshots.append(snap)
    (
        fs.collection.return_value
        .document.return_value
        .collection.return_value
        .where.return_value
        .stream
    ).return_value = iter(snapshots)


def _confirmed(call_sid: str, total: float, age_days: float = 0) -> Order:
    return Order(
        call_sid=call_sid,
        items=[
            LineItem(
                name="P",
                category=ItemCategory.PIZZA,
                quantity=1,
                unit_price=total,
            ),
        ],
        order_type=OrderType.PICKUP,
        status=OrderStatus.CONFIRMED,
        created_at=_now() - timedelta(days=age_days),
        confirmed_at=_now() - timedelta(days=age_days),
    )


def _completed(call_sid: str, total: float, age_days: float = 0) -> Order:
    base = _confirmed(call_sid, total, age_days=age_days)
    return base.model_copy(update={"status": OrderStatus.COMPLETED})


def test_summarize_orders_counts_today_and_seven_day_window():
    _wire_orders(
        [
            _confirmed("CA1", 20.00, age_days=0),
            _confirmed("CA2", 30.00, age_days=2),
            _confirmed("CA3", 50.00, age_days=8),  # outside 7d window
        ],
    )
    s = analytics.summarize_orders(restaurant_id="r1")
    assert s.today_count == 1
    assert s.seven_day_count == 2  # CA1 + CA2; CA3 too old


def test_summarize_orders_average_order_value_uses_seven_day_window():
    _wire_orders(
        [
            _confirmed("CA1", 20.00, age_days=0),
            _confirmed("CA2", 30.00, age_days=2),
        ],
    )
    s = analytics.summarize_orders(restaurant_id="r1")
    assert s.average_order_value_7d == 25.00


def test_summarize_orders_completion_rate_seven_day():
    _wire_orders(
        [
            _completed("CA1", 20.00, age_days=0),
            _completed("CA2", 30.00, age_days=2),
            _confirmed("CA3", 40.00, age_days=3),  # not yet completed
        ],
    )
    s = analytics.summarize_orders(restaurant_id="r1")
    # 2 completed of 3 confirmed-or-later in window
    assert s.completion_rate_7d == pytest.approx(2 / 3, rel=1e-3)


def test_summarize_orders_handles_empty():
    _wire_orders([])
    s = analytics.summarize_orders(restaurant_id="r1")
    assert s.today_count == 0
    assert s.seven_day_count == 0
    assert s.average_order_value_7d == 0.0
    assert s.completion_rate_7d == 0.0
