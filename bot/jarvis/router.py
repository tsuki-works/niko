"""Routing decision for an incoming Discord message.

Three cases the bot cares about:
- MENTION_NEW_THREAD: the bot was @-mentioned in a top-level channel;
  the events handler should create a thread and reply there.
- IN_THREAD: the message arrived in a thread the bot has previously
  joined (recorded in memory); reply in place.
- IGNORE: everything else (other bots, unrelated channel chatter,
  threads we don't own).

The discord.py runtime types we depend on:
- `message.author.bot: bool`
- `message.channel.type` — for thread detection we check via the
  `is_thread` helper rather than string-matching the type name; the
  test uses a fake with .type == "thread".
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol


class RoutingDecision(str, Enum):
    IGNORE = "ignore"
    MENTION_NEW_THREAD = "mention_new_thread"
    IN_THREAD = "in_thread"


class _MemoryProto(Protocol):
    async def thread_exists(self, thread_id: str) -> bool: ...


def _is_thread_channel(channel: Any) -> bool:
    """True if `channel` is a Discord thread.

    We accept either:
      - discord.py's real Thread (has `.parent` and a numeric .type that
        equals discord.ChannelType.public_thread or .private_thread); or
      - a test fake with `.type == "thread"`.
    """
    type_str = str(getattr(channel, "type", "")).lower()
    return "thread" in type_str


async def classify_incoming(
    message: Any,
    *,
    bot_user_id: int,
    memory: _MemoryProto,
) -> RoutingDecision:
    if getattr(message.author, "bot", False):
        return RoutingDecision.IGNORE

    if _is_thread_channel(message.channel):
        if await memory.thread_exists(str(message.channel.id)):
            return RoutingDecision.IN_THREAD
        return RoutingDecision.IGNORE

    # Top-level channel — only respond on @-mention.
    mention_ids = {getattr(u, "id", None) for u in (message.mentions or [])}
    if bot_user_id in mention_ids:
        return RoutingDecision.MENTION_NEW_THREAD

    return RoutingDecision.IGNORE
