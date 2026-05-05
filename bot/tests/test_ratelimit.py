"""Tests for jarvis.ratelimit.InMemoryRateLimiter."""

from __future__ import annotations

import pytest
from jarvis.ratelimit import InMemoryRateLimiter


def test_first_call_is_allowed():
    rl = InMemoryRateLimiter(max_per_window=3, window_seconds=60.0)
    assert rl.check_and_record(user_id=1) is True


def test_per_user_isolation():
    rl = InMemoryRateLimiter(max_per_window=2, window_seconds=60.0)
    assert rl.check_and_record(user_id=1) is True
    assert rl.check_and_record(user_id=1) is True
    assert rl.check_and_record(user_id=2) is True
    # User 1 hits the limit on third try; user 2 still has room.
    assert rl.check_and_record(user_id=1) is False
    assert rl.check_and_record(user_id=2) is True


def test_limit_blocks_after_max():
    rl = InMemoryRateLimiter(max_per_window=3, window_seconds=60.0)
    for _ in range(3):
        assert rl.check_and_record(user_id=1) is True
    assert rl.check_and_record(user_id=1) is False
    assert rl.check_and_record(user_id=1) is False


def test_old_entries_drop_when_window_passes():
    """Inject a clock so we can travel forward without sleeping."""
    now = [0.0]
    rl = InMemoryRateLimiter(max_per_window=2, window_seconds=10.0, clock=lambda: now[0])
    assert rl.check_and_record(user_id=1) is True
    assert rl.check_and_record(user_id=1) is True
    assert rl.check_and_record(user_id=1) is False  # at limit
    now[0] += 11.0  # past the window
    assert rl.check_and_record(user_id=1) is True


def test_default_clock_is_monotonic_safe(monkeypatch):
    """A real call should not blow up — minimal smoke check on the default clock."""
    rl = InMemoryRateLimiter(max_per_window=1, window_seconds=60.0)
    assert rl.check_and_record(user_id=1) is True
    assert rl.check_and_record(user_id=1) is False
