"""Tests for jarvis.events.OnMessageHandler."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from jarvis.events import OnMessageHandler
from jarvis.router import RoutingDecision

# --- Discord fakes ---


@dataclass
class FakeUser:
    id: int
    bot: bool = False


@dataclass
class FakePlaceholder:
    edits: list[str] = field(default_factory=list)

    async def edit(self, *, content: str) -> None:
        self.edits.append(content)


@dataclass
class FakeThread:
    id: int
    parent_id: int
    name: str = ""
    last_send: str | None = None
    placeholder: FakePlaceholder | None = None

    async def send(self, content: str) -> FakePlaceholder:
        self.last_send = content
        ph = FakePlaceholder()
        self.placeholder = ph
        return ph


@dataclass
class FakeChannel:
    id: int
    type: str = "text"
    created_thread: FakeThread | None = None

    async def create_thread(self, *, name: str, message: Any | None = None) -> FakeThread:
        # Real discord.py creates a thread off a message with
        # `message.create_thread(name=...)`. The events handler is
        # written against `message.create_thread`, so this fake's
        # method matches.
        raise AssertionError("test should call message.create_thread, not channel")


@dataclass
class FakeMessage:
    id: int
    author: FakeUser
    channel: Any
    guild: Any
    mentions: list[FakeUser] = field(default_factory=list)
    content: str = ""

    async def create_thread(self, *, name: str) -> FakeThread:
        thread = FakeThread(id=self.id + 100_000, parent_id=self.channel.id, name=name)
        self.created_thread = thread  # type: ignore[attr-defined]
        return thread


def _team_user() -> FakeUser:
    return FakeUser(id=1001, bot=False)


def _bot_user_id() -> int:
    return 42


# --- Stub dependencies ---


def _stub_agent(deltas: list[str]):
    """Return an async generator-producing callable matching agent.respond's surface."""

    async def _agent(*, system_prompt, history, user_message, **_kwargs):
        for d in deltas:
            yield d

    return _agent


async def _stream_writer(placeholder, chunks: AsyncIterator[str]) -> str:
    """Test stub matching stream_writer.stream_to_discord — concatenates and edits once."""
    out = ""
    async for d in chunks:
        out += d
    await placeholder.edit(content=out or "(empty response)")
    return out


# --- Tests ---


async def test_ignores_when_router_says_ignore():
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=False)
    handler = OnMessageHandler(
        bot_user_id=_bot_user_id(),
        memory=memory,
        agent_fn=_stub_agent(["hi"]),
        system_prompt_fn=lambda: "SYS",
        stream_writer_fn=_stream_writer,
        rate_limiter=None,
        tool_registry=None,
        tool_context_factory=lambda _msg: None,
    )
    msg = FakeMessage(
        id=1,
        author=_team_user(),
        channel=FakeChannel(id=10, type="text"),
        guild=MagicMock(id=99),
        mentions=[],  # no mention → IGNORE
    )
    await handler.handle(msg)
    memory.record_thread.assert_not_awaited()
    memory.append_turn.assert_not_awaited()


async def test_mention_creates_thread_replies_and_persists():
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=False)
    memory.get_turns = AsyncMock(return_value=[])
    deltas = ["hel", "lo!"]
    handler = OnMessageHandler(
        bot_user_id=_bot_user_id(),
        memory=memory,
        agent_fn=_stub_agent(deltas),
        system_prompt_fn=lambda: "SYS",
        stream_writer_fn=_stream_writer,
        rate_limiter=None,
        tool_registry=None,
        tool_context_factory=lambda _msg: None,
    )
    msg = FakeMessage(
        id=500,
        author=_team_user(),
        channel=FakeChannel(id=10, type="text"),
        guild=MagicMock(id=99),
        mentions=[FakeUser(id=_bot_user_id(), bot=True)],
        content="@jarvis hi",
    )
    await handler.handle(msg)
    # Thread was created off the triggering message.
    assert hasattr(msg, "created_thread") and msg.created_thread is not None
    thread = msg.created_thread
    # Thread was recorded in memory (= "this is a Jarvis thread").
    memory.record_thread.assert_awaited_once()
    record_kwargs = memory.record_thread.await_args.kwargs
    assert record_kwargs["thread_id"] == str(thread.id)
    assert record_kwargs["parent_channel_id"] == "10"
    # Placeholder message was sent and edited with the final reply.
    assert thread.placeholder is not None
    assert thread.placeholder.edits[-1] == "hello!"
    # User turn + assistant turn both persisted.
    appended_calls = memory.append_turn.await_args_list
    assert len(appended_calls) == 2
    assert appended_calls[0].kwargs["role"] == "user"
    assert appended_calls[0].kwargs["content"] == "@jarvis hi"
    assert appended_calls[1].kwargs["role"] == "assistant"
    assert appended_calls[1].kwargs["content"] == "hello!"


async def test_in_existing_thread_does_not_create_new_thread():
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=True)
    memory.get_turns = AsyncMock(
        return_value=[
            {"role": "user", "content": "earlier"},
            {"role": "assistant", "content": "ack"},
        ]
    )
    handler = OnMessageHandler(
        bot_user_id=_bot_user_id(),
        memory=memory,
        agent_fn=_stub_agent(["fine"]),
        system_prompt_fn=lambda: "SYS",
        stream_writer_fn=_stream_writer,
        rate_limiter=None,
        tool_registry=None,
        tool_context_factory=lambda _msg: None,
    )
    thread_channel = FakeThread(id=20, parent_id=10)
    # Make the thread channel quack like a discord.py Thread (has .send).
    msg = FakeMessage(
        id=600,
        author=_team_user(),
        channel=thread_channel,
        guild=MagicMock(id=99),
        mentions=[],
        content="follow-up",
    )
    # Patch channel.type to look thread-y for the router.
    msg.channel.type = "thread"
    await handler.handle(msg)
    # No new thread created.
    memory.record_thread.assert_not_awaited()
    # Reply was sent inside the existing thread.
    assert thread_channel.placeholder is not None
    assert thread_channel.placeholder.edits[-1] == "fine"
    # Both turns persisted using the existing thread id.
    for call in memory.append_turn.await_args_list:
        assert call.kwargs["thread_id"] == "20"


async def test_history_passed_through_to_agent():
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=True)
    history = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]
    memory.get_turns = AsyncMock(return_value=history)

    captured = {}

    async def capture_agent(*, system_prompt, history, user_message, tool_registry, tool_context):
        captured["system_prompt"] = system_prompt
        captured["history"] = history
        captured["user_message"] = user_message
        yield "ok"

    handler = OnMessageHandler(
        bot_user_id=_bot_user_id(),
        memory=memory,
        agent_fn=capture_agent,
        system_prompt_fn=lambda: "SYS_TEXT",
        stream_writer_fn=_stream_writer,
        rate_limiter=None,
        tool_registry=None,
        tool_context_factory=lambda _msg: None,
    )
    thread = FakeThread(id=20, parent_id=10)
    msg = FakeMessage(
        id=601,
        author=_team_user(),
        channel=thread,
        guild=MagicMock(id=99),
        mentions=[],
        content="next",
    )
    msg.channel.type = "thread"
    await handler.handle(msg)
    assert captured["system_prompt"] == "SYS_TEXT"
    assert captured["history"] == history
    assert captured["user_message"] == "next"


async def test_rate_limited_caller_gets_one_reply_no_thread():
    """When the rate limiter rejects the user, post a one-line reply
    in the original channel and skip everything else."""
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=False)
    rl = MagicMock()
    rl.check_and_record = MagicMock(return_value=False)

    replies = []

    @dataclass
    class FakeReplyMessage:
        id: int
        author: FakeUser
        channel: FakeChannel
        guild: Any
        mentions: list
        content: str = ""

        async def reply(self, content: str) -> None:
            replies.append(content)

        async def create_thread(self, *, name: str):
            raise AssertionError("must not create thread when rate-limited")

    handler = OnMessageHandler(
        bot_user_id=_bot_user_id(),
        memory=memory,
        agent_fn=_stub_agent(["should-not-run"]),
        system_prompt_fn=lambda: "SYS",
        stream_writer_fn=_stream_writer,
        rate_limiter=rl,
        tool_registry=None,
        tool_context_factory=lambda _msg: None,
    )

    msg = FakeReplyMessage(
        id=900,
        author=_team_user(),
        channel=FakeChannel(id=10, type="text"),
        guild=MagicMock(id=99),
        mentions=[FakeUser(id=_bot_user_id(), bot=True)],
        content="@jarvis hi",
    )
    await handler.handle(msg)
    assert len(replies) == 1
    assert "rate" in replies[0].lower() or "limit" in replies[0].lower()
    memory.record_thread.assert_not_awaited()
    memory.append_turn.assert_not_awaited()


async def test_agent_fn_receives_tool_registry_and_context():
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=False)
    memory.get_turns = AsyncMock(return_value=[])

    captured = {}

    async def capture_agent(*, system_prompt, history, user_message, tool_registry, tool_context):
        captured["registry"] = tool_registry
        captured["context"] = tool_context
        yield "ok"

    sentinel_registry = object()
    sentinel_context = object()

    handler = OnMessageHandler(
        bot_user_id=_bot_user_id(),
        memory=memory,
        agent_fn=capture_agent,
        system_prompt_fn=lambda: "SYS",
        stream_writer_fn=_stream_writer,
        rate_limiter=None,
        tool_registry=sentinel_registry,
        tool_context_factory=lambda _msg: sentinel_context,
    )
    msg = FakeMessage(
        id=901,
        author=_team_user(),
        channel=FakeChannel(id=10, type="text"),
        guild=MagicMock(id=99),
        mentions=[FakeUser(id=_bot_user_id(), bot=True)],
        content="@jarvis hi",
    )
    await handler.handle(msg)
    assert captured["registry"] is sentinel_registry
    assert captured["context"] is sentinel_context
