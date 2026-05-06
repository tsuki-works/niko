"""Static alias → Discord channel ID map for the jobs framework.

Names can change; IDs are stable. Keeping a static dict (vs a name lookup)
means `validate_manifest()` can verify every job's target at boot, so a
typo crashes the bot at startup rather than at 9am.
"""

from __future__ import annotations

from typing import Any

CHANNEL_IDS: dict[str, int] = {
    "#jarvis":             1500002427389087787,
    "#code-review":        1495194166886400021,
    "#ci-alerts":          1495194041246285857,
    "#blockers":           1495192657545396354,
    "#weekly-sync":        1499827602397859961,
    "#milestones-updates": 1495607520444551278,
    "#decisions-log":      1495192153947766885,
    "#general":            1495192027913130074,
    "#infra":              1495193915362508911,
    "#backend":            1495193663628640256,
    "#frontend":           1495193789592113156,
    "#demos":              1499827733302349844,
}


class UnknownChannelError(LookupError):
    pass


def resolve(client: Any, alias: str):
    if alias not in CHANNEL_IDS:
        raise UnknownChannelError(f"unknown channel alias: {alias}")
    cid = CHANNEL_IDS[alias]
    ch = client.get_channel(cid)
    if ch is None:
        raise UnknownChannelError(
            f"channel {alias} ({cid}) not in cache — bot not in guild?"
        )
    return ch
