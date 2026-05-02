"""Shared fixtures for the bot test suite."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    """Snapshot root logger state before each test and restore after.

    The bot's logging tests (and any future test that exercises modules
    using the root logger) mutate global state. Without this, ordering
    between test files becomes load-bearing — fail loudly here, not
    obscurely later.
    """
    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = list(root.handlers)
    try:
        yield
    finally:
        root.setLevel(saved_level)
        root.handlers = saved_handlers


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Install a minimal valid env for Settings()."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "1495086675523797032")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_POST_SECRET", raising=False)
    monkeypatch.delenv("JARVIS_HTTP_PORT", raising=False)
    monkeypatch.delenv("JARVIS_LOG_LEVEL", raising=False)
    monkeypatch.delenv("COMMIT_SHA", raising=False)
    yield
