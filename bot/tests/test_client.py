"""Tests for jarvis.client.JarvisBot — construction + a non-crash on_ready check.

Faking discord.py's internal _connection state to fully exercise on_ready
in a unit test is brittle and not worth the maintenance cost. The real
verification of on_ready is the manual smoke gate in Task 7.3 against a
live dev guild. These tests cover what's tractable in pure unit form:
construction with the right intents, and that on_ready can be called
without raising when the standard discord.py properties are stubbed.
"""

from __future__ import annotations

import logging

from jarvis.client import JarvisBot


def test_jarvis_bot_constructs_with_message_intent():
    bot = JarvisBot(guild_id=123, on_message_handler=None)
    assert bot.guild_id == 123
    assert bot.intents.message_content is True
    assert bot.intents.guilds is True


async def test_on_ready_does_not_crash(monkeypatch, caplog):
    bot = JarvisBot(guild_id=123, on_message_handler=None)
    # Replace the properties that touch discord.py's internal _connection.
    monkeypatch.setattr(
        type(bot),
        "user",
        property(lambda self: "TestBot#0001"),
        raising=False,
    )

    class FakeGuild:
        id = 123
        name = "TestGuild"

    monkeypatch.setattr(
        type(bot),
        "guilds",
        property(lambda self: [FakeGuild()]),
        raising=False,
    )

    with caplog.at_level(logging.INFO, logger="jarvis.client"):
        await bot.on_ready()

    msgs = [r.getMessage() for r in caplog.records]
    assert any("ready" in m.lower() for m in msgs), msgs
    assert any("123" in m for m in msgs), msgs


async def test_on_message_delegates_to_handler(monkeypatch):
    from unittest.mock import AsyncMock

    handler = AsyncMock()
    handler.handle = AsyncMock()

    bot = JarvisBot(guild_id=123, on_message_handler=handler)
    fake_message = object()
    await bot.on_message(fake_message)
    handler.handle.assert_awaited_once_with(fake_message)
