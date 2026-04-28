"""Caller-correction transcripts for the live-Haiku regression suite (#103).

Each entry is a multi-turn scenario:
- ``initial_turns`` runs first (no assertions) to seed the order state
  the way it would look in a real call right before the correction.
- ``correction_transcript`` is the caller's correction utterance.
- ``assert_end_state`` runs against the final ``Order`` and raises
  ``AssertionError`` with a human-readable message on mismatch — used
  instead of equality on a full Order because Haiku reasonably varies
  on incidentals (extra modifications, exact unit_price for a size we
  don't enumerate, etc.) and we only want to assert the load-bearing
  fields per pattern.

Add a row whenever a real correction bug is found in production. Pair
the row with a backstop in ``tests/test_llm_client.py`` that exercises
the same shape against ``_apply_update`` deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.orders.models import Order, OrderType


@dataclass
class CorrectionScenario:
    id: str
    initial_turns: list[str]
    correction_transcript: str
    assert_end_state: Callable[[Order], None]


def _assert_remove_item(final: Order) -> None:
    names = [i.name.lower() for i in final.items]
    assert not any("coke" in n for n in names), (
        f"Coke should be removed; items were {names}"
    )
    assert any("margherita" in n or "pepperoni" in n or "veggie" in n
               for n in names), (
        f"At least one pizza should remain; items were {names}"
    )


def _assert_substitute_item(final: Order) -> None:
    names = [i.name.lower() for i in final.items]
    # The substitute landed (calzone present)
    assert any("calzone" in n for n in names), (
        f"Calzone should be present; items were {names}"
    )
    # The replaced item is gone
    assert not any("margherita" in n for n in names), (
        f"Margherita should be replaced; items were {names}"
    )
    # No accidental duplication
    assert len(final.items) == 1, (
        f"Expected exactly one item after substitution; got {len(final.items)}"
    )


def _assert_quantity_change(final: Order) -> None:
    assert len(final.items) == 1, (
        f"Quantity change must not duplicate the line; got {len(final.items)} items"
    )
    assert final.items[0].quantity == 2, (
        f"Expected quantity=2; got {final.items[0].quantity}"
    )


def _assert_size_change(final: Order) -> None:
    assert len(final.items) == 1, (
        f"Size change must not duplicate the line; got {len(final.items)} items"
    )
    size = (final.items[0].size or "").lower()
    assert "large" in size, f"Expected size=large; got {final.items[0].size!r}"
    # unit_price should reflect the large price (>medium); we don't pin to
    # an exact value because the demo menu may shift, but it must be
    # strictly greater than a typical medium price (~$14).
    assert final.items[0].unit_price >= 16.00, (
        f"Expected unit_price >= 16.00 for large; got {final.items[0].unit_price}"
    )


def _assert_swap_to_pickup(final: Order) -> None:
    assert final.order_type is OrderType.PICKUP, (
        f"Expected order_type=pickup; got {final.order_type}"
    )
    assert final.delivery_address in (None, ""), (
        f"delivery_address should be cleared on swap-to-pickup; got "
        f"{final.delivery_address!r}"
    )


def _assert_address_fix(final: Order) -> None:
    assert final.order_type is OrderType.DELIVERY, (
        f"Expected order_type=delivery; got {final.order_type}"
    )
    assert final.delivery_address is not None, "Expected an address"
    assert "14" in final.delivery_address, (
        f"Expected corrected address to contain '14'; got "
        f"{final.delivery_address!r}"
    )
    assert "40" not in final.delivery_address, (
        f"Old address number '40' should be gone; got "
        f"{final.delivery_address!r}"
    )


SCENARIOS: list[CorrectionScenario] = [
    CorrectionScenario(
        id="remove_item",
        initial_turns=[
            "I'd like a large margherita and a Coke for pickup, please.",
        ],
        correction_transcript="Actually, take off the Coke.",
        assert_end_state=_assert_remove_item,
    ),
    CorrectionScenario(
        id="substitute_item",
        initial_turns=[
            "Can I get a large margherita for pickup?",
        ],
        correction_transcript="Wait, change the margherita to a calzone instead.",
        assert_end_state=_assert_substitute_item,
    ),
    CorrectionScenario(
        id="quantity_change",
        initial_turns=[
            "One large margherita for pickup, please.",
        ],
        correction_transcript="Actually, make that two — not one.",
        assert_end_state=_assert_quantity_change,
    ),
    CorrectionScenario(
        id="size_change",
        initial_turns=[
            "Can I get a medium margherita for pickup?",
        ],
        correction_transcript="Sorry, I meant large, not medium.",
        assert_end_state=_assert_size_change,
    ),
    CorrectionScenario(
        id="swap_to_pickup",
        initial_turns=[
            "I'd like a large margherita for delivery to 14 Spadina Avenue.",
        ],
        correction_transcript="Actually, switch it back to pickup.",
        assert_end_state=_assert_swap_to_pickup,
    ),
    CorrectionScenario(
        id="address_fix",
        initial_turns=[
            "Large margherita for delivery to 40 Main Street, please.",
        ],
        correction_transcript="Sorry, I meant 14 Main Street, not 40.",
        assert_end_state=_assert_address_fix,
    ),
]
