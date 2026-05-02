"""Discord gateway client for the Jarvis bot.

Subclass of discord.Client. PR 1 only logs ready and stores the guild
ID. PR 2 attaches an on_message handler; PR 4 registers app commands.
Construction is side-effect-free — no network — so unit tests can
exercise it without a live token.
"""

from __future__ import annotations

import logging

import discord

logger = logging.getLogger(__name__)


class JarvisBot(discord.Client):
    def __init__(self, *, guild_id: int) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # PR 2 needs this for @-mentions
        intents.guilds = True
        super().__init__(intents=intents)
        self.guild_id = guild_id

    async def on_ready(self) -> None:
        user = self.user
        guild_names = ", ".join(f"{g.name}({g.id})" for g in self.guilds)
        logger.info(
            "jarvis ready: user=%s guilds=[%s] expected_guild_id=%d",
            user,
            guild_names,
            self.guild_id,
        )
