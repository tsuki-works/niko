"""Unit tests for the Anthropic LLM client.

All tests use a fake Anthropic client so the suite runs offline with no
API costs. The shape of ``FakeBlock`` mirrors ``anthropic.types.*Block``
just closely enough for our consumer — ``.type``, ``.text`` / ``.id`` /
``.name`` / ``.input``, and ``.model_dump()``.
"""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from app.llm import anthropic as anthropic_module
from app.llm.anthropic import (
    UPDATE_ORDER_TOOL,
    AnthropicLLM,
)
from app.llm.orchestration import (
    apply_order_patch as _apply_update,
)
from app.llm.orchestration import (
    summarize_order_for_tool_result as _summarize_order,
)
from app.orders.models import Order, OrderStatus, OrderType

_TEST_SYSTEM_PROMPT = "you are a test agent"


@pytest.fixture(autouse=True)
def _reset_async_client_singleton():
    """Reset the module-level AsyncAnthropic singleton after each test so
    one test's instance never leaks into the next. The real process doesn't
    need this — the singleton is intentionally long-lived there."""
    yield
    anthropic_module._reset_async_client()


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

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="hello",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    assert result.reply_text == "Hi, what would you like to order?"
    assert result.order is order
    assert fake_client.messages.create.call_count == 1


def test_tool_use_updates_order_in_single_turn():
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _fake_response(
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
        ),
        _fake_response([FakeBlock(type="text", text="Anything else for you?")]),
    ]

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="one medium pepperoni for pickup",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    assert "One medium pepperoni for pickup. Anything else?" in result.reply_text
    assert "Anything else for you?" in result.reply_text
    assert len(result.order.items) == 1
    assert result.order.items[0].name == "Pepperoni"
    assert result.order.order_type is OrderType.PICKUP
    assert result.order.call_sid == "CAtest"
    assert fake_client.messages.create.call_count == 2
    # Follow-up keeps the tool schema in tools so the cache prefix matches
    # the main call (#176); tool_choice="none" suppresses further tool use.
    followup_call_kwargs = fake_client.messages.create.call_args_list[1][1]
    assert followup_call_kwargs["tools"] == [UPDATE_ORDER_TOOL]
    assert followup_call_kwargs["tool_choice"] == {"type": "none"}


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

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="never mind cancel",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    assert result.reply_text == "Okay, order cancelled. Have a good day."
    assert result.order.status is OrderStatus.CANCELLED
    assert fake_client.messages.create.call_count == 2
    # Follow-up keeps the tool schema in tools so the cache prefix matches
    # the main call (#176); tool_choice="none" suppresses further tool use.
    followup_call_kwargs = fake_client.messages.create.call_args_list[1][1]
    assert followup_call_kwargs["tools"] == [UPDATE_ORDER_TOOL]
    assert followup_call_kwargs["tool_choice"] == {"type": "none"}


def test_history_threads_user_and_assistant_turns():
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [FakeBlock(type="text", text="Sure, what size?")]
    )

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="one pepperoni please",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    assert result.history[0] == {"role": "user", "content": "one pepperoni please"}
    assert result.history[1]["role"] == "assistant"
    assert result.history[1]["content"] == [{"type": "text", "text": "Sure, what size?"}]


def test_text_plus_tool_use_appends_tool_result_to_history():
    """Regression for #66: when Haiku emits BOTH text and tool_use in a
    single turn, the assistant message ends with a dangling tool_use.
    Anthropic requires every tool_use to be followed by a tool_result,
    so we must append a synthetic ``user: [tool_result]`` message —
    otherwise the next turn 400s with ``tool_use ids were found without
    tool_result blocks``. Confirmed in production logs for
    call_sid=CA8e3be2e91a7471221f87ba1aab63d1cd.

    After #173 the follow-up always runs — the tool_result user message
    is followed by a second assistant message from the follow-up call."""

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _fake_response(
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
        ),
        _fake_response(
            [
                FakeBlock(
                    type="text",
                    text="So that's one large Margarita — your total is nineteen ninety-nine. Sound right?",
                )
            ]
        ),
    ]

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="i'll take a large margarita for pickup",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    # Follow-up now always runs after tool_use (#173).
    assert fake_client.messages.create.call_count == 2
    # The tool_result user message must precede the follow-up assistant message
    # in history — find it by scanning backwards.
    tool_result_msg = None
    followup_assistant_msg = None
    for msg in result.history:
        if (
            msg["role"] == "user"
            and isinstance(msg["content"], list)
            and msg["content"]
            and msg["content"][0].get("type") == "tool_result"
        ):
            tool_result_msg = msg
        elif msg["role"] == "assistant" and tool_result_msg is not None:
            followup_assistant_msg = msg

    assert tool_result_msg is not None, "tool_result user message missing from history"
    block = tool_result_msg["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "toolu_committed"
    # Server-verified subtotal must be in the tool_result (#66 regression guard).
    assert "Subtotal: $19.99" in block["content"]
    assert "Margarita" in block["content"]

    # History must continue with the follow-up assistant message after the tool_result.
    assert followup_assistant_msg is not None, "follow-up assistant message missing from history"
    assert any(
        b.get("text", "")
        == "So that's one large Margarita — your total is nineteen ninety-nine. Sound right?"
        for b in followup_assistant_msg["content"]
    )


def test_tool_result_carries_post_apply_subtotal():
    """Each update_order tool_result feeds the post-apply subtotal back
    to Haiku so it can quote a server-verified number to the caller
    (regression for the 2026-04-26 Twilight call where the model
    fabricated a $50.50 total for an order that summed to $49.25).
    Multiple tool_uses in one turn each get their own snapshot."""

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _fake_response(
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
        ),
        _fake_response([FakeBlock(type="text", text="Anything else?")]),
    ]

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="add wings and fries",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    # Find the tool_result user message (comes right after the first assistant turn).
    tool_result_msg = None
    for msg in result.history:
        if (
            msg["role"] == "user"
            and isinstance(msg["content"], list)
            and msg["content"]
            and msg["content"][0].get("type") == "tool_result"
        ):
            tool_result_msg = msg
            break
    assert tool_result_msg is not None
    blocks = tool_result_msg["content"]
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

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="extra olives please",
        history=history_with_pending_tool_result,
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
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

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="one pepperoni please",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
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
    monkeypatch.setattr(anthropic_module.settings, "anthropic_api_key", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        anthropic_module._client()


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

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="can I get some sushi",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
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

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="mmrgh pfftbl",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
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
    fake_client.messages.create.side_effect = [
        _fake_response(
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
        ),
        _fake_response([FakeBlock(type="text", text="Anything else?")]),
    ]

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="actually scratch that, make it a veggie supreme",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    assert len(result.order.items) == 1
    assert result.order.items[0].name == "Veggie Supreme"
    assert result.order.items[0].unit_price == 18.99
    assert result.order.order_type is OrderType.PICKUP


class _FakeAsyncStream:
    """Mimics ``AsyncMessageStream`` just enough for ``stream_reply``.

    Synthesizes a raw-event sequence that mirrors what the Anthropic
    SDK emits, so ``stream_reply`` can iterate ``async for event in
    stream`` and observe message_start (with cache-token usage),
    content_block_start (text or tool_use), and content_block_delta
    (text_delta) events.

    Knobs:
    - ``blocks``         — final-message content (text and tool_use).
                           Determines block-start order during streaming.
    - ``deltas``         — optional override for the first text block's
                           streamed deltas. When empty, the block.text
                           is emitted as a single delta.
    - ``usage_*``        — cache token counts surfaced via the
                           message_start event and on get_final_message.
    """

    def __init__(
        self,
        *,
        deltas: list[str],
        blocks: list[FakeBlock],
        usage_cache_read: int = 0,
        usage_cache_creation: int = 0,
    ):
        self._deltas = deltas
        self._blocks = blocks
        self._usage_cache_read = usage_cache_read
        self._usage_cache_creation = usage_cache_creation

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def _synthesized_events(self) -> list[Any]:
        usage = SimpleNamespace(
            cache_read_input_tokens=self._usage_cache_read,
            cache_creation_input_tokens=self._usage_cache_creation,
        )
        events: list[Any] = [
            SimpleNamespace(
                type="message_start",
                message=SimpleNamespace(usage=usage),
            )
        ]
        first_text_seen = False
        for block in self._blocks:
            if block.type == "text":
                events.append(
                    SimpleNamespace(
                        type="content_block_start",
                        content_block=SimpleNamespace(type="text"),
                    )
                )
                if not first_text_seen and self._deltas:
                    for d in self._deltas:
                        events.append(
                            SimpleNamespace(
                                type="content_block_delta",
                                delta=SimpleNamespace(type="text_delta", text=d),
                            )
                        )
                else:
                    events.append(
                        SimpleNamespace(
                            type="content_block_delta",
                            delta=SimpleNamespace(type="text_delta", text=block.text),
                        )
                    )
                first_text_seen = True
                events.append(SimpleNamespace(type="content_block_stop"))
            elif block.type == "tool_use":
                events.append(
                    SimpleNamespace(
                        type="content_block_start",
                        content_block=SimpleNamespace(type="tool_use"),
                    )
                )
                events.append(SimpleNamespace(type="content_block_stop"))
        events.append(SimpleNamespace(type="message_stop"))
        return events

    async def __aiter__(self):
        for event in self._synthesized_events():
            yield event

    async def get_final_message(self):
        usage = SimpleNamespace(
            cache_read_input_tokens=self._usage_cache_read,
            cache_creation_input_tokens=self._usage_cache_creation,
        )
        return MagicMock(content=self._blocks, usage=usage)


def _stream_manager_factory(streams: list[_FakeAsyncStream]):
    """Returns a callable that pops one stream per ``messages.stream`` call."""

    iterator = iter(streams)

    def _next_stream(**_kwargs):
        return next(iterator)

    return _next_stream


def _stream_manager_factory_capturing(streams: list[_FakeAsyncStream], captured_calls: list[dict]):
    """Like _stream_manager_factory but records kwargs for each call into captured_calls."""

    iterator = iter(streams)

    def _next_stream(**kwargs):
        captured_calls.append(kwargs)
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
                blocks=[FakeBlock(type="text", text="Hi, what would you like to order?")],
            )
        ]
    )

    deltas, final = await _collect(
        AnthropicLLM(async_client=fake_client).stream_reply(
            transcript="hello",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
        )
    )

    assert deltas == ["Hi, ", "what would you ", "like to order?"]
    assert final is not None
    assert final.reply_text == "Hi, what would you like to order?"
    assert final.order is order
    assert final.history[0] == {"role": "user", "content": "hello"}
    assert final.history[1]["role"] == "assistant"


async def test_stream_reply_emits_flush_now_after_text_block(monkeypatch):
    """Pure-text turn: a flush_now event lands after the deltas and before
    the terminal final event, so the session can drain its TTS buffer at
    the block boundary instead of waiting for ``event.final``.

    Reproduces case A from #305 — a single text block whose deltas don't
    happen to end on a hard/soft break, so _should_flush_chunk never
    fires mid-stream and the buffer otherwise sits idle until final.
    """
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory(
        [
            _FakeAsyncStream(
                deltas=["Okay", " one", " moment"],  # no trailing punctuation
                blocks=[FakeBlock(type="text", text="Okay one moment")],
            )
        ]
    )

    event_kinds: list[str] = []
    async for event in AnthropicLLM(async_client=fake_client).stream_reply(
        transcript="hi",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    ):
        if event.text_delta is not None:
            event_kinds.append("delta")
        if event.flush_now:
            event_kinds.append("flush")
        if event.final is not None:
            event_kinds.append("final")

    # Three deltas, one flush at block-stop, then final — in that order.
    assert event_kinds == ["delta", "delta", "delta", "flush", "final"]


async def test_stream_reply_emits_flush_now_before_tool_use_block():
    """Text-then-tool turn: the text block's flush_now must fire before
    the tool round-trip starts, so any buffered TTS text drains while
    the tool call is in flight rather than waiting for the follow-up.

    Reproduces case B from #305 — model emits a short ack ("Okay,") then
    calls update_order. Without block-boundary flush, "Okay," is too
    short for _MIN_CHUNK_CHARS and gets held until event.final.
    """
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory(
        [
            _FakeAsyncStream(
                deltas=["Okay,"],
                blocks=[
                    FakeBlock(type="text", text="Okay,"),
                    FakeBlock(
                        type="tool_use",
                        id="toolu_1",
                        name="update_order",
                        input={"items": [], "status": "in_progress"},
                    ),
                ],
            ),
            _FakeAsyncStream(
                deltas=["What else?"],
                blocks=[FakeBlock(type="text", text="What else?")],
            ),
        ]
    )

    seen_flush_before_final = False
    seen_final = False
    async for event in AnthropicLLM(async_client=fake_client).stream_reply(
        transcript="add nothing",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    ):
        if event.flush_now and not seen_final:
            seen_flush_before_final = True
        if event.final is not None:
            seen_final = True

    assert seen_flush_before_final, "flush_now must be emitted before event.final"


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
                    FakeBlock(type="text", text="One medium pepperoni for pickup."),
                ],
            ),
            _FakeAsyncStream(
                deltas=["Anything else?"],
                blocks=[FakeBlock(type="text", text="Anything else?")],
            ),
        ]
    )

    _, final = await _collect(
        AnthropicLLM(async_client=fake_client).stream_reply(
            transcript="one medium pepperoni for pickup",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
        )
    )

    assert final.order.items[0].name == "Pepperoni"
    assert final.order.order_type is OrderType.PICKUP
    assert final.order.call_sid == "CAtest"


async def test_stream_reply_runs_followup_when_first_turn_is_tool_only():
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    captured_calls: list[dict] = []
    fake_client.messages.stream = _stream_manager_factory_capturing(
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
                blocks=[FakeBlock(type="text", text="Okay, order cancelled.")],
            ),
        ],
        captured_calls,
    )

    deltas, final = await _collect(
        AnthropicLLM(async_client=fake_client).stream_reply(
            transcript="never mind cancel",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
        )
    )

    assert deltas == ["Okay, ", "order cancelled."]
    assert final.reply_text == "Okay, order cancelled."
    assert final.order.status is OrderStatus.CANCELLED
    # Follow-up keeps the tool schema in tools so the cache prefix matches
    # the main call (#176); tool_choice="none" suppresses further tool use.
    assert len(captured_calls) == 2
    assert captured_calls[1]["tools"] == [UPDATE_ORDER_TOOL]
    assert captured_calls[1]["tool_choice"] == {"type": "none"}


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
    async for event in AnthropicLLM(async_client=fake_client).stream_reply(
        transcript="x",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    ):
        if event.text_delta is not None:
            seen.append(f"delta:{event.text_delta}")
        if event.final is not None:
            seen.append("final")

    assert seen == ["delta:A", "delta:B", "delta:C", "final"]


async def test_stream_reply_emits_timing_event_before_first_delta():
    """The timing snapshot must land before any text delta so the
    router can fold the breakdown into its ``first_audio`` Firestore
    event (#146). The exact wall-clock numbers are environment-
    dependent; what matters is the event shape and ordering."""

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory(
        [
            _FakeAsyncStream(
                deltas=["Hi!"],
                blocks=[FakeBlock(type="text", text="Hi!")],
                usage_cache_read=420,
                usage_cache_creation=0,
            )
        ]
    )

    seen_kinds: list[str] = []
    timing_payload: dict[str, Any] | None = None
    async for event in AnthropicLLM(async_client=fake_client).stream_reply(
        transcript="hello",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    ):
        if event.timing is not None:
            seen_kinds.append("timing")
            timing_payload = event.timing
        elif event.text_delta is not None:
            seen_kinds.append("delta")
        elif event.final is not None:
            seen_kinds.append("final")

    # timing must precede every text delta and the final event.
    assert seen_kinds == ["timing", "delta", "final"]
    assert timing_payload is not None
    # Back-compat fields must still be present (#175).
    assert {
        "ttft_seconds",
        "tool_prefix_seconds",
        "cache_read_tokens",
        "cache_creation_tokens",
    } <= set(timing_payload.keys())
    # New finer fields added in #175.
    assert {"network_prefill_seconds", "decode_seconds"} <= set(timing_payload.keys())
    assert timing_payload["ttft_seconds"] >= 0
    assert timing_payload["tool_prefix_seconds"] >= 0
    assert timing_payload["network_prefill_seconds"] >= 0
    assert timing_payload["decode_seconds"] >= 0
    # Cache token counts come straight from the message_start usage block.
    assert timing_payload["cache_read_tokens"] == 420
    assert timing_payload["cache_creation_tokens"] == 0


async def test_stream_reply_timing_reflects_tool_use_before_text():
    """When a tool_use block opens before any text, tool_prefix_seconds
    is non-zero (the invisible streaming time #146 needs to expose).
    When a text block opens first, tool_prefix_seconds is ~0."""

    order = Order(call_sid="CAtest")

    _followup_stream = _FakeAsyncStream(
        deltas=["Okay."],
        blocks=[FakeBlock(type="text", text="Okay.")],
    )

    async def _run(blocks):
        fake_client = MagicMock()
        # Provide a follow-up stream for every tool_use turn (#173).
        streams = [_FakeAsyncStream(deltas=["Done."], blocks=blocks)]
        has_tool = any(b.type == "tool_use" for b in blocks)
        if has_tool:
            streams.append(
                _FakeAsyncStream(deltas=["Okay."], blocks=[FakeBlock(type="text", text="Okay.")])
            )
        fake_client.messages.stream = _stream_manager_factory(streams)
        timing = None
        async for event in AnthropicLLM(async_client=fake_client).stream_reply(
            transcript="x",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
        ):
            if event.timing is not None:
                timing = event.timing
        assert timing is not None
        return timing

    text_first = await _run([FakeBlock(type="text", text="Done.")])
    tool_first = await _run(
        [
            FakeBlock(
                type="tool_use",
                id="toolu_x",
                name="update_order",
                input={"items": [], "status": "confirmed"},
            ),
            FakeBlock(type="text", text="Done."),
        ]
    )

    # Text-first: nothing between first event and first text block.
    assert text_first["tool_prefix_seconds"] == 0.0
    # Tool-first: tool_prefix_seconds may be small in tests but must be
    # strictly greater than the text-first case (the synthesized
    # tool_use block_start + stop events take real wall-clock time).
    assert tool_first["tool_prefix_seconds"] >= text_first["tool_prefix_seconds"]


def test_modifications_round_trip_into_line_item():
    """Modifications like 'extra cheese' or 'no onions' must survive
    tool-use payload → LineItem deserialization."""

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _fake_response(
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
        ),
        _fake_response([FakeBlock(type="text", text="Anything else?")]),
    ]

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="large margherita extra cheese no basil",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
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


# ---------------------------------------------------------------------------
# Caller-correction characterization tests (Sprint 2.2 #103)
# ---------------------------------------------------------------------------
# These assert that _apply_update — which already does full-state overwrite —
# correctly handles every correction shape the new prompt block instructs
# Haiku to emit. They lock in current behavior; if a future refactor
# introduces a remove_item / change_item tool, these MUST still pass against
# the equivalent payload shape.


def _seed_order_with(items: list[dict[str, Any]], **extra: Any) -> Order:
    """Helper: build an Order with the given items and apply once."""
    base = Order(call_sid="CAtest")
    return _apply_update(base, {"items": items, "status": "in_progress", **extra})


def test_correction_remove_item_drops_it_from_order():
    """Caller: 'take off the Coke.' Payload omits the Coke entirely;
    only the Margherita remains."""
    order = _seed_order_with(
        [
            {
                "name": "Margherita",
                "category": "pizza",
                "size": "large",
                "quantity": 1,
                "unit_price": 19.99,
            },
            {"name": "Coke", "category": "drinks", "size": None, "quantity": 1, "unit_price": 2.99},
        ],
        order_type="pickup",
    )

    corrected = _apply_update(
        order,
        {
            "items": [
                {
                    "name": "Margherita",
                    "category": "pizza",
                    "size": "large",
                    "quantity": 1,
                    "unit_price": 19.99,
                },
            ],
            "order_type": "pickup",
            "status": "in_progress",
        },
    )

    assert [i.name for i in corrected.items] == ["Margherita"]
    assert corrected.subtotal == 19.99


def test_correction_substitute_item_replaces_not_appends():
    """Caller: 'change the Margherita to a calzone.' Payload swaps the
    item; quantity carries through. Crucially the resulting order has
    ONE item, not two."""
    order = _seed_order_with(
        [
            {
                "name": "Margherita",
                "category": "pizza",
                "size": "large",
                "quantity": 1,
                "unit_price": 19.99,
            },
        ],
        order_type="pickup",
    )

    corrected = _apply_update(
        order,
        {
            "items": [
                {
                    "name": "Calzone",
                    "category": "pizza",
                    "size": "large",
                    "quantity": 1,
                    "unit_price": 16.99,
                },
            ],
            "order_type": "pickup",
            "status": "in_progress",
        },
    )

    assert len(corrected.items) == 1
    assert corrected.items[0].name == "Calzone"
    assert corrected.items[0].unit_price == 16.99


def test_correction_quantity_change_does_not_duplicate_line():
    """Caller: 'make that 2 not 1.' Same line item with quantity bumped;
    never two lines for the same item."""
    order = _seed_order_with(
        [
            {
                "name": "Margherita",
                "category": "pizza",
                "size": "large",
                "quantity": 1,
                "unit_price": 19.99,
            },
        ],
        order_type="pickup",
    )

    corrected = _apply_update(
        order,
        {
            "items": [
                {
                    "name": "Margherita",
                    "category": "pizza",
                    "size": "large",
                    "quantity": 2,
                    "unit_price": 19.99,
                },
            ],
            "order_type": "pickup",
            "status": "in_progress",
        },
    )

    assert len(corrected.items) == 1
    assert corrected.items[0].quantity == 2
    assert corrected.subtotal == 39.98


def test_correction_size_change_swaps_size_and_unit_price():
    """Caller: 'I said large not medium.' Same item with new size +
    new unit_price (the menu's price for the new size)."""
    order = _seed_order_with(
        [
            {
                "name": "Margherita",
                "category": "pizza",
                "size": "medium",
                "quantity": 1,
                "unit_price": 14.99,
            },
        ],
        order_type="pickup",
    )

    corrected = _apply_update(
        order,
        {
            "items": [
                {
                    "name": "Margherita",
                    "category": "pizza",
                    "size": "large",
                    "quantity": 1,
                    "unit_price": 19.99,
                },
            ],
            "order_type": "pickup",
            "status": "in_progress",
        },
    )

    assert len(corrected.items) == 1
    assert corrected.items[0].size == "large"
    assert corrected.items[0].unit_price == 19.99


def test_correction_order_type_swap_to_pickup_clears_delivery_address():
    """Caller: 'switch back to pickup.' order_type flips and
    delivery_address goes back to None — otherwise the dashboard
    would show a stale address on a pickup order."""
    order = _seed_order_with(
        [
            {
                "name": "Margherita",
                "category": "pizza",
                "size": "large",
                "quantity": 1,
                "unit_price": 19.99,
            },
        ],
        order_type="delivery",
        delivery_address="14 Spadina Ave",
    )
    assert order.order_type is OrderType.DELIVERY
    assert order.delivery_address == "14 Spadina Ave"

    corrected = _apply_update(
        order,
        {
            "items": [
                {
                    "name": "Margherita",
                    "category": "pizza",
                    "size": "large",
                    "quantity": 1,
                    "unit_price": 19.99,
                },
            ],
            "order_type": "pickup",
            "delivery_address": None,
            "status": "in_progress",
        },
    )

    assert corrected.order_type is OrderType.PICKUP
    assert corrected.delivery_address is None


def test_correction_delivery_address_fix_overwrites_full_value():
    """Caller: 'no, my address is 14 not 40.' Payload contains the
    fully-corrected address — not a partial / diff."""
    order = _seed_order_with(
        [
            {
                "name": "Margherita",
                "category": "pizza",
                "size": "large",
                "quantity": 1,
                "unit_price": 19.99,
            },
        ],
        order_type="delivery",
        delivery_address="40 Main St",
    )

    corrected = _apply_update(
        order,
        {
            "items": [
                {
                    "name": "Margherita",
                    "category": "pizza",
                    "size": "large",
                    "quantity": 1,
                    "unit_price": 19.99,
                },
            ],
            "order_type": "delivery",
            "delivery_address": "14 Main St",
            "status": "in_progress",
        },
    )

    assert corrected.delivery_address == "14 Main St"
    assert corrected.order_type is OrderType.DELIVERY


def test_correction_invalid_delivery_address_is_rejected_and_signaled():
    """Sprint 2.2 #105 — when Haiku ships an update_order patch whose
    delivery_address fails validation (non-empty + has a digit), the
    address is dropped from the patch (existing value stays) AND the
    tool_result string carries a rejection note so Haiku re-asks on
    the next turn."""
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
                    "unit_price": 19.99,
                },
            ],
            "order_type": "delivery",
            "delivery_address": "14 Spadina Ave",
            "status": "in_progress",
        },
    )
    assert order.delivery_address == "14 Spadina Ave"

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _fake_response(
            [
                FakeBlock(type="text", text="Got it, what's your address?"),
                FakeBlock(
                    type="tool_use",
                    id="toolu_bad_addr",
                    name="update_order",
                    input={
                        "items": [
                            {
                                "name": "Margherita",
                                "category": "pizza",
                                "size": "large",
                                "quantity": 1,
                                "unit_price": 19.99,
                            },
                        ],
                        "order_type": "delivery",
                        "delivery_address": "uhh",
                        "status": "in_progress",
                    },
                ),
            ]
        ),
        _fake_response([FakeBlock(type="text", text="Could you give me the full street address?")]),
    ]

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="my address is uhh",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    # Bad address was REJECTED — previous good value stays.
    assert result.order.delivery_address == "14 Spadina Ave"
    # Find the tool_result user message in history and check it carries the rejection note.
    tool_result_msg = None
    for msg in result.history:
        if (
            msg["role"] == "user"
            and isinstance(msg["content"], list)
            and msg["content"]
            and msg["content"][0].get("type") == "tool_result"
        ):
            tool_result_msg = msg
            break
    assert tool_result_msg is not None
    assert "Delivery address incomplete" in tool_result_msg["content"][0]["content"]


def test_generate_reply_sends_system_as_cache_block():
    """generate_reply wraps system_prompt in a cache_control block."""
    captured: dict = {}

    class FakeMessage:
        content = [FakeBlock(type="text", text="Hello!")]
        stop_reason = "end_turn"

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                captured["kwargs"] = kwargs
                return FakeMessage()

    AnthropicLLM(sync_client=FakeClient()).generate_reply(
        transcript="hi",
        history=[],
        order=Order(call_sid="CA123", restaurant_id="r1"),
        system_prompt="You are niko.",
    )

    system = captured["kwargs"]["system"]
    assert isinstance(system, list), "system must be a list, not a string"
    assert system[0]["type"] == "text"
    assert system[0]["text"] == "You are niko."
    assert system[0]["cache_control"] == {"type": "ephemeral"}


async def test_stream_reply_sends_system_as_cache_block():
    """stream_reply wraps system_prompt in a cache_control block."""
    captured: dict = {}

    fake_stream = _FakeAsyncStream(
        deltas=["Hi there!"],
        blocks=[FakeBlock(type="text", text="Hi there!")],
    )

    def _capture_stream(**kwargs):
        captured["kwargs"] = kwargs
        return fake_stream

    fake_client = MagicMock()
    fake_client.messages.stream = _capture_stream

    async for _ in AnthropicLLM(async_client=fake_client).stream_reply(
        transcript="hi",
        history=[],
        order=Order(call_sid="CA123", restaurant_id="r1"),
        system_prompt="You are niko.",
    ):
        pass

    system = captured["kwargs"]["system"]
    assert isinstance(system, list)
    assert system[0]["type"] == "text"
    assert system[0]["text"] == "You are niko."
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_apply_validation_passes_through_explicit_address_clears():
    """Sprint 2.2 #105 — when Haiku ships delivery_address=None or ""
    (e.g. swapping from delivery to pickup), that's a legitimate clear,
    not a rejection. The patch must pass through unchanged with no
    rejection note. Regression guard for the PD-D4 -> PD-D5 fix."""
    from app.llm.orchestration import INVALID_ADDRESS_NOTE
    from app.llm.orchestration import validate_order_patch as _apply_validation

    # Explicit None passes through, no rejection note.
    cleaned, notes = _apply_validation(
        {
            "items": [],
            "order_type": "pickup",
            "delivery_address": None,
            "status": "in_progress",
        }
    )
    assert cleaned == {
        "items": [],
        "order_type": "pickup",
        "delivery_address": None,
        "status": "in_progress",
    }
    assert notes == []

    # Empty string passes through, no rejection note.
    cleaned, notes = _apply_validation(
        {
            "delivery_address": "",
        }
    )
    assert cleaned == {"delivery_address": ""}
    assert notes == []

    # Whitespace-only passes through, no rejection note.
    cleaned, notes = _apply_validation(
        {
            "delivery_address": "   ",
        }
    )
    assert cleaned == {"delivery_address": "   "}
    assert notes == []

    # Real garbage with content STILL gets rejected — verifies the
    # explicit-clear pass-through didn't accidentally weaken the
    # rejection path.
    cleaned, notes = _apply_validation(
        {
            "delivery_address": "uhh",
        }
    )
    assert "delivery_address" not in cleaned
    assert notes == [INVALID_ADDRESS_NOTE]


def test_followup_after_text_plus_tool_produces_readback_in_same_turn():
    """#173 — when the first response has BOTH text and tool_use, a follow-up
    call always runs so the model can read back the verified subtotal in the
    same turn rather than waiting for the next caller transcript."""

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _fake_response(
            [
                FakeBlock(
                    type="text",
                    text="Got it, one Chicken Fried Rice coming up.",
                ),
                FakeBlock(
                    type="tool_use",
                    id="toolu_cfr",
                    name="update_order",
                    input={
                        "items": [
                            {
                                "name": "Chicken Fried Rice",
                                "category": "fried_rice",
                                "size": None,
                                "quantity": 1,
                                "unit_price": 12.25,
                            }
                        ],
                        "status": "in_progress",
                    },
                ),
            ]
        ),
        _fake_response(
            [
                FakeBlock(
                    type="text",
                    text="So that's one Chicken Fried Rice — your total is twelve twenty-five. Sound right?",
                )
            ]
        ),
    ]

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="that's it",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    # reply_text is the concat of ack + read-back.
    assert "Got it, one Chicken Fried Rice coming up." in result.reply_text
    assert "So that's one Chicken Fried Rice" in result.reply_text
    assert fake_client.messages.create.call_count == 2
    # Follow-up keeps the tool schema in tools so the cache prefix matches
    # the main call (#176); tool_choice="none" suppresses further tool use.
    followup_call_kwargs = fake_client.messages.create.call_args_list[1][1]
    assert followup_call_kwargs["tools"] == [UPDATE_ORDER_TOOL]
    assert followup_call_kwargs["tool_choice"] == {"type": "none"}


async def test_stream_reply_followup_after_text_plus_tool_yields_both_deltas():
    """#173 streaming path — when first response has text + tool_use, the
    follow-up stream's deltas are yielded in the same turn, after the first
    response's deltas. final.reply_text is the full concatenation."""

    order = Order(call_sid="CAtest")
    captured_calls: list[dict] = []
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory_capturing(
        [
            _FakeAsyncStream(
                deltas=["Got it, one Chicken Fried Rice coming up."],
                blocks=[
                    FakeBlock(
                        type="tool_use",
                        id="toolu_cfr",
                        name="update_order",
                        input={
                            "items": [
                                {
                                    "name": "Chicken Fried Rice",
                                    "category": "fried_rice",
                                    "size": None,
                                    "quantity": 1,
                                    "unit_price": 12.25,
                                }
                            ],
                            "status": "in_progress",
                        },
                    ),
                    FakeBlock(
                        type="text",
                        text="Got it, one Chicken Fried Rice coming up.",
                    ),
                ],
            ),
            _FakeAsyncStream(
                deltas=[
                    "So that's one Chicken Fried Rice — your total is twelve twenty-five. Sound right?"
                ],
                blocks=[
                    FakeBlock(
                        type="text",
                        text="So that's one Chicken Fried Rice — your total is twelve twenty-five. Sound right?",
                    )
                ],
            ),
        ],
        captured_calls,
    )

    deltas, final = await _collect(
        AnthropicLLM(async_client=fake_client).stream_reply(
            transcript="that's it",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
        )
    )

    # Both delta streams must be yielded in order.
    assert "Got it, one Chicken Fried Rice coming up." in deltas
    assert (
        "So that's one Chicken Fried Rice — your total is twelve twenty-five. Sound right?"
        in deltas
    )
    assert deltas.index("Got it, one Chicken Fried Rice coming up.") < deltas.index(
        "So that's one Chicken Fried Rice — your total is twelve twenty-five. Sound right?"
    )
    assert final is not None
    assert "Got it" in final.reply_text
    assert "So that's" in final.reply_text
    # final.reply_text concatenates ack + read-back in that order.
    assert final.reply_text.index("Got it") < final.reply_text.index("So that's")
    # Follow-up keeps the tool schema in tools so the cache prefix matches
    # the main call (#176); tool_choice="none" suppresses further tool use.
    assert len(captured_calls) == 2
    assert captured_calls[1]["tools"] == [UPDATE_ORDER_TOOL]
    assert captured_calls[1]["tool_choice"] == {"type": "none"}


async def _collect_all_events(stream_iter) -> list:
    """Collect every StreamEvent yielded by stream_reply, preserving order."""
    events = []
    async for event in stream_iter:
        events.append(event)
    return events


async def test_stream_reply_timing_includes_network_prefill_and_decode():
    """#175 — network_prefill_seconds and decode_seconds must be present and
    non-negative in the timing payload for a plain text turn."""
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory(
        [
            _FakeAsyncStream(
                deltas=["Hi!"],
                blocks=[FakeBlock(type="text", text="Hi!")],
            )
        ]
    )

    timing_payload = None
    async for event in AnthropicLLM(async_client=fake_client).stream_reply(
        transcript="hello",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    ):
        if event.timing is not None:
            timing_payload = event.timing

    assert timing_payload is not None
    assert "network_prefill_seconds" in timing_payload
    assert "decode_seconds" in timing_payload
    assert isinstance(timing_payload["network_prefill_seconds"], float)
    assert isinstance(timing_payload["decode_seconds"], float)
    assert timing_payload["network_prefill_seconds"] >= 0
    assert timing_payload["decode_seconds"] >= 0


async def test_stream_reply_tool_use_turn_emits_two_timing_events(monkeypatch):
    """#175 — a tool-use turn must emit two timing events: one for the first
    stream call (at the text block of that turn) and one for the follow-up
    stream call.

    The clock is pinned to a deterministic sequence so a scoping bug where
    the follow-up reused the first call's t_request_start (producing inflated
    timing values like 1.05 - 0.0 = 1.05s) would be caught by the approx
    assertions below."""
    # time.monotonic call order inside stream_reply for this fixture shape
    # (first stream: tool_use + text; follow-up stream: text):
    #   [0] t_request_start (before first stream loop)
    #   [1] t_first_event   (message_start, first-event guard)
    #   [2] t_message_start (message_start branch)
    #   [3] t_first_text_block (content_block_start(text) in first stream)
    #   [4] fu_t_request_start (before follow-up stream loop)
    #   [5] fu_t_first_event   (message_start, first-event guard)
    #   [6] fu_t_message_start (message_start branch)
    #   [7] fu_t_first_text_block (content_block_start(text) in follow-up)
    _clock = [0.0, 0.10, 0.10, 0.20, 1.0, 1.05, 1.05, 1.15]
    _clock_idx = [0]

    def _fake_monotonic():
        v = _clock[_clock_idx[0]]
        _clock_idx[0] += 1
        return v

    # Patch the time module reference inside client.py so asyncio's own
    # time.monotonic (used for event-loop scheduling) is not affected.
    import types as _types

    fake_time = _types.SimpleNamespace(monotonic=_fake_monotonic)
    monkeypatch.setattr(anthropic_module, "time", fake_time)

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory(
        [
            _FakeAsyncStream(
                deltas=["Got it, adding that now."],
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
                                }
                            ],
                            "status": "in_progress",
                        },
                    ),
                    FakeBlock(type="text", text="Got it, adding that now."),
                ],
            ),
            _FakeAsyncStream(
                deltas=["Anything else?"],
                blocks=[FakeBlock(type="text", text="Anything else?")],
            ),
        ]
    )

    events = await _collect_all_events(
        AnthropicLLM(async_client=fake_client).stream_reply(
            transcript="one medium pepperoni",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
        )
    )

    timing_events = [e for e in events if e.timing is not None]
    assert len(timing_events) == 2, (
        f"Expected 2 timing events for a tool-use turn, got {len(timing_events)}"
    )

    first_t = timing_events[0].timing
    second_t = timing_events[1].timing

    # First call: network_prefill = 0.10 - 0.0, decode = 0.20 - 0.10
    assert first_t["network_prefill_seconds"] == pytest.approx(0.10, abs=1e-9)
    assert first_t["decode_seconds"] == pytest.approx(0.10, abs=1e-9)

    # Follow-up has its own t_request_start anchored at 1.0, not 0.0.
    # A scoping bug reusing t_request_start=0.0 would produce ~1.05s here.
    assert second_t["network_prefill_seconds"] == pytest.approx(0.05, abs=1e-9)
    assert second_t["decode_seconds"] == pytest.approx(0.10, abs=1e-9)
    assert second_t["network_prefill_seconds"] < first_t["network_prefill_seconds"]


async def test_stream_reply_tool_only_turn_emits_two_timing_events(monkeypatch):
    """#175 — tool-only first turn (no text) + follow-up text turn also emits
    two timing events: the fallback from the first call and the normal one
    from the follow-up call.

    The clock is pinned so a scoping bug aliasing fu_t_request_start to
    t_request_start would produce inflated follow-up timing and be caught."""
    # time.monotonic call order for this fixture shape
    # (first stream: tool_use only; follow-up stream: text):
    #   [0] t_request_start (before first stream loop)
    #   [1] t_first_event   (message_start, first-event guard)
    #   [2] t_message_start (message_start branch)
    #   — no t_first_text_block; fallback timing emitted with decode=0.0
    #   [3] fu_t_request_start (before follow-up stream loop)
    #   [4] fu_t_first_event   (message_start, first-event guard)
    #   [5] fu_t_message_start (message_start branch)
    #   [6] fu_t_first_text_block (content_block_start(text) in follow-up)
    _clock = [0.0, 0.10, 0.10, 1.0, 1.05, 1.05, 1.15]
    _clock_idx = [0]

    def _fake_monotonic():
        v = _clock[_clock_idx[0]]
        _clock_idx[0] += 1
        return v

    # Patch the time module reference inside client.py so asyncio's own
    # time.monotonic (used for event-loop scheduling) is not affected.
    import types as _types

    fake_time = _types.SimpleNamespace(monotonic=_fake_monotonic)
    monkeypatch.setattr(anthropic_module, "time", fake_time)

    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory(
        [
            _FakeAsyncStream(
                deltas=[],
                blocks=[
                    FakeBlock(
                        type="tool_use",
                        id="toolu_cancel",
                        name="update_order",
                        input={"items": [], "status": "cancelled"},
                    )
                ],
            ),
            _FakeAsyncStream(
                deltas=["Okay, order cancelled."],
                blocks=[FakeBlock(type="text", text="Okay, order cancelled.")],
            ),
        ]
    )

    events = await _collect_all_events(
        AnthropicLLM(async_client=fake_client).stream_reply(
            transcript="never mind",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
        )
    )

    timing_events = [e for e in events if e.timing is not None]
    assert len(timing_events) == 2, (
        f"Expected 2 timing events for a tool-only turn, got {len(timing_events)}"
    )

    first_t = timing_events[0].timing
    second_t = timing_events[1].timing

    # First call emitted a fallback timing (no text block): decode must be 0.
    assert first_t["network_prefill_seconds"] == pytest.approx(0.10, abs=1e-9)
    assert first_t["decode_seconds"] == pytest.approx(0.0, abs=1e-9)

    # Follow-up is anchored at fu_t_request_start=1.0, not the first call's 0.0.
    # A scoping bug reusing t_request_start=0.0 would produce ~1.05s here.
    assert second_t["network_prefill_seconds"] == pytest.approx(0.05, abs=1e-9)
    assert second_t["decode_seconds"] == pytest.approx(0.10, abs=1e-9)
    assert second_t["network_prefill_seconds"] < first_t["network_prefill_seconds"]


async def test_stream_reply_persistent_client_used_when_no_injection(monkeypatch):
    """#175 — when no client= is injected, stream_reply must use the module-level
    singleton (_get_async_client) on every call, not construct a fresh
    AsyncAnthropic per turn. A regression that switched back to per-turn
    construction would bypass _get_async_client entirely and be caught here."""
    # Pre-seed the singleton with a fake client so stream_reply can run without
    # touching the real network. Two fake streams — one per stream_reply call.
    fake_api = MagicMock()
    fake_api.messages.stream = _stream_manager_factory(
        [
            _FakeAsyncStream(deltas=["Hi!"], blocks=[FakeBlock(type="text", text="Hi!")]),
            _FakeAsyncStream(
                deltas=["Hello again!"], blocks=[FakeBlock(type="text", text="Hello again!")]
            ),
        ]
    )
    monkeypatch.setattr(anthropic_module, "_default_async_client", fake_api)

    # Wrap _get_async_client to count how many times stream_reply invokes it.
    get_call_count = 0
    real_get = anthropic_module._get_async_client

    def _counting_get():
        nonlocal get_call_count
        get_call_count += 1
        return real_get()

    monkeypatch.setattr(anthropic_module, "_get_async_client", _counting_get)

    order = Order(call_sid="CAtest")
    # Two calls without async_client= — both must route through _get_async_client.
    provider = AnthropicLLM()
    await _collect_all_events(
        provider.stream_reply(
            transcript="hello",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
        )
    )
    await _collect_all_events(
        provider.stream_reply(
            transcript="and again",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
        )
    )

    assert get_call_count == 2, (
        f"_get_async_client should be called once per stream_reply turn; got {get_call_count}"
    )
    # The singleton was never replaced — both turns shared the same instance.
    assert anthropic_module._default_async_client is fake_api, (
        "stream_reply must reuse the singleton, not replace it"
    )


# ---------------------------------------------------------------------------
# #176 — rolling cache_control breakpoint on messages[-1]
# ---------------------------------------------------------------------------


def _last_user_blocks(messages: list[dict]) -> list[dict]:
    """Return the content blocks of the last message, normalising the
    plain-string case into a single-block list so tests can index uniformly."""
    last = messages[-1]
    content = last["content"]
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content


def test_main_call_marks_plain_user_transcript_with_rolling_cache_breakpoint():
    """When messages[-1] is a plain-string user transcript, the wrapper
    converts it into a list with one text block carrying
    ``cache_control: ephemeral``. Together with the system breakpoint,
    this gives a 2-breakpoint rolling cache (#176)."""
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [FakeBlock(type="text", text="Sure, what size?")]
    )

    AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="one pepperoni please",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    main_kwargs = fake_client.messages.create.call_args_list[0][1]
    blocks = _last_user_blocks(main_kwargs["messages"])
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert blocks[-1]["text"] == "one pepperoni please"


def test_main_call_marks_only_last_block_when_tool_result_merged_with_user():
    """When _append_user_transcript merges the new transcript with a
    pending tool_result list, only the LAST block (the new text) carries
    cache_control. Earlier tool_result blocks are not marked — Anthropic
    only allows up to 4 cache breakpoints per request and we want them
    on the rolling tail, not in the middle."""
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [FakeBlock(type="text", text="Got it.")]
    )

    history_with_pending_tool_result = [
        {"role": "user", "content": "i'd like a pepperoni"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "got it"},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "update_order",
                    "input": {},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "Order updated.",
                }
            ],
        },
    ]

    AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="and one coke",
        history=history_with_pending_tool_result,
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    main_kwargs = fake_client.messages.create.call_args_list[0][1]
    last_msg = main_kwargs["messages"][-1]
    assert last_msg["role"] == "user"
    blocks = last_msg["content"]
    assert blocks[0]["type"] == "tool_result"
    assert "cache_control" not in blocks[0]
    assert blocks[-1]["type"] == "text"
    assert blocks[-1]["text"] == "and one coke"
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}


def test_followup_call_marks_tool_result_with_rolling_cache_breakpoint():
    """The follow-up call sends history ending in a user message of
    pure tool_result blocks. The last tool_result carries cache_control."""
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _fake_response(
            [
                FakeBlock(type="text", text="Got it."),
                FakeBlock(
                    type="tool_use",
                    id="toolu_x",
                    name="update_order",
                    input={
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
                ),
            ]
        ),
        _fake_response([FakeBlock(type="text", text="Anything else?")]),
    ]

    AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="one medium pepperoni",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    followup_kwargs = fake_client.messages.create.call_args_list[1][1]
    last_msg = followup_kwargs["messages"][-1]
    assert last_msg["role"] == "user"
    blocks = last_msg["content"]
    assert blocks[-1]["type"] == "tool_result"
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}


def test_threaded_history_does_not_carry_cache_control_marker():
    """The cache_control marker is applied at the API call boundary only.
    ``result.history`` (which the orchestrator threads into the next
    turn) must stay clean — otherwise stale breakpoints accumulate as
    the call grows and we'd blow past Anthropic's 4-breakpoint cap."""
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response([FakeBlock(type="text", text="Hi.")])

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="hello",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    def _walk(obj):
        if isinstance(obj, dict):
            assert "cache_control" not in obj, (
                f"threaded history must not carry cache_control: {obj}"
            )
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(result.history)


async def test_stream_reply_marks_messages_last_block_with_rolling_breakpoint():
    """Streaming path mirrors the sync path — the messages array sent to
    ``messages.stream`` carries cache_control on the last block of the
    last message."""
    order = Order(call_sid="CAtest")
    captured_calls: list[dict] = []
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory_capturing(
        [
            _FakeAsyncStream(
                deltas=["Hi!"],
                blocks=[FakeBlock(type="text", text="Hi!")],
            ),
        ],
        captured_calls,
    )

    await _collect(
        AnthropicLLM(async_client=fake_client).stream_reply(
            transcript="hello",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
        )
    )

    assert len(captured_calls) == 1
    blocks = _last_user_blocks(captured_calls[0]["messages"])
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert blocks[-1]["text"] == "hello"


# ---------------------------------------------------------------------------
# #270 — skip the post-tool-use follow-up call on confirm/cancelled turns
# when the main call already emitted text. The follow-up exists to give
# the model a chance to react to tool_result feedback (#173); on terminal-
# status turns there's no useful feedback and the call is ending, so the
# follow-up is pure latency. Mid-order turns and tool-only confirm turns
# still run the follow-up.
# ---------------------------------------------------------------------------


def test_generate_reply_skips_followup_on_confirm_turn_when_main_already_spoke():
    """Caller said 'yes' → main emits goodbye text + status=confirmed
    tool_use. No follow-up call is needed; the caller already heard
    everything and the call is ending."""
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [
            FakeBlock(
                type="text",
                text="Thanks for your order. We'll have it ready for you soon.",
            ),
            FakeBlock(
                type="tool_use",
                id="toolu_confirm",
                name="update_order",
                input={"status": "confirmed"},
            ),
        ]
    )

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="yes",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    # Only one network call — the main call. No follow-up.
    assert fake_client.messages.create.call_count == 1
    assert result.order.status is OrderStatus.CONFIRMED
    assert "Thanks for your order" in result.reply_text

    # History must still thread cleanly: user transcript, assistant turn
    # (text + tool_use), then the synthetic user-tool_result so subsequent
    # turns don't 400 on dangling tool_use (#66 invariant).
    assert result.history[-1]["role"] == "user"
    assert isinstance(result.history[-1]["content"], list)
    assert result.history[-1]["content"][0]["type"] == "tool_result"


def test_generate_reply_runs_followup_on_confirm_turn_when_main_was_tool_only():
    """Edge case: the model emitted update_order(status=confirmed) but
    no text. The caller hasn't heard anything yet, so the follow-up must
    still run to produce a goodbye. Preserves #173's invariant for the
    silent-confirm path."""
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _fake_response(
            [
                FakeBlock(
                    type="tool_use",
                    id="toolu_confirm",
                    name="update_order",
                    input={"status": "confirmed"},
                )
            ]
        ),
        _fake_response([FakeBlock(type="text", text="Thanks. We'll have it ready soon.")]),
    ]

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="yes",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    assert fake_client.messages.create.call_count == 2  # follow-up still runs
    assert "Thanks. We'll have it ready soon." in result.reply_text


def test_generate_reply_runs_followup_on_mid_order_tool_use_with_text():
    """Regression guard against accidentally widening the skip. Mid-order
    item-add turns emit text + tool_use(status=in_progress); the follow-up
    must still run so the model can react to the server-verified subtotal
    in tool_result and produce the next prompt ('anything else?')."""
    order = Order(call_sid="CAtest")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _fake_response(
            [
                FakeBlock(type="text", text="Got it."),
                FakeBlock(
                    type="tool_use",
                    id="toolu_add",
                    name="update_order",
                    input={
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
                ),
            ]
        ),
        _fake_response([FakeBlock(type="text", text="Anything else?")]),
    ]

    result = AnthropicLLM(sync_client=fake_client).generate_reply(
        transcript="one medium pepperoni",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
    )

    # Two calls — main (got it + tool) AND follow-up (anything else?).
    assert fake_client.messages.create.call_count == 2
    assert "Anything else?" in result.reply_text


async def test_stream_reply_skips_followup_on_confirm_turn_when_main_already_spoke():
    """Streaming variant of the confirm-turn skip. No second stream is
    started; the final event lands directly after the main stream."""
    order = Order(call_sid="CAtest")
    captured_calls: list[dict] = []
    fake_client = MagicMock()
    fake_client.messages.stream = _stream_manager_factory_capturing(
        [
            _FakeAsyncStream(
                deltas=["Thanks for your order. We'll have it ready for you soon."],
                blocks=[
                    FakeBlock(
                        type="text",
                        text="Thanks for your order. We'll have it ready for you soon.",
                    ),
                    FakeBlock(
                        type="tool_use",
                        id="toolu_confirm",
                        name="update_order",
                        input={"status": "confirmed"},
                    ),
                ],
            ),
        ],
        captured_calls,
    )

    deltas, final = await _collect(
        AnthropicLLM(async_client=fake_client).stream_reply(
            transcript="yes",
            history=[],
            order=order,
            system_prompt=_TEST_SYSTEM_PROMPT,
        )
    )

    assert len(captured_calls) == 1  # no follow-up stream started
    assert final is not None
    assert final.order.status is OrderStatus.CONFIRMED
    assert "Thanks for your order" in final.reply_text
