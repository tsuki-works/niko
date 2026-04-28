"""Pickup vs delivery transcripts for the live-Haiku regression suite (#105).

Same scenario shape as tests/fixtures/correction_transcripts.py:
- ``initial_turns`` runs first to seed state.
- ``correction_transcript`` is the trigger turn (named for shape
  consistency with the sibling catalog; here it's the 'first delivery
  ask' or 'address attempt' turn).
- ``assert_end_state`` asserts the load-bearing fields on the final
  Order; pattern-specific, not full equality.

Three scenarios cover the three load-bearing behaviors:
1. delivery_address_complete — a valid address lands cleanly
2. delivery_address_uhh_then_real — invalid address is rejected, Haiku
   re-asks, valid address lands. Closes the validator-feedback loop.
3. pickup_only_soft_pivot — pickup-only tenant; caller asks for
   delivery; Haiku soft-pivots; final order is pickup with no address.
"""

from __future__ import annotations

from app.orders.models import Order, OrderType
from tests.fixtures.correction_transcripts import CorrectionScenario


def _assert_delivery_address_complete(final: Order) -> None:
    assert final.order_type is OrderType.DELIVERY, (
        f"Expected order_type=delivery; got {final.order_type}"
    )
    assert final.delivery_address is not None, "Expected an address"
    addr_lower = final.delivery_address.lower()
    assert "14" in addr_lower, (
        f"Expected captured address to contain '14'; got "
        f"{final.delivery_address!r}"
    )
    assert "spadina" in addr_lower, (
        f"Expected captured address to contain 'Spadina'; got "
        f"{final.delivery_address!r}"
    )


def _assert_uhh_then_real(final: Order) -> None:
    assert final.order_type is OrderType.DELIVERY, (
        f"Expected order_type=delivery; got {final.order_type}"
    )
    assert final.delivery_address is not None, (
        "Expected an address after the re-ask"
    )
    addr_lower = final.delivery_address.lower()
    assert "uhh" not in addr_lower, (
        f"'uhh' should have been rejected and replaced; got "
        f"{final.delivery_address!r}"
    )
    assert "14" in addr_lower, (
        f"Expected the corrected address to contain '14'; got "
        f"{final.delivery_address!r}"
    )


def _assert_pickup_only_soft_pivot(final: Order) -> None:
    assert final.order_type is OrderType.PICKUP, (
        f"Expected order_type=pickup; got {final.order_type}"
    )
    assert final.delivery_address in (None, ""), (
        f"Expected no delivery_address on pickup-only flow; got "
        f"{final.delivery_address!r}"
    )


# This catalog is consumed by the parametrized test in
# tests/test_llm_integration.py. Three scenarios ≈ ~10s each ≈ 30s total
# at live Haiku rates.
SCENARIOS: list[CorrectionScenario] = [
    CorrectionScenario(
        id="delivery_address_complete",
        initial_turns=[],
        correction_transcript=(
            "I'd like a large margherita for delivery to 14 Spadina Avenue."
        ),
        assert_end_state=_assert_delivery_address_complete,
    ),
    CorrectionScenario(
        id="delivery_address_uhh_then_real",
        initial_turns=[
            "Large margherita for delivery please.",
            "My address is uhh.",
        ],
        correction_transcript="14 Spadina Avenue.",
        assert_end_state=_assert_uhh_then_real,
    ),
    CorrectionScenario(
        id="pickup_only_soft_pivot",
        initial_turns=[
            "Hi, can I get a large margherita for delivery please?",
            "Yes, pickup is fine.",
        ],
        correction_transcript="No modifications, that's everything.",
        assert_end_state=_assert_pickup_only_soft_pivot,
    ),
]
