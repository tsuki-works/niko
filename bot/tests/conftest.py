"""Shared fixtures for the bot test suite."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


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
    # Block .env file resolution by chdir'ing to a fresh tmp dir.
    yield
