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
from app.llm.client import generate_reply
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
