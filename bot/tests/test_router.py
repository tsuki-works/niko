"""Tests for jarvis.router.classify_incoming."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from jarvis.router import RoutingDecision, classify_incoming


@dataclass
class FakeUser:
    id: int
    bot: bool = False


@dataclass
class FakeChannel:
    id: int
    type: str  # "text" | "thread"


@dataclass
class FakeGuild:
    id: int


@dataclass
class FakeMessage:
    id: int
    author: FakeUser
    channel: FakeChannel
    guild: FakeGuild
    mentions: list[FakeUser]
    content: str = ""


def _bot_user() -> FakeUser:
    return FakeUser(id=42, bot=True)


def _team_user() -> FakeUser:
    return FakeUser(id=1001, bot=False)


async def test_ignores_messages_from_bots():
    msg = FakeMessage(
        id=1,
        author=_bot_user(),  # author is a bot
        channel=FakeChannel(id=10, type="text"),
        guild=FakeGuild(id=99),
        mentions=[],
    )
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=False)
    decision = await classify_incoming(msg, bot_user_id=42, memory=memory)
    assert decision == RoutingDecision.IGNORE


async def test_ignores_messages_with_no_mention_in_channel():
    msg = FakeMessage(
        id=2,
        author=_team_user(),
        channel=FakeChannel(id=10, type="text"),
        guild=FakeGuild(id=99),
        mentions=[],
    )
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=False)
    decision = await classify_incoming(msg, bot_user_id=42, memory=memory)
    assert decision == RoutingDecision.IGNORE


async def test_responds_when_mentioned_in_channel():
    msg = FakeMessage(
        id=3,
        author=_team_user(),
        channel=FakeChannel(id=10, type="text"),
        guild=FakeGuild(id=99),
        mentions=[_bot_user()],
    )
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=False)
    decision = await classify_incoming(msg, bot_user_id=42, memory=memory)
    assert decision == RoutingDecision.MENTION_NEW_THREAD


async def test_responds_in_existing_jarvis_thread():
    msg = FakeMessage(
        id=4,
        author=_team_user(),
        channel=FakeChannel(id=20, type="thread"),
        guild=FakeGuild(id=99),
        mentions=[],  # no mention required inside a thread
    )
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=True)
    decision = await classify_incoming(msg, bot_user_id=42, memory=memory)
    assert decision == RoutingDecision.IN_THREAD
    memory.thread_exists.assert_awaited_once_with("20")


async def test_ignores_thread_message_when_thread_not_jarvis_owned():
    msg = FakeMessage(
        id=5,
        author=_team_user(),
        channel=FakeChannel(id=21, type="thread"),
        guild=FakeGuild(id=99),
        mentions=[],
    )
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=False)
    decision = await classify_incoming(msg, bot_user_id=42, memory=memory)
    assert decision == RoutingDecision.IGNORE


async def test_mention_inside_jarvis_thread_still_in_thread():
    msg = FakeMessage(
        id=6,
        author=_team_user(),
        channel=FakeChannel(id=22, type="thread"),
        guild=FakeGuild(id=99),
        mentions=[_bot_user()],
    )
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=True)
    decision = await classify_incoming(msg, bot_user_id=42, memory=memory)
    # Inside an owned thread the routing is IN_THREAD whether or not
    # the user @'d again.
    assert decision == RoutingDecision.IN_THREAD
