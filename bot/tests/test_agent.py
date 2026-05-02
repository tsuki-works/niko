"""Tests for jarvis.agent.respond — the Claude streaming wrapper."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.agent import MODEL, respond


def _make_anthropic_mock_with_text_chunks(chunks: list[str]):
    """Build a mock anthropic client whose messages.stream context
    manager yields text deltas matching `chunks`."""

    async def text_stream():
        for c in chunks:
            yield c

    stream_obj = MagicMock()
    stream_obj.text_stream = text_stream()

    @asynccontextmanager
    async def stream_cm(**kwargs):
        # Stash the kwargs so the test can introspect them later.
        stream_cm.last_kwargs = kwargs  # type: ignore[attr-defined]
        yield stream_obj

    messages = MagicMock()
    messages.stream = stream_cm

    client = MagicMock()
    client.messages = messages
    return client, stream_cm


async def test_respond_yields_chunks_in_order():
    client, _cm = _make_anthropic_mock_with_text_chunks(["he", "llo", " world"])
    out = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
    ):
        out.append(delta)
    assert out == ["he", "llo", " world"]


async def test_respond_uses_correct_model_and_max_tokens():
    client, cm = _make_anthropic_mock_with_text_chunks(["x"])
    async for _ in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
    ):
        pass
    kwargs = cm.last_kwargs  # type: ignore[attr-defined]
    assert kwargs["model"] == MODEL
    assert kwargs["max_tokens"] == 1024


async def test_respond_passes_system_prompt_with_cache_control():
    client, cm = _make_anthropic_mock_with_text_chunks(["x"])
    async for _ in respond(
        anthropic_client=client,
        system_prompt="SYSTEM_TEXT",
        history=[],
        user_message="hi",
    ):
        pass
    kwargs = cm.last_kwargs  # type: ignore[attr-defined]
    system = kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["text"] == "SYSTEM_TEXT"
    assert system[0]["cache_control"] == {"type": "ephemeral"}


async def test_respond_appends_user_message_to_history():
    client, cm = _make_anthropic_mock_with_text_chunks(["x"])
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ack"},
    ]
    async for _ in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=history,
        user_message="second",
    ):
        pass
    kwargs = cm.last_kwargs  # type: ignore[attr-defined]
    messages = kwargs["messages"]
    assert messages[-1] == {"role": "user", "content": "second"}
    assert messages[0]["content"] == "first"
    assert messages[1]["content"] == "ack"
    # respond() must not mutate the caller's history list.
    assert history == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ack"},
    ]


async def test_respond_handles_empty_stream():
    client, _cm = _make_anthropic_mock_with_text_chunks([])
    out = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
    ):
        out.append(delta)
    assert out == []
