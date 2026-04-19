"""Pydantic models for order state.

Shared across three consumers:

- The LLM conversation engine (#38) emits partial ``Order`` state via
  Anthropic tool-use as the caller builds their order.
- The call flow orchestrator (#40) holds an ``Order`` in memory across
  a single call and writes it to Firestore on confirmation.
- The dashboard (#41) reads ``Order`` documents from Firestore and
  renders them via the Next.js frontend.

Prices are stored as ``float`` to match the demo menu in ``app.menu``
and Firestore's native number type. The model is intentionally
permissive — partial states are valid during the LLM conversation loop.
Completeness for confirmation is checked via ``Order.is_ready_to_confirm``
rather than at validation time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class OrderType(str, Enum):
    PICKUP = "pickup"
    DELIVERY = "delivery"


class OrderStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ItemCategory(str, Enum):
    PIZZA = "pizza"
    SIDE = "side"
    DRINK = "drink"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class LineItem(BaseModel):
    name: str
    category: ItemCategory
    size: Optional[str] = None
    quantity: int = Field(ge=1)
    unit_price: float = Field(ge=0)
    modifications: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def line_total(self) -> float:
        return round(self.unit_price * self.quantity, 2)


class Order(BaseModel):
    call_sid: str
    caller_phone: Optional[str] = None
    restaurant_id: str = "niko-pizza-kitchen"
    items: list[LineItem] = Field(default_factory=list)
    order_type: Optional[OrderType] = None
    delivery_address: Optional[str] = None
    status: OrderStatus = OrderStatus.IN_PROGRESS
    created_at: datetime = Field(default_factory=_now_utc)
    confirmed_at: Optional[datetime] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def subtotal(self) -> float:
        return round(sum(item.line_total for item in self.items), 2)

    def is_ready_to_confirm(self) -> bool:
        if not self.items:
            return False
        if self.order_type is None:
            return False
        if self.order_type is OrderType.DELIVERY and not self.delivery_address:
            return False
        return True
