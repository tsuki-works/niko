"""Tests for jarvis.main — wiring of gateway + HTTP."""

from __future__ import annotations

import asyncio

import pytest
from jarvis import main as main_mod


async def test_main_runs_both_subsystems_and_returns_when_one_finishes(monkeypatch):
    started = {"client": False, "http": False}

    class FakeClient:
        async def start(self, token: str) -> None:
            started["client"] = True
            # Simulate gateway running for a moment, then exiting cleanly.
            await asyncio.sleep(0.05)

        async def close(self) -> None:
            pass

    async def fake_serve_http(app, port: int) -> None:
        started["http"] = True
        # Run "forever" until cancelled.
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return

    fake_settings = type(
        "S",
        (),
        {
            "discord_bot_token": "tok",
            "discord_guild_id": 1,
            "jarvis_http_port": 8080,
            "jarvis_log_level": "INFO",
            "commit_sha": "deadbeef",
            "anthropic_api_key": "ak",
            "gcp_project_id": None,
        },
    )()

    monkeypatch.setattr(main_mod, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(main_mod, "_build_handler", lambda settings, **kw: object())
    monkeypatch.setattr(
        main_mod, "_build_clients", lambda settings: (object(), object(), None)
    )
    monkeypatch.setattr(
        main_mod,
        "JarvisBot",
        lambda *, guild_id, on_message_handler: FakeClient(),
    )
    monkeypatch.setattr(main_mod, "serve_http", fake_serve_http)

    await asyncio.wait_for(main_mod.run(), timeout=2.0)
    assert started["client"] is True
    assert started["http"] is True


async def test_main_cancels_http_when_gateway_raises(monkeypatch):
    http_cancelled = {"value": False}

    class ExplodingClient:
        async def start(self, token: str) -> None:
            await asyncio.sleep(0.01)
            raise RuntimeError("gateway lost")

        async def close(self) -> None:
            pass

    async def fake_serve_http(app, port: int) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            http_cancelled["value"] = True
            raise

    fake_settings = type(
        "S",
        (),
        {
            "discord_bot_token": "tok",
            "discord_guild_id": 1,
            "jarvis_http_port": 8080,
            "jarvis_log_level": "INFO",
            "commit_sha": "",
            "anthropic_api_key": "ak",
            "gcp_project_id": None,
        },
    )()

    monkeypatch.setattr(main_mod, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(main_mod, "_build_handler", lambda settings, **kw: object())
    monkeypatch.setattr(
        main_mod, "_build_clients", lambda settings: (object(), object(), None)
    )
    monkeypatch.setattr(
        main_mod,
        "JarvisBot",
        lambda *, guild_id, on_message_handler: ExplodingClient(),
    )
    monkeypatch.setattr(main_mod, "serve_http", fake_serve_http)

    with pytest.raises(RuntimeError, match="gateway lost"):
        await asyncio.wait_for(main_mod.run(), timeout=2.0)
    assert http_cancelled["value"] is True


async def test_run_constructs_full_dep_graph(monkeypatch):
    """run() should build memory, agent, stream writer, handler and pass
    the handler into JarvisBot."""
    captured = {}

    class FakeClient:
        async def start(self, token):
            await asyncio.sleep(0.01)

        async def close(self):
            pass

    async def fake_serve_http(app, port):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return

    fake_settings = type(
        "S",
        (),
        {
            "discord_bot_token": "tok",
            "discord_guild_id": 1,
            "jarvis_http_port": 8080,
            "jarvis_log_level": "INFO",
            "commit_sha": "",
            "anthropic_api_key": "ak",
            "gcp_project_id": None,
            "github_token": "ghp_x",
            "github_repo": "tsuki-works/niko",
            "github_project_id": "PVT_x",
        },
    )()

    monkeypatch.setattr(main_mod, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(main_mod, "serve_http", fake_serve_http)

    def fake_jarvis_bot(*, guild_id, on_message_handler):
        captured["on_message_handler"] = on_message_handler
        return FakeClient()

    monkeypatch.setattr(main_mod, "JarvisBot", fake_jarvis_bot)
    monkeypatch.setattr(main_mod, "AsyncAnthropic", lambda **kw: object())
    monkeypatch.setattr(main_mod, "AsyncFirestoreClient", lambda **kw: object())
    monkeypatch.setattr(main_mod, "AsyncGitHubClient", lambda **kw: object())

    await asyncio.wait_for(main_mod.run(), timeout=2.0)
    assert captured["on_message_handler"] is not None


def test_main_imports_jobs_subsystem_without_error():
    """Importing jarvis.main should populate the kind registry."""
    import jarvis.main  # noqa: F401
    from jarvis.jobs.kinds import KIND_REGISTRY

    assert "pr_review_nudge" in KIND_REGISTRY
    assert "digest_via_agent" in KIND_REGISTRY
    assert "stuck_in_progress" in KIND_REGISTRY
