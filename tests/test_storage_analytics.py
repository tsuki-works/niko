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


def test_summarize_orders_completion_rate_counts_cancelled_against():
    """Cancelled orders count against the completion rate. They had a
    chance to complete and didn't — that's exactly what the rate
    measures."""
    _wire_orders(
        [
            _completed("CA1", 20.00, age_days=0),
            _completed("CA2", 30.00, age_days=2),
            _confirmed("CA3", 40.00, age_days=3).model_copy(
                update={"status": OrderStatus.CANCELLED},
            ),
        ],
    )
    s = analytics.summarize_orders(restaurant_id="r1")
    # 2 completed of 3 had-chance-to-complete (denominator now includes cancelled)
    assert s.completion_rate_7d == pytest.approx(2 / 3, rel=1e-3)


def test_summarize_orders_aov_excludes_cancelled_and_in_progress():
    """AOV averages over orders that became real revenue
    opportunities."""
    _wire_orders(
        [
            _confirmed("CA1", 20.00, age_days=0),
            _confirmed("CA2", 30.00, age_days=2),
            _confirmed("CA3", 999.00, age_days=3).model_copy(
                update={"status": OrderStatus.CANCELLED},
            ),
            _confirmed("CA4", 999.00, age_days=4).model_copy(
                update={"status": OrderStatus.IN_PROGRESS},
            ),
        ],
    )
    s = analytics.summarize_orders(restaurant_id="r1")
    # AOV averages CA1 + CA2 only (the two CONFIRMED). CA3/CA4 excluded.
    assert s.average_order_value_7d == 25.00


def test_summarize_orders_today_start_uses_local_timezone():
    """An order placed at 22:00 Toronto local on 2026-05-01 (= 02:00 UTC
    on 2026-05-02) should count as TODAY when checked at 23:00 Toronto
    local on 2026-05-01 (= 03:00 UTC on 2026-05-02), not yesterday."""
    from datetime import datetime, timezone, timedelta

    _wire_orders([])
    # Use the public window helper directly to assert the boundary
    # without time-traveling the test clock.
    win = analytics._window()
    # today_start should be in UTC but match local-midnight Toronto.
    # Toronto is UTC-4 (EDT in May), so local midnight = 04:00 UTC.
    # The test asserts the boundary is at 04:00 or 05:00 UTC, never
    # 00:00 UTC — that's the bug we're fixing.
    assert win.today_start.tzinfo == timezone.utc
    assert win.today_start.hour in (4, 5), (
        f"Expected today_start at 04:00 or 05:00 UTC (Toronto local "
        f"midnight EDT/EST), got {win.today_start.isoformat()}"
    )
