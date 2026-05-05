"""`get_recent_messages` — read recent Discord channel history.

This is the first tool in PR 3a/3b that needs live Discord state, so
it sets `wants_context=True` and reads `context.guild` at dispatch
time. Channel allowlist (spec §9 — no DMs, no other servers) is
satisfied by construction: we only resolve channels via
`guild.text_channels` of the bot's own guild, so DMs and other-server
channels are unreachable.

Channel resolution accepts either a numeric ID string (e.g.
"1495192027913130074") or a channel name (e.g. "general" or
"#general", case-insensitive).
"""

from __future__ import annotations

from typing import Any, Optional

from jarvis.tools import ToolContext, ToolDescriptor

_MAX_MESSAGES = 100


def _clamp_n(n: int) -> int:
    if n < 1:
        return 1
    if n > _MAX_MESSAGES:
        return _MAX_MESSAGES
    return n


def _resolve_channel(guild: Any, channel: str) -> Optional[Any]:
    """Resolve a channel by numeric id or by case-insensitive name."""
    s = (channel or "").strip()
    if not s:
        return None
    if s.isdigit():
        return guild.get_channel(int(s))
    clean = s.lstrip("#").lower()
    for ch in getattr(guild, "text_channels", []):
        if getattr(ch, "name", "").lower() == clean:
            return ch
    return None


def build_get_recent_messages_tool() -> ToolDescriptor:
    async def get_recent_messages(channel: str, n: int = 50, *, context: ToolContext) -> Any:
        guild = context.guild
        if guild is None:
            return {"error": "no guild context — bot is not in a guild"}

        target = _resolve_channel(guild, channel)
        if target is None:
            return {
                "error": (f"channel '{channel}' not found in guild (use a #name or numeric id)")
            }

        clamped = _clamp_n(int(n))
        out: list[dict[str, Any]] = []
        async for msg in target.history(limit=clamped):
            author = getattr(msg, "author", None)
            display = getattr(author, "display_name", None) if author else None
            created = getattr(msg, "created_at", None)
            out.append(
                {
                    "author": display or "?",
                    "content": getattr(msg, "content", "") or "",
                    "timestamp": (created.isoformat() if created is not None else None),
                }
            )
        return out

    return ToolDescriptor(
        name="get_recent_messages",
        description=(
            "Read recent messages from a Discord text channel in the "
            "Tsuki Works guild. Pass `channel` as either a name "
            "('general', '#blockers') or a numeric channel id. "
            "Returns up to 100 messages newest-first as "
            "{author, content, timestamp}. Use this when the user "
            "asks 'what did the team say in #blockers?', 'summarize "
            "today's #ci-alerts', or to ground answers in recent chat."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": (
                        "Channel name (with or without leading '#') or numeric channel id."
                    ),
                },
                "n": {
                    "type": "integer",
                    "description": ("How many messages to fetch (1–100, default 50)."),
                },
            },
            "required": ["channel"],
        },
        fn=get_recent_messages,
        wants_context=True,
    )
