"""Discord gateway client for the Jarvis bot.

Subclass of discord.Client. The on_message hook delegates to a
constructor-injected OnMessageHandler so tests don't need a live
Anthropic / Firestore wiring to exercise the bot's event surface.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import discord

logger = logging.getLogger(__name__)


class JarvisBot(discord.Client):
    def __init__(
        self,
        *,
        guild_id: int,
        on_message_handler: Optional[Any],
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        super().__init__(intents=intents)
        self.guild_id = guild_id
        self._on_message_handler = on_message_handler

    async def on_ready(self) -> None:
        user = self.user
        guild_names = ", ".join(f"{g.name}({g.id})" for g in self.guilds)
        logger.info(
            "jarvis ready: user=%s guilds=[%s] expected_guild_id=%d",
            user,
            guild_names,
            self.guild_id,
        )

    async def on_message(self, message: Any) -> None:
        if self._on_message_handler is None:
            return  # PR 1 / test path — no handler wired
        await self._on_message_handler.handle(message)
