"""Unit tests for the Anthropic LLM client.

All tests use a fake Anthropic client so the suite runs offline with no
API costs. The shape of ``FakeBlock`` mirrors ``anthropic.types.*Block``
just closely enough for our consumer — ``.type``, ``.text`` / ``.id`` /
``.name`` / ``.input``, and ``.model_dump()``.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from app.llm import client as client_module
from app.llm.client import _apply_update, generate_reply
from app.orders.models import Order, OrderStatus, OrderType


@dataclass
class FakeBlock:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: Optional[dict[str, Any]] = field(default=None)

    def model_dump(self) -> dict[str, Any]:
        if self.type == "text":
            return {"type": "text", "text": self.text}
        return {
            "type": "tool_use",
            "id": self.id,
            "name": self.name,
            "input": self.input or {},
        }


def _fake_response(blocks: list[FakeBlock]) -> MagicMock:
    return MagicMock(content=blocks)


def test_plain_text_response_leaves_order_unchanged():
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [FakeBlock(type="text", text="Hi, what would you like to order?")]
    )

    result = generate_reply(
        transcript="hello",
        history=[],
        order=order,
        client=fake_client,
    )

    assert result.reply_text == "Hi, what would you like to order?"
    assert result.order is order
    assert fake_client.messages.create.call_count == 1


def test_tool_use_updates_order_in_single_turn():
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [
            FakeBlock(
                type="tool_use",
                id="toolu_1",
                name="update_order",
                input={
                    "items": [
                        {
                            "name": "Pepperoni",
                            "category": "pizza",
                            "size": "medium",
                            "quantity": 1,
                            "unit_price": 17.99,
                            "modifications": [],
                        }
                    ],
                    "order_type": "pickup",
                    "status": "in_progress",
                },
            ),
            FakeBlock(
                type="text",
                text="One medium pepperoni for pickup. Anything else?",
            ),
        ]
    )

    result = generate_reply(
        transcript="one medium pepperoni for pickup",
        history=[],
        order=order,
        client=fake_client,
    )

    assert result.reply_text == "One medium pepperoni for pickup. Anything else?"
    assert len(result.order.items) == 1
    assert result.order.items[0].name == "Pepperoni"
    assert result.order.order_type is OrderType.PICKUP
    assert result.order.call_sid == "CAtest"
    assert fake_client.messages.create.call_count == 1


def test_tool_only_response_triggers_followup_call():
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _fake_response(
            [
                FakeBlock(
                    type="tool_use",
                    id="toolu_1",
                    name="update_order",
                    input={"items": [], "status": "cancelled"},
                ),
            ]
        ),
        _fake_response(
            [
                FakeBlock(
                    type="text",
                    text="Okay, order cancelled. Have a good day.",
                ),
            ]
        ),
    ]

    result = generate_reply(
        transcript="never mind cancel",
        history=[],
        order=order,
        client=fake_client,
    )

    assert result.reply_text == "Okay, order cancelled. Have a good day."
    assert result.order.status is OrderStatus.CANCELLED
    assert fake_client.messages.create.call_count == 2


def test_history_threads_user_and_assistant_turns():
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [FakeBlock(type="text", text="Sure, what size?")]
    )

    result = generate_reply(
        transcript="one pepperoni please",
        history=[],
        order=order,
        client=fake_client,
    )

    assert result.history[0] == {"role": "user", "content": "one pepperoni please"}
    assert result.history[1]["role"] == "assistant"
    assert result.history[1]["content"] == [
        {"type": "text", "text": "Sure, what size?"}
    ]


def test_apply_update_preserves_call_sid_and_created_at():
    original = Order(call_sid="CAoriginal")
    original_created_at = original.created_at

    updated = _apply_update(
        original,
        {
            "call_sid": "CAhacked",
            "created_at": "1999-01-01T00:00:00Z",
            "items": [
                {
                    "name": "Coke",
                    "category": "drink",
                    "quantity": 1,
                    "unit_price": 2.99,
                }
            ],
        },
    )

    assert updated.call_sid == "CAoriginal"
    assert updated.created_at == original_created_at
    assert len(updated.items) == 1


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.setattr(client_module.settings, "anthropic_api_key", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        client_module._client()


def test_off_menu_request_leaves_order_empty():
    """When the caller asks for something off-menu, the model declines
    without calling update_order. Order state must not advance."""

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [
            FakeBlock(
                type="text",
                text=(
                    "Sorry, we don't offer sushi here. We have pizzas, "
                    "sides, and drinks — would any of those work?"
                ),
            )
        ]
    )

    result = generate_reply(
        transcript="can I get some sushi",
        history=[],
        order=order,
        client=fake_client,
    )

    assert "sushi" in result.reply_text.lower()
    assert result.order.items == []
    assert result.order.status is OrderStatus.IN_PROGRESS
    assert fake_client.messages.create.call_count == 1


def test_unclear_utterance_asks_for_clarification():
    """A garbled / unclear caller utterance should produce a clarifying
    question with no order mutation."""

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [
            FakeBlock(
                type="text",
                text="Sorry, I didn't catch that. Could you say it again?",
            )
        ]
    )

    result = generate_reply(
        transcript="mmrgh pfftbl",
        history=[],
        order=order,
        client=fake_client,
    )

    assert "again" in result.reply_text.lower() or "didn't catch" in result.reply_text.lower()
    assert result.order.items == []
    assert fake_client.messages.create.call_count == 1


def test_caller_changes_mind_replaces_items():
    """When the caller switches their order mid-conversation, the model
    emits the FULL new state via update_order — the previous item is
    replaced, not appended to."""

    order = Order(call_sid="CAtest")
    order = _apply_update(
        order,
        {
            "items": [
                {
                    "name": "Pepperoni",
                    "category": "pizza",
                    "size": "medium",
                    "quantity": 1,
                    "unit_price": 17.99,
                }
            ],
            "order_type": "pickup",
            "status": "in_progress",
        },
    )
    assert order.items[0].name == "Pepperoni"

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [
            FakeBlock(
                type="tool_use",
                id="toolu_change",
                name="update_order",
                input={
                    "items": [
                        {
                            "name": "Veggie Supreme",
                            "category": "pizza",
                            "size": "medium",
                            "quantity": 1,
                            "unit_price": 18.99,
                            "modifications": [],
                        }
                    ],
                    "order_type": "pickup",
                    "status": "in_progress",
                },
            ),
            FakeBlock(
                type="text",
                text="Got it — one medium veggie supreme for pickup instead.",
            ),
        ]
    )

    result = generate_reply(
        transcript="actually scratch that, make it a veggie supreme",
        history=[],
        order=order,
        client=fake_client,
    )

    assert len(result.order.items) == 1
    assert result.order.items[0].name == "Veggie Supreme"
    assert result.order.items[0].unit_price == 18.99
    assert result.order.order_type is OrderType.PICKUP


def test_modifications_round_trip_into_line_item():
    """Modifications like 'extra cheese' or 'no onions' must survive
    tool-use payload → LineItem deserialization."""

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [
            FakeBlock(
                type="tool_use",
                id="toolu_mods",
                name="update_order",
                input={
                    "items": [
                        {
                            "name": "Margherita",
                            "category": "pizza",
                            "size": "large",
                            "quantity": 1,
                            "unit_price": 20.99,
                            "modifications": ["extra cheese", "no basil"],
                        }
                    ],
                    "order_type": "pickup",
                    "status": "in_progress",
                },
            ),
            FakeBlock(
                type="text",
                text="One large margherita with extra cheese and no basil.",
            ),
        ]
    )

    result = generate_reply(
        transcript="large margherita extra cheese no basil",
        history=[],
        order=order,
        client=fake_client,
    )

    assert result.order.items[0].modifications == ["extra cheese", "no basil"]
