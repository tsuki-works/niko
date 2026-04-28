"""Live integration tests for the Anthropic LLM client.

Gated on the ``ANTHROPIC_API_KEY`` environment variable: skipped
silently when the key is absent (CI, teammates without the key, etc.).
When the key is present, makes real Haiku 4.5 calls to prove the tool
schema actually works against the model — mocked tests can't catch
schema rejections or unexpected tool-use behavior.

Run locally with:

    ANTHROPIC_API_KEY=sk-ant-... pytest -v -s tests/test_llm_integration.py

The ``-s`` flag keeps ``print()`` output visible so you can read the
reply transcript and the structured Order state.
"""

import pytest

from app.config import settings
from app.llm.client import generate_reply, stream_reply
from app.llm.prompts import build_system_prompt
from app.orders.models import Order
from app.restaurants.models import Restaurant

pytestmark = pytest.mark.skipif(
    not settings.anthropic_api_key,
    reason="ANTHROPIC_API_KEY not set; skipping live integration tests",
)

# ---------------------------------------------------------------------------
# Demo restaurant fixture — used by every live call in this file.
# Menu includes all items referenced by the correction scenarios (margherita,
# calzone, Coke) plus a couple of extras so the menu reads naturally.
# large margherita is $18.99 to satisfy _assert_size_change (>= $16).
# ---------------------------------------------------------------------------
_DEMO_RESTAURANT = Restaurant(
    id="demo-pizza",
    name="Niko Pizza Kitchen",
    display_phone="416-555-0100",
    twilio_phone="+14165550100",
    address="1 Demo Street, Toronto, ON",
    hours="Mon–Sun 11 am – 10 pm",
    menu={
        "pizzas": [
            {
                "name": "Margherita",
                "description": "Classic tomato and mozzarella",
                "sizes": {"small": 12.99, "medium": 15.99, "large": 18.99},
            },
            {
                "name": "Pepperoni",
                "description": "Classic pepperoni",
                "sizes": {"small": 13.99, "medium": 16.99, "large": 19.99},
            },
            {
                "name": "Veggie Supreme",
                "description": "Garden vegetables on a white base",
                "sizes": {"medium": 16.49, "large": 19.49},
            },
        ],
        "calzones": [
            {
                "name": "Calzone",
                "description": "Folded pizza with ricotta and mozzarella",
                "sizes": {"regular": 14.99, "large": 17.99},
            },
        ],
        "drinks": [
            {"name": "Coke", "price": 2.99},
            {"name": "Water", "price": 1.50},
        ],
    },
)

_DEMO_SYSTEM_PROMPT = build_system_prompt(_DEMO_RESTAURANT)


def test_pickup_order_round_trip():
    """A concrete pickup order should produce a spoken reply AND record
    the item via the update_order tool."""

    order = Order(call_sid="CAintegration-pickup")
    transcript = "Hi, I'd like a large pepperoni pizza for pickup please."

    result = generate_reply(
        transcript=transcript, history=[], order=order,
        system_prompt=_DEMO_SYSTEM_PROMPT,
    )

    print(f"\n--- Caller ---\n{transcript}")
    print(f"\n--- Haiku reply ---\n{result.reply_text}")
    print(f"\n--- Order state ---\n{result.order.model_dump_json(indent=2)}")

    assert len(result.reply_text) > 5, "Haiku should produce a spoken reply"
    assert result.order.call_sid == "CAintegration-pickup", "call_sid preserved"
    assert len(result.order.items) >= 1, (
        "Expected Haiku to record the pepperoni via update_order"
    )


def test_greeting_does_not_mutate_order():
    """A bare greeting shouldn't trigger any tool calls."""

    order = Order(call_sid="CAintegration-greeting")
    transcript = "Hello?"

    result = generate_reply(
        transcript=transcript, history=[], order=order,
        system_prompt=_DEMO_SYSTEM_PROMPT,
    )

    print(f"\n--- Caller ---\n{transcript}")
    print(f"\n--- Haiku reply ---\n{result.reply_text}")

    assert len(result.reply_text) > 5, "Haiku should greet back"
    assert len(result.order.items) == 0, "No items added from a pure greeting"


def test_off_menu_item_is_declined_without_adding():
    """Asking for something not on the demo menu (sushi) should produce
    a polite decline and NOT add anything to the order."""

    order = Order(call_sid="CAintegration-offmenu")
    transcript = "Hi, can I get some sushi please?"

    result = generate_reply(
        transcript=transcript, history=[], order=order,
        system_prompt=_DEMO_SYSTEM_PROMPT,
    )

    print(f"\n--- Caller ---\n{transcript}")
    print(f"\n--- Haiku reply ---\n{result.reply_text}")
    print(f"\n--- Order items ---\n{result.order.items}")

    assert len(result.reply_text) > 5, "Haiku should respond"
    assert len(result.order.items) == 0, (
        "Off-menu requests must not be added to the order"
    )


def test_caller_changes_mind_replaces_pizza():
    """A multi-turn conversation where the caller switches pizzas
    mid-order. The final order should reflect ONLY the new pizza —
    the model is instructed to emit full state, not diffs."""

    order = Order(call_sid="CAintegration-changemind")

    first = generate_reply(
        transcript="I'd like a medium pepperoni for pickup.",
        history=[],
        order=order,
        system_prompt=_DEMO_SYSTEM_PROMPT,
    )
    print(f"\n--- Turn 1 reply ---\n{first.reply_text}")
    print(f"\n--- Turn 1 order ---\n{first.order.model_dump_json(indent=2)}")
    assert any(
        "pepperoni" in item.name.lower() for item in first.order.items
    ), "Turn 1 should record the pepperoni"

    second = generate_reply(
        transcript="Actually, scratch that — make it a large veggie supreme instead.",
        history=first.history,
        order=first.order,
        system_prompt=_DEMO_SYSTEM_PROMPT,
    )
    print(f"\n--- Turn 2 reply ---\n{second.reply_text}")
    print(f"\n--- Turn 2 order ---\n{second.order.model_dump_json(indent=2)}")

    pizza_names = [item.name.lower() for item in second.order.items]
    assert any("veggie" in name for name in pizza_names), (
        "Turn 2 should record the veggie supreme"
    )
    assert not any("pepperoni" in name for name in pizza_names), (
        "Turn 2 should have replaced the pepperoni, not kept both"
    )


async def test_stream_reply_yields_deltas_before_final():
    """Real Haiku call: prove text deltas actually arrive incrementally
    and the terminal event carries the assembled reply + order."""

    order = Order(call_sid="CAintegration-stream")
    transcript = "Hi, can I get a large pepperoni for pickup?"

    delta_count = 0
    seen_final_after_deltas = False
    final = None

    async for event in stream_reply(
        transcript=transcript, history=[], order=order,
        system_prompt=_DEMO_SYSTEM_PROMPT,
    ):
        if event.text_delta is not None:
            delta_count += 1
        if event.final is not None:
            seen_final_after_deltas = True
            final = event.final
            break

    assert delta_count >= 1, "Expected at least one text delta from Haiku"
    assert seen_final_after_deltas, "Stream must end with a final event"
    assert final is not None
    assert len(final.reply_text) > 5
    print(f"\n--- Reply ({delta_count} deltas) ---\n{final.reply_text}")
    print(f"\n--- Order ---\n{final.order.model_dump_json(indent=2)}")


# ---------------------------------------------------------------------------
# Caller-correction live regression suite (Sprint 2.2 #103)
# ---------------------------------------------------------------------------
# Marker-gated so it only runs on `pytest -m live_llm`. Unlike the rest of
# this file (which auto-runs whenever ANTHROPIC_API_KEY is set), this suite
# costs ~6× a normal call and is meant to be run pre-merge, not on every
# `pytest` invocation. The module-level skipif still applies — without the
# API key we skip even when -m live_llm is passed.

from tests.fixtures.correction_transcripts import SCENARIOS, CorrectionScenario


@pytest.mark.live_llm
@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_caller_correction_lands_in_final_order(scenario: CorrectionScenario):
    """For each scenario: seed the order via initial turns, then send the
    correction utterance, then assert the final Order matches the
    pattern-specific expectation."""

    order = Order(call_sid=f"CAlive-corr-{scenario.id}")
    history: list[dict] = []

    for turn in scenario.initial_turns:
        result = generate_reply(
            transcript=turn, history=history, order=order,
            system_prompt=_DEMO_SYSTEM_PROMPT,
        )
        order = result.order
        history = result.history
        print(f"\n--- Seed turn ({scenario.id}) ---\nCaller: {turn}\n"
              f"Haiku: {result.reply_text}\n"
              f"Order: {order.model_dump_json(indent=2)}")

    correction = scenario.correction_transcript
    result = generate_reply(
        transcript=correction, history=history, order=order,
        system_prompt=_DEMO_SYSTEM_PROMPT,
    )
    order = result.order

    print(f"\n--- Correction ({scenario.id}) ---\nCaller: {correction}\n"
          f"Haiku: {result.reply_text}\n"
          f"Final order: {order.model_dump_json(indent=2)}")

    scenario.assert_end_state(order)
