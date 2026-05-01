"""Analytics aggregations on Firestore order data.

Computes the four tile metrics (today_count, seven_day_count,
average_order_value_7d, completion_rate_7d) the dashboard's analytics
page renders. No new collections — reads from
``restaurants/{rid}/orders``.

Streams the past 7 days into memory; for pilot scale this is fine
(<200 orders/day per restaurant). When restaurants get to 1k orders/
day we'll move to scheduled aggregations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from app.orders.models import Order, OrderStatus
from app.storage import firestore as order_storage


@dataclass(frozen=True)
class _Window:
    today_start: datetime
    seven_days_ago: datetime


def _window(now: datetime | None = None) -> _Window:
    now = now or datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return _Window(
        today_start=today_start,
        seven_days_ago=now - timedelta(days=7),
    )


class OrderSummary(BaseModel):
    today_count: int
    seven_day_count: int
    average_order_value_7d: float
    completion_rate_7d: float


def _stream_recent_orders(restaurant_id: str, since: datetime) -> list[Order]:
    """Read orders newer than ``since`` for one tenant. Uses the
    restaurants/{rid}/orders subcollection that
    ``app.storage.firestore`` writes to."""
    client = order_storage._get_client()
    coll = (
        client.collection("restaurants")
        .document(restaurant_id)
        .collection("orders")
        .where("created_at", ">=", since)
    )
    return [Order.model_validate(snap.to_dict()) for snap in coll.stream()]


def summarize_orders(*, restaurant_id: str) -> OrderSummary:
    win = _window()
    orders = _stream_recent_orders(restaurant_id, win.seven_days_ago)

    today: list[Order] = []
    seven_day: list[Order] = []
    for o in orders:
        if o.created_at >= win.today_start:
            today.append(o)
        if o.created_at >= win.seven_days_ago:
            seven_day.append(o)

    if seven_day:
        aov = round(sum(o.subtotal for o in seven_day) / len(seven_day), 2)
        completed = sum(
            1 for o in seven_day if o.status is OrderStatus.COMPLETED
        )
        # Denominator: orders that reached confirmed (or beyond) — i.e.
        # excluding still-in-progress and cancelled-before-confirm.
        confirmed_or_later = sum(
            1
            for o in seven_day
            if o.status
            in {
                OrderStatus.CONFIRMED,
                OrderStatus.PREPARING,
                OrderStatus.READY,
                OrderStatus.COMPLETED,
            }
        )
        completion_rate = (
            completed / confirmed_or_later if confirmed_or_later else 0.0
        )
    else:
        aov = 0.0
        completion_rate = 0.0

    return OrderSummary(
        today_count=len(today),
        seven_day_count=len(seven_day),
        average_order_value_7d=aov,
        completion_rate_7d=completion_rate,
    )
