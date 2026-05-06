"""GitHub login → Discord user ID, plus mention() helper.

Centralizing the mapping here means kinds never hand-build `<@id>` strings
and the team-posts-tag-Meet rule lives in one place.

Add new mappings as teammates' GitHub logins are confirmed.
"""

from __future__ import annotations


GH_LOGIN_TO_DISCORD: dict[str, int] = {
    "MeetDigrajkar": 295016116881850370,
}


def mention(login: str | None) -> str:
    if not login:
        return "_(unassigned)_"
    uid = GH_LOGIN_TO_DISCORD.get(login)
    return f"<@{uid}>" if uid else f"`{login}`"
