# Jarvis 2.0 — PR 3a: Agent Tool-Use Loop + First Three Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `agent.respond` into a Claude tool-use loop (Sonnet 4.6, max 6 tool steps) and ship three useful read-only tools — `get_current_sprint`, `get_recent_commits`, `search_repo_docs` — plus a per-user rate limiter wrapping every LLM-backed interaction. The bot answers "what shipped this week?" with sourced links instead of hallucinating.

**Architecture:** A `ToolRegistry` owns named tool descriptors (Anthropic JSON schema + async callable) and exposes `as_anthropic_tools()` for the SDK and `dispatch(name, input, context)` for execution. Tools that need state (Discord guild, GitHub creds, filesystem path) receive a `ToolContext` dataclass at dispatch time. The agent loop streams text deltas to the caller, then on each turn checks the final message for `tool_use` blocks; if present, dispatches the tools and feeds back `tool_result` blocks; otherwise stops. A separate `RateLimiter` (in-memory, 20 calls/user/hour) gates the events handler before the agent loop runs.

**Tech Stack:** Python 3.12, `anthropic` async SDK with tool-use, `httpx` for GitHub REST + GraphQL (no new dep), local filesystem for docs grep. Existing test infra: pytest + pytest-asyncio + pytest-mock.

**Out of scope (PR 3b — next plan):** `get_pr`, `get_issue`, `open_issue`, `get_recent_messages`. Once 3a's patterns are proven, 3b is mostly more-of-the-same.

**Spec reference:** `docs/superpowers/specs/2026-05-01-jarvis-bot-design.md` §6 (tool list) and §9 (rate limit, tool-step cap).

**Plan-level deltas from spec (acknowledged):**
- Spec §6 says `search_repo_docs` "Uses ripgrep over a fresh git clone refreshed hourly." Plan uses Python's stdlib (`pathlib` + `re`) over the local repo's `docs/` directory. Reason: in PR 3a the bot still runs from the repo (no GCE deploy yet — that's PR 5), and pulling in ripgrep + a clone-refresh cron adds operational surface that doesn't earn its keep until deploy. The substitute is functionally equivalent for the team's docs corpus (~10 markdown files); the freshness story moves to PR 5 alongside the deploy.
- GitHub auth: spec §8 calls for a GitHub App. Plan uses a `GITHUB_TOKEN` PAT (Meet's read-scoped token). Reason: setting up a GitHub App on the org is non-trivial coordination work; deferring to PR 5 lets the deploy story drive that decision (the App's private key wants Secret Manager). All three PR-3a tools are read-only, so a PAT's blast radius is bounded.

---

## File Structure

**Created in this PR:**

```
bot/jarvis/
├── ratelimit.py              # InMemoryRateLimiter — per-user 20 calls/hour, monotonic time
├── github_client.py          # AsyncGitHubClient — httpx wrapper for REST + GraphQL
└── tools/
    ├── __init__.py           # ToolRegistry + ToolContext (kept together — same module)
    ├── sprint.py             # build_get_current_sprint_tool(github_client, project_id)
    ├── github.py             # build_get_recent_commits_tool(github_client, repo)
    └── docs.py               # build_search_repo_docs_tool(docs_root)

bot/tests/
├── test_ratelimit.py
├── test_github_client.py
├── test_tools_registry.py    # registry + context tests
├── test_tools_sprint.py
├── test_tools_github.py
└── test_tools_docs.py
```

**Modified in this PR:**

- `bot/jarvis/config.py` — add `github_token: Optional[str]` and `github_repo: str = "tsuki-works/niko"` and `github_project_id: str = "PVT_kwDOEIgWQM4BVBdK"`.
- `bot/jarvis/agent.py` — `respond()` becomes the tool-use loop; preserves the streaming-deltas contract for the Discord layer.
- `bot/jarvis/system_prompt.py` — replace the "no tools yet" paragraph with a brief "you can look up …" section listing the three tools.
- `bot/jarvis/events.py` — accept a `RateLimiter` and a `ToolRegistry`; reject rate-limited callers with a single Discord reply (no thread, no LLM call); pass the registry into `agent_fn`.
- `bot/jarvis/main.py` — construct `RateLimiter`, `AsyncGitHubClient`, `ToolRegistry` (with the three build_* helpers), and inject into `OnMessageHandler`.
- `bot/tests/conftest.py` — add `monkeypatch.delenv("GITHUB_TOKEN", raising=False)` to `fake_env` (defensive).
- `.env.example` — add `GITHUB_TOKEN`, `GITHUB_REPO`, `GITHUB_PROJECT_ID` to the bot block.
- `bot/tests/test_config.py` — extend with override tests for the new fields.
- `bot/tests/test_events.py` — extend with rate-limit + tool-registry passthrough tests.
- `bot/tests/test_main.py` — extend the dep-graph test with rate-limit + tool-registry fields.

**NOT modified in this PR:**

- `bot/jarvis/memory.py`, `bot/jarvis/router.py`, `bot/jarvis/stream_writer.py`, `bot/jarvis/client.py`, `bot/jarvis/http/app.py`, `bot/jarvis/logging_setup.py` — unchanged from PR 2.
- `app/` — backend untouched.

---

## Conventions (read once, apply throughout)

- **Tools are factories, not bare functions.** Each tool module exports a `build_<name>_tool(deps...) -> ToolDescriptor` that closes over its deps and returns a descriptor the registry can register. This keeps tools testable (pass a mock `AsyncGitHubClient`) and lets `main.py` wire production deps once.
- **`ToolDescriptor`** is a small dataclass: `name: str`, `description: str`, `input_schema: dict`, `fn: Callable[..., Awaitable[Any]]`. The registry stores these.
- **Tool dispatch always returns a string.** The registry serializes tool output (success result or error message) to JSON before feeding back to Anthropic as `tool_result.content`. Tools may raise — the registry catches and converts to `{"error": str(exc)}`.
- **Rate-limited reply** (when a user exceeds 20/hour) is a one-line message in the same channel where they @-mentioned ("rate-limited — try again in a few minutes"); no thread is created and no LLM call happens.
- **Tool-step cap = 6** (per spec §9). After 6 round-trips of `tool_use → tool_result`, force-close the loop with a final non-tool turn ("max tool steps reached, summarizing…"). In practice tools tend to terminate in 1–3 round-trips.
- **GitHub model.** `tsuki-works/niko` is hardcoded as the default repo via `Settings.github_repo`. The bot is single-tenant for our org.
- **Logging.** Each tool logs `name=... duration_ms=... result_kind=ok|error` at INFO; agent loop logs `step=... tool_count=...` at DEBUG. No tool input/output logged (potentially sensitive).
- **Tests never hit live GitHub or Anthropic.** GitHub tools take an `AsyncGitHubClient` they can mock at the seam. Agent tests use the same `_make_anthropic_mock_with_text_chunks` shape from PR 2 with one extension for `get_final_message`.
- **Commit style:** matches PR 1/2 — `feat(bot): …` / `test(bot): …`, short body explaining why.

---

## Task 0: Plumbing — config + .env.example + conftest

**Files:**
- Modify: `bot/jarvis/config.py`
- Modify: `bot/tests/conftest.py`
- Modify: `bot/tests/test_config.py`
- Modify: `.env.example` (root)

- [ ] **Step 0.1: Update `bot/jarvis/config.py`**

Read the current file. Final class body:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    discord_bot_token: str
    discord_guild_id: int

    anthropic_api_key: Optional[str] = None
    jarvis_post_secret: Optional[str] = None
    jarvis_http_port: int = 8080
    jarvis_log_level: str = "INFO"

    # Firestore project ID. Optional — google-cloud-firestore auto-detects
    # from credentials (gcloud ADC locally, metadata server on GCE). Set
    # explicitly only when you need to override (e.g., dev pointing at a
    # staging project).
    gcp_project_id: Optional[str] = None

    # GitHub credentials (PR 3a). Token is a PAT with read:org / repo
    # scope (or fine-grained equivalent). PR 5 swaps to a GitHub App
    # whose private key lives in Secret Manager — this PAT path is the
    # bridging step.
    github_token: Optional[str] = None
    github_repo: str = "tsuki-works/niko"
    github_project_id: str = "PVT_kwDOEIgWQM4BVBdK"

    commit_sha: str = ""
```

- [ ] **Step 0.2: Update `bot/tests/conftest.py`**

Read the file. The `fake_env` fixture currently strips `ANTHROPIC_API_KEY`, `JARVIS_POST_SECRET`, `JARVIS_HTTP_PORT`, `JARVIS_LOG_LEVEL`, `COMMIT_SHA`, `GCP_PROJECT_ID`. Add three more delenv lines for the new vars (insert after the existing delenvs, before the final `yield`):

```python
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    monkeypatch.delenv("GITHUB_PROJECT_ID", raising=False)
```

- [ ] **Step 0.3: Update `bot/tests/test_config.py`**

Read the file. The `test_settings_defaults` test asserts the existing optional fields default correctly. Append three lines in the same function:

```python
    assert s.github_token is None
    assert s.github_repo == "tsuki-works/niko"
    assert s.github_project_id == "PVT_kwDOEIgWQM4BVBdK"
```

Also add a new test mirroring `test_settings_gcp_project_id_override`:

```python
def test_settings_github_overrides(fake_env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    monkeypatch.setenv("GITHUB_REPO", "myorg/myrepo")
    monkeypatch.setenv("GITHUB_PROJECT_ID", "PVT_other")
    s = Settings()
    assert s.github_token == "ghp_fake"
    assert s.github_repo == "myorg/myrepo"
    assert s.github_project_id == "PVT_other"
```

- [ ] **Step 0.4: Update `.env.example`**

Read the file. The Jarvis bot block is at the bottom. Append three new vars to that block:

```
# GitHub PAT for read-only project board / commits queries (PR 3a).
# Need read:org + repo scopes (fine-grained equivalent OK). PR 5 swaps
# to a GitHub App with the private key in Secret Manager.
GITHUB_TOKEN=

# Default GitHub repo (owner/name). Override only for dev forks.
GITHUB_REPO=tsuki-works/niko

# GitHub Project (V2) node ID for the niko sprint board. Get via:
#   gh api graphql -f query='{ organization(login:"tsuki-works") { projectV2(number:2) { id } } }'
GITHUB_PROJECT_ID=PVT_kwDOEIgWQM4BVBdK
```

- [ ] **Step 0.5: Run the bot test suite**

```bash
.venv/Scripts/python -m pytest bot/tests -v
```

Expected: 49 passed (PR 2's 48 + the new `test_settings_github_overrides` = +1; the three `assert` lines added to `test_settings_defaults` are inline so the test count doesn't grow). If you see 50, you accidentally duplicated the existing test instead of extending it in place — fix.

- [ ] **Step 0.6: Commit**

```bash
git add bot/jarvis/config.py bot/tests/conftest.py bot/tests/test_config.py .env.example
git commit -m "chore(bot): add GITHUB_TOKEN/REPO/PROJECT_ID config for PR 3a tools

PR 3a's tools call GitHub's REST + GraphQL APIs via a PAT. github_repo
and github_project_id default to tsuki-works/niko's known values so a
fresh checkout doesn't need to set them. PR 5 will swap the PAT for a
GitHub App when deploy moves the secret to Secret Manager.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 1: `bot/jarvis/ratelimit.py` — per-user in-memory rate limiter

**Files:**
- Create: `bot/jarvis/ratelimit.py`
- Test: `bot/tests/test_ratelimit.py`

20 calls per user per rolling 60-minute window. In-memory only — restart resets the limiter, which is fine for a 4-person team and a bot we restart on deploys.

- [ ] **Step 1.1: Write the failing test**

`bot/tests/test_ratelimit.py`:

```python
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
    rl = InMemoryRateLimiter(
        max_per_window=2, window_seconds=10.0, clock=lambda: now[0]
    )
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
```

- [ ] **Step 1.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_ratelimit.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 1.3: Implement `bot/jarvis/ratelimit.py`**

```python
"""Per-user in-memory rate limiter.

Sliding window: each user has a deque of timestamps; on `check_and_record`
we drop expired timestamps from the front and either reject (deque is at
capacity) or append.

In-memory only. A restart resets the limiter — fine for a small team
where the worst case is a teammate who hit the limit before deploy gets
20 fresh calls right after. PR-3b/4 may move this to Firestore if usage
patterns warrant.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable


class InMemoryRateLimiter:
    def __init__(
        self,
        *,
        max_per_window: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_per_window
        self._window = window_seconds
        self._clock = clock
        self._calls: dict[int, deque[float]] = {}

    def check_and_record(self, *, user_id: int) -> bool:
        """Return True if the call is allowed; False if rate-limited.

        On True, a timestamp is recorded against the user."""
        now = self._clock()
        cutoff = now - self._window
        timestamps = self._calls.setdefault(user_id, deque())
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        if len(timestamps) >= self._max:
            return False
        timestamps.append(now)
        return True
```

- [ ] **Step 1.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_ratelimit.py -v
```

Expected: 5 passed.

- [ ] **Step 1.5: Commit**

```bash
git add bot/jarvis/ratelimit.py bot/tests/test_ratelimit.py
git commit -m "feat(bot): per-user in-memory rate limiter

Sliding-window deque-per-user. Default 20 calls / 3600s per spec §9.
Injected clock makes window-rollover testable without sleeping.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `bot/jarvis/github_client.py` — async GitHub HTTP wrapper

**Files:**
- Create: `bot/jarvis/github_client.py`
- Test: `bot/tests/test_github_client.py`

A thin async httpx wrapper that exposes:
- `graphql(query: str, variables: dict) -> dict`
- `get(path: str, params: dict | None = None) -> dict`
- `post(path: str, json: dict) -> dict` (used in PR 3b for `open_issue`)

Auth is bearer token from `Settings.github_token`. Base URL is `https://api.github.com`.

- [ ] **Step 2.1: Write the failing test**

`bot/tests/test_github_client.py`:

```python
"""Tests for jarvis.github_client.AsyncGitHubClient.

Mocks httpx at the AsyncClient level — no live GitHub.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from jarvis.github_client import AsyncGitHubClient


def _make_response(status: int, json_body: dict) -> httpx.Response:
    request = httpx.Request("GET", "https://api.github.com/")
    return httpx.Response(status, json=json_body, request=request)


def _make_async_client(response: httpx.Response):
    """Return a MagicMock standing in for httpx.AsyncClient with .request()."""
    client = MagicMock()
    client.request = AsyncMock(return_value=response)
    return client


async def test_get_returns_parsed_json():
    response = _make_response(200, {"login": "tsuki-works"})
    httpx_client = _make_async_client(response)
    gh = AsyncGitHubClient(token="ghp_x", httpx_client=httpx_client)
    out = await gh.get("/orgs/tsuki-works")
    assert out == {"login": "tsuki-works"}
    httpx_client.request.assert_awaited_once()
    call_kwargs = httpx_client.request.await_args.kwargs
    assert call_kwargs["method"] == "GET"
    assert call_kwargs["url"] == "https://api.github.com/orgs/tsuki-works"
    assert call_kwargs["headers"]["Authorization"] == "Bearer ghp_x"
    assert call_kwargs["headers"]["Accept"] == "application/vnd.github+json"


async def test_get_with_params():
    response = _make_response(200, [{"sha": "abc"}])
    httpx_client = _make_async_client(response)
    gh = AsyncGitHubClient(token="t", httpx_client=httpx_client)
    out = await gh.get("/repos/x/y/commits", params={"per_page": 5})
    assert out == [{"sha": "abc"}]
    assert httpx_client.request.await_args.kwargs["params"] == {"per_page": 5}


async def test_graphql_posts_query_and_variables():
    response = _make_response(200, {"data": {"node": {"items": []}}})
    httpx_client = _make_async_client(response)
    gh = AsyncGitHubClient(token="t", httpx_client=httpx_client)
    out = await gh.graphql("query { x }", variables={"id": "PVT_x"})
    assert out == {"node": {"items": []}}
    kwargs = httpx_client.request.await_args.kwargs
    assert kwargs["method"] == "POST"
    assert kwargs["url"] == "https://api.github.com/graphql"
    assert kwargs["json"] == {"query": "query { x }", "variables": {"id": "PVT_x"}}


async def test_graphql_raises_on_top_level_errors():
    response = _make_response(
        200, {"errors": [{"message": "Could not resolve"}], "data": None}
    )
    httpx_client = _make_async_client(response)
    gh = AsyncGitHubClient(token="t", httpx_client=httpx_client)
    with pytest.raises(RuntimeError, match="Could not resolve"):
        await gh.graphql("query { x }", variables={})


async def test_non_2xx_raises_with_status_and_body():
    response = _make_response(404, {"message": "Not Found"})
    httpx_client = _make_async_client(response)
    gh = AsyncGitHubClient(token="t", httpx_client=httpx_client)
    with pytest.raises(RuntimeError, match="404"):
        await gh.get("/repos/x/y/pulls/9999")


async def test_close_closes_underlying_client():
    httpx_client = _make_async_client(_make_response(200, {}))
    httpx_client.aclose = AsyncMock()
    gh = AsyncGitHubClient(token="t", httpx_client=httpx_client)
    await gh.close()
    httpx_client.aclose.assert_awaited_once()
```

- [ ] **Step 2.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_github_client.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 2.3: Implement `bot/jarvis/github_client.py`**

```python
"""Thin async GitHub API wrapper.

Two surfaces:
- REST  via .get() / .post() against https://api.github.com/<path>
- GraphQL via .graphql(query, variables) against https://api.github.com/graphql

Auth is a Bearer token (PAT in PR 3a; GitHub App installation token in PR 5).

Constructor takes the httpx client so tests can mock at that seam without
monkeypatching httpx.AsyncClient at module scope.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

_BASE_URL = "https://api.github.com"
_USER_AGENT = "jarvis-bot/0.1"


class AsyncGitHubClient:
    def __init__(
        self,
        *,
        token: str,
        httpx_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._token = token
        self._client = httpx_client or httpx.AsyncClient(timeout=10.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
        }

    async def get(
        self, path: str, params: Optional[dict[str, Any]] = None
    ) -> Any:
        url = _BASE_URL + path
        response = await self._client.request(
            method="GET",
            url=url,
            headers=self._headers(),
            params=params,
        )
        if response.status_code >= 300:
            raise RuntimeError(
                f"GitHub GET {path} -> {response.status_code}: {response.text}"
            )
        return response.json()

    async def post(self, path: str, json: dict[str, Any]) -> Any:
        url = _BASE_URL + path
        response = await self._client.request(
            method="POST",
            url=url,
            headers=self._headers(),
            json=json,
        )
        if response.status_code >= 300:
            raise RuntimeError(
                f"GitHub POST {path} -> {response.status_code}: {response.text}"
            )
        return response.json()

    async def graphql(
        self, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        url = _BASE_URL + "/graphql"
        response = await self._client.request(
            method="POST",
            url=url,
            headers=self._headers(),
            json={"query": query, "variables": variables},
        )
        if response.status_code >= 300:
            raise RuntimeError(
                f"GitHub GraphQL -> {response.status_code}: {response.text}"
            )
        body = response.json()
        if body.get("errors"):
            messages = "; ".join(
                e.get("message", "?") for e in body["errors"]
            )
            raise RuntimeError(f"GitHub GraphQL errors: {messages}")
        return body.get("data") or {}

    async def close(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 2.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_github_client.py -v
```

Expected: 6 passed.

- [ ] **Step 2.5: Commit**

```bash
git add bot/jarvis/github_client.py bot/tests/test_github_client.py
git commit -m "feat(bot): async GitHub REST + GraphQL wrapper

AsyncGitHubClient exposes get/post/graphql against api.github.com with
a Bearer token. graphql() raises on top-level GraphQL errors so callers
get a clean RuntimeError instead of unwrapping nested error arrays.
Constructor takes the httpx client for test injection.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `bot/jarvis/tools/__init__.py` — `ToolRegistry` + `ToolContext`

**Files:**
- Create: `bot/jarvis/tools/__init__.py`
- Test: `bot/tests/test_tools_registry.py`

The registry holds `ToolDescriptor`s and exposes the two surfaces the agent loop needs: `as_anthropic_tools()` for the API and `dispatch(name, input, context)` for execution.

- [ ] **Step 3.1: Write the failing test**

`bot/tests/test_tools_registry.py`:

```python
"""Tests for jarvis.tools — ToolRegistry + ToolContext."""

from __future__ import annotations

import json

from jarvis.tools import ToolContext, ToolDescriptor, ToolRegistry


def _ctx() -> ToolContext:
    # Minimal context — no real fields needed for these tests.
    return ToolContext(guild=None, github_client=None, github_repo="org/repo",
                       github_project_id="PVT_x", docs_root=None)


async def test_register_and_as_anthropic_tools_shape():
    async def echo(*, x: int) -> dict:
        return {"x": x}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="echo",
            description="Echoes x.",
            input_schema={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            },
            fn=echo,
        )
    )
    tools = reg.as_anthropic_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "echo"
    assert tools[0]["description"] == "Echoes x."
    assert tools[0]["input_schema"]["properties"]["x"]["type"] == "integer"


async def test_dispatch_returns_json_string_on_success():
    async def echo(*, x: int) -> dict:
        return {"x": x, "doubled": x * 2}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="echo", description="d", input_schema={}, fn=echo,
        )
    )
    out = await reg.dispatch(name="echo", tool_input={"x": 3}, context=_ctx())
    parsed = json.loads(out)
    assert parsed == {"x": 3, "doubled": 6}


async def test_dispatch_returns_error_json_for_unknown_tool():
    reg = ToolRegistry()
    out = await reg.dispatch(name="nope", tool_input={}, context=_ctx())
    parsed = json.loads(out)
    assert "error" in parsed
    assert "nope" in parsed["error"]


async def test_dispatch_catches_tool_exception():
    async def explode(**_kwargs) -> dict:
        raise ValueError("boom")

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="explode", description="d", input_schema={}, fn=explode,
        )
    )
    out = await reg.dispatch(name="explode", tool_input={}, context=_ctx())
    parsed = json.loads(out)
    assert "error" in parsed
    assert "boom" in parsed["error"]


async def test_dispatch_passes_context_when_fn_accepts_it():
    """Tools may opt-in to the context by accepting a `context` kwarg."""
    seen = {}

    async def needs_ctx(*, x: int, context: ToolContext) -> dict:
        seen["repo"] = context.github_repo
        return {"x": x}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="needs_ctx", description="d", input_schema={}, fn=needs_ctx,
            wants_context=True,
        )
    )
    await reg.dispatch(
        name="needs_ctx", tool_input={"x": 1}, context=_ctx()
    )
    assert seen["repo"] == "org/repo"


async def test_register_rejects_duplicate_name():
    async def fn(**_kwargs):
        return {}

    reg = ToolRegistry()
    desc = ToolDescriptor(name="t", description="", input_schema={}, fn=fn)
    reg.register(desc)
    import pytest
    with pytest.raises(ValueError, match="already registered"):
        reg.register(desc)
```

- [ ] **Step 3.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_registry.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3.3: Implement `bot/jarvis/tools/__init__.py`**

```python
"""Tool registry + execution context for Jarvis's agent loop.

A ToolRegistry holds named ToolDescriptors. The agent loop calls
`as_anthropic_tools()` to get the SDK-formatted tool list and
`dispatch(name, input, context)` to run a tool by name.

Tools that need state (Discord guild, GitHub client, docs path) opt into
a ToolContext via the `wants_context=True` flag on their descriptor.
The registry passes `context=ctx` as a kwarg only when that flag is set
— this keeps tool functions readable when they don't need state.

Tool output is always a string (JSON-serialized) because that's what
Anthropic's tool_result.content expects. Errors are caught at dispatch
time and serialized as `{"error": "<message>"}` so the model can surface
the failure rather than the loop blowing up.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Per-turn execution context handed to tools that need state."""

    guild: Any  # discord.Guild — `Any` to keep this module discord-import-free
    github_client: Any  # AsyncGitHubClient — likewise
    github_repo: str
    github_project_id: str
    docs_root: Optional[Path]


@dataclass
class ToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., Awaitable[Any]]
    wants_context: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDescriptor] = {}

    def register(self, descriptor: ToolDescriptor) -> None:
        if descriptor.name in self._tools:
            raise ValueError(f"tool {descriptor.name!r} already registered")
        self._tools[descriptor.name] = descriptor

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def as_anthropic_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": d.name,
                "description": d.description,
                "input_schema": d.input_schema,
            }
            for d in self._tools.values()
        ]

    async def dispatch(
        self,
        *,
        name: str,
        tool_input: dict[str, Any],
        context: ToolContext,
    ) -> str:
        """Run tool `name` with `tool_input` and return its result as a
        JSON string suitable for Anthropic's tool_result.content."""
        desc = self._tools.get(name)
        if desc is None:
            payload = {"error": f"unknown tool: {name}"}
            return json.dumps(payload)
        kwargs = dict(tool_input)
        if desc.wants_context:
            kwargs["context"] = context
        try:
            result = await desc.fn(**kwargs)
        except Exception as exc:
            logger.warning("tool %s raised: %s", name, exc)
            return json.dumps({"error": str(exc)})
        return json.dumps(result, default=str)
```

- [ ] **Step 3.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_registry.py -v
```

Expected: 6 passed.

- [ ] **Step 3.5: Commit**

```bash
git add bot/jarvis/tools/__init__.py bot/tests/test_tools_registry.py
git commit -m "feat(bot): tool registry + context for the agent loop

ToolRegistry holds ToolDescriptors and exposes as_anthropic_tools()
plus dispatch(name, input, context). Context is passed only to tools
that opt in via wants_context=True. dispatch() catches exceptions
and serializes them as {error: ...} JSON so a failing tool surfaces
to the model rather than crashing the loop.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Tool — `get_current_sprint` (GitHub GraphQL)

**Files:**
- Create: `bot/jarvis/tools/sprint.py`
- Test: `bot/tests/test_tools_sprint.py`

Queries the niko Project (V2) for items, prioritizes `Status = "In progress"` and falls back to lowest open Phase. Returns a JSON-friendly dict.

The GraphQL query mirrors the one used by the `current-sprint` skill — fetch project items by node ID, return title/status/phase/url for each open one.

- [ ] **Step 4.1: Write the failing test**

`bot/tests/test_tools_sprint.py`:

```python
"""Tests for jarvis.tools.sprint.build_get_current_sprint_tool."""

from __future__ import annotations

from unittest.mock import AsyncMock

from jarvis.tools.sprint import build_get_current_sprint_tool


def _gh_with_response(data: dict):
    gh = AsyncMock()
    gh.graphql = AsyncMock(return_value=data)
    return gh


async def test_returns_in_progress_items():
    data = {
        "node": {
            "items": {
                "nodes": [
                    {
                        "content": {"title": "Sprint 2.4", "url": "u4", "number": 7},
                        "fieldValues": {
                            "nodes": [
                                {"name": "In progress", "field": {"name": "Status"}},
                                {"name": "Phase 2: MVP", "field": {"name": "Phase"}},
                            ]
                        },
                    },
                    {
                        "content": {"title": "Sprint 2.1", "url": "u1", "number": 4},
                        "fieldValues": {
                            "nodes": [
                                {"name": "Done", "field": {"name": "Status"}},
                                {"name": "Phase 2: MVP", "field": {"name": "Phase"}},
                            ]
                        },
                    },
                ]
            }
        }
    }
    gh = _gh_with_response(data)
    desc = build_get_current_sprint_tool(
        github_client=gh, project_id="PVT_x"
    )
    out = await desc.fn()
    assert out["selected_by"] == "in_progress"
    assert len(out["items"]) == 1
    assert out["items"][0]["title"] == "Sprint 2.4"
    assert out["items"][0]["url"] == "u4"
    assert out["items"][0]["status"] == "In progress"
    assert out["items"][0]["phase"] == "Phase 2: MVP"


async def test_falls_back_to_lowest_open_phase_when_none_in_progress():
    data = {
        "node": {
            "items": {
                "nodes": [
                    {
                        "content": {"title": "Phase 0 wrap", "url": "u0", "number": 2},
                        "fieldValues": {
                            "nodes": [
                                {"name": "Done", "field": {"name": "Status"}},
                                {"name": "Phase 0: Foundation", "field": {"name": "Phase"}},
                            ]
                        },
                    },
                    {
                        "content": {"title": "Sprint 3.1", "url": "u31", "number": 8},
                        "fieldValues": {
                            "nodes": [
                                {"name": "Todo", "field": {"name": "Status"}},
                                {"name": "Phase 3: Beta", "field": {"name": "Phase"}},
                            ]
                        },
                    },
                    {
                        "content": {"title": "Sprint 2.4", "url": "u24", "number": 7},
                        "fieldValues": {
                            "nodes": [
                                {"name": "Todo", "field": {"name": "Status"}},
                                {"name": "Phase 2: MVP", "field": {"name": "Phase"}},
                            ]
                        },
                    },
                ]
            }
        }
    }
    gh = _gh_with_response(data)
    desc = build_get_current_sprint_tool(
        github_client=gh, project_id="PVT_x"
    )
    out = await desc.fn()
    assert out["selected_by"] == "lowest_open_phase"
    titles = [item["title"] for item in out["items"]]
    assert "Sprint 2.4" in titles
    assert "Sprint 3.1" not in titles  # later phase, dropped


async def test_handles_empty_board():
    gh = _gh_with_response({"node": {"items": {"nodes": []}}})
    desc = build_get_current_sprint_tool(
        github_client=gh, project_id="PVT_x"
    )
    out = await desc.fn()
    assert out["selected_by"] == "empty"
    assert out["items"] == []


async def test_descriptor_metadata():
    gh = _gh_with_response({"node": {"items": {"nodes": []}}})
    desc = build_get_current_sprint_tool(
        github_client=gh, project_id="PVT_x"
    )
    assert desc.name == "get_current_sprint"
    assert "sprint" in desc.description.lower()
    # No required input — the tool takes no args.
    assert desc.input_schema["type"] == "object"
    assert desc.input_schema.get("required", []) == []
```

- [ ] **Step 4.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_sprint.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4.3: Implement `bot/jarvis/tools/sprint.py`**

```python
"""`get_current_sprint` — pulls the niko sprint board via GraphQL.

Selection rules mirror the `current-sprint` Claude Code skill:
  1. Prefer items with Status = "In progress".
  2. Otherwise, items at the lowest open phase (parsed from the Phase
     field's "Phase N: ..." prefix) whose status != "Done".
  3. Otherwise, empty.
"""

from __future__ import annotations

import re
from typing import Any

from jarvis.tools import ToolDescriptor

_QUERY = """
query($id: ID!) {
  node(id: $id) {
    ... on ProjectV2 {
      items(first: 100) {
        nodes {
          content {
            ... on Issue { title url number }
            ... on PullRequest { title url number }
          }
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { name } }
              }
            }
          }
        }
      }
    }
  }
}
"""


def _phase_number(phase_label: str | None) -> int | None:
    if not phase_label:
        return None
    m = re.match(r"Phase\s+(\d+)", phase_label)
    return int(m.group(1)) if m else None


def _flatten(item: dict[str, Any]) -> dict[str, Any]:
    content = item.get("content") or {}
    field_values = (item.get("fieldValues") or {}).get("nodes") or []
    by_field = {}
    for fv in field_values:
        field_meta = fv.get("field") or {}
        fname = field_meta.get("name")
        if fname:
            by_field[fname] = fv.get("name")
    return {
        "title": content.get("title"),
        "url": content.get("url"),
        "number": content.get("number"),
        "status": by_field.get("Status"),
        "phase": by_field.get("Phase"),
    }


def build_get_current_sprint_tool(
    *, github_client: Any, project_id: str
) -> ToolDescriptor:
    async def get_current_sprint() -> dict[str, Any]:
        data = await github_client.graphql(_QUERY, variables={"id": project_id})
        nodes = (((data or {}).get("node") or {}).get("items") or {}).get("nodes") or []
        flat = [_flatten(n) for n in nodes]

        in_progress = [i for i in flat if i["status"] == "In progress"]
        if in_progress:
            return {"selected_by": "in_progress", "items": in_progress}

        open_items = [i for i in flat if i["status"] != "Done"]
        if not open_items:
            return {"selected_by": "empty", "items": []}

        phases = [
            _phase_number(i.get("phase")) for i in open_items
        ]
        present = [p for p in phases if p is not None]
        if not present:
            return {"selected_by": "no_phase_field", "items": open_items}

        lowest = min(present)
        items_at_lowest = [
            i
            for i, p in zip(open_items, phases)
            if p == lowest
        ]
        return {"selected_by": "lowest_open_phase", "items": items_at_lowest}

    return ToolDescriptor(
        name="get_current_sprint",
        description=(
            "Get the current sprint from the tsuki-works/niko GitHub Project. "
            "Returns items currently In progress, or the lowest open Phase if "
            "none are In progress. Use this when the user asks 'what are we "
            "working on?', 'what's the current sprint?', or 'sprint status'."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        fn=get_current_sprint,
    )
```

- [ ] **Step 4.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_sprint.py -v
```

Expected: 4 passed.

- [ ] **Step 4.5: Commit**

```bash
git add bot/jarvis/tools/sprint.py bot/tests/test_tools_sprint.py
git commit -m "feat(bot): tool — get_current_sprint via GraphQL

Mirrors the current-sprint Claude Code skill's selection rule:
prefer In-progress items, fall back to lowest open Phase. Tool is a
factory closing over the AsyncGitHubClient + project_id so main.py
wires production deps once.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Tool — `get_recent_commits` (GitHub REST)

**Files:**
- Create: `bot/jarvis/tools/github.py`
- Test: `bot/tests/test_tools_github.py`

Returns the last N commits from a branch on `tsuki-works/niko`. Default branch master, default n=10. Each commit's `{sha, title, author, date, url}`.

PR 3b will add `get_pr`, `get_issue`, `open_issue` to this same module.

- [ ] **Step 5.1: Write the failing test**

`bot/tests/test_tools_github.py`:

```python
"""Tests for jarvis.tools.github — GitHub-API-backed tools."""

from __future__ import annotations

from unittest.mock import AsyncMock

from jarvis.tools.github import build_get_recent_commits_tool


def _gh_with_response(data):
    gh = AsyncMock()
    gh.get = AsyncMock(return_value=data)
    return gh


async def test_get_recent_commits_returns_compact_records():
    raw = [
        {
            "sha": "abc123def456",
            "html_url": "https://github.com/o/r/commit/abc",
            "commit": {
                "message": "feat: did a thing\n\nbody we drop",
                "author": {"name": "Meet", "date": "2026-04-30T18:22:00Z"},
            },
        },
        {
            "sha": "789xyz",
            "html_url": "https://github.com/o/r/commit/789",
            "commit": {
                "message": "fix: another thing",
                "author": {"name": "Sandeep", "date": "2026-04-29T10:00:00Z"},
            },
        },
    ]
    gh = _gh_with_response(raw)
    desc = build_get_recent_commits_tool(
        github_client=gh, repo="tsuki-works/niko"
    )
    out = await desc.fn(n=2, branch="master")
    assert len(out) == 2
    assert out[0]["sha"] == "abc123de"  # short sha
    assert out[0]["title"] == "feat: did a thing"  # subject only
    assert out[0]["author"] == "Meet"
    assert out[0]["date"] == "2026-04-30T18:22:00Z"
    assert out[0]["url"] == "https://github.com/o/r/commit/abc"
    gh.get.assert_awaited_once()
    call_kwargs = gh.get.await_args.kwargs
    assert call_kwargs["params"]["sha"] == "master"
    assert call_kwargs["params"]["per_page"] == 2


async def test_get_recent_commits_defaults_to_master_and_10():
    gh = _gh_with_response([])
    desc = build_get_recent_commits_tool(
        github_client=gh, repo="tsuki-works/niko"
    )
    await desc.fn()
    params = gh.get.await_args.kwargs["params"]
    assert params["sha"] == "master"
    assert params["per_page"] == 10


async def test_get_recent_commits_clamps_n():
    gh = _gh_with_response([])
    desc = build_get_recent_commits_tool(
        github_client=gh, repo="tsuki-works/niko"
    )
    # Anthropic models occasionally pass big numbers; we cap to 50.
    await desc.fn(n=10000)
    assert gh.get.await_args.kwargs["params"]["per_page"] == 50
    # And clamps low values to 1.
    await desc.fn(n=0)
    assert gh.get.await_args.kwargs["params"]["per_page"] == 1


async def test_get_recent_commits_descriptor_metadata():
    gh = _gh_with_response([])
    desc = build_get_recent_commits_tool(
        github_client=gh, repo="tsuki-works/niko"
    )
    assert desc.name == "get_recent_commits"
    assert "commit" in desc.description.lower()
    assert "n" in desc.input_schema["properties"]
    assert "branch" in desc.input_schema["properties"]
    # Both args optional.
    assert desc.input_schema.get("required", []) == []
```

- [ ] **Step 5.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_github.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 5.3: Implement `bot/jarvis/tools/github.py`**

```python
"""GitHub-backed tools for Jarvis.

PR 3a ships `get_recent_commits`. PR 3b will add `get_pr`,
`get_issue`, `open_issue` in the same module.
"""

from __future__ import annotations

from typing import Any

from jarvis.tools import ToolDescriptor

_MAX_COMMITS = 50


def _clamp_n(n: int) -> int:
    if n < 1:
        return 1
    if n > _MAX_COMMITS:
        return _MAX_COMMITS
    return n


def build_get_recent_commits_tool(
    *, github_client: Any, repo: str
) -> ToolDescriptor:
    async def get_recent_commits(
        n: int = 10, branch: str = "master"
    ) -> list[dict[str, Any]]:
        clamped = _clamp_n(n)
        raw = await github_client.get(
            f"/repos/{repo}/commits",
            params={"sha": branch, "per_page": clamped},
        )
        return [
            {
                "sha": (c.get("sha") or "")[:8],
                "title": (c.get("commit", {}).get("message") or "").split(
                    "\n", 1
                )[0],
                "author": c.get("commit", {})
                .get("author", {})
                .get("name"),
                "date": c.get("commit", {})
                .get("author", {})
                .get("date"),
                "url": c.get("html_url"),
            }
            for c in (raw or [])
        ]

    return ToolDescriptor(
        name="get_recent_commits",
        description=(
            "List the most recent commits on a branch of "
            "tsuki-works/niko. Defaults to master / last 10. Use this "
            "when the user asks 'what shipped this week?', 'what's "
            "in master?', 'recent changes?'. Each commit returns its "
            "short SHA, subject line, author, date, and GitHub URL."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "Number of commits (1–50, default 10).",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch name (default 'master').",
                },
            },
            "required": [],
        },
        fn=get_recent_commits,
    )
```

- [ ] **Step 5.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_github.py -v
```

Expected: 4 passed.

- [ ] **Step 5.5: Commit**

```bash
git add bot/jarvis/tools/github.py bot/tests/test_tools_github.py
git commit -m "feat(bot): tool — get_recent_commits via GitHub REST

Returns short-SHA / subject / author / date / url for the last N
commits on a branch. Clamps n to 1–50 to defend against the model
asking for absurd page sizes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Tool — `search_repo_docs` (local filesystem)

**Files:**
- Create: `bot/jarvis/tools/docs.py`
- Test: `bot/tests/test_tools_docs.py`

Greps the local `docs/` directory for a query string. Returns a list of `{path, snippet}` matches with up to one snippet per matching file. Substring match (case-insensitive); regex caller-controllable in a future iteration.

- [ ] **Step 6.1: Write the failing test**

`bot/tests/test_tools_docs.py`:

```python
"""Tests for jarvis.tools.docs.build_search_repo_docs_tool."""

from __future__ import annotations

from pathlib import Path

from jarvis.tools.docs import build_search_repo_docs_tool


def _seed_docs(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


async def test_search_finds_substring_matches(tmp_path):
    _seed_docs(
        tmp_path,
        {
            "docs/01-prd.md": "Twilio is the telephony provider.\n",
            "docs/02-roadmap.md": "Phase 2 work.\n",
            "docs/06-creds.md": "Twilio creds in 1Password.\n",
        },
    )
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "docs")
    out = await desc.fn(query="twilio")
    paths = sorted(item["path"] for item in out)
    assert paths == ["01-prd.md", "06-creds.md"]
    snippets = [item["snippet"].lower() for item in out]
    assert all("twilio" in s for s in snippets)


async def test_search_returns_empty_for_no_matches(tmp_path):
    _seed_docs(tmp_path, {"docs/x.md": "nothing relevant"})
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "docs")
    out = await desc.fn(query="zzznothere")
    assert out == []


async def test_search_skips_non_md_files(tmp_path):
    _seed_docs(
        tmp_path,
        {
            "docs/note.md": "telephony rules",
            "docs/note.png": "telephony rules",  # not markdown
            "docs/sub/deep.md": "telephony deep",
        },
    )
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "docs")
    out = await desc.fn(query="telephony")
    paths = sorted(item["path"] for item in out)
    assert paths == ["note.md", "sub/deep.md"]


async def test_search_caps_results(tmp_path):
    files = {f"docs/n{i}.md": "match" for i in range(60)}
    _seed_docs(tmp_path, files)
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "docs")
    out = await desc.fn(query="match")
    assert len(out) <= 25  # default cap


async def test_search_handles_missing_root(tmp_path):
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "no-such-dir")
    out = await desc.fn(query="anything")
    assert out == []


async def test_descriptor_metadata(tmp_path):
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "docs")
    assert desc.name == "search_repo_docs"
    assert "docs" in desc.description.lower()
    assert "query" in desc.input_schema["properties"]
    assert desc.input_schema.get("required") == ["query"]
```

- [ ] **Step 6.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_docs.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 6.3: Implement `bot/jarvis/tools/docs.py`**

```python
"""`search_repo_docs` — substring grep over the local docs/ directory.

This is the PR 3a substitute for the spec's "ripgrep over a fresh git
clone refreshed hourly" plan. The bot runs from the repo (until PR 5
deploys to GCE), so reading directly from `docs/` is sufficient and
avoids spinning up a clone-refresh cron.

PR 5 (deploy) will revisit: either bake docs/ into the container at
build time or maintain a checked-out copy on the GCE VM with a refresh
cron.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from jarvis.tools import ToolDescriptor

_MAX_RESULTS = 25
_SNIPPET_RADIUS = 80  # chars on each side of the match


def _snippet(line: str, query_lower: str) -> str:
    idx = line.lower().find(query_lower)
    if idx < 0:
        return line.strip()[: _SNIPPET_RADIUS * 2]
    start = max(0, idx - _SNIPPET_RADIUS)
    end = min(len(line), idx + len(query_lower) + _SNIPPET_RADIUS)
    snippet = line[start:end].strip()
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(line) else "")


def build_search_repo_docs_tool(
    *, docs_root: Optional[Path]
) -> ToolDescriptor:
    async def search_repo_docs(query: str) -> list[dict[str, Any]]:
        if not query:
            return []
        if docs_root is None or not docs_root.exists():
            return []
        q = query.lower()
        results: list[dict[str, Any]] = []
        for md_path in sorted(docs_root.rglob("*.md")):
            try:
                text = md_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if q in line.lower():
                    results.append(
                        {
                            "path": str(
                                md_path.relative_to(docs_root)
                            ).replace("\\", "/"),
                            "snippet": _snippet(line, q),
                        }
                    )
                    break  # one snippet per file
            if len(results) >= _MAX_RESULTS:
                break
        return results

    return ToolDescriptor(
        name="search_repo_docs",
        description=(
            "Search the niko repo's docs/ directory for a substring "
            "(case-insensitive). Returns up to 25 matches as "
            "{path, snippet} pairs (one per file). Use this when the "
            "user asks 'where do we configure X?', 'what does the doc "
            "say about Y?', or to ground answers in repo documentation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to grep for, case-insensitive.",
                },
            },
            "required": ["query"],
        },
        fn=search_repo_docs,
    )
```

- [ ] **Step 6.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_docs.py -v
```

Expected: 6 passed.

- [ ] **Step 6.5: Commit**

```bash
git add bot/jarvis/tools/docs.py bot/tests/test_tools_docs.py
git commit -m "feat(bot): tool — search_repo_docs (local filesystem)

Substring grep over docs/, one snippet per file, capped at 25 results.
Plan §1 deltas vs spec: substitutes ripgrep + clone-refresh with
stdlib pathlib + str.lower() — pragmatic for PR 3a where the bot
runs from the repo.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Refactor `agent.respond` into a tool-use loop

**Files:**
- Modify: `bot/jarvis/agent.py`
- Modify: `bot/tests/test_agent.py`

`respond()` keeps its public signature but adds two new kwargs: `tool_registry` (optional `ToolRegistry`) and `tool_context` (optional `ToolContext`). When both are present and non-empty, the loop hands `tools=registry.as_anthropic_tools()` to Anthropic, processes `tool_use` blocks via `registry.dispatch(...)`, and feeds back `tool_result` blocks until the model stops asking for tools or `MAX_TOOL_STEPS` is reached.

- [ ] **Step 7.1: Update `bot/tests/test_agent.py`**

Read the current file. Replace its contents with the new test set (existing 5 tests are renamed/extended; 4 new tests cover the tool loop). The new contents:

```python
"""Tests for jarvis.agent — Claude streaming with optional tool-use loop."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.agent import MAX_TOOL_STEPS, MODEL, respond
from jarvis.tools import ToolContext, ToolDescriptor, ToolRegistry


# ---------- Fakes ----------


@dataclass
class FakeTextBlock:
    type: str  # "text"
    text: str


@dataclass
class FakeToolUseBlock:
    type: str  # "tool_use"
    id: str
    name: str
    input: dict


@dataclass
class FakeMessage:
    content: list  # list of FakeTextBlock | FakeToolUseBlock


def _ctx() -> ToolContext:
    return ToolContext(
        guild=None,
        github_client=None,
        github_repo="o/r",
        github_project_id="PVT_x",
        docs_root=None,
    )


def _make_anthropic_with_responses(responses: list[tuple[list[str], FakeMessage]]):
    """Each tuple = (text_deltas to stream, final FakeMessage). The mock
    yields responses in order across successive `messages.stream(...)` calls."""
    response_iter = iter(responses)
    captured_calls = []

    @asynccontextmanager
    async def stream_cm(**kwargs):
        captured_calls.append(kwargs)
        deltas, final = next(response_iter)

        async def text_stream():
            for d in deltas:
                yield d

        stream_obj = MagicMock()
        stream_obj.text_stream = text_stream()
        stream_obj.get_final_message = AsyncMock(return_value=final)
        yield stream_obj

    messages = MagicMock()
    messages.stream = stream_cm

    client = MagicMock()
    client.messages = messages
    return client, captured_calls


# ---------- No-tools path (parity with PR 2) ----------


async def test_respond_yields_chunks_in_order_no_tools():
    final = FakeMessage(content=[FakeTextBlock(type="text", text="hello")])
    client, _ = _make_anthropic_with_responses([(["he", "llo"], final)])
    out = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=None,
        tool_context=_ctx(),
    ):
        out.append(delta)
    assert out == ["he", "llo"]


async def test_respond_uses_correct_model_and_max_tokens():
    final = FakeMessage(content=[FakeTextBlock(type="text", text="x")])
    client, calls = _make_anthropic_with_responses([(["x"], final)])
    async for _ in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=None,
        tool_context=_ctx(),
    ):
        pass
    assert calls[0]["model"] == MODEL
    assert calls[0]["max_tokens"] == 1024
    assert calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


async def test_respond_does_not_pass_tools_when_registry_is_none():
    final = FakeMessage(content=[FakeTextBlock(type="text", text="x")])
    client, calls = _make_anthropic_with_responses([(["x"], final)])
    async for _ in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=None,
        tool_context=_ctx(),
    ):
        pass
    assert "tools" not in calls[0]


# ---------- Tool-use path ----------


async def test_respond_dispatches_tool_and_loops():
    """One tool round-trip: model asks for a tool, we dispatch, then it
    streams the final answer."""
    # First response: model emits a tool_use block (no text).
    final1 = FakeMessage(
        content=[
            FakeToolUseBlock(
                type="tool_use", id="tu_1", name="ping", input={"x": 1}
            ),
        ]
    )
    # Second response: model emits the final text answer.
    final2 = FakeMessage(content=[FakeTextBlock(type="text", text="pong")])
    client, calls = _make_anthropic_with_responses(
        [
            ([], final1),
            (["pong"], final2),
        ]
    )

    # Tool registry with one tool that returns {"ok": x*2}.
    async def ping(*, x: int) -> dict:
        return {"ok": x * 2}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="ping",
            description="d",
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
            fn=ping,
        )
    )

    out = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=reg,
        tool_context=_ctx(),
    ):
        out.append(delta)
    assert out == ["pong"]
    # Two API calls: initial + after-tool.
    assert len(calls) == 2
    # Initial call had tools=...
    assert "tools" in calls[0]
    assert calls[0]["tools"][0]["name"] == "ping"
    # Second call's messages includes the assistant tool_use turn AND a
    # user turn carrying the tool_result.
    second_messages = calls[1]["messages"]
    last_two = second_messages[-2:]
    assert last_two[0]["role"] == "assistant"
    # tool_result is wrapped in a user-role message
    assert last_two[1]["role"] == "user"
    tr_blocks = last_two[1]["content"]
    assert tr_blocks[0]["type"] == "tool_result"
    assert tr_blocks[0]["tool_use_id"] == "tu_1"
    assert "ok" in tr_blocks[0]["content"]


async def test_respond_aborts_at_max_tool_steps():
    """If the model keeps asking for tools, stop after MAX_TOOL_STEPS
    and yield a brief safety message."""
    # Build MAX_TOOL_STEPS + 1 responses, every one a tool_use (no text).
    tool_responses = [
        (
            [],
            FakeMessage(
                content=[
                    FakeToolUseBlock(
                        type="tool_use",
                        id=f"tu_{i}",
                        name="ping",
                        input={},
                    )
                ]
            ),
        )
        for i in range(MAX_TOOL_STEPS + 1)
    ]
    client, calls = _make_anthropic_with_responses(tool_responses)

    async def ping(**_kwargs) -> dict:
        return {"ok": True}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="ping", description="d", input_schema={}, fn=ping
        )
    )

    chunks = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=reg,
        tool_context=_ctx(),
    ):
        chunks.append(delta)
    # Loop stopped before consuming the (MAX_TOOL_STEPS+1)-th response.
    assert len(calls) == MAX_TOOL_STEPS
    # A safety message was yielded so the user isn't left empty-handed.
    final_text = "".join(chunks)
    assert "tool" in final_text.lower() and "max" in final_text.lower()


async def test_respond_handles_unknown_tool_name():
    """If the model invents a tool name, the registry returns an error
    JSON and the loop continues; the model gets a chance to recover."""
    final1 = FakeMessage(
        content=[
            FakeToolUseBlock(
                type="tool_use", id="tu_1", name="nope", input={}
            )
        ]
    )
    final2 = FakeMessage(content=[FakeTextBlock(type="text", text="sorry")])
    client, calls = _make_anthropic_with_responses(
        [
            ([], final1),
            (["sorry"], final2),
        ]
    )
    reg = ToolRegistry()  # empty registry

    out = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=reg,
        tool_context=_ctx(),
    ):
        out.append(delta)
    assert "".join(out) == "sorry"
    tr_blocks = calls[1]["messages"][-1]["content"]
    assert "error" in tr_blocks[0]["content"]


async def test_respond_does_not_mutate_history():
    final = FakeMessage(content=[FakeTextBlock(type="text", text="x")])
    client, _ = _make_anthropic_with_responses([(["x"], final)])
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ack"},
    ]
    history_before = [dict(t) for t in history]
    async for _ in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=history,
        user_message="second",
        tool_registry=None,
        tool_context=_ctx(),
    ):
        pass
    assert history == history_before


async def test_respond_handles_text_and_tool_in_same_response():
    """If the model emits both text deltas and a tool_use in one turn,
    we stream the text AND dispatch the tool, then continue."""
    final1 = FakeMessage(
        content=[
            FakeTextBlock(type="text", text="checking…"),
            FakeToolUseBlock(
                type="tool_use", id="tu_1", name="ping", input={}
            ),
        ]
    )
    final2 = FakeMessage(content=[FakeTextBlock(type="text", text="done")])
    client, calls = _make_anthropic_with_responses(
        [
            (["checking…"], final1),
            (["done"], final2),
        ]
    )

    async def ping(**_kwargs) -> dict:
        return {"ok": True}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="ping", description="d", input_schema={}, fn=ping
        )
    )

    out = []
    async for delta in respond(
        anthropic_client=client,
        system_prompt="SYS",
        history=[],
        user_message="hi",
        tool_registry=reg,
        tool_context=_ctx(),
    ):
        out.append(delta)
    assert out == ["checking…", "done"]
    assert len(calls) == 2
```

- [ ] **Step 7.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_agent.py -v
```

Expected: most tests fail because `respond` doesn't accept `tool_registry`/`tool_context` yet. The new tool-use tests fail because the loop doesn't exist.

- [ ] **Step 7.3: Implement `bot/jarvis/agent.py`**

Read the existing file. Replace with:

```python
"""Anthropic Claude streaming wrapper for Jarvis with tool-use loop.

Public API stays the same (yields text deltas) but the function now
accepts an optional ToolRegistry + ToolContext. When both are present
and the registry has tools, the loop hands `tools=...` to Anthropic on
each turn and processes any `tool_use` blocks it returns by dispatching
through the registry and feeding back `tool_result` blocks. Loops at
most MAX_TOOL_STEPS times; if the model keeps asking for tools beyond
that, the loop aborts with a brief safety message so the user isn't
left empty-handed.

Streaming-with-tools nuance: each loop iteration is a fresh streaming
call. Text deltas yielded mid-iteration arrive in real time. After a
tool round-trip, the next iteration's text continues seamlessly to the
caller (the events handler edits the same Discord placeholder).
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

from anthropic import AsyncAnthropic

from jarvis.tools import ToolContext, ToolRegistry

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024
MAX_TOOL_STEPS = 6


async def respond(
    *,
    anthropic_client: AsyncAnthropic,
    system_prompt: str,
    history: list[dict[str, Any]],
    user_message: str,
    tool_registry: Optional[ToolRegistry],
    tool_context: ToolContext,
) -> AsyncIterator[str]:
    """Yield text deltas from Claude, running tools as needed.

    `history` is the prior conversation in Anthropic message format
    (list of {"role": "user"|"assistant", "content": str}). `user_message`
    is appended internally; the caller's `history` is never mutated.

    If `tool_registry` is None or empty, this is a no-tools call (PR 2
    behavior).
    """
    messages: list[dict[str, Any]] = list(history) + [
        {"role": "user", "content": user_message}
    ]

    tools_payload: Optional[list[dict[str, Any]]] = None
    if tool_registry is not None and tool_registry.names():
        tools_payload = tool_registry.as_anthropic_tools()

    for step in range(MAX_TOOL_STEPS):
        stream_kwargs: dict[str, Any] = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": messages,
        }
        if tools_payload is not None:
            stream_kwargs["tools"] = tools_payload

        async with anthropic_client.messages.stream(**stream_kwargs) as stream:
            async for delta in stream.text_stream:
                yield delta
            final = await stream.get_final_message()

        tool_uses = [
            b for b in final.content if getattr(b, "type", None) == "tool_use"
        ]
        if not tool_uses:
            return  # done

        # Append the assistant's full turn (text + tool_use blocks) and
        # then a user-role message carrying the tool_result blocks.
        assistant_blocks: list[dict[str, Any]] = []
        for b in final.content:
            btype = getattr(b, "type", None)
            if btype == "text":
                assistant_blocks.append({"type": "text", "text": b.text})
            elif btype == "tool_use":
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": b.id,
                        "name": b.name,
                        "input": b.input,
                    }
                )
        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_result_blocks: list[dict[str, Any]] = []
        if tool_registry is None:
            # Defensive: model asked for a tool but we have no registry.
            for tu in tool_uses:
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(
                            {"error": "no tools available"}
                        ),
                    }
                )
        else:
            for tu in tool_uses:
                content_str = await tool_registry.dispatch(
                    name=tu.name,
                    tool_input=tu.input or {},
                    context=tool_context,
                )
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": content_str,
                    }
                )
        messages.append({"role": "user", "content": tool_result_blocks})

    # Reached MAX_TOOL_STEPS without a non-tool turn. Yield a safety
    # message so the user sees something.
    yield (
        "(I hit my max tool-use step count and didn't finish — "
        "could you try a more specific question?)"
    )
```

- [ ] **Step 7.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_agent.py -v
```

Expected: 8 passed (3 no-tools + 5 tool-loop tests).

- [ ] **Step 7.5: Commit**

```bash
git add bot/jarvis/agent.py bot/tests/test_agent.py
git commit -m "feat(bot): tool-use loop in agent.respond

Adds tool_registry + tool_context kwargs. When the registry is non-
empty, the streaming loop hands tools to Anthropic, dispatches any
tool_use blocks via the registry, and feeds back tool_result blocks
until the model stops asking. Loops at most MAX_TOOL_STEPS=6 (per
spec §9); on overrun, yields a safety message rather than dangling.
History is still never mutated.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Update `system_prompt.py` — replace "no tools yet" with the tool list

**Files:**
- Modify: `bot/jarvis/system_prompt.py`
- Modify: `bot/tests/test_system_prompt.py`

The PR 2 prompt told the model "you have no tools — say so honestly". PR 3a flips that.

- [ ] **Step 8.1: Update `bot/tests/test_system_prompt.py`**

Read the file. Update the existing `test_system_prompt_acknowledges_no_tools` to assert the OPPOSITE — the prompt now mentions the available tools:

```python
def test_system_prompt_lists_available_tools():
    p = build_system_prompt()
    # PR 3a: three tools available
    assert "get_current_sprint" in p
    assert "get_recent_commits" in p
    assert "search_repo_docs" in p
```

Delete the old `test_system_prompt_acknowledges_no_tools` test entirely (it's no longer accurate).

- [ ] **Step 8.2: Update `bot/jarvis/system_prompt.py`**

Read the file. Replace the "This version of you (PR 2 of your own buildout)..." paragraph through "...coming in my next PR." with a new tools-aware section:

```
You have a small set of tools you can use to ground your answers. Use them whenever a question would otherwise require you to guess about repo state:

- get_current_sprint — pulls the current sprint from the GitHub Project board (tsuki-works/niko #2). Use for "what are we working on?", "sprint status", "what's blocked?".
- get_recent_commits — last N commits on a branch. Use for "what shipped this week?", "what's in master?", "recent changes".
- search_repo_docs — substring grep over docs/. Use for "where do we configure X?", "what does the doc say about Y?".

Other questions about live Discord history, GitHub PRs/issues, or the ability to open issues are coming in a follow-up PR. If you don't have a tool for what's being asked, say so honestly.
```

Update the module docstring's reference from "PR 2 — pre-tools" to "PR 3a — first three tools":

```python
"""Static system prompt for Jarvis (PR 3a — three tools available).

PR 3b will add `get_pr`, `get_issue`, `open_issue`, `get_recent_messages`.
For PR 3a the prompt is still constant — every conversation gets the
same persona, team roster, tool list, and hard rules.
"""
```

- [ ] **Step 8.3: Run tests**

```bash
.venv/Scripts/python -m pytest bot/tests/test_system_prompt.py -v
```

Expected: 5 passed (still 5 tests; the no-tools test was replaced, not removed in count).

Wait — the previous count was 5 tests including the no-tools acknowledgment. We replaced one with a tool-list test. So count stays at 5. If you literally deleted without replacing, you'll see 4 — re-add the new test.

- [ ] **Step 8.4: Commit**

```bash
git add bot/jarvis/system_prompt.py bot/tests/test_system_prompt.py
git commit -m "feat(bot): system prompt — list available tools (PR 3a)

Replaces the 'no tools yet' paragraph with a brief catalog of the
three available tools and what they're for. Keeps an honest fallback
for capabilities still pending in PR 3b.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Wire it up — `events.py` + `main.py`

**Files:**
- Modify: `bot/jarvis/events.py`
- Modify: `bot/jarvis/main.py`
- Modify: `bot/tests/test_events.py`
- Modify: `bot/tests/test_main.py`

`OnMessageHandler` grows two new constructor kwargs: `rate_limiter: Optional[InMemoryRateLimiter]` and `tool_registry: Optional[ToolRegistry]` and `tool_context_factory: Callable[[Any], ToolContext]` (the factory builds a fresh context per message — it gets the message itself so it can reach `message.guild`).

Rate-limit behavior: before any LLM call, check `rate_limiter.check_and_record(user_id=author.id)`. If False, post a single rate-limit message in the same channel where the @-mention happened (`await message.reply(...)`) and return. No thread is created.

Agent call signature gains `tool_registry`, `tool_context` from the closure context.

`main._build_handler` constructs the rate limiter, the registry (with all three build_* helpers), the AsyncGitHubClient, and the context factory.

- [ ] **Step 9.1: Update `bot/tests/test_events.py`**

Read the current file. Add a new test asserting rate-limit blocks a user:

```python
async def test_rate_limited_caller_gets_one_reply_no_thread():
    """When the rate limiter rejects the user, post a one-line reply
    in the original channel and skip everything else."""
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=False)
    rl = MagicMock()
    rl.check_and_record = MagicMock(return_value=False)

    replies = []

    @dataclass
    class FakeReplyMessage:
        id: int
        author: FakeUser
        channel: FakeChannel
        guild: Any
        mentions: list
        content: str = ""

        async def reply(self, content: str) -> None:
            replies.append(content)

        async def create_thread(self, *, name: str):
            raise AssertionError("must not create thread when rate-limited")

    handler = OnMessageHandler(
        bot_user_id=_bot_user_id(),
        memory=memory,
        agent_fn=_stub_agent(["should-not-run"]),
        system_prompt_fn=lambda: "SYS",
        stream_writer_fn=_stream_writer,
        rate_limiter=rl,
        tool_registry=None,
        tool_context_factory=lambda _msg: None,
    )

    msg = FakeReplyMessage(
        id=900,
        author=_team_user(),
        channel=FakeChannel(id=10, type="text"),
        guild=MagicMock(id=99),
        mentions=[FakeUser(id=_bot_user_id(), bot=True)],
        content="@jarvis hi",
    )
    await handler.handle(msg)
    assert len(replies) == 1
    assert "rate" in replies[0].lower() or "limit" in replies[0].lower()
    memory.record_thread.assert_not_awaited()
    memory.append_turn.assert_not_awaited()


async def test_agent_fn_receives_tool_registry_and_context():
    memory = AsyncMock()
    memory.thread_exists = AsyncMock(return_value=False)
    memory.get_turns = AsyncMock(return_value=[])

    captured = {}

    async def capture_agent(*, system_prompt, history, user_message, tool_registry, tool_context):
        captured["registry"] = tool_registry
        captured["context"] = tool_context
        yield "ok"

    sentinel_registry = object()
    sentinel_context = object()

    handler = OnMessageHandler(
        bot_user_id=_bot_user_id(),
        memory=memory,
        agent_fn=capture_agent,
        system_prompt_fn=lambda: "SYS",
        stream_writer_fn=_stream_writer,
        rate_limiter=None,
        tool_registry=sentinel_registry,
        tool_context_factory=lambda _msg: sentinel_context,
    )
    msg = FakeMessage(
        id=901,
        author=_team_user(),
        channel=FakeChannel(id=10, type="text"),
        guild=MagicMock(id=99),
        mentions=[FakeUser(id=_bot_user_id(), bot=True)],
        content="@jarvis hi",
    )
    await handler.handle(msg)
    assert captured["registry"] is sentinel_registry
    assert captured["context"] is sentinel_context
```

Also update the constructor calls in the existing four tests to pass the new kwargs (default to None / lambda returning None):

```python
# Add to every existing OnMessageHandler(...) call in this file:
rate_limiter=None,
tool_registry=None,
tool_context_factory=lambda _msg: None,
```

**Important:** the existing `_stub_agent` factory and the `capture_agent` function in `test_history_passed_through_to_agent` are defined with three kwargs (`system_prompt, history, user_message`). The events handler now calls `agent_fn(...)` with **five** kwargs (adding `tool_registry, tool_context`). Update both stubs to swallow the new kwargs:

```python
def _stub_agent(deltas: list[str]):
    async def _agent(*, system_prompt, history, user_message, **_kwargs):
        for d in deltas:
            yield d
    return _agent
```

For `capture_agent` in `test_history_passed_through_to_agent`, add the two new params explicitly so you can also assert on them:

```python
async def capture_agent(
    *, system_prompt, history, user_message, tool_registry, tool_context
):
    captured["system_prompt"] = system_prompt
    captured["history"] = history
    captured["user_message"] = user_message
    yield "ok"
```

(The existing test only asserts on the three old kwargs, so this is purely additive — no assertion change needed.)

- [ ] **Step 9.2: Update `bot/jarvis/events.py`**

Read the file. Modify the constructor and `handle`:

```python
class OnMessageHandler:
    def __init__(
        self,
        *,
        bot_user_id: int,
        memory: _MemoryProto,
        agent_fn: _AgentFn,
        system_prompt_fn: Callable[[], str],
        stream_writer_fn: _StreamWriterFn,
        rate_limiter: Any,  # Optional[InMemoryRateLimiter] — Any to keep events.py independent of ratelimit
        tool_registry: Any,  # Optional[ToolRegistry]
        tool_context_factory: Callable[[Any], Any],
    ) -> None:
        self._bot_user_id = bot_user_id
        self._memory = memory
        self._agent_fn = agent_fn
        self._system_prompt_fn = system_prompt_fn
        self._stream_writer_fn = stream_writer_fn
        self._rate_limiter = rate_limiter
        self._tool_registry = tool_registry
        self._tool_context_factory = tool_context_factory

    async def handle(self, message: Any) -> None:
        decision = await classify_incoming(
            message,
            bot_user_id=self._bot_user_id,
            memory=self._memory,
        )
        if decision == RoutingDecision.IGNORE:
            return

        # Rate limit BEFORE thread creation — a rate-limited caller
        # shouldn't pollute the channel with empty threads.
        if self._rate_limiter is not None:
            allowed = self._rate_limiter.check_and_record(
                user_id=int(message.author.id)
            )
            if not allowed:
                logger.info(
                    "rate-limited user %s in channel %s",
                    message.author.id,
                    message.channel.id,
                )
                try:
                    await message.reply(
                        "Rate limit reached — try again in a few minutes."
                    )
                except Exception:  # noqa: BLE001 — best-effort notice
                    logger.exception("failed to post rate-limit reply")
                return

        if decision == RoutingDecision.MENTION_NEW_THREAD:
            thread = await self._open_thread(message)
        elif decision == RoutingDecision.IN_THREAD:
            thread = message.channel
        else:
            logger.warning("unknown routing decision: %s", decision)
            return

        thread_id = str(thread.id)

        await self._memory.append_turn(
            thread_id=thread_id,
            role="user",
            content=message.content,
            user_id=str(message.author.id),
        )

        history = await self._memory.get_turns(thread_id)
        if history and history[-1]["role"] == "user":
            history = history[:-1]

        placeholder = await thread.send(_PLACEHOLDER_TEXT)

        chunks = self._agent_fn(
            system_prompt=self._system_prompt_fn(),
            history=history,
            user_message=message.content,
            tool_registry=self._tool_registry,
            tool_context=self._tool_context_factory(message),
        )
        final_text = await self._stream_writer_fn(placeholder, chunks)

        await self._memory.append_turn(
            thread_id=thread_id,
            role="assistant",
            content=final_text or _EMPTY_RESPONSE,
        )
```

(Promote the magic string to a module constant `_EMPTY_RESPONSE = "(empty response)"` at the top of the file — addresses a final-review nit from PR 2.)

Also update the `_AgentFn` Protocol signature to include the two new kwargs:

```python
class _AgentFn(Protocol):
    def __call__(
        self,
        *,
        system_prompt: str,
        history: list[dict[str, Any]],
        user_message: str,
        tool_registry: Any,
        tool_context: Any,
    ) -> AsyncIterator[str]: ...
```

- [ ] **Step 9.3: Run events tests**

```bash
.venv/Scripts/python -m pytest bot/tests/test_events.py -v
```

Expected: 6 passed (4 existing + 2 new).

- [ ] **Step 9.4: Update `bot/tests/test_main.py`**

The existing `test_run_constructs_full_dep_graph` patches the deps minimally. Update to also patch the new constructors:

```python
async def test_run_constructs_full_dep_graph(monkeypatch):
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
```

The two existing tests (`test_main_runs_both_subsystems_and_returns_when_one_finishes`, `test_main_cancels_http_when_gateway_raises`) already patch `_build_handler`, so they don't need changes.

- [ ] **Step 9.5: Update `bot/jarvis/main.py`**

Read the file. The plan-relevant changes:

1. Import the new modules.
2. `_build_handler` now also constructs `RateLimiter`, `AsyncGitHubClient`, `ToolRegistry` (calling each `build_*_tool` helper), and a `tool_context_factory`.
3. Pass new args to `OnMessageHandler`.

Final shape of `_build_handler` (rest of `main.py` is unchanged from PR 2):

```python
def _build_handler(settings: Settings) -> OnMessageHandler:
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is required for PR 2 chat. "
            "Set it in .env or Secret Manager."
        )
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    fs_kwargs = {}
    if settings.gcp_project_id:
        fs_kwargs["project"] = settings.gcp_project_id
    firestore_client = AsyncFirestoreClient(**fs_kwargs)
    memory = ThreadMemory(firestore_client)

    rate_limiter = InMemoryRateLimiter(
        max_per_window=20, window_seconds=3600.0
    )

    # Tool registry — only wired if a GitHub token is present. Without
    # it the bot still works (PR 2 behavior); with it the agent can
    # ground answers in repo state.
    tool_registry = None
    github_client = None
    if settings.github_token:
        github_client = AsyncGitHubClient(token=settings.github_token)
        tool_registry = ToolRegistry()
        tool_registry.register(
            build_get_current_sprint_tool(
                github_client=github_client,
                project_id=settings.github_project_id,
            )
        )
        tool_registry.register(
            build_get_recent_commits_tool(
                github_client=github_client,
                repo=settings.github_repo,
            )
        )
        tool_registry.register(
            build_search_repo_docs_tool(
                docs_root=Path("docs"),
            )
        )
        logger.info(
            "tool registry: %s", ", ".join(tool_registry.names())
        )
    else:
        logger.info(
            "GITHUB_TOKEN not set — running without repo-grounding tools"
        )

    async def agent_fn(
        *, system_prompt, history, user_message, tool_registry, tool_context
    ):
        async for d in agent_respond(
            anthropic_client=anthropic_client,
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
            tool_registry=tool_registry,
            tool_context=tool_context,
        ):
            yield d

    def make_tool_context(message: Any) -> ToolContext:
        return ToolContext(
            guild=getattr(message, "guild", None),
            github_client=github_client,
            github_repo=settings.github_repo,
            github_project_id=settings.github_project_id,
            docs_root=Path("docs"),
        )

    return OnMessageHandler(
        bot_user_id=0,
        memory=memory,
        agent_fn=agent_fn,
        system_prompt_fn=build_system_prompt,
        stream_writer_fn=stream_to_discord,
        rate_limiter=rate_limiter,
        tool_registry=tool_registry,
        tool_context_factory=make_tool_context,
    )
```

Add the corresponding imports at the top:

```python
from pathlib import Path
from typing import Any

from jarvis.github_client import AsyncGitHubClient
from jarvis.ratelimit import InMemoryRateLimiter
from jarvis.tools import ToolContext, ToolRegistry
from jarvis.tools.docs import build_search_repo_docs_tool
from jarvis.tools.github import build_get_recent_commits_tool
from jarvis.tools.sprint import build_get_current_sprint_tool
```

- [ ] **Step 9.6: Run main tests**

```bash
.venv/Scripts/python -m pytest bot/tests/test_main.py -v
```

Expected: 3 passed.

- [ ] **Step 9.7: Run the full bot suite**

```bash
.venv/Scripts/python -m pytest bot/tests -v
```

Expected: all green. Count target: PR 2's 48 + 1 (config) + 5 (ratelimit) + 6 (github_client) + 6 (registry) + 4 (sprint) + 4 (github tools) + 6 (docs) + 3 (agent — 8 total minus 5 replaced) + 0 (system_prompt — replacement) + 2 (events) + 0 (main — extended in place) = **85 passing**.

If the count differs by a couple, audit the test additions; the per-task counts above are the source of truth.

- [ ] **Step 9.8: Commit**

```bash
git add bot/jarvis/events.py bot/jarvis/main.py bot/tests/test_events.py bot/tests/test_main.py
git commit -m "feat(bot): wire rate limiter + tool registry into events + main

OnMessageHandler grows rate_limiter, tool_registry, and a
tool_context_factory. Rate-limited callers get a one-line reply in
the original channel and don't spawn a thread. agent_fn forwards the
registry + context into agent.respond.

main._build_handler constructs the registry only when GITHUB_TOKEN
is set; without a token the bot still runs (PR 2 behavior). Adds a
20/hour InMemoryRateLimiter for every user.

Promotes the (empty response) fallback string to a module constant
in events.py — addresses a final-review nit from PR 2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Final cross-implementation review + manual smoke + PR

**Files:** none modified.

- [ ] **Step 10.1: Run the full bot suite one more time**

```bash
.venv/Scripts/python -m pytest bot/tests -v
```

Expected: 85 passed. Note the count for the PR description.

- [ ] **Step 10.2: Run the root suite**

```bash
.venv/Scripts/python -m pytest 2>&1 | tail -10
```

Expected: bot green; backend `lameenc`/`tzdata` errors are pre-existing (carried from PR 1). No new collisions.

- [ ] **Step 10.3: Manual smoke gate — TOOL EDITION**

Same setup as PR 2's smoke gate, plus:

1. `.env` has `GITHUB_TOKEN` set to a PAT with `read:org` + `repo` scopes.
2. Run `python -m jarvis.main` (PowerShell or bash form).
3. In your dev guild, post `@<bot> what shipped this week?`.
4. Verify:
   - The placeholder appears.
   - Streaming text mentions specific commits with short SHAs and links (proving `get_recent_commits` ran).
   - The reply is grounded — no fabricated commit titles.
5. Try `@<bot> what's our current sprint?` — answer should mention live sprint state from the project board.
6. Try `@<bot> where is Twilio configured?` — answer should cite a docs/ path.
7. Spam-test: send 21 mentions in quick succession from one account. After the 20th, you should get a "rate limit reached" reply and no thread for the 21st.
8. **Critical model-ID check:** if any of the above immediately fails with an Anthropic 400/404 mentioning the model name, the floating `claude-sonnet-4-6` ID isn't recognized. Update `bot/jarvis/agent.py:25` to the dated form (the SDK's error message will give the exact ID it expects) and re-run.

If any step fails, fix before opening the PR.

- [ ] **Step 10.4: Push and open the PR**

```bash
git push -u origin feat/jarvis-bot-pr3a-tools
gh pr create --title "Jarvis 2.0 — PR 3a: agent tool-use loop + first three tools" --body "$(cat <<'EOF'
## Summary

PR 3a of 6+ in the Jarvis bot replacement build. Splits spec PR 3 into 3a (this PR) and 3b (next PR).

- **Tool-use loop** in `agent.respond`: Sonnet 4.6 with `tools=[...]`; max 6 round-trips before bailing with a safety message.
- **Tool registry + context**: `ToolRegistry.dispatch(name, input, context)` returns a JSON string for Anthropic's `tool_result.content`; tools opt into `ToolContext` via `wants_context=True`.
- **Three tools** (read-only):
  - `get_current_sprint` — GraphQL against the niko project board, In-progress-first selection.
  - `get_recent_commits` — REST against `tsuki-works/niko`, default master / last 10.
  - `search_repo_docs` — substring grep over `docs/`, capped at 25 results.
- **Per-user rate limit**: 20 calls / 3600s sliding window, in-memory. Rate-limited callers get a one-line channel reply and no thread.
- **System prompt** updated to enumerate the available tools and the still-missing capabilities (deferred to PR 3b).

Plan: `docs/superpowers/plans/2026-05-01-jarvis-pr3a-tools.md`
Spec: `docs/superpowers/specs/2026-05-01-jarvis-bot-design.md` §6 + §9.

## Out of scope

- `get_pr`, `get_issue`, `open_issue`, `get_recent_messages` → **PR 3b**.
- Slash commands → PR 4. GCE deploy → PR 5. MCP shim → PR 6.

## Spec deltas (acknowledged in plan)

1. **`search_repo_docs` reads the local `docs/` directory**, not a fresh git clone refreshed hourly. Pragmatic for PR 3a (bot runs from the repo); PR 5 deploy revisits.
2. **GitHub auth is a PAT**, not a GitHub App. PR 5 swaps when Secret Manager is wired up.

## Test plan

- [x] `.venv/Scripts/python -m pytest bot/tests -v` → **85 passed**
- [x] Per-task spec + code-quality reviews (10 commits, each gated)
- [x] Final cross-implementation review
- [ ] **Manual smoke gate (do before merging):**
  - [ ] `.env` has `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, plus PR 1/2's `DISCORD_BOT_TOKEN`/`DISCORD_GUILD_ID`/(optional)`GCP_PROJECT_ID`.
  - [ ] PowerShell: `$env:PYTHONPATH = "bot"; .venv\Scripts\python -m jarvis.main`.
  - [ ] `@bot what shipped this week?` → grounded reply with real commit SHAs + links.
  - [ ] `@bot what's our current sprint?` → live sprint state.
  - [ ] `@bot where is Twilio configured?` → cites a docs/ path.
  - [ ] Spam 21 messages from one account → 21st gets "rate limit reached", no thread.
  - [ ] **Model ID check**: if Anthropic returns 400/404 on the model name, update `agent.py:25` to the dated `claude-sonnet-4-6-YYYYMMDD` form per the SDK's error message.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review (run after writing the plan, before handoff)

**Spec coverage for PR 3a:**
- Spec §4.2 step 4 ("Agent runs the Claude tool-use loop") → Task 7.
- Spec §6 tool list — three of the seven implemented in 3a → Tasks 4, 5, 6. Remaining four called out as PR 3b.
- Spec §9 guardrails → rate limiter (Task 1) + MAX_TOOL_STEPS=6 (Task 7).
- Spec §3 stack — Sonnet 4.6, prompt caching, async — preserved from PR 2 + extended with tool-use.

**Placeholder scan:** No "TBD" / "implement later" / "fill in details" / "similar to Task N" anywhere in the plan body.

**Type / name consistency:**
- `ToolDescriptor(name, description, input_schema, fn, wants_context=False)` — defined Task 3, used Tasks 4/5/6 and `register()` calls in Task 9.
- `ToolContext(guild, github_client, github_repo, github_project_id, docs_root)` — defined Task 3, constructed in `make_tool_context` (Task 9).
- `ToolRegistry.dispatch(name=..., tool_input=..., context=...)` — Task 3 signature; called in Task 7 agent loop with the same kwargs.
- `build_get_current_sprint_tool(github_client=, project_id=)` — Task 4; called Task 9.
- `build_get_recent_commits_tool(github_client=, repo=)` — Task 5; called Task 9.
- `build_search_repo_docs_tool(docs_root=)` — Task 6; called Task 9.
- `InMemoryRateLimiter(max_per_window=, window_seconds=)` — Task 1; constructed Task 9.
- `respond(..., tool_registry=, tool_context=)` — Task 7; called by `agent_fn` closure Task 9.
- `OnMessageHandler(..., rate_limiter=, tool_registry=, tool_context_factory=)` — Task 9; constructed `_build_handler` Task 9.
- `AsyncGitHubClient(token=, httpx_client=)` — Task 2; constructed Task 9.

**Spec deltas:** Both documented at the top (search_repo_docs simplification, PAT vs App).

No fixes required from review.

---

## Handoff

After PR 3a merges:

- **Plan 3b:** the four remaining tools — `get_pr`, `get_issue`, `open_issue` (in `tools/github.py`), and `get_recent_messages` (in a new `tools/chat.py`). Same registry/context infrastructure, more endpoints + Discord channel-history reads. Estimated ~6 tasks.
- **Plan 4:** slash commands.
- **Plan 5:** GCE deploy + Secret Manager wiring + GitHub App migration + docs-clone refresh.
- **Plan 6:** custom MCP shim, retire `@quadslab.io/discord-mcp`.
