from __future__ import annotations

import pytest

from jarvis.jobs.channels import CHANNEL_IDS, UnknownChannelError, resolve


class _FakeClient:
    def __init__(self, mapping: dict[int, object] | None = None):
        self._mapping = mapping or {}

    def get_channel(self, cid: int):
        return self._mapping.get(cid)


def test_known_aliases_present():
    for alias in (
        "#jarvis",
        "#code-review",
        "#blockers",
        "#weekly-sync",
        "#milestones-updates",
    ):
        assert alias in CHANNEL_IDS


def test_resolve_returns_channel_when_in_cache():
    sentinel = object()
    client = _FakeClient({CHANNEL_IDS["#jarvis"]: sentinel})
    assert resolve(client, "#jarvis") is sentinel


def test_resolve_unknown_alias_raises():
    with pytest.raises(UnknownChannelError):
        resolve(_FakeClient(), "#does-not-exist")


def test_resolve_uncached_channel_raises():
    with pytest.raises(UnknownChannelError) as exc:
        resolve(_FakeClient(), "#jarvis")
    assert "not in cache" in str(exc.value)
