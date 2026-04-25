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
from app.orders.models import Order

pytestmark = pytest.mark.skipif(
    not settings.anthropic_api_key,
    reason="ANTHROPIC_API_KEY not set; skipping live integration tests",
)


def test_pickup_order_round_trip():
    """A concrete pickup order should produce a spoken reply AND record
    the item via the update_order tool."""

    order = Order(call_sid="CAintegration-pickup")
    transcript = "Hi, I'd like a large pepperoni pizza for pickup please."

    result = generate_reply(transcript=transcript, history=[], order=order)

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

    result = generate_reply(transcript=transcript, history=[], order=order)

    print(f"\n--- Caller ---\n{transcript}")
    print(f"\n--- Haiku reply ---\n{result.reply_text}")

    assert len(result.reply_text) > 5, "Haiku should greet back"
    assert len(result.order.items) == 0, "No items added from a pure greeting"


def test_off_menu_item_is_declined_without_adding():
    """Asking for something not on the demo menu (sushi) should produce
    a polite decline and NOT add anything to the order."""

    order = Order(call_sid="CAintegration-offmenu")
    transcript = "Hi, can I get some sushi please?"

    result = generate_reply(transcript=transcript, history=[], order=order)

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

    async for event in stream_reply(transcript=transcript, history=[], order=order):
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
