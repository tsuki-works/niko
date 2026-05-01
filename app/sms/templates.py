"""SMS body templates rendered from order data.

Each function takes the data it needs and returns a plain string — no
Twilio dependency, no I/O. Templates are intentionally short to fit a
single 160-char SMS segment for typical orders; multi-item delivery
orders may spill into a second segment, accepted.
"""

from __future__ import annotations

from app.orders.models import Order, OrderType


def order_confirmation(order: Order) -> str:
    """Body for the post-confirmation SMS. Format:

        Niko: order confirmed.
        1x Pepperoni (large)
        Total: $18.99
        Pickup at the restaurant.

    For delivery orders, the last line carries the delivery address.
    """
    lines = ["Niko: order confirmed."]

    for item in order.items:
        size_part = f" ({item.size})" if item.size else ""
        lines.append(f"{item.quantity}x {item.name}{size_part}")

    lines.append(f"Total: ${order.subtotal:.2f}")

    if order.order_type is OrderType.DELIVERY:
        lines.append(f"Delivery to {order.delivery_address}.")
    else:
        lines.append("Pickup at the restaurant.")

    return "\n".join(lines)
