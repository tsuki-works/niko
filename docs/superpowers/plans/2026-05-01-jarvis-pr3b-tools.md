# Jarvis 2.0 — PR 3b: Remaining Four Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the four tools deferred from PR 3a — `get_pr`, `get_issue`, `open_issue` (extending `bot/jarvis/tools/github.py`), and `get_recent_messages` (new `bot/jarvis/tools/chat.py`). After this PR the bot can read PR/issue context, file new issues with a label allowlist, and pull recent Discord channel history to ground its replies.

**Architecture:** Same patterns as PR 3a — each tool is a `build_<name>_tool(...)` factory that closes over its deps and returns a `ToolDescriptor`. The three GitHub tools reuse the existing `AsyncGitHubClient`. `get_recent_messages` is the first tool that needs `wants_context=True` because it reads the live `discord.Guild` from the per-message `ToolContext`. `open_issue` validates labels against a hardcoded allowlist; main.py passes the allowlist to the factory.

**Tech Stack:** Python 3.12, `anthropic` async SDK with tool-use (already wired in PR 3a), existing `AsyncGitHubClient` for REST, `discord.py` 2.x for channel history.

**Out of scope (later PRs):** Slash commands → PR 4. GCE deploy + GitHub App migration → PR 5. Custom MCP shim → PR 6.

**Spec reference:** `docs/superpowers/specs/2026-05-01-jarvis-bot-design.md` §6 (tool list — last four entries).

**No spec deltas in 3b** — all four tools are exactly as specified.

---

## File Structure

**Created in this PR:**

```
bot/jarvis/tools/
└── chat.py                    # build_get_recent_messages_tool — uses ToolContext.guild

bot/tests/
└── test_tools_chat.py
```

**Modified in this PR:**

- `bot/jarvis/tools/github.py` — append three new factories: `build_get_pr_tool`, `build_get_issue_tool`, `build_open_issue_tool`.
- `bot/tests/test_tools_github.py` — append tests for the three new tools.
- `bot/jarvis/system_prompt.py` — replace the "PR 3b coming" paragraph with the full seven-tool catalog; update module docstring.
- `bot/tests/test_system_prompt.py` — update `test_system_prompt_lists_available_tools` to assert on all seven tool names.
- `bot/jarvis/main.py` — register the four new tools in `_build_handler`. Hardcode `_OPEN_ISSUE_LABEL_ALLOWLIST` and pass it to `build_open_issue_tool`.

**NOT modified in this PR:**

- `bot/jarvis/agent.py` — tool-use loop unchanged from PR 3a.
- `bot/jarvis/events.py` — orchestrator unchanged.
- `bot/jarvis/ratelimit.py` — rate limiter unchanged.
- `bot/jarvis/github_client.py` — already has `.get()` and `.post()`; both reused as-is.
- `bot/jarvis/tools/__init__.py` — `ToolRegistry` / `ToolContext` / `ToolDescriptor` unchanged.

---

## Conventions (read once, apply throughout)

- **`get_pr`, `get_issue`, `open_issue`** all live in `bot/jarvis/tools/github.py`. They share the existing `AsyncGitHubClient` injected at factory time. The factory closes over `github_client` + `repo`.
- **`open_issue` allowlist semantics**: requested labels NOT in the allowlist are silently dropped from the API call; the response includes a `dropped_labels` field listing them so the model knows. Allowlist is `["bug", "feature", "docs", "chore", "question"]` for v1 (issues opened by the bot are limited to this set).
- **`get_recent_messages` channel resolution**: the model passes `channel` as either a numeric ID string ("1495192027913130074") or a name (`"general"` or `"#general"`). The tool resolves via `guild.get_channel(int(...))` for the ID path or iterates `guild.text_channels` matching by lowercase name otherwise. Returns `{"error": ...}` if the guild is None or the channel can't be resolved.
- **Channel allowlist (spec §9)**: implicitly satisfied — the tool only ever looks at `guild.text_channels` of the bot's own guild. DMs and other-server channels are unreachable by construction. Document this in the tool docstring.
- **`get_recent_messages` is the first `wants_context=True` tool** in the codebase. Test fixtures need to construct a `ToolContext` with a fake `discord.Guild`.
- **Tests never hit live GitHub or live Discord.** GitHub gets `AsyncMock`; Discord gets a small fake `FakeGuild`/`FakeTextChannel` with an async-iter `.history()`.
- **Commit style** matches PR 1/2/3a — `feat(bot): …`, `chore(bot): …`, short body explaining why.

---

## Task 1: `build_get_pr_tool` in `bot/jarvis/tools/github.py`

**Files:**
- Modify: `bot/jarvis/tools/github.py` (append)
- Modify: `bot/tests/test_tools_github.py` (append)

GitHub REST `GET /repos/{repo}/pulls/{number}` returns the full PR object. We extract a compact subset: `{title, state, author, body, files_changed, url}`.

- [ ] **Step 1.1: Write the failing test**

Read `bot/tests/test_tools_github.py`. Append (after the existing `get_recent_commits` tests):

```python
from jarvis.tools.github import build_get_pr_tool


async def test_get_pr_returns_compact_record():
    raw = {
        "title": "Add Twilio recording",
        "state": "open",
        "user": {"login": "meet"},
        "body": "Closes #42. Adds recording webhook.",
        "changed_files": 5,
        "html_url": "https://github.com/o/r/pull/123",
    }
    gh = AsyncMock()
    gh.get = AsyncMock(return_value=raw)
    desc = build_get_pr_tool(github_client=gh, repo="tsuki-works/niko")
    out = await desc.fn(number=123)
    assert out == {
        "title": "Add Twilio recording",
        "state": "open",
        "author": "meet",
        "body": "Closes #42. Adds recording webhook.",
        "files_changed": 5,
        "url": "https://github.com/o/r/pull/123",
    }
    gh.get.assert_awaited_once_with("/repos/tsuki-works/niko/pulls/123")


async def test_get_pr_handles_null_body():
    raw = {
        "title": "T",
        "state": "closed",
        "user": {"login": "u"},
        "body": None,
        "changed_files": 0,
        "html_url": "u",
    }
    gh = AsyncMock()
    gh.get = AsyncMock(return_value=raw)
    desc = build_get_pr_tool(github_client=gh, repo="o/r")
    out = await desc.fn(number=1)
    assert out["body"] == ""


async def test_get_pr_descriptor_metadata():
    gh = AsyncMock()
    desc = build_get_pr_tool(github_client=gh, repo="o/r")
    assert desc.name == "get_pr"
    assert "pull request" in desc.description.lower() or "pr" in desc.description.lower()
    assert desc.input_schema["properties"]["number"]["type"] == "integer"
    assert desc.input_schema.get("required") == ["number"]
```

- [ ] **Step 1.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_github.py -v
```

Expected: 3 tests fail with `ImportError: cannot import name 'build_get_pr_tool'`. The existing 4 tests for `get_recent_commits` still pass.

- [ ] **Step 1.3: Implement in `bot/jarvis/tools/github.py`**

Read the file. After the existing `build_get_recent_commits_tool` factory, append:

```python
def build_get_pr_tool(
    *, github_client: Any, repo: str
) -> ToolDescriptor:
    async def get_pr(number: int) -> dict[str, Any]:
        raw = await github_client.get(f"/repos/{repo}/pulls/{number}")
        return {
            "title": raw.get("title"),
            "state": raw.get("state"),
            "author": (raw.get("user") or {}).get("login"),
            "body": raw.get("body") or "",
            "files_changed": raw.get("changed_files"),
            "url": raw.get("html_url"),
        }

    return ToolDescriptor(
        name="get_pr",
        description=(
            "Fetch a single pull request from tsuki-works/niko by number. "
            "Returns title, state (open/closed/merged), author, body, "
            "files_changed count, and GitHub URL. Use this when the user "
            "asks 'what does PR #123 do?', 'is #123 ready?', or to read "
            "a PR's description before commenting."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "number": {
                    "type": "integer",
                    "description": "Pull request number (e.g., 191).",
                },
            },
            "required": ["number"],
        },
        fn=get_pr,
    )
```

- [ ] **Step 1.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_github.py -v
```

Expected: 7 passed (4 existing + 3 new).

- [ ] **Step 1.5: Commit**

```bash
git add bot/jarvis/tools/github.py bot/tests/test_tools_github.py
git commit -m "feat(bot): tool — get_pr via GitHub REST

Returns title/state/author/body/files_changed/url for a PR by number.
Reuses the AsyncGitHubClient from PR 3a; extends tools/github.py
rather than creating a new module so all GitHub-REST tools cohabit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `build_get_issue_tool` in `bot/jarvis/tools/github.py`

**Files:**
- Modify: `bot/jarvis/tools/github.py` (append)
- Modify: `bot/tests/test_tools_github.py` (append)

GitHub REST `GET /repos/{repo}/issues/{number}`. Extract `{title, state, body, labels (list of names), assignees (list of logins), url}`.

- [ ] **Step 2.1: Write the failing test**

Append to `bot/tests/test_tools_github.py`:

```python
from jarvis.tools.github import build_get_issue_tool


async def test_get_issue_returns_compact_record():
    raw = {
        "title": "Fix the thing",
        "state": "open",
        "body": "Steps to reproduce: ...",
        "labels": [
            {"name": "bug"},
            {"name": "phase-2"},
        ],
        "assignees": [
            {"login": "meet"},
            {"login": "sandeep"},
        ],
        "html_url": "https://github.com/o/r/issues/45",
    }
    gh = AsyncMock()
    gh.get = AsyncMock(return_value=raw)
    desc = build_get_issue_tool(github_client=gh, repo="o/r")
    out = await desc.fn(number=45)
    assert out == {
        "title": "Fix the thing",
        "state": "open",
        "body": "Steps to reproduce: ...",
        "labels": ["bug", "phase-2"],
        "assignees": ["meet", "sandeep"],
        "url": "https://github.com/o/r/issues/45",
    }
    gh.get.assert_awaited_once_with("/repos/o/r/issues/45")


async def test_get_issue_handles_empty_labels_assignees():
    raw = {
        "title": "T",
        "state": "closed",
        "body": "",
        "labels": [],
        "assignees": [],
        "html_url": "u",
    }
    gh = AsyncMock()
    gh.get = AsyncMock(return_value=raw)
    desc = build_get_issue_tool(github_client=gh, repo="o/r")
    out = await desc.fn(number=1)
    assert out["labels"] == []
    assert out["assignees"] == []


async def test_get_issue_descriptor_metadata():
    gh = AsyncMock()
    desc = build_get_issue_tool(github_client=gh, repo="o/r")
    assert desc.name == "get_issue"
    assert "issue" in desc.description.lower()
    assert desc.input_schema["properties"]["number"]["type"] == "integer"
    assert desc.input_schema.get("required") == ["number"]
```

- [ ] **Step 2.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_github.py -v
```

Expected: 3 new tests fail with `ImportError`. Existing 7 still pass.

- [ ] **Step 2.3: Implement in `bot/jarvis/tools/github.py`**

After `build_get_pr_tool`, append:

```python
def build_get_issue_tool(
    *, github_client: Any, repo: str
) -> ToolDescriptor:
    async def get_issue(number: int) -> dict[str, Any]:
        raw = await github_client.get(f"/repos/{repo}/issues/{number}")
        return {
            "title": raw.get("title"),
            "state": raw.get("state"),
            "body": raw.get("body") or "",
            "labels": [
                (l or {}).get("name") for l in (raw.get("labels") or [])
            ],
            "assignees": [
                (a or {}).get("login") for a in (raw.get("assignees") or [])
            ],
            "url": raw.get("html_url"),
        }

    return ToolDescriptor(
        name="get_issue",
        description=(
            "Fetch a single issue from tsuki-works/niko by number. "
            "Returns title, state, body, labels, assignees, and "
            "GitHub URL. Use this when the user asks 'what's #42 "
            "about?', 'who's working on #42?', or to read an issue "
            "before referencing it. Note that GitHub treats PRs as a "
            "subtype of issues — for PRs prefer get_pr for richer fields."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "number": {
                    "type": "integer",
                    "description": "Issue number (e.g., 42).",
                },
            },
            "required": ["number"],
        },
        fn=get_issue,
    )
```

- [ ] **Step 2.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_github.py -v
```

Expected: 10 passed (7 + 3 new).

- [ ] **Step 2.5: Commit**

```bash
git add bot/jarvis/tools/github.py bot/tests/test_tools_github.py
git commit -m "feat(bot): tool — get_issue via GitHub REST

Returns title/state/body/labels/assignees/url for an issue by number.
labels and assignees are flattened to lists of names/logins so the
model gets directly-usable data instead of nested objects.

Description tells the model to prefer get_pr for PRs (since GitHub
treats PRs as issues at the API level).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `build_open_issue_tool` in `bot/jarvis/tools/github.py` (with label allowlist)

**Files:**
- Modify: `bot/jarvis/tools/github.py` (append)
- Modify: `bot/tests/test_tools_github.py` (append)

GitHub REST `POST /repos/{repo}/issues` with `{title, body, labels?}`. Labels not in the allowlist are silently dropped from the API call but reported back in the result as `dropped_labels` so the model knows what happened.

- [ ] **Step 3.1: Write the failing test**

Append to `bot/tests/test_tools_github.py`:

```python
from jarvis.tools.github import build_open_issue_tool


async def test_open_issue_creates_issue_with_basic_fields():
    raw = {"number": 200, "html_url": "https://github.com/o/r/issues/200"}
    gh = AsyncMock()
    gh.post = AsyncMock(return_value=raw)
    desc = build_open_issue_tool(
        github_client=gh,
        repo="o/r",
        allowed_labels=["bug", "feature"],
    )
    out = await desc.fn(title="Bug: x", body="Steps: ...", labels=["bug"])
    assert out == {"number": 200, "url": "https://github.com/o/r/issues/200"}
    gh.post.assert_awaited_once()
    path, kwargs = gh.post.await_args.args[0], gh.post.await_args.kwargs
    assert path == "/repos/o/r/issues"
    payload = kwargs["json"]
    assert payload["title"] == "Bug: x"
    assert payload["body"] == "Steps: ..."
    assert payload["labels"] == ["bug"]


async def test_open_issue_drops_labels_not_in_allowlist():
    raw = {"number": 201, "html_url": "u"}
    gh = AsyncMock()
    gh.post = AsyncMock(return_value=raw)
    desc = build_open_issue_tool(
        github_client=gh,
        repo="o/r",
        allowed_labels=["bug", "feature"],
    )
    out = await desc.fn(
        title="t", body="b", labels=["bug", "production-incident", "paid"]
    )
    payload = gh.post.await_args.kwargs["json"]
    assert payload["labels"] == ["bug"]
    assert out["dropped_labels"] == ["production-incident", "paid"]


async def test_open_issue_omits_labels_field_when_none_accepted():
    raw = {"number": 202, "html_url": "u"}
    gh = AsyncMock()
    gh.post = AsyncMock(return_value=raw)
    desc = build_open_issue_tool(
        github_client=gh,
        repo="o/r",
        allowed_labels=["bug"],
    )
    out = await desc.fn(title="t", body="b", labels=["foo", "bar"])
    payload = gh.post.await_args.kwargs["json"]
    assert "labels" not in payload  # don't send empty list
    assert out["dropped_labels"] == ["foo", "bar"]


async def test_open_issue_handles_no_labels_kwarg():
    raw = {"number": 203, "html_url": "u"}
    gh = AsyncMock()
    gh.post = AsyncMock(return_value=raw)
    desc = build_open_issue_tool(
        github_client=gh,
        repo="o/r",
        allowed_labels=["bug"],
    )
    out = await desc.fn(title="t", body="b")
    payload = gh.post.await_args.kwargs["json"]
    assert "labels" not in payload
    assert "dropped_labels" not in out


async def test_open_issue_descriptor_metadata():
    gh = AsyncMock()
    desc = build_open_issue_tool(
        github_client=gh, repo="o/r", allowed_labels=["bug"]
    )
    assert desc.name == "open_issue"
    assert "open" in desc.description.lower() or "create" in desc.description.lower()
    props = desc.input_schema["properties"]
    assert props["title"]["type"] == "string"
    assert props["body"]["type"] == "string"
    assert props["labels"]["type"] == "array"
    assert props["labels"]["items"]["type"] == "string"
    # title and body required; labels optional.
    assert set(desc.input_schema.get("required", [])) == {"title", "body"}
```

- [ ] **Step 3.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_github.py -v
```

Expected: 5 new tests fail with `ImportError`. Existing 10 still pass.

- [ ] **Step 3.3: Implement in `bot/jarvis/tools/github.py`**

After `build_get_issue_tool`, append:

```python
def build_open_issue_tool(
    *, github_client: Any, repo: str, allowed_labels: list[str]
) -> ToolDescriptor:
    allowed_set = set(allowed_labels)
    allowed_for_doc = ", ".join(sorted(allowed_set)) or "(none)"

    async def open_issue(
        title: str, body: str, labels: list[str] | None = None
    ) -> dict[str, Any]:
        requested = list(labels or [])
        accepted = [l for l in requested if l in allowed_set]
        dropped = [l for l in requested if l not in allowed_set]

        payload: dict[str, Any] = {"title": title, "body": body}
        if accepted:
            payload["labels"] = accepted

        raw = await github_client.post(f"/repos/{repo}/issues", json=payload)

        result: dict[str, Any] = {
            "number": raw.get("number"),
            "url": raw.get("html_url"),
        }
        if dropped:
            result["dropped_labels"] = dropped
        return result

    return ToolDescriptor(
        name="open_issue",
        description=(
            "Open a new GitHub issue in tsuki-works/niko. Returns the new "
            "issue's number and URL. Labels are validated against an "
            f"allowlist ({allowed_for_doc}); any unrecognized labels are "
            "silently dropped and surfaced in 'dropped_labels' in the "
            "response. Use this when the user asks you to file a bug, "
            "feature request, or chore — confirm with the user before "
            "calling unless they explicitly asked you to file."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Issue title (one line).",
                },
                "body": {
                    "type": "string",
                    "description": "Issue body in markdown.",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        f"Optional labels. Allowed: {allowed_for_doc}. "
                        "Other labels are dropped."
                    ),
                },
            },
            "required": ["title", "body"],
        },
        fn=open_issue,
    )
```

- [ ] **Step 3.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_github.py -v
```

Expected: 15 passed (10 + 5 new).

- [ ] **Step 3.5: Commit**

```bash
git add bot/jarvis/tools/github.py bot/tests/test_tools_github.py
git commit -m "feat(bot): tool — open_issue with label allowlist

Posts to /repos/{repo}/issues with title, body, and a filtered
labels list. Labels not in the allowlist are silently dropped from
the API call but surfaced in the result as 'dropped_labels' so the
model knows what happened. Allowlist is passed by main.py at
factory time so different deploys can configure different sets.

Description nudges the model toward 'confirm with the user before
filing unless they asked' — defense in depth alongside the rate
limiter.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `build_get_recent_messages_tool` in new `bot/jarvis/tools/chat.py`

**Files:**
- Create: `bot/jarvis/tools/chat.py`
- Test: `bot/tests/test_tools_chat.py`

First tool that needs `wants_context=True`. Resolves channel by ID (numeric string) or by name (with optional `#` prefix), then iterates `channel.history(limit=n)`. Channel allowlist is implicit — only `guild.text_channels` of the bot's own guild is reachable.

- [ ] **Step 4.1: Write the failing test**

`bot/tests/test_tools_chat.py`:

```python
"""Tests for jarvis.tools.chat.build_get_recent_messages_tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from jarvis.tools import ToolContext
from jarvis.tools.chat import build_get_recent_messages_tool


@dataclass
class FakeAuthor:
    display_name: str = "Meet"


@dataclass
class FakeMessage:
    content: str
    author: FakeAuthor = field(default_factory=FakeAuthor)
    created_at: datetime = field(
        default_factory=lambda: datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    )


class FakeTextChannel:
    def __init__(self, channel_id: int, name: str, messages: list[FakeMessage]):
        self.id = channel_id
        self.name = name
        self._messages = messages

    def history(self, limit: int = 50):
        # discord.py's history returns an async iterator yielding
        # newest-first. Our fake honors the limit.
        msgs = self._messages[:limit]

        async def _iter():
            for m in msgs:
                yield m

        return _iter()


@dataclass
class FakeGuild:
    text_channels: list[FakeTextChannel]
    by_id: dict[int, FakeTextChannel] = field(default_factory=dict)

    def __post_init__(self):
        self.by_id = {c.id: c for c in self.text_channels}

    def get_channel(self, channel_id: int) -> Optional[FakeTextChannel]:
        return self.by_id.get(channel_id)


def _ctx_with_guild(guild: Optional[FakeGuild]) -> ToolContext:
    return ToolContext(
        guild=guild,
        github_client=None,
        github_repo="o/r",
        github_project_id="PVT_x",
        docs_root=None,
    )


async def test_resolves_channel_by_name_and_returns_messages():
    msgs = [
        FakeMessage(content="hello"),
        FakeMessage(content="world"),
    ]
    chan = FakeTextChannel(channel_id=10, name="general", messages=msgs)
    guild = FakeGuild(text_channels=[chan])
    desc = build_get_recent_messages_tool()
    ctx = _ctx_with_guild(guild)
    out = await desc.fn(channel="general", n=10, context=ctx)
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0]["content"] == "hello"
    assert out[0]["author"] == "Meet"
    assert "T" in out[0]["timestamp"]  # ISO format


async def test_resolves_channel_with_hash_prefix():
    chan = FakeTextChannel(
        channel_id=11, name="blockers", messages=[FakeMessage(content="x")]
    )
    guild = FakeGuild(text_channels=[chan])
    desc = build_get_recent_messages_tool()
    out = await desc.fn(channel="#blockers", n=5, context=_ctx_with_guild(guild))
    assert len(out) == 1


async def test_resolves_channel_by_numeric_id():
    chan = FakeTextChannel(
        channel_id=99, name="alerts", messages=[FakeMessage(content="a")]
    )
    guild = FakeGuild(text_channels=[chan])
    desc = build_get_recent_messages_tool()
    out = await desc.fn(channel="99", n=5, context=_ctx_with_guild(guild))
    assert len(out) == 1


async def test_returns_error_when_no_guild():
    desc = build_get_recent_messages_tool()
    out = await desc.fn(channel="anything", n=5, context=_ctx_with_guild(None))
    assert "error" in out


async def test_returns_error_when_channel_not_found():
    chan = FakeTextChannel(
        channel_id=10, name="general", messages=[FakeMessage(content="x")]
    )
    guild = FakeGuild(text_channels=[chan])
    desc = build_get_recent_messages_tool()
    out = await desc.fn(channel="ghost", n=5, context=_ctx_with_guild(guild))
    assert "error" in out
    assert "ghost" in out["error"]


async def test_clamps_n_to_safe_range():
    msgs = [FakeMessage(content=str(i)) for i in range(200)]
    chan = FakeTextChannel(channel_id=10, name="general", messages=msgs)
    guild = FakeGuild(text_channels=[chan])
    desc = build_get_recent_messages_tool()
    # n=10000 should clamp to 100 (max)
    out_max = await desc.fn(
        channel="general", n=10000, context=_ctx_with_guild(guild)
    )
    assert len(out_max) == 100
    # n=0 should clamp to 1
    out_min = await desc.fn(
        channel="general", n=0, context=_ctx_with_guild(guild)
    )
    assert len(out_min) == 1


async def test_descriptor_metadata():
    desc = build_get_recent_messages_tool()
    assert desc.name == "get_recent_messages"
    assert "discord" in desc.description.lower() or "channel" in desc.description.lower()
    assert desc.input_schema["properties"]["channel"]["type"] == "string"
    assert "n" in desc.input_schema["properties"]
    assert desc.input_schema.get("required") == ["channel"]
    assert desc.wants_context is True  # this tool needs the ToolContext
```

- [ ] **Step 4.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_chat.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4.3: Implement `bot/jarvis/tools/chat.py`**

```python
"""`get_recent_messages` — read recent Discord channel history.

This is the first tool in PR 3a/3b that needs live Discord state, so
it sets `wants_context=True` and reads `context.guild` at dispatch
time. Channel allowlist (spec §9 — no DMs, no other servers) is
satisfied by construction: we only resolve channels via
`guild.text_channels` of the bot's own guild, so DMs and other-server
channels are unreachable.

Channel resolution accepts either a numeric ID string (e.g.
"1495192027913130074") or a channel name (e.g. "general" or
"#general", case-insensitive).
"""

from __future__ import annotations

from typing import Any, Optional

from jarvis.tools import ToolContext, ToolDescriptor

_MAX_MESSAGES = 100


def _clamp_n(n: int) -> int:
    if n < 1:
        return 1
    if n > _MAX_MESSAGES:
        return _MAX_MESSAGES
    return n


def _resolve_channel(guild: Any, channel: str) -> Optional[Any]:
    """Resolve a channel by numeric id or by case-insensitive name."""
    s = (channel or "").strip()
    if not s:
        return None
    if s.isdigit():
        return guild.get_channel(int(s))
    clean = s.lstrip("#").lower()
    for ch in getattr(guild, "text_channels", []):
        if getattr(ch, "name", "").lower() == clean:
            return ch
    return None


def build_get_recent_messages_tool() -> ToolDescriptor:
    async def get_recent_messages(
        channel: str, n: int = 50, *, context: ToolContext
    ) -> Any:
        guild = context.guild
        if guild is None:
            return {"error": "no guild context — bot is not in a guild"}

        target = _resolve_channel(guild, channel)
        if target is None:
            return {
                "error": (
                    f"channel '{channel}' not found in guild "
                    "(use a #name or numeric id)"
                )
            }

        clamped = _clamp_n(int(n))
        out: list[dict[str, Any]] = []
        async for msg in target.history(limit=clamped):
            author = getattr(msg, "author", None)
            display = getattr(author, "display_name", None) if author else None
            created = getattr(msg, "created_at", None)
            out.append(
                {
                    "author": display or "?",
                    "content": getattr(msg, "content", "") or "",
                    "timestamp": (
                        created.isoformat() if created is not None else None
                    ),
                }
            )
        return out

    return ToolDescriptor(
        name="get_recent_messages",
        description=(
            "Read recent messages from a Discord text channel in the "
            "Tsuki Works guild. Pass `channel` as either a name "
            "('general', '#blockers') or a numeric channel id. "
            "Returns up to 100 messages newest-first as "
            "{author, content, timestamp}. Use this when the user "
            "asks 'what did the team say in #blockers?', 'summarize "
            "today's #ci-alerts', or to ground answers in recent chat."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": (
                        "Channel name (with or without leading '#') or "
                        "numeric channel id."
                    ),
                },
                "n": {
                    "type": "integer",
                    "description": (
                        "How many messages to fetch (1–100, default 50)."
                    ),
                },
            },
            "required": ["channel"],
        },
        fn=get_recent_messages,
        wants_context=True,
    )
```

- [ ] **Step 4.4: Run to verify pass**

```bash
.venv/Scripts/python -m pytest bot/tests/test_tools_chat.py -v
```

Expected: 7 passed.

If `test_resolves_channel_by_name_and_returns_messages` fails because `out[0]["timestamp"]` doesn't have `T` — `datetime.isoformat()` always produces `T` for the date/time separator on aware datetimes, so the assertion holds. If it fails for another reason, inspect the fake's `created_at` plumbing.

- [ ] **Step 4.5: Commit**

```bash
git add bot/jarvis/tools/chat.py bot/tests/test_tools_chat.py
git commit -m "feat(bot): tool — get_recent_messages from Discord history

First wants_context=True tool. Resolves channel by name or numeric
id, reads up to 100 messages newest-first via channel.history(),
returns {author, content, timestamp} per message. Channel allowlist
is implicit — only the bot's own guild.text_channels is reachable,
so DMs and other-server channels can't be queried by construction.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wire all four tools into `_build_handler` + update system prompt

**Files:**
- Modify: `bot/jarvis/main.py`
- Modify: `bot/jarvis/system_prompt.py`
- Modify: `bot/tests/test_system_prompt.py`

`_build_handler` registers the four new tools when `github_token` is set; `get_recent_messages` is registered unconditionally (no token needed). System prompt is updated to enumerate all seven tools.

- [ ] **Step 5.1: Update `bot/tests/test_system_prompt.py`**

Read the file. Find `test_system_prompt_lists_available_tools` and update it to assert on all seven tool names:

```python
def test_system_prompt_lists_available_tools():
    p = build_system_prompt()
    # PR 3b: seven tools available
    assert "get_current_sprint" in p
    assert "get_recent_commits" in p
    assert "search_repo_docs" in p
    assert "get_pr" in p
    assert "get_issue" in p
    assert "open_issue" in p
    assert "get_recent_messages" in p
```

- [ ] **Step 5.2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest bot/tests/test_system_prompt.py -v
```

Expected: `test_system_prompt_lists_available_tools` fails because the prompt doesn't yet mention the four new tools.

- [ ] **Step 5.3: Update `bot/jarvis/system_prompt.py`**

Read the file. Update the module docstring:

```python
"""Static system prompt for Jarvis (PR 3b — seven tools available).

The prompt is constant — every conversation gets the same persona,
team roster, tool list, and hard rules. Future PRs (deploy, MCP shim)
won't change this; only the tool catalog changes.
"""
```

Find the existing tool-list block (added in PR 3a, right after the "You run in the team's private Discord server..." paragraph) and replace it with the seven-tool catalog. The new block:

```
You have a small set of tools you can use to ground your answers. Use them whenever a question would otherwise require you to guess about repo or chat state:

- get_current_sprint — pulls the current sprint from the GitHub Project board (tsuki-works/niko #2). Use for "what are we working on?", "sprint status", "what's blocked?".
- get_recent_commits — last N commits on a branch. Use for "what shipped this week?", "what's in master?", "recent changes".
- search_repo_docs — substring grep over docs/. Use for "where do we configure X?", "what does the doc say about Y?".
- get_pr — fetch a PR by number. Use for "what does PR #N do?", "is #N ready?".
- get_issue — fetch an issue by number. Use for "what's #N about?", "who's working on #N?".
- open_issue — file a new GitHub issue (with a label allowlist). Use for "open an issue for X" — confirm with the user first unless they explicitly asked you to file.
- get_recent_messages — read recent messages from a Discord channel. Use for "what did the team say in #blockers?", "summarize today's #ci-alerts".

If you don't have a tool for what's being asked, say so honestly rather than guessing.
```

(Replaces the existing block from "You have a small set of tools..." through "...say so honestly." — the closing fallback sentence is preserved in spirit but tightened.)

- [ ] **Step 5.4: Run system prompt tests**

```bash
.venv/Scripts/python -m pytest bot/tests/test_system_prompt.py -v
```

Expected: 5 passed.

- [ ] **Step 5.5: Update `bot/jarvis/main.py`**

Read the file. The existing `_build_handler` registers three tools inside `if settings.github_token:`. Update to register the additional GitHub tools there + register `get_recent_messages` (no token needed) outside the token gate.

The simplest concrete edits:

a) Add new imports at the top of `bot/jarvis/main.py`:

```python
from jarvis.tools.chat import build_get_recent_messages_tool
from jarvis.tools.github import (
    build_get_recent_commits_tool,
    build_get_pr_tool,
    build_get_issue_tool,
    build_open_issue_tool,
)
```

(Replace the existing single-import line for `build_get_recent_commits_tool` with the multi-import.)

b) Add the label-allowlist constant near the other module constants (or just above `_build_handler`):

```python
_OPEN_ISSUE_LABEL_ALLOWLIST = ["bug", "feature", "docs", "chore", "question"]
```

c) Inside `_build_handler`, replace the existing tool-registration block. The new shape:

```python
    tool_registry: Optional[ToolRegistry] = None
    github_client = None

    # get_recent_messages doesn't need GitHub — register it
    # unconditionally so the bot can still ground replies in chat
    # history when GITHUB_TOKEN is unset.
    chat_only_registry = ToolRegistry()
    chat_only_registry.register(build_get_recent_messages_tool())

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
            build_search_repo_docs_tool(docs_root=Path("docs"))
        )
        tool_registry.register(
            build_get_pr_tool(
                github_client=github_client,
                repo=settings.github_repo,
            )
        )
        tool_registry.register(
            build_get_issue_tool(
                github_client=github_client,
                repo=settings.github_repo,
            )
        )
        tool_registry.register(
            build_open_issue_tool(
                github_client=github_client,
                repo=settings.github_repo,
                allowed_labels=_OPEN_ISSUE_LABEL_ALLOWLIST,
            )
        )
        tool_registry.register(build_get_recent_messages_tool())
        logger.info(
            "tool registry: %s", ", ".join(tool_registry.names())
        )
    else:
        tool_registry = chat_only_registry
        logger.info(
            "GITHUB_TOKEN not set — running with only chat tools: %s",
            ", ".join(tool_registry.names()),
        )
```

The token-set path registers all seven tools in a single registry. The token-unset path uses the chat-only registry (one tool: `get_recent_messages`).

Reasoning: previously the no-token path returned `tool_registry = None`, and `agent.respond` skipped `tools=` in the API call. With `get_recent_messages` not needing a token, we should still hand a registry to the model. The agent loop already handles a registry with any subset of tools.

- [ ] **Step 5.6: Run main + events tests**

```bash
.venv/Scripts/python -m pytest bot/tests/test_main.py bot/tests/test_events.py -v
```

Expected: still passing (PR 3a's `test_run_constructs_full_dep_graph` patches `AsyncGitHubClient` and only asserts `on_message_handler is not None`, which still holds; events tests are unaffected).

- [ ] **Step 5.7: Run the full bot suite**

```bash
.venv/Scripts/python -m pytest bot/tests -v
```

Expected: **103 passed**. Math: PR 3a's 85 + 18 net new from PR 3b (3 `get_pr` + 3 `get_issue` + 5 `open_issue` + 7 `get_recent_messages`). The two extended-in-place tests (`test_run_constructs_full_dep_graph` and `test_system_prompt_lists_available_tools`) don't change the count; they're modifications, not additions.

Per-file audit if the number differs:
- `test_tools_github.py`: 4 (existing) + 11 (new from Tasks 1–3) = **15**
- `test_tools_chat.py`: **7** new
- Everything else unchanged from PR 3a.

- [ ] **Step 5.8: Commit**

```bash
git add bot/jarvis/main.py bot/jarvis/system_prompt.py bot/tests/test_system_prompt.py
git commit -m "feat(bot): wire PR 3b tools + update system prompt to seven-tool catalog

main._build_handler registers get_pr, get_issue, open_issue alongside
the PR-3a GitHub tools (all gated on GITHUB_TOKEN). Adds
get_recent_messages, which doesn't need a token, so the bot still has
some grounding even when GITHUB_TOKEN is unset.

open_issue label allowlist is hardcoded in main as
_OPEN_ISSUE_LABEL_ALLOWLIST = [bug, feature, docs, chore, question].

System prompt enumerates all seven tools and drops the
'PR 3b coming' caveat.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Final cross-implementation review + manual smoke + PR

**Files:** none modified.

- [ ] **Step 6.1: Run the full bot suite one more time**

```bash
.venv/Scripts/python -m pytest bot/tests -v
```

Expected: 103 passed. Note the count for the PR description.

- [ ] **Step 6.2: Run the root suite**

```bash
.venv/Scripts/python -m pytest 2>&1 | tail -10
```

Expected: bot green; backend `lameenc`/`tzdata` collection errors are pre-existing (carried from PR 1).

- [ ] **Step 6.3: Manual smoke gate — PR 3b edition**

Setup carries forward from PR 3a (`.env` has `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, etc.).

1. Run `python -m jarvis.main`.
2. In your dev guild: `@<bot> what does PR #191 do?` → tool-use round-trip with `get_pr`, then a grounded summary.
3. `@<bot> what's #42 about?` → `get_issue` round-trip + summary including labels and assignees.
4. `@<bot> file an issue: title "test issue", body "ignore me", label "bug"` → bot confirms first, then `open_issue` runs and the bot reports the new issue's number + URL. Verify the issue appears on GitHub.
5. `@<bot> file an issue with label "production-incident"` → bot files it but reports `dropped_labels`.
6. `@<bot> what did the team say in #blockers?` → `get_recent_messages` reads the channel history and the bot summarizes.
7. `@<bot> what's in #nonexistent?` → bot gets `{error: ...}` from the tool and surfaces the error.

If any step fails, fix before opening the PR.

- [ ] **Step 6.4: Push and open the PR**

```bash
git push -u origin feat/jarvis-bot-pr3b-tools
gh pr create --title "Jarvis 2.0 — PR 3b: remaining four tools (get_pr, get_issue, open_issue, get_recent_messages)" --body "$(cat <<'EOF'
## Summary

PR 3b of 6+ in the Jarvis bot replacement build. Completes spec PR 3 (3a + 3b). After this PR the agent has the full seven-tool catalog from spec §6.

- **`get_pr`** — REST `GET /repos/{repo}/pulls/{n}` → compact `{title, state, author, body, files_changed, url}`.
- **`get_issue`** — REST `GET /repos/{repo}/issues/{n}` → compact `{title, state, body, labels, assignees, url}`.
- **`open_issue`** — REST `POST /repos/{repo}/issues` with title + body + filtered labels. Allowlist: `bug, feature, docs, chore, question`. Dropped labels surface in the result so the model knows.
- **`get_recent_messages`** — first `wants_context=True` tool. Reads `discord.Guild.text_channels` of the bot's own guild via `channel.history(limit=n)`. Channel allowlist (spec §9 — no DMs, no other servers) is implicit by construction.
- **System prompt** updated to enumerate all seven tools; module docstring bumps to "PR 3b — seven tools available".

Plan: `docs/superpowers/plans/2026-05-01-jarvis-pr3b-tools.md`.

## Bonus: bot still works without GITHUB_TOKEN

PR 3a's no-token path returned `tool_registry=None`. PR 3b adds a chat-only registry (just `get_recent_messages`) for that path so the bot can still ground replies in Discord history when GitHub creds are absent. Six GitHub tools remain gated on `GITHUB_TOKEN`.

## Out of scope

Slash commands → PR 4. GCE deploy + GitHub App migration → PR 5. Custom MCP shim → PR 6.

## Test plan

- [x] `.venv/Scripts/python -m pytest bot/tests -v` → **103 passed**
- [x] Per-task spec + code-quality reviews (5 commits, each gated)
- [x] Final cross-implementation review
- [ ] **Manual smoke gate (do before merging):**
  - [ ] `@bot what does PR #191 do?` → grounded summary via `get_pr`.
  - [ ] `@bot what's #42 about?` → grounded summary via `get_issue`.
  - [ ] `@bot file a test issue with body "ignore me"` → confirms first, then opens; `open_issue` returns number + URL.
  - [ ] `@bot file with label "production-incident"` → opens with no labels + `dropped_labels` in result.
  - [ ] `@bot what did the team say in #blockers?` → reads + summarizes via `get_recent_messages`.
  - [ ] `@bot what's in #nonexistent?` → tool returns error, bot surfaces it.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review (run after writing the plan, before handoff)

**Spec coverage for PR 3b:**
- Spec §6 entries 4–7 (`get_pr`, `get_issue`, `open_issue`, `get_recent_messages`) → Tasks 1–4.
- Spec §6 `open_issue` label allowlist → Task 3 with `_OPEN_ISSUE_LABEL_ALLOWLIST`.
- Spec §6 `get_recent_messages` "Channel allowlist (no DMs, no other servers)" → satisfied by construction (Task 4 docstring + the `guild.text_channels` lookup).
- Spec §9 — rate limiter and tool-step cap inherited from PR 3a, no new work.

**Placeholder scan:** No "TBD" / "implement later" / "fill in details" anywhere.

**Type / name consistency:**
- `build_get_pr_tool(*, github_client, repo)` — Task 1 factory, used in Task 5 main.
- `build_get_issue_tool(*, github_client, repo)` — Task 2, used Task 5.
- `build_open_issue_tool(*, github_client, repo, allowed_labels)` — Task 3 (note: `allowed_labels` is keyword-only required), used Task 5 with the `_OPEN_ISSUE_LABEL_ALLOWLIST` constant.
- `build_get_recent_messages_tool()` — Task 4 (no kwargs — closes over nothing), used Task 5. Sets `wants_context=True` so the registry passes the per-message context.
- `ToolContext.guild` — populated in PR 3a's `make_tool_context(message)`, consumed in Task 4's `get_recent_messages`.
- All four tools return JSON-friendly dicts/lists; `ToolRegistry.dispatch` serializes via `json.dumps(..., default=str)`.

**Spec deltas:** None. PR 3b is a faithful implementation of the four spec entries.

**Test count audit:** PR 3a left 85. PR 3b adds 11 (github tests) + 7 (chat tests) = 18. Total: 103.

No fixes required from review.

---

## Handoff

After PR 3b merges, the spec PR 3 is complete. Next:

- **Plan 4:** slash commands (`/sprint`, `/blockers`, `/issue`, `/ask`, `/digest`).
- **Plan 5:** GCE deploy + Secret Manager + GitHub App migration + docs-clone refresh.
- **Plan 6:** custom MCP shim, retire `@quadslab.io/discord-mcp`.
