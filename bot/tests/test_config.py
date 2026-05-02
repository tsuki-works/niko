"""Tests for jarvis.config.Settings."""

from __future__ import annotations

import pytest

from jarvis.config import Settings


def test_settings_load_required_fields(fake_env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # avoid picking up a repo .env
    s = Settings()
    assert s.discord_bot_token == "test-token"
    assert s.discord_guild_id == 1495086675523797032


def test_settings_defaults(fake_env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = Settings()
    assert s.anthropic_api_key is None
    assert s.jarvis_post_secret is None
    assert s.jarvis_http_port == 8080
    assert s.jarvis_log_level == "INFO"
    assert s.commit_sha == ""


def test_settings_overrides_via_env(fake_env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_HTTP_PORT", "9090")
    monkeypatch.setenv("JARVIS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("COMMIT_SHA", "abc1234")
    s = Settings()
    assert s.jarvis_http_port == 9090
    assert s.jarvis_log_level == "DEBUG"
    assert s.commit_sha == "abc1234"


def test_settings_missing_required_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_GUILD_ID", raising=False)
    with pytest.raises(Exception):  # pydantic.ValidationError; broad to avoid pinning the import path
        Settings()
