"""Tests for jarvis.agent — Claude streaming with optional tool-use loop."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.agent import MAX_TOOL_STEPS, MODEL, respond
from jarvis.tools import ToolContext, ToolDescriptor, ToolRegistry


# ---------- Fakes ----------


@dataclass
class FakeTextBlock:
    type: str  # "text"
    text: str


@dataclass
class FakeToolUseBlock:
    type: str  # "tool_use"
    id: str
    name: str
    input: dict


@dataclass
class FakeMessage:
    content: list  # list of FakeTextBlock | FakeToolUseBlock


def _ctx() -> ToolContext:
    return ToolContext(
        guild=None,
        github_client=None,
        github_repo="o/r",
        github_project_id="PVT_x",
        docs_root=None,
    )


def _make_anthropic_with_responses(responses: list[tuple[list[str], FakeMessage]]):
    """Each tuple = (text_deltas to stream, final FakeMessage). The mock
    yields responses in order across successive `messages.stream(...)` calls."""
    response_iter = iter(responses)
    captured_calls = []

    @asynccontextmanager
    async def stream_cm(**kwargs):
        captured_calls.append(kwargs)
        deltas, final = next(response_iter)

        async def text_stream():
            for d in deltas:
                yield d

        stream_obj = MagicMock()
        stream_obj.text_stream = text_stream()
        stream_obj.get_final_message = AsyncMock(return_value=final)
        yield stream_obj

    messages = MagicMock()
    messages.stream = stream_cm

    client = MagicMock()
    client.messages = messages
    return client, captured_calls


# ---------- No-tools path (parity with PR 2) ----------


async def test_respond_yields_chunks_in_order_no_tools():
    final = FakeMessage(content=[FakeTextBlock(type="text", text="hello")])
    client, _ = _make_anthropic_with_responses([(["he", "llo"], final)])
    out = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=None,
        tool_context=_ctx(),
    ):
        out.append(delta)
    assert out == ["he", "llo"]


async def test_respond_uses_correct_model_and_max_tokens():
    final = FakeMessage(content=[FakeTextBlock(type="text", text="x")])
    client, calls = _make_anthropic_with_responses([(["x"], final)])
    async for _ in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=None,
        tool_context=_ctx(),
    ):
        pass
    assert calls[0]["model"] == MODEL
    assert calls[0]["max_tokens"] == 1024
    assert calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


async def test_respond_does_not_pass_tools_when_registry_is_none():
    final = FakeMessage(content=[FakeTextBlock(type="text", text="x")])
    client, calls = _make_anthropic_with_responses([(["x"], final)])
    async for _ in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=None,
        tool_context=_ctx(),
    ):
        pass
    assert "tools" not in calls[0]


# ---------- Tool-use path ----------


async def test_respond_dispatches_tool_and_loops():
    """One tool round-trip: model asks for a tool, we dispatch, then it
    streams the final answer."""
    # First response: model emits a tool_use block (no text).
    final1 = FakeMessage(
        content=[
            FakeToolUseBlock(
                type="tool_use", id="tu_1", name="ping", input={"x": 1}
            ),
        ]
    )
    # Second response: model emits the final text answer.
    final2 = FakeMessage(content=[FakeTextBlock(type="text", text="pong")])
    client, calls = _make_anthropic_with_responses(
        [
            ([], final1),
            (["pong"], final2),
        ]
    )

    # Tool registry with one tool that returns {"ok": x*2}.
    async def ping(*, x: int) -> dict:
        return {"ok": x * 2}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="ping",
            description="d",
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
            fn=ping,
        )
    )

    out = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=reg,
        tool_context=_ctx(),
    ):
        out.append(delta)
    assert out == ["pong"]
    # Two API calls: initial + after-tool.
    assert len(calls) == 2
    # Initial call had tools=...
    assert "tools" in calls[0]
    assert calls[0]["tools"][0]["name"] == "ping"
    # Second call's messages includes the assistant tool_use turn AND a
    # user turn carrying the tool_result.
    second_messages = calls[1]["messages"]
    last_two = second_messages[-2:]
    assert last_two[0]["role"] == "assistant"
    # tool_result is wrapped in a user-role message
    assert last_two[1]["role"] == "user"
    tr_blocks = last_two[1]["content"]
    assert tr_blocks[0]["type"] == "tool_result"
    assert tr_blocks[0]["tool_use_id"] == "tu_1"
    assert "ok" in tr_blocks[0]["content"]


async def test_respond_aborts_at_max_tool_steps():
    """If the model keeps asking for tools, stop after MAX_TOOL_STEPS
    and yield a brief safety message."""
    # Build MAX_TOOL_STEPS + 1 responses, every one a tool_use (no text).
    tool_responses = [
        (
            [],
            FakeMessage(
                content=[
                    FakeToolUseBlock(
                        type="tool_use",
                        id=f"tu_{i}",
                        name="ping",
                        input={},
                    )
                ]
            ),
        )
        for i in range(MAX_TOOL_STEPS + 1)
    ]
    client, calls = _make_anthropic_with_responses(tool_responses)

    async def ping(**_kwargs) -> dict:
        return {"ok": True}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="ping", description="d", input_schema={}, fn=ping
        )
    )

    chunks = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=reg,
        tool_context=_ctx(),
    ):
        chunks.append(delta)
    # Loop stopped before consuming the (MAX_TOOL_STEPS+1)-th response.
    assert len(calls) == MAX_TOOL_STEPS
    # A safety message was yielded so the user isn't left empty-handed.
    final_text = "".join(chunks)
    assert "tool" in final_text.lower() and "max" in final_text.lower()


async def test_respond_handles_unknown_tool_name():
    """If the model invents a tool name, the registry returns an error
    JSON and the loop continues; the model gets a chance to recover."""
    final1 = FakeMessage(
        content=[
            FakeToolUseBlock(
                type="tool_use", id="tu_1", name="nope", input={}
            )
        ]
    )
    final2 = FakeMessage(content=[FakeTextBlock(type="text", text="sorry")])
    client, calls = _make_anthropic_with_responses(
        [
            ([], final1),
            (["sorry"], final2),
        ]
    )
    reg = ToolRegistry()  # empty registry

    out = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=reg,
        tool_context=_ctx(),
    ):
        out.append(delta)
    assert "".join(out) == "sorry"
    tr_blocks = calls[1]["messages"][-1]["content"]
    assert "error" in tr_blocks[0]["content"]


async def test_respond_does_not_mutate_history():
    final = FakeMessage(content=[FakeTextBlock(type="text", text="x")])
    client, _ = _make_anthropic_with_responses([(["x"], final)])
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ack"},
    ]
    history_before = [dict(t) for t in history]
    async for _ in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=history,
        user_message="second",
        tool_registry=None,
        tool_context=_ctx(),
    ):
        pass
    assert history == history_before


async def test_respond_handles_text_and_tool_in_same_response():
    """If the model emits both text deltas and a tool_use in one turn,
    we stream the text AND dispatch the tool, then continue."""
    final1 = FakeMessage(
        content=[
            FakeTextBlock(type="text", text="checking…"),
            FakeToolUseBlock(
                type="tool_use", id="tu_1", name="ping", input={}
            ),
        ]
    )
    final2 = FakeMessage(content=[FakeTextBlock(type="text", text="done")])
    client, calls = _make_anthropic_with_responses(
        [
            (["checking…"], final1),
            (["done"], final2),
        ]
    )

    async def ping(**_kwargs) -> dict:
        return {"ok": True}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="ping", description="d", input_schema={}, fn=ping
        )
    )

    out = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=reg,
        tool_context=_ctx(),
    ):
        out.append(delta)
    assert out == ["checking…", "done"]
    assert len(calls) == 2
