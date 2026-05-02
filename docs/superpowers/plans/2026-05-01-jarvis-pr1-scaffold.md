# Jarvis 2.0 — PR 1: Bot Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land a `bot/` Python package whose entrypoint connects to the Discord gateway, comes online in the Tsuki Works guild, and concurrently serves a FastAPI `/healthz` endpoint. No conversational behavior yet — just proof of life.

**Architecture:** Single Python process. `discord.py` 2.x holds the gateway websocket; an embedded FastAPI app served by `uvicorn` lives on the same event loop via `asyncio.gather`. Config comes from env / `.env` (same `pydantic-settings` pattern as `app/config.py`). All deps isolated under `bot/requirements*.txt` (matches existing repo convention; deviates from §3 of the spec which had said `pyproject.toml` — calling that out explicitly so reviewers know it's intentional).

**Tech Stack:** Python 3.12, `discord.py` 2.x, FastAPI, uvicorn, pydantic-settings, pytest + pytest-asyncio.

**Out of scope (later PRs):** any LLM call, slash commands, agent loop, tools, GCE deploy, MCP shim, Firestore. This PR's bot just connects and answers `/healthz`.

**Spec reference:** `docs/superpowers/specs/2026-05-01-jarvis-bot-design.md` §4.1 (modules), §12 (rollout PR #1).

---

## File Structure

**Created in this PR:**

```
bot/
├── README.md                       # local dev instructions
├── requirements.txt                # runtime deps (discord.py, fastapi, uvicorn, pydantic-settings, anthropic — added now to keep one source of truth though unused this PR)
├── requirements-dev.txt            # pytest, pytest-asyncio, pytest-mock
├── jarvis/
│   ├── __init__.py
│   ├── config.py                   # Settings(BaseSettings) — discord_token, guild_id, anthropic_api_key, post_secret, log_level, http_port
│   ├── logging_setup.py            # configure_logging(level: str) — stdlib logging w/ JSON-ish format
│   ├── client.py                   # class JarvisBot(discord.Client) — on_ready logger
│   ├── http/
│   │   ├── __init__.py
│   │   └── app.py                  # FastAPI app w/ /healthz returning {status, commit_sha, started_at}
│   └── main.py                     # asyncio entrypoint; runs gateway + uvicorn together
└── tests/
    ├── __init__.py
    ├── conftest.py                 # fake_settings fixture, freezes datetime
    ├── test_config.py              # env loading + defaults + missing-required-field error
    ├── test_logging_setup.py       # configures root logger correctly
    ├── test_http_app.py            # /healthz returns 200 + correct shape
    ├── test_client.py              # JarvisBot constructs; on_ready logs without exploding
    └── test_main.py                # main() wires both subsystems; cancellation propagates
```

**Modified in this PR:**

- `pytest.ini` (root) — add `bot/tests` to testpaths so the existing test runner picks it up.
- `.env.example` — add the new env vars the bot reads, with placeholder values.
- `.gitignore` — confirm `bot/.env` is covered (the existing `.env` rule covers it; verify in step 0.3).

**NOT modified in this PR:**

- `requirements.txt` (root) — bot deps are isolated under `bot/`. No backend impact.
- `Dockerfile` (root) — stays scoped to the FastAPI backend. Bot Dockerfile is PR 5 (deploy).
- `CLAUDE.md` — no doc update yet; that lands in PR 6 when Jarvis-the-MCP is retired.

---

## Conventions (read once, apply throughout)

- **Imports:** absolute, e.g. `from jarvis.config import Settings`. Tests run with `bot/` on `PYTHONPATH` (via the root `pytest.ini` change in Task 0).
- **Async:** the codebase uses `asyncio_mode = auto` (root `pytest.ini`). Test functions are plain `async def` with no `@pytest.mark.asyncio`.
- **Settings:** mirror the pattern in `app/config.py`. Use `pydantic_settings.BaseSettings` with `SettingsConfigDict(env_file=".env", extra="ignore")`. Required fields are typed without defaults so missing env raises at instantiation; optional fields default to `None` or a literal.
- **Logging:** use the stdlib `logging` module. The bot's `configure_logging` sets the root level and a single `StreamHandler` with format `%(asctime)s %(levelname)s %(name)s %(message)s`. JSON logging is a future hardening item, not v1.
- **Commits:** one commit per task, message style matches the repo (`feat(bot): …`, `test(bot): …`, `chore(bot): …`). Co-author trailer kept when pair-programming with Claude.

---

## Task 0: Repo plumbing

**Files:**
- Create: `bot/`, `bot/jarvis/`, `bot/jarvis/http/`, `bot/tests/`
- Create: `bot/jarvis/__init__.py` (empty), `bot/jarvis/http/__init__.py` (empty), `bot/tests/__init__.py` (empty)
- Create: `bot/requirements.txt`, `bot/requirements-dev.txt`
- Modify: `pytest.ini` (root)
- Modify: `.env.example` (root)

- [ ] **Step 0.1: Create the directory tree and empty `__init__.py` files**

```bash
mkdir -p bot/jarvis/http bot/tests
touch bot/jarvis/__init__.py bot/jarvis/http/__init__.py bot/tests/__init__.py
```

- [ ] **Step 0.2: Write `bot/requirements.txt`**

Content (verbatim):

```
discord.py>=2.4,<3.0
fastapi==0.115.0
uvicorn[standard]==0.32.0
pydantic-settings>=2.0,<3.0
anthropic>=0.40,<1.0
httpx>=0.27,<1.0
```

Pin reasoning:
- `discord.py>=2.4` — the line that added stable application-command (slash) support; PR 4 will lean on it.
- `fastapi`/`uvicorn` versions match the root `requirements.txt` so we run a single FastAPI version across the repo.
- `anthropic` listed now (unused in PR 1) so PR 2/3 don't redo this dance.
- `httpx` for the test client and for HTTP calls to GitHub later; pinned to match root.

- [ ] **Step 0.3: Write `bot/requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0,<9.0
pytest-asyncio>=0.24,<1.0
pytest-mock>=3.12,<4.0
```

Verify `.env` is gitignored (covers `bot/.env` too):

```bash
grep -n '^\.env$' .gitignore
```

Expected: a line `.env` in the file. If missing, add it; otherwise leave alone.

- [ ] **Step 0.4: Update root `pytest.ini` to discover bot tests**

Read the current file:

```bash
cat pytest.ini
```

Then replace it with:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests bot/tests
markers =
    live_llm: hits the live Anthropic API; opt-in via `pytest -m live_llm`. Costs credits.
    live_discord: hits the live Discord gateway; opt-in via `pytest -m live_discord`. Requires a dev bot token.
```

The added `testpaths` line tells pytest where to look so `pytest` from the repo root collects both backend and bot tests in one run. The new `live_discord` marker reserves the convention for later PRs (PR 2+) but is a no-op now.

- [ ] **Step 0.5: Update `.env.example` with the bot's env vars**

Read it first:

```bash
cat .env.example
```

Append (do not duplicate keys that already exist; only add the ones below if absent):

```
# --- Jarvis bot (bot/) ---
# Discord bot token (Secret Manager: jarvis-discord-token in prod). Required.
DISCORD_BOT_TOKEN=

# Tsuki Works guild ID. Required.
DISCORD_GUILD_ID=1495086675523797032

# Shared secret for the future POST /post HTTP endpoint (PR 6). Optional in PR 1.
JARVIS_POST_SECRET=

# Bot's HTTP port for /healthz. Default 8080.
JARVIS_HTTP_PORT=8080

# Log level: DEBUG, INFO, WARNING, ERROR. Default INFO.
JARVIS_LOG_LEVEL=INFO
```

`ANTHROPIC_API_KEY` is already in `.env.example` (used by `app/`); the bot reuses it, no duplicate entry.

- [ ] **Step 0.6: Install bot deps locally and verify pytest collects zero tests cleanly**

```bash
.venv/Scripts/python -m pip install -r bot/requirements-dev.txt
.venv/Scripts/python -m pytest bot/tests --collect-only
```

Expected: exit code 0, output mentions `0 tests collected`. (No tests yet; we just want pytest to find and parse the empty package.) If you see `ImportError` for `bot/`, the directory layout is wrong — fix before continuing.

- [ ] **Step 0.7: Commit**

```bash
git add bot/ pytest.ini .env.example
git commit -m "chore(bot): scaffold bot/ package + pytest discovery

Adds bot/jarvis/, bot/jarvis/http/, bot/tests/ with empty __init__.py
files, plus bot/requirements*.txt pinning discord.py, FastAPI, anthropic,
and pytest. Updates root pytest.ini with testpaths and reserves the
live_discord marker for later PRs. Adds bot env vars to .env.example.

No runtime behavior; pure plumbing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 1: `bot/jarvis/config.py` — typed settings

**Files:**
- Create: `bot/jarvis/config.py`
- Test: `bot/tests/test_config.py`
- Test: `bot/tests/conftest.py`

Settings shape (locked here; later tasks reference these field names):

| Field | Type | Required | Default |
|---|---|---|---|
| `discord_bot_token` | `str` | yes | — |
| `discord_guild_id` | `int` | yes | — |
| `anthropic_api_key` | `Optional[str]` | no (used in PR 2) | `None` |
| `jarvis_post_secret` | `Optional[str]` | no (used in PR 6) | `None` |
| `jarvis_http_port` | `int` | no | `8080` |
| `jarvis_log_level` | `str` | no | `"INFO"` |
| `commit_sha` | `str` | no | `""` |

- [ ] **Step 1.1: Write `bot/tests/conftest.py`**

```python
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
```

- [ ] **Step 1.2: Write the failing test for `Settings`**

`bot/tests/test_config.py`:

```python
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
```

- [ ] **Step 1.3: Run the test to confirm it fails**

```bash
.venv/Scripts/python -m pytest bot/tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'jarvis.config'` or similar.

- [ ] **Step 1.4: Write the minimal `bot/jarvis/config.py`**

```python
"""Runtime settings for the Jarvis bot.

Mirrors the pattern used by `app/config.py`: pydantic-settings reading
from environment variables (and optionally a .env file), with required
fields typed without defaults so a missing env var fails loudly at
construction. Optional fields used only by later PRs (anthropic_api_key,
jarvis_post_secret) default to None so importing this module never
crashes a PR-1-only install.
"""

from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    discord_bot_token: str
    discord_guild_id: int

    anthropic_api_key: Optional[str] = None
    jarvis_post_secret: Optional[str] = None
    jarvis_http_port: int = 8080
    jarvis_log_level: str = "INFO"

    commit_sha: str = ""


def get_settings() -> Settings:
    """Single accessor — useful for tests that want to monkeypatch."""
    return Settings()
```

- [ ] **Step 1.5: Run the tests to verify they pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_config.py -v
```

Expected: 4 passed.

- [ ] **Step 1.6: Commit**

```bash
git add bot/jarvis/config.py bot/tests/conftest.py bot/tests/test_config.py
git commit -m "feat(bot): typed Settings loader

Mirrors app/config.py: discord_bot_token + discord_guild_id required,
anthropic_api_key + jarvis_post_secret optional (used in later PRs),
http_port / log_level / commit_sha with safe defaults.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `bot/jarvis/logging_setup.py`

**Files:**
- Create: `bot/jarvis/logging_setup.py`
- Test: `bot/tests/test_logging_setup.py`

- [ ] **Step 2.1: Write the failing test**

`bot/tests/test_logging_setup.py`:

```python
"""Tests for jarvis.logging_setup."""

from __future__ import annotations

import logging

from jarvis.logging_setup import configure_logging


def test_configure_logging_sets_root_level():
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_idempotent():
    configure_logging("INFO")
    handlers_before = list(logging.getLogger().handlers)
    configure_logging("INFO")
    handlers_after = list(logging.getLogger().handlers)
    # Should not duplicate handlers on repeat invocation.
    assert len(handlers_after) == len(handlers_before)


def test_configure_logging_invalid_level_falls_back_to_info(caplog):
    configure_logging("NOT_A_LEVEL")
    assert logging.getLogger().level == logging.INFO
```

- [ ] **Step 2.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_logging_setup.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 2.3: Implement `bot/jarvis/logging_setup.py`**

```python
"""Bot logging configuration.

A single function that configures the root logger. Designed to be safe
to call more than once (handler dedup) so test ordering doesn't matter.
JSON logging is intentionally deferred until we ship to GCE and start
ingesting via Cloud Logging — at that point a structured formatter
gets wired up here without changing any callers.
"""

from __future__ import annotations

import logging

_HANDLER_TAG = "_jarvis_stream_handler"


def configure_logging(level: str = "INFO") -> None:
    resolved = getattr(logging, level.upper(), None)
    if not isinstance(resolved, int):
        resolved = logging.INFO

    root = logging.getLogger()
    root.setLevel(resolved)

    has_ours = any(getattr(h, _HANDLER_TAG, False) for h in root.handlers)
    if not has_ours:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)
```

- [ ] **Step 2.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_logging_setup.py -v
```

Expected: 3 passed.

- [ ] **Step 2.5: Commit**

```bash
git add bot/jarvis/logging_setup.py bot/tests/test_logging_setup.py
git commit -m "feat(bot): idempotent logging setup

configure_logging(level) sets root level + a single stream handler.
Safe to call repeatedly; falls back to INFO on unknown levels.
JSON formatter deferred to deploy PR.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `bot/jarvis/http/app.py` — `/healthz`

**Files:**
- Create: `bot/jarvis/http/app.py`
- Test: `bot/tests/test_http_app.py`

- [ ] **Step 3.1: Write the failing test**

`bot/tests/test_http_app.py`:

```python
"""Tests for jarvis.http.app — the FastAPI /healthz surface."""

from __future__ import annotations

from fastapi.testclient import TestClient

from jarvis.http.app import build_app


def test_healthz_returns_ok():
    app = build_app(commit_sha="abc1234")
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["commit_sha"] == "abc1234"
    assert isinstance(body["started_at"], str)
    assert len(body["started_at"]) > 0


def test_healthz_unknown_route_404():
    app = build_app(commit_sha="")
    client = TestClient(app)
    r = client.get("/does-not-exist")
    assert r.status_code == 404
```

- [ ] **Step 3.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_http_app.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3.3: Implement `bot/jarvis/http/app.py`**

```python
"""FastAPI surface co-located with the Discord gateway client.

Exposes /healthz for uptime checks. POST /post is added in PR 6 when
the custom MCP shim lands. build_app(commit_sha=...) is a factory so
tests can inject a known SHA without touching env vars.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI


def build_app(commit_sha: str) -> FastAPI:
    started_at = datetime.now(timezone.utc).isoformat()
    app = FastAPI(title="jarvis", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "commit_sha": commit_sha,
            "started_at": started_at,
        }

    return app
```

- [ ] **Step 3.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_http_app.py -v
```

Expected: 2 passed.

- [ ] **Step 3.5: Commit**

```bash
git add bot/jarvis/http/app.py bot/tests/test_http_app.py
git commit -m "feat(bot): /healthz endpoint via build_app(commit_sha)

Factory returns a FastAPI app exposing GET /healthz with status,
commit_sha, and started_at. docs_url/redoc_url disabled — no
public schema surface. POST /post comes in PR 6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `bot/jarvis/client.py` — `JarvisBot`

**Files:**
- Create: `bot/jarvis/client.py`
- Test: `bot/tests/test_client.py`

We do NOT connect to the gateway in tests. We construct the client and assert intents/state. Live-gateway smoke is a manual gate noted in spec §13.

- [ ] **Step 4.1: Write the failing test**

`bot/tests/test_client.py`:

```python
"""Tests for jarvis.client.JarvisBot — construction + a non-crash on_ready check.

Faking discord.py's internal _connection state to fully exercise on_ready
in a unit test is brittle and not worth the maintenance cost. The real
verification of on_ready is the manual smoke gate in Task 7.3 against a
live dev guild. These tests cover what's tractable in pure unit form:
construction with the right intents, and that on_ready can be called
without raising when the standard discord.py properties are stubbed.
"""

from __future__ import annotations

import logging

from jarvis.client import JarvisBot


def test_jarvis_bot_constructs_with_message_intent():
    bot = JarvisBot(guild_id=123)
    assert bot.guild_id == 123
    # Must have message_content intent for PR 2 (@-mention path).
    assert bot.intents.message_content is True
    assert bot.intents.guilds is True


async def test_on_ready_does_not_crash(monkeypatch, caplog):
    bot = JarvisBot(guild_id=123)
    # Replace the properties that touch discord.py's internal _connection.
    monkeypatch.setattr(
        type(bot),
        "user",
        property(lambda self: "TestBot#0001"),
        raising=False,
    )

    class FakeGuild:
        id = 123
        name = "TestGuild"

    monkeypatch.setattr(
        type(bot),
        "guilds",
        property(lambda self: [FakeGuild()]),
        raising=False,
    )

    with caplog.at_level(logging.INFO, logger="jarvis.client"):
        await bot.on_ready()

    msgs = [r.getMessage() for r in caplog.records]
    assert any("ready" in m.lower() for m in msgs), msgs
    assert any("123" in m for m in msgs), msgs
```

- [ ] **Step 4.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_client.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4.3: Implement `bot/jarvis/client.py`**

```python
"""Discord gateway client for the Jarvis bot.

Subclass of discord.Client. PR 1 only logs ready and stores the guild
ID. PR 2 attaches an on_message handler; PR 4 registers app commands.
Construction is side-effect-free — no network — so unit tests can
exercise it without a live token.
"""

from __future__ import annotations

import logging

import discord

logger = logging.getLogger(__name__)


class JarvisBot(discord.Client):
    def __init__(self, *, guild_id: int) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # PR 2 needs this for @-mentions
        intents.guilds = True
        super().__init__(intents=intents)
        self.guild_id = guild_id

    async def on_ready(self) -> None:
        user = self.user
        guild_names = ", ".join(f"{g.name}({g.id})" for g in self.guilds)
        logger.info(
            "jarvis ready: user=%s guilds=[%s] expected_guild_id=%d",
            user,
            guild_names,
            self.guild_id,
        )
```

- [ ] **Step 4.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_client.py -v
```

Expected: 2 passed.

- [ ] **Step 4.5: Commit**

```bash
git add bot/jarvis/client.py bot/tests/test_client.py
git commit -m "feat(bot): JarvisBot client subclass + on_ready logging

discord.Client subclass with message_content + guilds intents (PR 2
will use the message_content intent for @-mentions). on_ready logs
authenticated user and connected guilds. No network in tests; live
gateway is a manual smoke gate per spec §13.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `bot/jarvis/main.py` — entrypoint

**Files:**
- Create: `bot/jarvis/main.py`
- Test: `bot/tests/test_main.py`

`main()` runs the gateway and uvicorn concurrently via `asyncio.gather`. On either subsystem raising or finishing, the other gets cancelled and the process exits.

- [ ] **Step 5.1: Write the failing test**

`bot/tests/test_main.py`:

```python
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
        },
    )()

    monkeypatch.setattr(main_mod, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(main_mod, "JarvisBot", lambda *, guild_id: FakeClient())
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
        },
    )()

    monkeypatch.setattr(main_mod, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(main_mod, "JarvisBot", lambda *, guild_id: ExplodingClient())
    monkeypatch.setattr(main_mod, "serve_http", fake_serve_http)

    with pytest.raises(RuntimeError, match="gateway lost"):
        await asyncio.wait_for(main_mod.run(), timeout=2.0)
    assert http_cancelled["value"] is True
```

- [ ] **Step 5.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_main.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'jarvis.main'`.

- [ ] **Step 5.3: Implement `bot/jarvis/main.py`**

```python
"""Bot entrypoint.

Runs the Discord gateway client and the FastAPI /healthz server on the
same asyncio event loop. If either subsystem exits or raises, the other
is cancelled and the exception (if any) is re-raised so the supervising
process exits non-zero.

Invoked via:

    python -m jarvis.main
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from jarvis.client import JarvisBot
from jarvis.config import Settings, get_settings
from jarvis.http.app import build_app
from jarvis.logging_setup import configure_logging

logger = logging.getLogger(__name__)


async def serve_http(app, port: int) -> None:
    """Run uvicorn against `app` on port until cancelled."""
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def run() -> None:
    settings: Settings = get_settings()
    configure_logging(settings.jarvis_log_level)
    logger.info("jarvis starting commit_sha=%s", settings.commit_sha or "(unset)")

    bot = JarvisBot(guild_id=settings.discord_guild_id)
    app = build_app(commit_sha=settings.commit_sha)

    gateway_task = asyncio.create_task(bot.start(settings.discord_bot_token), name="gateway")
    http_task = asyncio.create_task(serve_http(app, settings.jarvis_http_port), name="http")

    try:
        done, pending = await asyncio.wait(
            {gateway_task, http_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        # Re-raise the first exception (if any) from the completed tasks.
        for task in done:
            if task.exception() is not None:
                raise task.exception()
    finally:
        try:
            await bot.close()
        except Exception:  # noqa: BLE001 — close() is best-effort on shutdown
            logger.exception("jarvis bot.close() raised during shutdown")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 5.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_main.py -v
```

Expected: 2 passed.

If the second test reports the wrong exception type (e.g. `asyncio.CancelledError` wrapping `RuntimeError`), inspect the `task.exception()` ordering — depending on Python version, both tasks may complete near-simultaneously. Adjust the test's tolerance (still expect a `RuntimeError` somewhere in the raised exception group) rather than the production code; the production code's "first failing task wins" behavior is correct.

- [ ] **Step 5.5: Commit**

```bash
git add bot/jarvis/main.py bot/tests/test_main.py
git commit -m "feat(bot): asyncio entrypoint runs gateway + /healthz together

run() launches JarvisBot.start() and uvicorn.serve() as concurrent
tasks; FIRST_COMPLETED triggers cancellation of the other and
re-raises the first exception. main() is the python -m entrypoint.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `bot/README.md` — local dev instructions

**Files:**
- Create: `bot/README.md`

- [ ] **Step 6.1: Write `bot/README.md`**

```markdown
# bot/ — Jarvis 2.0

Team-owned Discord bot for the Tsuki Works niko project. Replaces the
off-the-shelf `@quadslab.io/discord-mcp` over six PRs (see
`docs/superpowers/specs/2026-05-01-jarvis-bot-design.md`).

This PR (PR 1) lands only the scaffold: the bot connects to the Discord
gateway, comes online in the guild, and serves `GET /healthz`. No
conversational behavior, no slash commands, no LLM calls. Those land
in PRs 2–6.

## Local dev

1. Install the dev deps (one-time):

   ```bash
   .venv/Scripts/python -m pip install -r bot/requirements-dev.txt
   ```

2. Copy `.env.example` to `.env` (already gitignored) and fill in:

   - `DISCORD_BOT_TOKEN` — from the Discord developer portal. Use a
     **dev** bot account, not the production Jarvis token. Ask Meet for
     access, or create your own test bot in your own dev guild.
   - `DISCORD_GUILD_ID` — `1495086675523797032` for the Tsuki Works
     guild, or your dev guild ID.
   - `JARVIS_HTTP_PORT` — defaults to 8080.
   - `JARVIS_LOG_LEVEL` — `DEBUG` while iterating, `INFO` otherwise.

3. Run:

   ```bash
   PYTHONPATH=bot .venv/Scripts/python -m jarvis.main
   ```

   The bot should appear online in your guild within a few seconds.
   `curl http://localhost:8080/healthz` should return:

   ```json
   {"status": "ok", "commit_sha": "", "started_at": "2026-..."}
   ```

## Tests

From the repo root:

```bash
.venv/Scripts/python -m pytest bot/tests -v
```

The root `pytest.ini` includes `bot/tests` in `testpaths`, so a bare
`pytest` from the repo root runs both backend and bot tests.

The `live_discord` marker is reserved for tests that touch the live
gateway; PR 1 has none.
```

- [ ] **Step 6.2: Commit**

```bash
git add bot/README.md
git commit -m "docs(bot): local dev README for PR 1 scaffold

Covers .env setup with the dev-bot caveat, run command, and how to
verify /healthz. Points at the design doc for the bigger picture.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Full-suite green + manual smoke gate

**Files:** none modified.

- [ ] **Step 7.1: Run the full bot test suite**

```bash
.venv/Scripts/python -m pytest bot/tests -v
```

Expected: all tests pass. Count: ~13 tests across 5 files.

- [ ] **Step 7.2: Run the root suite to confirm no backend regressions**

```bash
.venv/Scripts/python -m pytest -v
```

Expected: all backend + bot tests pass. If a backend test fails, it's almost certainly a `pytest.ini` testpaths regression — diff against `master` and recheck Task 0.4.

- [ ] **Step 7.3: Manual smoke gate (live Discord)**

This step is performed once before opening the PR. It is **not** part of CI.

1. Create or reuse a dev bot account in the Discord developer portal.
2. Invite it to a personal/dev guild with the **`bot`** scope and **`Send Messages`** + **`Read Message History`** permissions.
3. Put the dev bot token in `.env`, set `DISCORD_GUILD_ID` to the dev guild's ID.
4. Run `PYTHONPATH=bot python -m jarvis.main`.
5. Verify in the dev guild that the bot appears online (green dot) within ~10 seconds.
6. Verify the logs show: `jarvis ready: user=<bot-name>#NNNN guilds=[<dev-guild-name>(<id>)] expected_guild_id=<id>`.
7. Verify `curl http://localhost:8080/healthz` returns 200 with `{"status":"ok",...}`.
8. Stop the process (Ctrl+C). Verify both subsystems shut down cleanly (no traceback).

If any step fails, the bug is in this PR — fix before opening.

- [ ] **Step 7.4: Push and open PR**

```bash
git push -u origin feat/jarvis-bot-spec
gh pr create --title "feat(bot): PR 1 — Jarvis bot scaffold + /healthz" --body "$(cat <<'EOF'
## Summary
- New `bot/` Python package: `discord.py` gateway client + FastAPI `/healthz` running on the same asyncio loop.
- Typed `Settings` mirrors `app/config.py` (pydantic-settings).
- `bot/tests/` covers config, logging, HTTP, client construction, and main() wiring (~13 tests, no live network).
- Root `pytest.ini` updated to discover `bot/tests` and reserve a `live_discord` marker for later PRs.
- `.env.example` documents the new bot env vars.

Per the design doc (`docs/superpowers/specs/2026-05-01-jarvis-bot-design.md`), this is PR 1 of 6. No conversational behavior or LLM calls land in this PR — that's PR 2.

## Test plan
- [x] `.venv/Scripts/python -m pytest bot/tests -v` → all green
- [x] `.venv/Scripts/python -m pytest -v` (full repo) → all green, no backend regressions
- [x] Manual smoke: dev bot appears online in a dev guild and `/healthz` returns 200

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review (run after writing the plan, before handoff)

The author of this plan ran the following checks against the spec (`docs/superpowers/specs/2026-05-01-jarvis-bot-design.md`):

**Spec coverage for PR 1's scope:**
- §3 stack picks → Tasks 0–5 use Python, discord.py 2.x, FastAPI, uvicorn, pydantic-settings, pytest. ✓
- §4.1 module layout for files in PR 1 (`config.py`, `client.py`, `http/app.py`, `main.py`, plus tests) → all present. Modules deferred to later PRs (`agent.py`, `system_prompt.py`, `memory.py`, `ratelimit.py`, `events.py`, `router.py`, `tools/`, `commands/`) are intentionally NOT created here. ✓
- §4.4 outbound `POST /post` → explicitly deferred to PR 6, but `build_app` factory leaves a clean seam for it (no `@app.get` calls outside the factory body). ✓
- §13 testing posture (unit tests yes, no live Discord in CI, manual smoke gate before PR open) → Task 7.3. ✓
- §12 PR 1 acceptance ("Bot appears online in Discord; CI green") → Task 7. ✓

**Placeholder scan:**
- No "TBD" / "implement later" / "fill in details" anywhere in the plan body.
- Every code step has the actual code; every test step has a real test; every shell step has the real command.

**Type / name consistency:**
- `Settings` field names locked in Task 1 (`discord_bot_token`, `discord_guild_id`, `jarvis_http_port`, `jarvis_log_level`, `commit_sha`) — referenced verbatim in Task 5 `main.py`. ✓
- `JarvisBot(guild_id=...)` keyword-only constructor — used identically in Task 4 and Task 5. ✓
- `build_app(commit_sha=...)` factory signature — used identically in Task 3 and Task 5. ✓
- `serve_http(app, port)` signature — used identically in Task 5 production code and tests. ✓

**Spec deltas worth surfacing in the PR description:**
- Spec §3 said "pyproject.toml". Plan uses `bot/requirements.txt` + `bot/requirements-dev.txt` to match the existing repo convention (root has `requirements.txt`, no pyproject). Documented at the top of the plan and again in the PR description.

No fixes required from review.

---

## Handoff

Next plans will be written one PR at a time, after each prior PR merges:

- **Plan 2:** PR 2 — conversational @-mention path with stub agent (no tools), Firestore-backed thread memory.
- **Plan 3:** PR 3 — Claude tool-use loop + tools (`sprint`, `github`, `docs`, `chat`).
- **Plan 4:** PR 4 — slash commands.
- **Plan 5:** PR 5 — GCE deploy + Secret Manager + uptime check.
- **Plan 6:** PR 6 — custom MCP shim, `.mcp.json.example` swap, retire `@quadslab.io/discord-mcp`.

Splitting plan-by-plan keeps each plan small enough to review thoroughly and lets us learn from each PR before locking the next plan's choices.
