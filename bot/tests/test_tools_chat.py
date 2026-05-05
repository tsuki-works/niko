"""Tests for jarvis.tools.chat.build_get_recent_messages_tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from jarvis.tools import ToolContext
from jarvis.tools.chat import build_get_recent_messages_tool


@dataclass
class FakeAuthor:
    display_name: str = "Meet"


@dataclass
class FakeMessage:
    content: str
    author: FakeAuthor = field(default_factory=FakeAuthor)
    created_at: datetime = field(
        default_factory=lambda: datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    )


class FakeTextChannel:
    def __init__(self, channel_id: int, name: str, messages: list[FakeMessage]):
        self.id = channel_id
        self.name = name
        self._messages = messages

    def history(self, limit: int = 50):
        # discord.py's history returns an async iterator yielding
        # newest-first. Our fake honors the limit.
        msgs = self._messages[:limit]

        async def _iter():
            for m in msgs:
                yield m

        return _iter()


@dataclass
class FakeGuild:
    text_channels: list[FakeTextChannel]
    by_id: dict[int, FakeTextChannel] = field(default_factory=dict)

    def __post_init__(self):
        self.by_id = {c.id: c for c in self.text_channels}

    def get_channel(self, channel_id: int) -> Optional[FakeTextChannel]:
        return self.by_id.get(channel_id)


def _ctx_with_guild(guild: Optional[FakeGuild]) -> ToolContext:
    return ToolContext(
        guild=guild,
        github_client=None,
        github_repo="o/r",
        github_project_id="PVT_x",
        docs_root=None,
    )


async def test_resolves_channel_by_name_and_returns_messages():
    msgs = [
        FakeMessage(content="hello"),
        FakeMessage(content="world"),
    ]
    chan = FakeTextChannel(channel_id=10, name="general", messages=msgs)
    guild = FakeGuild(text_channels=[chan])
    desc = build_get_recent_messages_tool()
    ctx = _ctx_with_guild(guild)
    out = await desc.fn(channel="general", n=10, context=ctx)
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0]["content"] == "hello"
    assert out[0]["author"] == "Meet"
    assert "T" in out[0]["timestamp"]  # ISO format


async def test_resolves_channel_with_hash_prefix():
    chan = FakeTextChannel(channel_id=11, name="blockers", messages=[FakeMessage(content="x")])
    guild = FakeGuild(text_channels=[chan])
    desc = build_get_recent_messages_tool()
    out = await desc.fn(channel="#blockers", n=5, context=_ctx_with_guild(guild))
    assert len(out) == 1


async def test_resolves_channel_by_numeric_id():
    chan = FakeTextChannel(channel_id=99, name="alerts", messages=[FakeMessage(content="a")])
    guild = FakeGuild(text_channels=[chan])
    desc = build_get_recent_messages_tool()
    out = await desc.fn(channel="99", n=5, context=_ctx_with_guild(guild))
    assert len(out) == 1


async def test_returns_error_when_no_guild():
    desc = build_get_recent_messages_tool()
    out = await desc.fn(channel="anything", n=5, context=_ctx_with_guild(None))
    assert "error" in out


async def test_returns_error_when_channel_not_found():
    chan = FakeTextChannel(channel_id=10, name="general", messages=[FakeMessage(content="x")])
    guild = FakeGuild(text_channels=[chan])
    desc = build_get_recent_messages_tool()
    out = await desc.fn(channel="ghost", n=5, context=_ctx_with_guild(guild))
    assert "error" in out
    assert "ghost" in out["error"]


async def test_clamps_n_to_safe_range():
    msgs = [FakeMessage(content=str(i)) for i in range(200)]
    chan = FakeTextChannel(channel_id=10, name="general", messages=msgs)
    guild = FakeGuild(text_channels=[chan])
    desc = build_get_recent_messages_tool()
    # n=10000 should clamp to 100 (max)
    out_max = await desc.fn(channel="general", n=10000, context=_ctx_with_guild(guild))
    assert len(out_max) == 100
    # n=0 should clamp to 1
    out_min = await desc.fn(channel="general", n=0, context=_ctx_with_guild(guild))
    assert len(out_min) == 1


async def test_descriptor_metadata():
    desc = build_get_recent_messages_tool()
    assert desc.name == "get_recent_messages"
    assert "discord" in desc.description.lower() or "channel" in desc.description.lower()
    assert desc.input_schema["properties"]["channel"]["type"] == "string"
    assert "n" in desc.input_schema["properties"]
    assert desc.input_schema.get("required") == ["channel"]
    assert desc.wants_context is True  # this tool needs the ToolContext
