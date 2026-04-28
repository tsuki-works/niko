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
from app.llm.client import _apply_update, _summarize_order, generate_reply, stream_reply
from app.orders.models import Order, OrderStatus, OrderType

_TEST_SYSTEM_PROMPT = "you are a test agent"


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
        system_prompt=_TEST_SYSTEM_PROMPT,
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
        system_prompt=_TEST_SYSTEM_PROMPT,
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
        system_prompt=_TEST_SYSTEM_PROMPT,
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
        system_prompt=_TEST_SYSTEM_PROMPT,
        client=fake_client,
    )

    assert result.history[0] == {"role": "user", "content": "one pepperoni please"}
    assert result.history[1]["role"] == "assistant"
    assert result.history[1]["content"] == [
        {"type": "text", "text": "Sure, what size?"}
    ]


def test_text_plus_tool_use_appends_tool_result_to_history():
    """Regression for #66: when Haiku emits BOTH text and tool_use in a
    single turn, the assistant message ends with a dangling tool_use.
    Anthropic requires every tool_use to be followed by a tool_result,
    so we must append a synthetic ``user: [tool_result]`` message —
    otherwise the next turn 400s with ``tool_use ids were found without
    tool_result blocks``. Confirmed in production logs for
    call_sid=CA8e3be2e91a7471221f87ba1aab63d1cd."""

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [
            FakeBlock(
                type="text",
                text="Got it, one large margarita for pickup. Anything else?",
            ),
            FakeBlock(
                type="tool_use",
                id="toolu_committed",
                name="update_order",
                input={
                    "items": [
                        {
                            "name": "Margarita",
                            "category": "pizza",
                            "size": "large",
                            "quantity": 1,
                            "unit_price": 19.99,
                        }
                    ],
                    "order_type": "pickup",
                    "status": "in_progress",
                },
            ),
        ]
    )

    result = generate_reply(
        transcript="i'll take a large margarita for pickup",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
        client=fake_client,
    )

    # No follow-up call — text was emitted.
    assert fake_client.messages.create.call_count == 1
    # History ends with a synthetic tool_result so the next turn is valid,
    # AND that result carries the server-computed subtotal so Haiku can
    # quote a verified number instead of fabricating one (per the 2026-04-26
    # Twilight $50.50-vs-$49.25 incident).
    last = result.history[-1]
    assert last["role"] == "user"
    assert len(last["content"]) == 1
    block = last["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "toolu_committed"
    assert "Subtotal: $19.99" in block["content"]
    assert "Margarita" in block["content"]


def test_tool_result_carries_post_apply_subtotal():
    """Each update_order tool_result feeds the post-apply subtotal back
    to Haiku so it can quote a server-verified number to the caller
    (regression for the 2026-04-26 Twilight call where the model
    fabricated a $50.50 total for an order that summed to $49.25).
    Multiple tool_uses in one turn each get their own snapshot."""

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [
            FakeBlock(type="text", text="Adding those now."),
            FakeBlock(
                type="tool_use",
                id="toolu_one",
                name="update_order",
                input={
                    "items": [
                        {
                            "name": "Wings",
                            "category": "appetizers",
                            "size": None,
                            "quantity": 1,
                            "unit_price": 14.50,
                        }
                    ],
                    "status": "in_progress",
                },
            ),
            FakeBlock(
                type="tool_use",
                id="toolu_two",
                name="update_order",
                input={
                    "items": [
                        {
                            "name": "Wings",
                            "category": "appetizers",
                            "size": None,
                            "quantity": 1,
                            "unit_price": 14.50,
                        },
                        {
                            "name": "Fries",
                            "category": "appetizers",
                            "size": None,
                            "quantity": 1,
                            "unit_price": 7.50,
                        },
                    ],
                    "status": "in_progress",
                },
            ),
        ]
    )

    result = generate_reply(
        transcript="add wings and fries",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
        client=fake_client,
    )

    last = result.history[-1]
    assert last["role"] == "user"
    blocks = last["content"]
    assert len(blocks) == 2
    # First tool_result: state after applying tool_one (just wings).
    assert blocks[0]["tool_use_id"] == "toolu_one"
    assert "Subtotal: $14.50" in blocks[0]["content"]
    assert "Wings" in blocks[0]["content"]
    # Second tool_result: state after applying tool_two (wings + fries).
    assert blocks[1]["tool_use_id"] == "toolu_two"
    assert "Subtotal: $22.00" in blocks[1]["content"]
    assert "Wings" in blocks[1]["content"] and "Fries" in blocks[1]["content"]


def test_next_transcript_merges_into_pending_tool_result():
    """When the prior turn ended with ``user: [tool_result]`` (text+tool_use
    case), the *next* turn must merge the new transcript into that user
    message rather than appending a second consecutive user message —
    Anthropic requires strict role alternation."""

    order = Order(call_sid="CAtest")
    history_with_pending_tool_result = [
        {"role": "user", "content": "i'll take a large margarita for pickup"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Got it, anything else?"},
                {
                    "type": "tool_use",
                    "id": "toolu_committed",
                    "name": "update_order",
                    "input": {"items": [], "status": "in_progress"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_committed",
                    "content": "Order updated.",
                }
            ],
        },
    ]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [FakeBlock(type="text", text="Sure thing.")]
    )

    result = generate_reply(
        transcript="extra olives please",
        history=history_with_pending_tool_result,
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
        client=fake_client,
    )

    # Find the last user message; assert the new transcript was merged
    # into the pending tool_result message rather than appended separately.
    user_messages = [m for m in result.history if m["role"] == "user"]
    last_user = user_messages[-1]
    assert isinstance(last_user["content"], list)
    assert last_user["content"][0]["type"] == "tool_result"
    assert last_user["content"][1] == {"type": "text", "text": "extra olives please"}


def test_history_strips_sdk_only_fields_from_assistant_blocks():
    """Regression for #64: the real Anthropic SDK's streaming TextBlock
    carries a ``parsed_output`` attribute (and others). If we ``model_dump``
    those into history, the next turn 400s with
    ``messages.N.content.0.text.parsed_output: Extra inputs are not permitted``.
    The serializer must emit only the API-valid shape regardless of what
    extra attributes the block carries."""

    class SdkLikeBlock:
        type = "text"
        text = "Sure, what size?"
        parsed_output = {"some": "sdk-internal-thing"}
        citations = None
        index = 0

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = MagicMock(content=[SdkLikeBlock()])

    result = generate_reply(
        transcript="one pepperoni please",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
        client=fake_client,
    )

    assistant_block = result.history[1]["content"][0]
    assert assistant_block == {"type": "text", "text": "Sure, what size?"}
    assert "parsed_output" not in assistant_block
    assert "citations" not in assistant_block
    assert "index" not in assistant_block


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
        system_prompt=_TEST_SYSTEM_PROMPT,
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
        system_prompt=_TEST_SYSTEM_PROMPT,
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
        system_prompt=_TEST_SYSTEM_PROMPT,
        client=fake_client,
    )

    assert len(result.order.items) == 1
    assert result.order.items[0].name == "Veggie Supreme"
    assert result.order.items[0].unit_price == 18.99
    assert result.order.order_type is OrderType.PICKUP


class _FakeAsyncStream:
    """Mimics ``AsyncMessageStream`` just enough for ``stream_reply``.

    Yields the configured text deltas through ``text_stream``, then
    returns a fake final message via ``get_final_message`` whose
    ``content`` blocks the consumer can iterate. ``model_dump`` is
    required because ``stream_reply`` serializes the assistant turn
    into history.
    """

    def __init__(self, *, deltas: list[str], blocks: list[FakeBlock]):
        self._deltas = deltas
        self._blocks = blocks

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    @property
    def text_stream(self):
        deltas = self._deltas

        async def _gen():
            for d in deltas:
                yield d

        return _gen()

    async def get_final_message(self):
        return MagicMock(content=self._blocks)


def _stream_manager_factory(streams: list[_FakeAsyncStream]):
    """Returns a callable that pops one stream per ``messages.stream`` call."""

    iterator = iter(streams)

    def _next_stream(**_kwargs):
        return next(iterator)

    return _next_stream


async def _collect(stream_iter):
    deltas: list[str] = []
    final = None
    async for event in stream_iter:
        if event.text_delta is not None:
            deltas.append(event.text_delta)
        if event.final is not None:
            final = event.final
    return deltas, final


async def test_stream_reply_emits_text_deltas_then_final():
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory(
        [
            _FakeAsyncStream(
                deltas=["Hi, ", "what would you ", "like to order?"],
                blocks=[
                    FakeBlock(
                        type="text", text="Hi, what would you like to order?"
                    )
                ],
            )
        ]
    )

    deltas, final = await _collect(
        stream_reply(
            transcript="hello",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
            client=fake_client,
        )
    )

    assert deltas == ["Hi, ", "what would you ", "like to order?"]
    assert final is not None
    assert final.reply_text == "Hi, what would you like to order?"
    assert final.order is order
    assert final.history[0] == {"role": "user", "content": "hello"}
    assert final.history[1]["role"] == "assistant"


async def test_stream_reply_applies_tool_use_to_order_state():
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory(
        [
            _FakeAsyncStream(
                deltas=["One medium pepperoni for pickup."],
                blocks=[
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
                        type="text", text="One medium pepperoni for pickup."
                    ),
                ],
            )
        ]
    )

    _, final = await _collect(
        stream_reply(
            transcript="one medium pepperoni for pickup",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
            client=fake_client,
        )
    )

    assert final.order.items[0].name == "Pepperoni"
    assert final.order.order_type is OrderType.PICKUP
    assert final.order.call_sid == "CAtest"


async def test_stream_reply_runs_followup_when_first_turn_is_tool_only():
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory(
        [
            _FakeAsyncStream(
                deltas=[],  # tool-use only, no text
                blocks=[
                    FakeBlock(
                        type="tool_use",
                        id="toolu_1",
                        name="update_order",
                        input={"items": [], "status": "cancelled"},
                    )
                ],
            ),
            _FakeAsyncStream(
                deltas=["Okay, ", "order cancelled."],
                blocks=[
                    FakeBlock(
                        type="text", text="Okay, order cancelled."
                    )
                ],
            ),
        ]
    )

    deltas, final = await _collect(
        stream_reply(
            transcript="never mind cancel",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
            client=fake_client,
        )
    )

    assert deltas == ["Okay, ", "order cancelled."]
    assert final.reply_text == "Okay, order cancelled."
    assert final.order.status is OrderStatus.CANCELLED


async def test_stream_reply_text_deltas_arrive_before_final():
    """Order matters — TTS must start on the first delta, not after
    the terminal event. This guards against accidental buffering."""

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory(
        [
            _FakeAsyncStream(
                deltas=["A", "B", "C"],
                blocks=[FakeBlock(type="text", text="ABC")],
            )
        ]
    )

    seen: list[str] = []
    async for event in stream_reply(
        transcript="x",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
        client=fake_client,
    ):
        if event.text_delta is not None:
            seen.append(f"delta:{event.text_delta}")
        if event.final is not None:
            seen.append("final")

    assert seen == ["delta:A", "delta:B", "delta:C", "final"]


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
        system_prompt=_TEST_SYSTEM_PROMPT,
        client=fake_client,
    )

    assert result.order.items[0].modifications == ["extra cheese", "no basil"]


def test_summarize_order_includes_modifications():
    """Sprint 2.2 #2 — _summarize_order must include modification strings in
    the tool_result so the agent can read them back to the caller verbatim."""
    order = Order(call_sid="CAtest")
    order = _apply_update(
        order,
        {
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
            "status": "in_progress",
        },
    )
    result = _summarize_order(order)
    assert "extra cheese, no basil" in result
    assert "Margherita" in result


def test_summarize_order_omits_parentheses_when_no_modifications():
    """Sprint 2.2 #3 — when an item has no modifications the summary must not
    emit a parenthesized clause; the agent should omit the modifier phrase
    entirely per the read-back instruction."""
    order = Order(call_sid="CAtest")
    order = _apply_update(
        order,
        {
            "items": [
                {
                    "name": "Margherita",
                    "category": "pizza",
                    "size": "large",
                    "quantity": 1,
                    "unit_price": 20.99,
                    "modifications": [],
                }
            ],
            "status": "in_progress",
        },
    )
    result = _summarize_order(order)
    assert "(" not in result
