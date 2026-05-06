# Jarvis 2.0 — Scheduled Jobs Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the full scheduled-jobs runtime described in `docs/superpowers/specs/2026-05-06-jarvis-scheduled-jobs-design.md` — framework, six kinds, seven jobs, manifest, channel routing, self-reporting, manual-trigger CLI, and `main.py` wiring — in a single feature branch.

**Architecture:** `apscheduler.schedulers.asyncio.AsyncIOScheduler` runs alongside the existing Discord gateway in `jarvis.main.run()`. Each cron fire calls `JobExecutor.run(job)`, which resolves the kind from a registry, calls a kind handler that returns `KindResult(posts, state_writes, summary)`, sends posts (with Firestore-backed dedup), and emits a self-report into `#jarvis`. Kinds use the existing `AsyncGitHubClient` and reuse helpers from `tools/sprint.py`. Digest kinds make a constrained Anthropic call (`tools=[]`) for prose polish; deterministic kinds use templates only.

**Tech Stack:** Python 3.12, APScheduler 3.x, existing `discord.py`, `httpx`, `pydantic-settings`, `google-cloud-firestore`, `anthropic` async SDK.

**Spec reference:** `docs/superpowers/specs/2026-05-06-jarvis-scheduled-jobs-design.md`.

---

## File Structure

**Created in this PR:**

```
bot/jarvis/jobs/
├── __init__.py                  # Job, KindContext, KindResult, PlannedPost dataclasses
├── manifest.py                  # JOBS list (v1 manifest)
├── executor.py                  # JobExecutor
├── scheduler.py                 # build_scheduler() + validate_manifest()
├── channels.py                  # CHANNEL_IDS + resolve()
├── team.py                      # GH_LOGIN_TO_DISCORD + mention()
├── state.py                     # FirestoreJobState
├── self_report.py               # SelfReporter
├── github_queries.py            # list_open_prs / list_pr_reviews / list_check_runs / list_dependabot_prs
├── run.py                       # CLI entrypoint: python -m jarvis.jobs.run <name>
└── kinds/
    ├── __init__.py              # KIND_REGISTRY
    ├── pr_review_nudge.py
    ├── approved_pr_not_merged.py
    ├── ci_red_pr_nudge.py
    ├── dependabot_pair_check.py
    ├── stuck_in_progress.py
    └── digest_via_agent.py

bot/tests/
├── test_jobs_types.py
├── test_jobs_channels.py
├── test_jobs_team.py
├── test_jobs_state.py
├── test_jobs_self_report.py
├── test_jobs_executor.py
├── test_jobs_scheduler.py
├── test_jobs_manifest.py
├── test_jobs_github_queries.py
├── test_jobs_run_cli.py
├── test_jobs_kind_pr_review_nudge.py
├── test_jobs_kind_approved_pr_not_merged.py
├── test_jobs_kind_ci_red_pr_nudge.py
├── test_jobs_kind_dependabot_pair_check.py
├── test_jobs_kind_stuck_in_progress.py
└── test_jobs_kind_digest_via_agent.py
```

**Modified:**

- `bot/requirements.txt` — add `apscheduler>=3.10,<4.0`
- `bot/jarvis/main.py` — wire scheduler, executor, self-reporter; call boot self-report on `on_ready`
- `CLAUDE.md` — drop `#okrs-roadmap` from channel-IDs list; add `#weekly-sync`, `#milestones-updates`, `#infra`, `#backend`, `#frontend`, `#demos`

**Deleted:**

- `.github/workflows/jarvis-discord.yml` — replaced by bot's own self-report path

---

## Conventions (read once, apply throughout)

- **Python 3.12 syntax.** `from __future__ import annotations` at the top of every module.
- **No imports of `discord.py` types in business logic.** Only `executor.py`, `self_report.py`, `run.py`, `main.py` touch `discord`. Kind modules use `Any` for `discord_channel`.
- **All async I/O.** Even one-shot Firestore reads use the AsyncClient already wired by `main.py`.
- **Time:** `datetime.now(timezone.utc)` everywhere. Cron timezones are per-job, but stored timestamps are always UTC.
- **No `discord.py` mocks in kind tests.** Kinds return `KindResult` — the executor is the only thing that posts. So kind tests assert `KindResult` directly.
- **Test naming:** `test_jobs_<module>.py` for non-kind tests; `test_jobs_kind_<name>.py` for kinds.
- **Commit style:** `feat(bot): jobs - <what>`, `chore(bot): jobs - <what>`, `test(bot): jobs - <what>`. Keep messages tight; the spec/plan supply context.
- **Branch:** all commits land on `feat/jarvis-scheduled-jobs-spec` (already created with the spec commit). No master commits.
- **One step per commit** — if a step says "Commit", that's the boundary. Don't accumulate.
- **Run pytest from repo root** with `PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests -v` (Windows) or `PYTHONPATH=bot .venv/bin/python -m pytest bot/tests -v` (POSIX). The plan uses the Windows form.
- **Imports:** absolute (`from jarvis.jobs.state import ...`), never relative.

---

## Task 1: Add APScheduler dependency + create skeleton dirs

**Files:**
- Modify: `bot/requirements.txt`
- Create: `bot/jarvis/jobs/__init__.py` (empty placeholder)
- Create: `bot/jarvis/jobs/kinds/__init__.py` (empty placeholder)

- [ ] **Step 1.1: Add APScheduler to requirements**

Edit `bot/requirements.txt`. Append a line:

```
apscheduler>=3.10,<4.0
```

- [ ] **Step 1.2: Install it**

```bash
.venv/Scripts/python -m pip install -r bot/requirements.txt
```

Expected: `Successfully installed APScheduler-3.x.x` (or "already satisfied" if it slipped in earlier).

- [ ] **Step 1.3: Create empty `__init__.py` files**

```bash
mkdir -p bot/jarvis/jobs/kinds
touch bot/jarvis/jobs/__init__.py bot/jarvis/jobs/kinds/__init__.py
```

- [ ] **Step 1.4: Verify import works**

```bash
PYTHONPATH=bot .venv/Scripts/python -c "import jarvis.jobs; import jarvis.jobs.kinds; print('ok')"
```

Expected: `ok`.

- [ ] **Step 1.5: Commit**

```bash
git add bot/requirements.txt bot/jarvis/jobs/__init__.py bot/jarvis/jobs/kinds/__init__.py
git commit -m "chore(bot): jobs - add apscheduler dep + skeleton dirs"
```

---

## Task 2: Core types — `Job`, `KindContext`, `KindResult`, `PlannedPost`

**Files:**
- Modify: `bot/jarvis/jobs/__init__.py`
- Create: `bot/tests/test_jobs_types.py`

- [ ] **Step 2.1: Write the failing test**

Create `bot/tests/test_jobs_types.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jarvis.jobs import Job, KindContext, KindResult, PlannedPost


def test_job_is_frozen_dataclass():
    job = Job(name="x", kind="y", cron="* * * * *", channel="#c")
    with pytest.raises(Exception):
        job.name = "renamed"  # type: ignore[misc]


def test_job_defaults():
    job = Job(name="x", kind="y", cron="* * * * *", channel="#c")
    assert job.timezone == "America/Toronto"
    assert job.params == {}
    assert job.enabled is True


def test_planned_post_dedup_key_optional():
    p = PlannedPost(content="hello")
    assert p.dedup_key is None


def test_kind_result_default_state_writes():
    r = KindResult(posts=[])
    assert r.state_writes == {}
    assert r.summary == ""


def test_kind_context_construction():
    now = datetime.now(timezone.utc)
    ctx = KindContext(
        job=Job(name="x", kind="y", cron="* * * * *", channel="#c"),
        discord_channel=object(),
        github_client=object(),
        anthropic_client=object(),
        state=object(),
        now=now,
        settings=object(),
        logger=object(),
    )
    assert ctx.now is now
    assert ctx.job.name == "x"
```

- [ ] **Step 2.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_types.py -v
```

Expected: ImportError / `cannot import name 'Job'`.

- [ ] **Step 2.3: Write the implementation**

Replace `bot/jarvis/jobs/__init__.py` with:

```python
"""Core types for the scheduled-jobs framework.

Manifest entries are `Job` dataclasses. Kinds are async callables that
take a `KindContext` and return a `KindResult` — a list of `PlannedPost`s
the executor will send, plus state writes and a one-line self-report
summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional


@dataclass(frozen=True)
class Job:
    name: str
    kind: str
    cron: str
    channel: str
    timezone: str = "America/Toronto"
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class PlannedPost:
    content: str
    dedup_key: Optional[str] = None


@dataclass
class KindResult:
    posts: list[PlannedPost]
    state_writes: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


@dataclass
class KindContext:
    job: Job
    discord_channel: Any
    github_client: Any
    anthropic_client: Any
    state: Any  # FirestoreJobState — Any to avoid circular import in this module
    now: datetime
    settings: Any
    logger: Any


KindHandler = Callable[[KindContext], Awaitable[KindResult]]
```

- [ ] **Step 2.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_types.py -v
```

Expected: 5 passed.

- [ ] **Step 2.5: Commit**

```bash
git add bot/jarvis/jobs/__init__.py bot/tests/test_jobs_types.py
git commit -m "feat(bot): jobs - core types (Job, KindContext, KindResult, PlannedPost)"
```

---

## Task 3: Channel registry — `channels.py`

**Files:**
- Create: `bot/jarvis/jobs/channels.py`
- Create: `bot/tests/test_jobs_channels.py`

- [ ] **Step 3.1: Write the failing test**

Create `bot/tests/test_jobs_channels.py`:

```python
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
```

- [ ] **Step 3.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_channels.py -v
```

Expected: ImportError.

- [ ] **Step 3.3: Implement `channels.py`**

Create `bot/jarvis/jobs/channels.py`:

```python
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
```

- [ ] **Step 3.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_channels.py -v
```

Expected: 4 passed.

- [ ] **Step 3.5: Commit**

```bash
git add bot/jarvis/jobs/channels.py bot/tests/test_jobs_channels.py
git commit -m "feat(bot): jobs - channel alias map + resolve()"
```

---

## Task 4: Team mention helper — `team.py`

**Files:**
- Create: `bot/jarvis/jobs/team.py`
- Create: `bot/tests/test_jobs_team.py`

GitHub login → Discord user ID. From `reference_team_ids` memory: Meet's Discord ID is `295016116881850370`. Other teammate IDs are filled in if memory has them; otherwise we leave the dict with just Meet for v1 and the `mention()` fallback handles the rest.

- [ ] **Step 4.1: Write the failing test**

Create `bot/tests/test_jobs_team.py`:

```python
from __future__ import annotations

from jarvis.jobs.team import GH_LOGIN_TO_DISCORD, mention


def test_known_login_returns_discord_mention():
    assert "MeetDigrajkar" in GH_LOGIN_TO_DISCORD
    assert mention("MeetDigrajkar") == f"<@{GH_LOGIN_TO_DISCORD['MeetDigrajkar']}>"


def test_unknown_login_returns_code_login():
    assert mention("ghost-user") == "`ghost-user`"


def test_none_login_returns_unassigned():
    assert mention(None) == "_(unassigned)_"


def test_empty_login_returns_unassigned():
    assert mention("") == "_(unassigned)_"
```

- [ ] **Step 4.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_team.py -v
```

Expected: ImportError.

- [ ] **Step 4.3: Implement `team.py`**

Create `bot/jarvis/jobs/team.py`:

```python
"""GitHub login → Discord user ID, plus mention() helper.

Centralizing the mapping here means kinds never hand-build `<@id>` strings
and the team-posts-tag-Meet rule lives in one place.

Add new mappings as teammates' GitHub logins are confirmed.
"""

from __future__ import annotations


GH_LOGIN_TO_DISCORD: dict[str, int] = {
    "MeetDigrajkar": 295016116881850370,
}


def mention(login: str | None) -> str:
    if not login:
        return "_(unassigned)_"
    uid = GH_LOGIN_TO_DISCORD.get(login)
    return f"<@{uid}>" if uid else f"`{login}`"
```

- [ ] **Step 4.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_team.py -v
```

Expected: 4 passed.

- [ ] **Step 4.5: Commit**

```bash
git add bot/jarvis/jobs/team.py bot/tests/test_jobs_team.py
git commit -m "feat(bot): jobs - team mention helper"
```

---

## Task 5: `FirestoreJobState` — `state.py`

**Files:**
- Create: `bot/jarvis/jobs/state.py`
- Create: `bot/tests/test_jobs_state.py`

Two collections:
- `job_state/{name}` — last-run + status + free-form merge fields.
- `job_dedup/{job}/keys/{dedup_key}` — `seen_at`, `expires_at`. `is_dedup_seen` reads the doc and returns True iff `expires_at > now`.

- [ ] **Step 5.1: Write the failing test**

Create `bot/tests/test_jobs_state.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.jobs.state import FirestoreJobState


def _fake_firestore_with(state_doc: dict | None, dedup_doc: dict | None):
    """Build a fake Firestore AsyncClient that returns the given docs."""
    client = MagicMock()

    state_snap = MagicMock()
    state_snap.exists = state_doc is not None
    state_snap.to_dict = MagicMock(return_value=state_doc or {})
    state_ref = MagicMock()
    state_ref.get = AsyncMock(return_value=state_snap)
    state_ref.set = AsyncMock()
    state_ref.update = AsyncMock()

    dedup_snap = MagicMock()
    dedup_snap.exists = dedup_doc is not None
    dedup_snap.to_dict = MagicMock(return_value=dedup_doc or {})
    dedup_ref = MagicMock()
    dedup_ref.get = AsyncMock(return_value=dedup_snap)
    dedup_ref.set = AsyncMock()

    state_collection = MagicMock()
    state_collection.document = MagicMock(return_value=state_ref)

    dedup_keys = MagicMock()
    dedup_keys.document = MagicMock(return_value=dedup_ref)
    dedup_collection = MagicMock()
    dedup_collection.document = MagicMock()
    dedup_doc_ref = MagicMock()
    dedup_doc_ref.collection = MagicMock(return_value=dedup_keys)
    dedup_collection.document.return_value = dedup_doc_ref

    def _collection(name):
        return state_collection if name == "job_state" else dedup_collection

    client.collection = MagicMock(side_effect=_collection)
    return client, state_ref, dedup_ref


@pytest.mark.asyncio
async def test_merge_state_calls_set_with_merge():
    client, state_ref, _ = _fake_firestore_with(None, None)
    state = FirestoreJobState(client, "morning_brief")
    await state.merge_state({"last_run_at": "now", "last_status": "ok"})
    state_ref.set.assert_awaited_once()
    args, kwargs = state_ref.set.call_args
    assert args[0]["last_status"] == "ok"
    assert kwargs.get("merge") is True


@pytest.mark.asyncio
async def test_is_dedup_seen_false_when_no_doc():
    client, _, _ = _fake_firestore_with(None, None)
    state = FirestoreJobState(client, "j")
    assert (await state.is_dedup_seen("k")) is False


@pytest.mark.asyncio
async def test_is_dedup_seen_false_when_expired():
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    client, _, _ = _fake_firestore_with(None, {"expires_at": past, "seen_at": past})
    state = FirestoreJobState(client, "j")
    assert (await state.is_dedup_seen("k")) is False


@pytest.mark.asyncio
async def test_is_dedup_seen_true_when_unexpired():
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    client, _, _ = _fake_firestore_with(None, {"expires_at": future, "seen_at": future})
    state = FirestoreJobState(client, "j")
    assert (await state.is_dedup_seen("k")) is True


@pytest.mark.asyncio
async def test_mark_dedup_seen_writes_expires_at():
    client, _, dedup_ref = _fake_firestore_with(None, None)
    state = FirestoreJobState(client, "j")
    await state.mark_dedup_seen("k", ttl=timedelta(hours=2))
    dedup_ref.set.assert_awaited_once()
    payload = dedup_ref.set.call_args.args[0]
    assert "seen_at" in payload
    assert "expires_at" in payload
    delta = payload["expires_at"] - payload["seen_at"]
    assert timedelta(hours=1, minutes=59) <= delta <= timedelta(hours=2, minutes=1)
```

- [ ] **Step 5.2: Confirm `pytest-asyncio` is configured**

`bot/tests/conftest.py` already declares pytest-asyncio mode (PR3a/3b set this up). If a test errors with "async def test... not natively supported", check `pytest.ini` or `pyproject.toml` for `asyncio_mode = "auto"` and add it under `[tool.pytest.ini_options]` if missing. Otherwise mark each async test with `@pytest.mark.asyncio` (already done above).

- [ ] **Step 5.3: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_state.py -v
```

Expected: ImportError.

- [ ] **Step 5.4: Implement `state.py`**

Create `bot/jarvis/jobs/state.py`:

```python
"""Firestore-backed per-job state + dedup.

Two collections:
  job_state/{job_name}                       — last_run_at, last_status, kind-merged fields
  job_dedup/{job_name}/keys/{dedup_key}      — seen_at, expires_at

is_dedup_seen reads the doc and returns True only if expires_at > now.
We chose read-time expiry (vs Firestore native TTL) for explicitness and
dev-environment friendliness — local emulators may not have TTL set up.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_STATE_COLLECTION = "job_state"
_DEDUP_COLLECTION = "job_dedup"


class FirestoreJobState:
    def __init__(self, client: Any, job_name: str) -> None:
        self._client = client
        self._job_name = job_name

    def _state_doc(self):
        return self._client.collection(_STATE_COLLECTION).document(self._job_name)

    def _dedup_keys(self):
        return (
            self._client.collection(_DEDUP_COLLECTION)
            .document(self._job_name)
            .collection("keys")
        )

    async def merge_state(self, fields: dict[str, Any]) -> None:
        await self._state_doc().set(fields, merge=True)

    async def get_state(self) -> dict[str, Any]:
        snap = await self._state_doc().get()
        if not snap.exists:
            return {}
        return snap.to_dict() or {}

    async def is_dedup_seen(self, key: str) -> bool:
        snap = await self._dedup_keys().document(key).get()
        if not snap.exists:
            return False
        data = snap.to_dict() or {}
        expires_at = data.get("expires_at")
        if expires_at is None:
            return False
        return expires_at > datetime.now(timezone.utc)

    async def mark_dedup_seen(self, key: str, *, ttl: timedelta) -> None:
        now = datetime.now(timezone.utc)
        await self._dedup_keys().document(key).set(
            {"seen_at": now, "expires_at": now + ttl}
        )
```

- [ ] **Step 5.5: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_state.py -v
```

Expected: 5 passed.

- [ ] **Step 5.6: Commit**

```bash
git add bot/jarvis/jobs/state.py bot/tests/test_jobs_state.py
git commit -m "feat(bot): jobs - FirestoreJobState (state + dedup)"
```

---

## Task 6: `SelfReporter` — `self_report.py`

**Files:**
- Create: `bot/jarvis/jobs/self_report.py`
- Create: `bot/tests/test_jobs_self_report.py`

Three event hooks: `boot`, `job_ok`, `job_error`. All write to `#jarvis`. Failures are swallowed so a transient Discord error in self-report can never take down a real job.

- [ ] **Step 6.1: Write the failing test**

Create `bot/tests/test_jobs_self_report.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.jobs import Job
from jarvis.jobs.channels import CHANNEL_IDS
from jarvis.jobs.self_report import SelfReporter


def _fake_client_with_channel():
    channel = MagicMock()
    channel.send = AsyncMock()
    client = MagicMock()
    client.get_channel = MagicMock(return_value=channel)
    return client, channel


@pytest.mark.asyncio
async def test_boot_posts_online_message():
    client, channel = _fake_client_with_channel()
    reporter = SelfReporter(client)
    await reporter.boot(commit_sha="abcdef1234", job_count=7)
    channel.send.assert_awaited_once()
    msg = channel.send.call_args.args[0]
    assert "🟢" in msg
    assert "abcdef1" in msg
    assert "7 jobs" in msg


@pytest.mark.asyncio
async def test_job_ok_includes_target_channel_and_summary():
    client, channel = _fake_client_with_channel()
    reporter = SelfReporter(client)
    job = Job(name="pr_review_nudge", kind="pr_review_nudge", cron="* * * * *", channel="#code-review")
    await reporter.job_ok(job, summary="2 post(s) → #code-review: …")
    channel.send.assert_awaited_once()
    msg = channel.send.call_args.args[0]
    assert "✅" in msg
    assert "pr_review_nudge" in msg
    assert "#code-review" in msg


@pytest.mark.asyncio
async def test_job_error_truncates_long_messages():
    client, channel = _fake_client_with_channel()
    reporter = SelfReporter(client)
    job = Job(name="x", kind="y", cron="* * * * *", channel="#blockers")
    long = ValueError("a" * 1000)
    await reporter.job_error(job, long)
    msg = channel.send.call_args.args[0]
    assert "❌" in msg
    assert len(msg) < 700


@pytest.mark.asyncio
async def test_self_report_swallows_send_errors():
    client = MagicMock()
    channel = MagicMock()
    channel.send = AsyncMock(side_effect=RuntimeError("discord 503"))
    client.get_channel = MagicMock(return_value=channel)
    reporter = SelfReporter(client)
    # Must not raise — self-report failures are not fatal
    await reporter.boot(commit_sha="x", job_count=0)


@pytest.mark.asyncio
async def test_self_report_swallows_missing_channel():
    client = MagicMock()
    client.get_channel = MagicMock(return_value=None)
    reporter = SelfReporter(client)
    await reporter.boot(commit_sha="x", job_count=0)
```

- [ ] **Step 6.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_self_report.py -v
```

Expected: ImportError.

- [ ] **Step 6.3: Implement `self_report.py`**

Create `bot/jarvis/jobs/self_report.py`:

```python
"""SelfReporter — middleware that posts to #jarvis on boot + after every job run.

Three hooks:
  - boot(commit_sha, job_count)     → 🟢 once at startup
  - job_ok(job, summary)            → ✅ after a successful run
  - job_error(job, exception)       → ❌ when a kind raised

All paths swallow failures (logged via the module logger) so a transient
Discord error in the self-report path can never take down a real job.
"""

from __future__ import annotations

import logging
from typing import Any

from jarvis.jobs import Job
from jarvis.jobs.channels import CHANNEL_IDS

logger = logging.getLogger(__name__)

_JARVIS_CHANNEL_ID = CHANNEL_IDS["#jarvis"]
_MAX_ERROR_MSG = 500


class SelfReporter:
    def __init__(self, discord_client: Any) -> None:
        self._client = discord_client

    async def boot(self, *, commit_sha: str, job_count: int) -> None:
        sha_short = (commit_sha or "unknown")[:7]
        await self._post(f"🟢 Jarvis online · commit `{sha_short}` · scheduler: {job_count} jobs")

    async def job_ok(self, job: Job, *, summary: str) -> None:
        await self._post(f"✅ `{job.name}` → {job.channel} · {summary}")

    async def job_error(self, job: Job, err: Exception) -> None:
        msg = f"{type(err).__name__}: {err}"[:_MAX_ERROR_MSG]
        await self._post(f"❌ `{job.name}` failed · {msg}")

    async def _post(self, content: str) -> None:
        try:
            ch = self._client.get_channel(_JARVIS_CHANNEL_ID)
            if ch is None:
                logger.warning("self-report skipped: #jarvis channel not in cache")
                return
            await ch.send(content)
        except Exception:  # noqa: BLE001 — never let self-report failure crash a job
            logger.exception("self-report failed")
```

- [ ] **Step 6.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_self_report.py -v
```

Expected: 5 passed.

- [ ] **Step 6.5: Commit**

```bash
git add bot/jarvis/jobs/self_report.py bot/tests/test_jobs_self_report.py
git commit -m "feat(bot): jobs - SelfReporter (boot + job ok/error → #jarvis)"
```

---

## Task 7: KIND_REGISTRY skeleton

**Files:**
- Modify: `bot/jarvis/jobs/kinds/__init__.py`
- Create: `bot/tests/test_jobs_kind_registry.py`

The registry is a `dict[str, KindHandler]`. Kind modules register themselves at import time via a `_register("name", handler)` helper. The registry is built lazily so circular imports between kinds and types don't bite.

- [ ] **Step 7.1: Write the failing test**

Create `bot/tests/test_jobs_kind_registry.py`:

```python
from __future__ import annotations

import pytest

from jarvis.jobs.kinds import KIND_REGISTRY, register_kind


@pytest.mark.asyncio
async def test_register_and_lookup_roundtrip():
    async def fake_handler(ctx):
        return None
    register_kind("__test_only_kind", fake_handler)
    assert KIND_REGISTRY["__test_only_kind"] is fake_handler


def test_duplicate_registration_raises():
    async def h(ctx):
        return None
    register_kind("__dup_kind", h)
    with pytest.raises(ValueError):
        register_kind("__dup_kind", h)
```

- [ ] **Step 7.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_registry.py -v
```

Expected: ImportError.

- [ ] **Step 7.3: Implement `kinds/__init__.py`**

Replace `bot/jarvis/jobs/kinds/__init__.py` with:

```python
"""Kind registry. Kinds register themselves at import time."""

from __future__ import annotations

from jarvis.jobs import KindHandler

KIND_REGISTRY: dict[str, KindHandler] = {}


def register_kind(name: str, handler: KindHandler) -> None:
    if name in KIND_REGISTRY:
        raise ValueError(f"kind '{name}' already registered")
    KIND_REGISTRY[name] = handler
```

- [ ] **Step 7.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_registry.py -v
```

Expected: 2 passed.

- [ ] **Step 7.5: Commit**

```bash
git add bot/jarvis/jobs/kinds/__init__.py bot/tests/test_jobs_kind_registry.py
git commit -m "feat(bot): jobs - KIND_REGISTRY + register_kind"
```

---

## Task 8: GitHub query helpers — `github_queries.py`

**Files:**
- Create: `bot/jarvis/jobs/github_queries.py`
- Create: `bot/tests/test_jobs_github_queries.py`

Helpers shared by ≥2 kinds. Five functions:
- `list_open_prs(client, repo)` — REST `GET /repos/{repo}/pulls?state=open&per_page=100` (paginate up to 200; v1 unlikely to exceed).
- `list_pr_reviews(client, repo, number)` — REST `GET /repos/{repo}/pulls/{n}/reviews`.
- `list_check_runs_for_ref(client, repo, ref)` — REST `GET /repos/{repo}/commits/{ref}/check-runs`.
- `list_dependabot_prs(client, repo)` — `list_open_prs` filtered by `user.login == "dependabot[bot]"`.
- `find_branch_with_issue_ref(client, repo, issue_number, since)` — search commits whose message contains `#<n>` since `since`. Used by `stuck_in_progress`.

- [ ] **Step 8.1: Write the failing test**

Create `bot/tests/test_jobs_github_queries.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from jarvis.jobs.github_queries import (
    list_check_runs_for_ref,
    list_dependabot_prs,
    list_open_prs,
    list_pr_reviews,
)


@pytest.mark.asyncio
async def test_list_open_prs_calls_correct_endpoint_and_returns_payload():
    client = AsyncMock()
    client.get = AsyncMock(return_value=[{"number": 1}, {"number": 2}])
    out = await list_open_prs(client, "tsuki-works/niko")
    assert out == [{"number": 1}, {"number": 2}]
    client.get.assert_awaited_once()
    args = client.get.call_args
    assert args.args[0] == "/repos/tsuki-works/niko/pulls"
    assert args.kwargs["params"]["state"] == "open"


@pytest.mark.asyncio
async def test_list_pr_reviews_uses_pulls_review_endpoint():
    client = AsyncMock()
    client.get = AsyncMock(return_value=[{"state": "APPROVED"}])
    out = await list_pr_reviews(client, "tsuki-works/niko", 191)
    assert out[0]["state"] == "APPROVED"
    client.get.assert_awaited_once_with("/repos/tsuki-works/niko/pulls/191/reviews")


@pytest.mark.asyncio
async def test_list_check_runs_for_ref_returns_check_runs_array():
    client = AsyncMock()
    client.get = AsyncMock(return_value={"total_count": 2, "check_runs": [{"name": "ci"}]})
    out = await list_check_runs_for_ref(client, "tsuki-works/niko", "abcd")
    assert out == [{"name": "ci"}]


@pytest.mark.asyncio
async def test_list_dependabot_prs_filters_by_login():
    client = AsyncMock()
    client.get = AsyncMock(return_value=[
        {"number": 1, "user": {"login": "alice"}},
        {"number": 2, "user": {"login": "dependabot[bot]"}},
        {"number": 3, "user": {"login": "dependabot[bot]"}},
    ])
    out = await list_dependabot_prs(client, "tsuki-works/niko")
    assert [p["number"] for p in out] == [2, 3]
```

- [ ] **Step 8.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_github_queries.py -v
```

Expected: ImportError.

- [ ] **Step 8.3: Implement `github_queries.py`**

Create `bot/jarvis/jobs/github_queries.py`:

```python
"""Read-only GitHub queries shared by ≥2 kind handlers.

Kept separate from bot/jarvis/tools/github.py — those are agent-callable
ToolDescriptors, these are async helpers callable directly from kinds.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


async def list_open_prs(client: Any, repo: str, *, max_pages: int = 2) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        chunk = await client.get(
            f"/repos/{repo}/pulls",
            params={"state": "open", "per_page": 100, "page": page},
        )
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < 100:
            break
    return out


async def list_pr_reviews(client: Any, repo: str, number: int) -> list[dict[str, Any]]:
    return await client.get(f"/repos/{repo}/pulls/{number}/reviews") or []


async def list_check_runs_for_ref(client: Any, repo: str, ref: str) -> list[dict[str, Any]]:
    raw = await client.get(f"/repos/{repo}/commits/{ref}/check-runs")
    return (raw or {}).get("check_runs") or []


async def list_dependabot_prs(client: Any, repo: str) -> list[dict[str, Any]]:
    prs = await list_open_prs(client, repo)
    return [p for p in prs if (p.get("user") or {}).get("login") == "dependabot[bot]"]


async def find_branch_with_issue_ref(
    client: Any, repo: str, issue_number: int, *, since: datetime
) -> dict[str, Any] | None:
    """Find the most recent commit whose message references #<issue_number>.

    Uses the GitHub search-commits API (cloak header). Returns None if no
    matching commit is newer than `since`. The first hit is enough — we just
    need 'has anyone touched this issue lately?' for staleness detection.
    """
    q = f"repo:{repo} #{issue_number}"
    raw = await client.get("/search/commits", params={"q": q, "per_page": 5})
    items = (raw or {}).get("items") or []
    for item in items:
        committed = (item.get("commit") or {}).get("committer", {}).get("date")
        if committed and committed >= since.isoformat().replace("+00:00", "Z"):
            return item
    return None
```

- [ ] **Step 8.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_github_queries.py -v
```

Expected: 4 passed.

- [ ] **Step 8.5: Commit**

```bash
git add bot/jarvis/jobs/github_queries.py bot/tests/test_jobs_github_queries.py
git commit -m "feat(bot): jobs - GitHub query helpers (list_open_prs, reviews, check-runs, dependabot)"
```

---

## Task 9: `JobExecutor` — `executor.py`

**Files:**
- Create: `bot/jarvis/jobs/executor.py`
- Create: `bot/tests/test_jobs_executor.py`

Executor responsibilities (per spec §"Executor"):
1. Resolve channel via `channels.resolve(client, job.channel)`.
2. Build a `KindContext`, look up the kind handler, await it.
3. For each `PlannedPost`: skip if dedup_key is already seen; send; mark_dedup_seen.
4. Merge `result.state_writes` + `last_run_at` + `last_status` into Firestore.
5. On success: `self_reporter.job_ok(...)`. On failure: `self_reporter.job_error(...)`. Never re-raise.

- [ ] **Step 9.1: Write the failing test**

Create `bot/tests/test_jobs_executor.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.jobs import Job, KindContext, KindResult, PlannedPost
from jarvis.jobs.executor import JobExecutor
from jarvis.jobs.kinds import KIND_REGISTRY


def _fake_state():
    state = MagicMock()
    state.is_dedup_seen = AsyncMock(return_value=False)
    state.mark_dedup_seen = AsyncMock()
    state.merge_state = AsyncMock()
    state.get_state = AsyncMock(return_value={})
    return state


def _fake_executor(*, channel=None, state=None, kind_result=None):
    channel = channel or MagicMock()
    channel.send = AsyncMock()
    state = state or _fake_state()

    discord_client = MagicMock()
    discord_client.get_channel = MagicMock(return_value=channel)

    self_reporter = MagicMock()
    self_reporter.job_ok = AsyncMock()
    self_reporter.job_error = AsyncMock()

    state_factory = MagicMock(return_value=state)

    captured = {}
    async def fake_kind(ctx: KindContext) -> KindResult:
        captured["ctx"] = ctx
        return kind_result if kind_result is not None else KindResult(posts=[], summary="ok")

    KIND_REGISTRY["__test_kind"] = fake_kind  # type: ignore[assignment]

    settings = MagicMock()
    executor = JobExecutor(
        discord_client=discord_client,
        github_client=MagicMock(),
        anthropic_client=MagicMock(),
        firestore_client=MagicMock(),
        self_reporter=self_reporter,
        settings=settings,
        state_factory=state_factory,
    )
    return executor, channel, state, self_reporter, captured


def _job(channel="#jarvis"):
    return Job(name="t", kind="__test_kind", cron="* * * * *", channel=channel)


@pytest.mark.asyncio
async def test_run_skips_dedup_seen_posts():
    state = _fake_state()
    state.is_dedup_seen = AsyncMock(side_effect=[True, False])  # first seen, second new
    result = KindResult(posts=[
        PlannedPost(content="A", dedup_key="ka"),
        PlannedPost(content="B", dedup_key="kb"),
    ])
    executor, channel, _, self_reporter, _ = _fake_executor(state=state, kind_result=result)
    await executor.run(_job())
    assert channel.send.await_count == 1
    state.mark_dedup_seen.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_writes_state_and_self_reports_ok():
    result = KindResult(posts=[PlannedPost(content="hi")], summary="1 nudge", state_writes={"foo": 1})
    executor, _, state, self_reporter, _ = _fake_executor(kind_result=result)
    await executor.run(_job())
    state.merge_state.assert_awaited_once()
    payload = state.merge_state.call_args.args[0]
    assert payload["foo"] == 1
    assert payload["last_status"] == "ok"
    self_reporter.job_ok.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_handles_kind_exception_via_self_report_and_does_not_raise():
    async def boom(ctx):
        raise RuntimeError("kind blew up")
    KIND_REGISTRY["__boom_kind"] = boom  # type: ignore[assignment]
    executor, _, state, self_reporter, _ = _fake_executor()
    job = Job(name="t", kind="__boom_kind", cron="* * * * *", channel="#jarvis")
    await executor.run(job)  # must not raise
    self_reporter.job_error.assert_awaited_once()
    payload = state.merge_state.call_args.args[0]
    assert payload["last_status"].startswith("error: RuntimeError")


@pytest.mark.asyncio
async def test_run_passes_kind_context_with_resolved_channel():
    executor, channel, _, _, captured = _fake_executor()
    await executor.run(_job())
    ctx = captured["ctx"]
    assert ctx.discord_channel is channel
    assert ctx.job.name == "t"
    assert isinstance(ctx.now, datetime)


@pytest.mark.asyncio
async def test_run_splits_long_messages_at_2000_chars():
    long = "x" * 2500
    result = KindResult(posts=[PlannedPost(content=long)])
    executor, channel, _, _, _ = _fake_executor(kind_result=result)
    await executor.run(_job())
    assert channel.send.await_count == 2
    assert len(channel.send.call_args_list[0].args[0]) <= 2000
```

- [ ] **Step 9.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_executor.py -v
```

Expected: ImportError.

- [ ] **Step 9.3: Implement `executor.py`**

Create `bot/jarvis/jobs/executor.py`:

```python
"""JobExecutor — runs one Job invocation: dispatch → kind → post → state → report."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from jarvis.jobs import Job, KindContext, KindResult
from jarvis.jobs.channels import resolve as resolve_channel
from jarvis.jobs.kinds import KIND_REGISTRY
from jarvis.jobs.self_report import SelfReporter
from jarvis.jobs.state import FirestoreJobState

logger = logging.getLogger(__name__)

_DISCORD_MAX_MESSAGE = 2000


class JobExecutor:
    def __init__(
        self,
        *,
        discord_client: Any,
        github_client: Any,
        anthropic_client: Any,
        firestore_client: Any,
        self_reporter: SelfReporter,
        settings: Any,
        state_factory: Callable[[Any, str], Any] | None = None,
    ) -> None:
        self._discord = discord_client
        self._github = github_client
        self._anthropic = anthropic_client
        self._firestore = firestore_client
        self._self_reporter = self_reporter
        self._settings = settings
        self._state_factory = state_factory or (lambda fs, name: FirestoreJobState(fs, name))

    async def run(self, job: Job) -> None:
        log = logging.getLogger(f"jarvis.jobs.{job.name}")
        started = datetime.now(timezone.utc)
        log.info("job start: %s → %s", job.name, job.channel)
        state = self._state_factory(self._firestore, job.name)

        try:
            channel = resolve_channel(self._discord, job.channel)
            ctx = KindContext(
                job=job,
                discord_channel=channel,
                github_client=self._github,
                anthropic_client=self._anthropic,
                state=state,
                now=started,
                settings=self._settings,
                logger=log,
            )
            kind_fn = KIND_REGISTRY[job.kind]
            result: KindResult = await kind_fn(ctx)

            posted = 0
            for post in result.posts:
                if post.dedup_key and await state.is_dedup_seen(post.dedup_key):
                    continue
                try:
                    await self._send(channel, post.content)
                except Exception:  # noqa: BLE001 — partial-success is acceptable
                    log.exception("post send failed; continuing with remaining posts")
                    continue
                if post.dedup_key:
                    await state.mark_dedup_seen(post.dedup_key, ttl=self._dedup_ttl(job))
                posted += 1

            await state.merge_state({
                **result.state_writes,
                "last_run_at": started,
                "last_status": "ok",
            })
            await self._self_reporter.job_ok(
                job, summary=f"{posted} post(s) → {job.channel} · {result.summary or 'ok'}"
            )
        except Exception as exc:  # noqa: BLE001 — own the report path
            log.exception("job %s failed", job.name)
            await state.merge_state({
                "last_run_at": started,
                "last_status": f"error: {type(exc).__name__}",
            })
            await self._self_reporter.job_error(job, exc)
            # do NOT re-raise — APScheduler logs would just duplicate

    async def _send(self, channel: Any, content: str) -> None:
        if len(content) <= _DISCORD_MAX_MESSAGE:
            await channel.send(content)
            return
        for i in range(0, len(content), _DISCORD_MAX_MESSAGE):
            await channel.send(content[i : i + _DISCORD_MAX_MESSAGE])

    @staticmethod
    def _dedup_ttl(job: Job) -> timedelta:
        window = (job.params or {}).get("dedup_window", "1d")
        # Parse simple suffixed strings: 30m, 2h, 1d, 7d
        unit = window[-1]
        try:
            n = int(window[:-1])
        except ValueError:
            return timedelta(days=1)
        if unit == "m":
            return timedelta(minutes=n)
        if unit == "h":
            return timedelta(hours=n)
        if unit == "d":
            return timedelta(days=n)
        return timedelta(days=1)
```

- [ ] **Step 9.4: Run tests to confirm they pass**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_executor.py -v
```

Expected: 5 passed.

- [ ] **Step 9.5: Commit**

```bash
git add bot/jarvis/jobs/executor.py bot/tests/test_jobs_executor.py
git commit -m "feat(bot): jobs - JobExecutor (dispatch + dedup + self-report)"
```

---

## Task 10: `build_scheduler` + `validate_manifest` — `scheduler.py`

**Files:**
- Create: `bot/jarvis/jobs/scheduler.py`
- Create: `bot/tests/test_jobs_scheduler.py`

- [ ] **Step 10.1: Write the failing test**

Create `bot/tests/test_jobs_scheduler.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from jarvis.jobs import Job
from jarvis.jobs.kinds import KIND_REGISTRY
from jarvis.jobs.scheduler import (
    ManifestValidationError,
    build_scheduler,
    validate_manifest,
)


def _kind_ok():
    KIND_REGISTRY["__noop"] = lambda ctx: None  # type: ignore[assignment]


def test_validate_manifest_ok():
    _kind_ok()
    jobs = [Job(name="a", kind="__noop", cron="0 9 * * *", channel="#jarvis")]
    validate_manifest(jobs)  # does not raise


def test_validate_manifest_unknown_kind():
    with pytest.raises(ManifestValidationError, match="kind"):
        validate_manifest([Job(name="a", kind="ghost", cron="0 9 * * *", channel="#jarvis")])


def test_validate_manifest_unknown_channel():
    _kind_ok()
    with pytest.raises(ManifestValidationError, match="channel"):
        validate_manifest([Job(name="a", kind="__noop", cron="0 9 * * *", channel="#nope")])


def test_validate_manifest_bad_cron():
    _kind_ok()
    with pytest.raises(ManifestValidationError, match="cron"):
        validate_manifest([Job(name="a", kind="__noop", cron="not-a-cron", channel="#jarvis")])


def test_validate_manifest_duplicate_names():
    _kind_ok()
    with pytest.raises(ManifestValidationError, match="duplicate"):
        validate_manifest([
            Job(name="a", kind="__noop", cron="0 9 * * *", channel="#jarvis"),
            Job(name="a", kind="__noop", cron="0 9 * * *", channel="#jarvis"),
        ])


def test_build_scheduler_skips_disabled():
    _kind_ok()
    executor = MagicMock()
    jobs = [
        Job(name="on", kind="__noop", cron="0 9 * * *", channel="#jarvis"),
        Job(name="off", kind="__noop", cron="0 9 * * *", channel="#jarvis", enabled=False),
    ]
    sched = build_scheduler(executor, jobs)
    ids = {j.id for j in sched.get_jobs()}
    assert ids == {"on"}
```

- [ ] **Step 10.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_scheduler.py -v
```

Expected: ImportError.

- [ ] **Step 10.3: Implement `scheduler.py`**

Create `bot/jarvis/jobs/scheduler.py`:

```python
"""Scheduler builder + manifest validator."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from jarvis.jobs import Job
from jarvis.jobs.channels import CHANNEL_IDS
from jarvis.jobs.kinds import KIND_REGISTRY

logger = logging.getLogger(__name__)


class ManifestValidationError(ValueError):
    pass


def validate_manifest(jobs: list[Job]) -> None:
    seen: set[str] = set()
    for job in jobs:
        if job.name in seen:
            raise ManifestValidationError(f"duplicate job name: {job.name}")
        seen.add(job.name)

        if job.kind not in KIND_REGISTRY:
            raise ManifestValidationError(
                f"job {job.name}: unknown kind '{job.kind}' (registered: {sorted(KIND_REGISTRY)})"
            )
        if job.channel not in CHANNEL_IDS:
            raise ManifestValidationError(
                f"job {job.name}: unknown channel '{job.channel}'"
            )
        try:
            CronTrigger.from_crontab(job.cron, timezone=job.timezone)
        except Exception as e:  # noqa: BLE001
            raise ManifestValidationError(
                f"job {job.name}: invalid cron '{job.cron}' ({e})"
            ) from e


def build_scheduler(executor, jobs: list[Job]) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone="UTC")
    for job in jobs:
        if not job.enabled:
            logger.info("skipping disabled job: %s", job.name)
            continue
        trigger = CronTrigger.from_crontab(job.cron, timezone=job.timezone)
        sched.add_job(
            executor.run,
            trigger,
            args=[job],
            id=job.name,
            name=job.name,
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )
    return sched
```

- [ ] **Step 10.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_scheduler.py -v
```

Expected: 6 passed.

- [ ] **Step 10.5: Commit**

```bash
git add bot/jarvis/jobs/scheduler.py bot/tests/test_jobs_scheduler.py
git commit -m "feat(bot): jobs - build_scheduler + validate_manifest"
```

---

## Task 11: Kind — `pr_review_nudge`

**Files:**
- Create: `bot/jarvis/jobs/kinds/pr_review_nudge.py`
- Create: `bot/tests/test_jobs_kind_pr_review_nudge.py`

Behavior (per spec):
- List open PRs (use `github_queries.list_open_prs`).
- Filter: not draft, ready_for_review, age > `params["min_age_hours"]` (default 4), assigned reviewers list non-empty (or fall back to author tag if no reviewers).
- `dedup_key = f"PR-{number}_{date.today().isoformat()}"` (one ping per PR per day).
- Compose: `"👀 PR #N waiting on review (Xh) — <@reviewer> {title} {url}"`.

- [ ] **Step 11.1: Write the failing test**

Create `bot/tests/test_jobs_kind_pr_review_nudge.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.jobs import Job, KindContext
from jarvis.jobs.kinds.pr_review_nudge import handle


def _ctx(prs):
    job = Job(name="pr_review_nudge", kind="pr_review_nudge", cron="* * * * *", channel="#code-review",
              params={"min_age_hours": 4})
    gh = AsyncMock()
    gh.get = AsyncMock(return_value=prs)
    state = MagicMock()
    state.is_dedup_seen = AsyncMock(return_value=False)
    return KindContext(
        job=job,
        discord_channel=MagicMock(),
        github_client=gh,
        anthropic_client=MagicMock(),
        state=state,
        now=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        settings=MagicMock(),
        logger=MagicMock(),
    )


@pytest.mark.asyncio
async def test_emits_post_per_eligible_pr():
    six_hours_ago = (datetime(2026, 5, 6, 6, 0, tzinfo=timezone.utc)).isoformat().replace("+00:00", "Z")
    prs = [{
        "number": 191,
        "title": "Add Twilio recording",
        "html_url": "https://github.com/x/y/pull/191",
        "draft": False,
        "user": {"login": "MeetDigrajkar"},
        "requested_reviewers": [{"login": "MeetDigrajkar"}],
        "created_at": six_hours_ago,
        "updated_at": six_hours_ago,
    }]
    result = await handle(_ctx(prs))
    assert len(result.posts) == 1
    msg = result.posts[0].content
    assert "PR #191" in msg
    assert "Add Twilio recording" in msg
    assert "<@" in msg or "MeetDigrajkar" in msg


@pytest.mark.asyncio
async def test_skips_drafts_and_too_recent():
    too_recent = (datetime(2026, 5, 6, 11, 30, tzinfo=timezone.utc)).isoformat().replace("+00:00", "Z")
    prs = [
        {"number": 1, "title": "draft", "html_url": "u", "draft": True,
         "user": {"login": "a"}, "requested_reviewers": [], "created_at": too_recent, "updated_at": too_recent},
        {"number": 2, "title": "too new", "html_url": "u", "draft": False,
         "user": {"login": "a"}, "requested_reviewers": [], "created_at": too_recent, "updated_at": too_recent},
    ]
    result = await handle(_ctx(prs))
    assert result.posts == []


@pytest.mark.asyncio
async def test_dedup_key_per_pr_per_day():
    six_hours_ago = (datetime(2026, 5, 6, 6, 0, tzinfo=timezone.utc)).isoformat().replace("+00:00", "Z")
    prs = [{
        "number": 191,
        "title": "x",
        "html_url": "u",
        "draft": False,
        "user": {"login": "a"},
        "requested_reviewers": [{"login": "MeetDigrajkar"}],
        "created_at": six_hours_ago, "updated_at": six_hours_ago,
    }]
    result = await handle(_ctx(prs))
    assert result.posts[0].dedup_key == "PR-191_2026-05-06"
```

- [ ] **Step 11.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_pr_review_nudge.py -v
```

Expected: ImportError.

- [ ] **Step 11.3: Implement `pr_review_nudge.py`**

Create `bot/jarvis/jobs/kinds/pr_review_nudge.py`:

```python
"""pr_review_nudge — pings #code-review for PRs waiting > N hours."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import list_open_prs
from jarvis.jobs.kinds import register_kind
from jarvis.jobs.team import mention


def _parse_iso8601(s: str) -> datetime:
    # GitHub uses "...Z"; Python's fromisoformat accepts +00:00 in 3.11+
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def handle(ctx: KindContext) -> KindResult:
    repo = ctx.settings.github_repo if hasattr(ctx.settings, "github_repo") else "tsuki-works/niko"
    min_age_hours = int(ctx.job.params.get("min_age_hours", 4))
    threshold = ctx.now - timedelta(hours=min_age_hours)

    prs = await list_open_prs(ctx.github_client, repo)
    posts: list[PlannedPost] = []
    for pr in prs:
        if pr.get("draft"):
            continue
        created_str = pr.get("created_at") or pr.get("updated_at")
        if not created_str:
            continue
        created = _parse_iso8601(created_str)
        if created > threshold:
            continue

        reviewers = [r.get("login") for r in (pr.get("requested_reviewers") or []) if r]
        target = reviewers[0] if reviewers else (pr.get("user") or {}).get("login")
        age_hours = max(1, int((ctx.now - created).total_seconds() // 3600))
        number = pr.get("number")
        title = pr.get("title") or ""
        url = pr.get("html_url") or ""

        msg = f"👀 PR #{number} waiting on review ({age_hours}h) — {mention(target)} {title} {url}"
        posts.append(PlannedPost(
            content=msg,
            dedup_key=f"PR-{number}_{ctx.now.date().isoformat()}",
        ))

    return KindResult(
        posts=posts,
        summary=f"{len(posts)} PR(s) flagged",
    )


register_kind("pr_review_nudge", handle)
```

- [ ] **Step 11.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_pr_review_nudge.py -v
```

Expected: 3 passed.

- [ ] **Step 11.5: Commit**

```bash
git add bot/jarvis/jobs/kinds/pr_review_nudge.py bot/tests/test_jobs_kind_pr_review_nudge.py
git commit -m "feat(bot): jobs - pr_review_nudge kind"
```

---

## Task 12: Kind — `approved_pr_not_merged`

**Files:**
- Create: `bot/jarvis/jobs/kinds/approved_pr_not_merged.py`
- Create: `bot/tests/test_jobs_kind_approved_pr_not_merged.py`

Filter: ≥1 APPROVED review, all check-runs `conclusion == "success"`, latest approval older than `params["min_age_after_approval_hours"]`. dedup_key includes the approval date.

- [ ] **Step 12.1: Write the failing test**

Create `bot/tests/test_jobs_kind_approved_pr_not_merged.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.jobs import Job, KindContext
from jarvis.jobs.kinds.approved_pr_not_merged import handle


def _ctx(*, prs, reviews_by_pr, check_runs_by_sha):
    job = Job(name="approved_pr_not_merged", kind="approved_pr_not_merged",
              cron="* * * * *", channel="#code-review",
              params={"min_age_after_approval_hours": 2})
    async def fake_get(path, params=None):
        # /repos/.../pulls — list
        if path.endswith("/pulls"):
            return prs
        if "/reviews" in path:
            number = int(path.rsplit("/", 2)[-2])
            return reviews_by_pr.get(number, [])
        if "/check-runs" in path:
            sha = path.rsplit("/", 2)[-2]
            return {"check_runs": check_runs_by_sha.get(sha, [])}
        return None
    gh = MagicMock()
    gh.get = AsyncMock(side_effect=fake_get)
    return KindContext(
        job=job,
        discord_channel=MagicMock(),
        github_client=gh,
        anthropic_client=MagicMock(),
        state=MagicMock(),
        now=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        settings=MagicMock(),
        logger=MagicMock(),
    )


@pytest.mark.asyncio
async def test_emits_for_approved_green_pr():
    prs = [{
        "number": 200, "title": "Ship it", "html_url": "u",
        "user": {"login": "MeetDigrajkar"},
        "head": {"sha": "abc"},
    }]
    reviews = {200: [{"state": "APPROVED", "submitted_at": "2026-05-06T08:00:00Z"}]}
    checks = {"abc": [{"name": "ci", "status": "completed", "conclusion": "success"}]}
    result = await handle(_ctx(prs=prs, reviews_by_pr=reviews, check_runs_by_sha=checks))
    assert len(result.posts) == 1
    assert "PR #200" in result.posts[0].content
    assert "✅" in result.posts[0].content


@pytest.mark.asyncio
async def test_skips_when_checks_red():
    prs = [{"number": 1, "title": "x", "html_url": "u", "user": {"login": "a"}, "head": {"sha": "abc"}}]
    reviews = {1: [{"state": "APPROVED", "submitted_at": "2026-05-06T08:00:00Z"}]}
    checks = {"abc": [{"name": "ci", "status": "completed", "conclusion": "failure"}]}
    result = await handle(_ctx(prs=prs, reviews_by_pr=reviews, check_runs_by_sha=checks))
    assert result.posts == []


@pytest.mark.asyncio
async def test_skips_when_approval_too_recent():
    prs = [{"number": 1, "title": "x", "html_url": "u", "user": {"login": "a"}, "head": {"sha": "abc"}}]
    reviews = {1: [{"state": "APPROVED", "submitted_at": "2026-05-06T11:00:00Z"}]}  # 1h ago
    checks = {"abc": [{"name": "ci", "status": "completed", "conclusion": "success"}]}
    result = await handle(_ctx(prs=prs, reviews_by_pr=reviews, check_runs_by_sha=checks))
    assert result.posts == []
```

- [ ] **Step 12.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_approved_pr_not_merged.py -v
```

Expected: ImportError.

- [ ] **Step 12.3: Implement the kind**

Create `bot/jarvis/jobs/kinds/approved_pr_not_merged.py`:

```python
"""approved_pr_not_merged — pings author when a green-checked, approved PR sits open."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import (
    list_check_runs_for_ref,
    list_open_prs,
    list_pr_reviews,
)
from jarvis.jobs.kinds import register_kind
from jarvis.jobs.team import mention


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def handle(ctx: KindContext) -> KindResult:
    repo = getattr(ctx.settings, "github_repo", "tsuki-works/niko")
    min_hours = int(ctx.job.params.get("min_age_after_approval_hours", 2))
    threshold = ctx.now - timedelta(hours=min_hours)

    prs = await list_open_prs(ctx.github_client, repo)
    posts: list[PlannedPost] = []
    for pr in prs:
        number = pr["number"]
        sha = (pr.get("head") or {}).get("sha")
        if not sha:
            continue

        reviews = await list_pr_reviews(ctx.github_client, repo, number)
        approvals = [r for r in reviews if r.get("state") == "APPROVED" and r.get("submitted_at")]
        if not approvals:
            continue
        latest_approval = max(_parse(r["submitted_at"]) for r in approvals)
        if latest_approval > threshold:
            continue

        check_runs = await list_check_runs_for_ref(ctx.github_client, repo, sha)
        completed = [c for c in check_runs if c.get("status") == "completed"]
        if not completed:
            continue
        if any(c.get("conclusion") not in ("success", "neutral", "skipped") for c in completed):
            continue

        author = (pr.get("user") or {}).get("login")
        age = max(1, int((ctx.now - latest_approval).total_seconds() // 3600))
        posts.append(PlannedPost(
            content=f"✅ PR #{number} approved {age}h ago and green — {mention(author)} ready to merge? {pr.get('html_url') or ''}",
            dedup_key=f"PR-{number}_approved_{latest_approval.date().isoformat()}",
        ))

    return KindResult(posts=posts, summary=f"{len(posts)} mergeable PR(s)")


register_kind("approved_pr_not_merged", handle)
```

- [ ] **Step 12.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_approved_pr_not_merged.py -v
```

Expected: 3 passed.

- [ ] **Step 12.5: Commit**

```bash
git add bot/jarvis/jobs/kinds/approved_pr_not_merged.py bot/tests/test_jobs_kind_approved_pr_not_merged.py
git commit -m "feat(bot): jobs - approved_pr_not_merged kind"
```

---

## Task 13: Kind — `ci_red_pr_nudge`

**Files:**
- Create: `bot/jarvis/jobs/kinds/ci_red_pr_nudge.py`
- Create: `bot/tests/test_jobs_kind_ci_red_pr_nudge.py`

Filter: PRs where ≥1 check-run has `conclusion in ("failure", "timed_out", "cancelled")`. dedup on `(PR, sha, failing_check_name)`.

- [ ] **Step 13.1: Write the failing test**

Create `bot/tests/test_jobs_kind_ci_red_pr_nudge.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.jobs import Job, KindContext
from jarvis.jobs.kinds.ci_red_pr_nudge import handle


def _ctx(*, prs, check_runs_by_sha):
    async def fake_get(path, params=None):
        if path.endswith("/pulls"):
            return prs
        if "/check-runs" in path:
            sha = path.rsplit("/", 2)[-2]
            return {"check_runs": check_runs_by_sha.get(sha, [])}
        return None
    gh = MagicMock()
    gh.get = AsyncMock(side_effect=fake_get)
    return KindContext(
        job=Job(name="ci_red_pr_nudge", kind="ci_red_pr_nudge", cron="* * * * *", channel="#code-review"),
        discord_channel=MagicMock(),
        github_client=gh,
        anthropic_client=MagicMock(),
        state=MagicMock(),
        now=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        settings=MagicMock(),
        logger=MagicMock(),
    )


@pytest.mark.asyncio
async def test_pings_author_with_failing_check_name():
    prs = [{"number": 5, "title": "x", "html_url": "u", "user": {"login": "MeetDigrajkar"}, "head": {"sha": "deadbeef"}}]
    checks = {"deadbeef": [
        {"name": "ci", "status": "completed", "conclusion": "failure", "html_url": "https://gh/checks/1"},
        {"name": "lint", "status": "completed", "conclusion": "success"},
    ]}
    result = await handle(_ctx(prs=prs, check_runs_by_sha=checks))
    assert len(result.posts) == 1
    msg = result.posts[0].content
    assert "❌" in msg
    assert "PR #5" in msg
    assert "ci" in msg


@pytest.mark.asyncio
async def test_dedup_key_includes_sha():
    prs = [{"number": 5, "title": "x", "html_url": "u", "user": {"login": "a"}, "head": {"sha": "abc"}}]
    checks = {"abc": [{"name": "ci", "status": "completed", "conclusion": "failure"}]}
    result = await handle(_ctx(prs=prs, check_runs_by_sha=checks))
    assert "PR-5_red_abc_ci" == result.posts[0].dedup_key


@pytest.mark.asyncio
async def test_skips_pr_with_all_green():
    prs = [{"number": 5, "title": "x", "html_url": "u", "user": {"login": "a"}, "head": {"sha": "abc"}}]
    checks = {"abc": [{"name": "ci", "status": "completed", "conclusion": "success"}]}
    result = await handle(_ctx(prs=prs, check_runs_by_sha=checks))
    assert result.posts == []
```

- [ ] **Step 13.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_ci_red_pr_nudge.py -v
```

Expected: ImportError.

- [ ] **Step 13.3: Implement the kind**

Create `bot/jarvis/jobs/kinds/ci_red_pr_nudge.py`:

```python
"""ci_red_pr_nudge — pings author when an open PR has at least one failing check-run."""

from __future__ import annotations

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import list_check_runs_for_ref, list_open_prs
from jarvis.jobs.kinds import register_kind
from jarvis.jobs.team import mention

_FAIL_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required"}


async def handle(ctx: KindContext) -> KindResult:
    repo = getattr(ctx.settings, "github_repo", "tsuki-works/niko")
    prs = await list_open_prs(ctx.github_client, repo)
    posts: list[PlannedPost] = []
    for pr in prs:
        sha = (pr.get("head") or {}).get("sha")
        number = pr["number"]
        if not sha:
            continue
        runs = await list_check_runs_for_ref(ctx.github_client, repo, sha)
        failing = [r for r in runs if (r.get("conclusion") or "") in _FAIL_CONCLUSIONS]
        if not failing:
            continue
        first = failing[0]
        check_name = first.get("name") or "unknown"
        check_url = first.get("html_url") or ""
        author = (pr.get("user") or {}).get("login")
        posts.append(PlannedPost(
            content=f"❌ PR #{number} — `{check_name}` failed. {mention(author)} {check_url or pr.get('html_url') or ''}",
            dedup_key=f"PR-{number}_red_{sha}_{check_name}",
        ))
    return KindResult(posts=posts, summary=f"{len(posts)} red PR(s)")


register_kind("ci_red_pr_nudge", handle)
```

- [ ] **Step 13.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_ci_red_pr_nudge.py -v
```

Expected: 3 passed.

- [ ] **Step 13.5: Commit**

```bash
git add bot/jarvis/jobs/kinds/ci_red_pr_nudge.py bot/tests/test_jobs_kind_ci_red_pr_nudge.py
git commit -m "feat(bot): jobs - ci_red_pr_nudge kind"
```

---

## Task 14: Kind — `dependabot_pair_check`

**Files:**
- Create: `bot/jarvis/jobs/kinds/dependabot_pair_check.py`
- Create: `bot/tests/test_jobs_kind_dependabot_pair_check.py`

Parse `"Bumps {pkg} from a to b"` (or `"Bump"`) from PR title. For each pair group in `params["pairs"]`, if ≥2 packages have an open PR, emit one post listing them.

- [ ] **Step 14.1: Write the failing test**

Create `bot/tests/test_jobs_kind_dependabot_pair_check.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.jobs import Job, KindContext
from jarvis.jobs.kinds.dependabot_pair_check import _extract_package, handle


def test_extract_package_from_bumps_title():
    assert _extract_package("Bumps react from 19.1.0 to 19.2.5") == "react"
    assert _extract_package("Bump react-dom from 19.1.0 to 19.2.5") == "react-dom"
    assert _extract_package("chore: random") is None


def _ctx(prs, pairs):
    job = Job(name="dependabot_pair_check", kind="dependabot_pair_check",
              cron="* * * * *", channel="#code-review", params={"pairs": pairs})
    gh = MagicMock()
    gh.get = AsyncMock(return_value=prs)
    return KindContext(
        job=job, discord_channel=MagicMock(), github_client=gh,
        anthropic_client=MagicMock(), state=MagicMock(),
        now=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        settings=MagicMock(), logger=MagicMock(),
    )


@pytest.mark.asyncio
async def test_emits_post_when_paired_prs_open():
    prs = [
        {"number": 10, "title": "Bumps react from 19.1.0 to 19.2.5",
         "html_url": "u/10", "user": {"login": "dependabot[bot]"}},
        {"number": 11, "title": "Bumps react-dom from 19.1.0 to 19.2.5",
         "html_url": "u/11", "user": {"login": "dependabot[bot]"}},
    ]
    result = await handle(_ctx(prs, pairs=[["react", "react-dom"]]))
    assert len(result.posts) == 1
    msg = result.posts[0].content
    assert "📦" in msg
    assert "PR #10" in msg and "PR #11" in msg


@pytest.mark.asyncio
async def test_no_post_when_only_one_of_pair_open():
    prs = [{"number": 10, "title": "Bumps react from 19.1.0 to 19.2.5",
            "html_url": "u/10", "user": {"login": "dependabot[bot]"}}]
    result = await handle(_ctx(prs, pairs=[["react", "react-dom"]]))
    assert result.posts == []
```

- [ ] **Step 14.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_dependabot_pair_check.py -v
```

Expected: ImportError.

- [ ] **Step 14.3: Implement the kind**

Create `bot/jarvis/jobs/kinds/dependabot_pair_check.py`:

```python
"""dependabot_pair_check — flags simultaneously-open paired dependency bumps."""

from __future__ import annotations

import re

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import list_dependabot_prs
from jarvis.jobs.kinds import register_kind

_TITLE_RE = re.compile(r"^Bumps?\s+(?P<pkg>[@\w./-]+)\s+from\s")


def _extract_package(title: str) -> str | None:
    if not title:
        return None
    m = _TITLE_RE.match(title)
    return m.group("pkg") if m else None


async def handle(ctx: KindContext) -> KindResult:
    repo = getattr(ctx.settings, "github_repo", "tsuki-works/niko")
    pairs: list[list[str]] = ctx.job.params.get("pairs", [])
    if not pairs:
        return KindResult(posts=[], summary="no pairs configured")

    prs = await list_dependabot_prs(ctx.github_client, repo)
    by_pkg: dict[str, dict] = {}
    for pr in prs:
        pkg = _extract_package(pr.get("title") or "")
        if pkg:
            by_pkg[pkg] = pr

    posts: list[PlannedPost] = []
    today = ctx.now.date().isoformat()
    for group in pairs:
        present = [pkg for pkg in group if pkg in by_pkg]
        if len(present) < 2:
            continue
        lines = [
            f"📦 Paired Dependabot PRs — merge together or master may break:",
        ]
        for pkg in present:
            pr = by_pkg[pkg]
            lines.append(f" • PR #{pr['number']} bumps `{pkg}` — {pr.get('html_url') or ''}")
        dedup = "pair_" + "_".join(sorted(present)) + "_" + today
        posts.append(PlannedPost(content="\n".join(lines), dedup_key=dedup))

    return KindResult(posts=posts, summary=f"{len(posts)} pair group(s) flagged")


register_kind("dependabot_pair_check", handle)
```

- [ ] **Step 14.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_dependabot_pair_check.py -v
```

Expected: 3 passed.

- [ ] **Step 14.5: Commit**

```bash
git add bot/jarvis/jobs/kinds/dependabot_pair_check.py bot/tests/test_jobs_kind_dependabot_pair_check.py
git commit -m "feat(bot): jobs - dependabot_pair_check kind"
```

---

## Task 15: Kind — `stuck_in_progress`

**Files:**
- Create: `bot/jarvis/jobs/kinds/stuck_in_progress.py`
- Create: `bot/tests/test_jobs_kind_stuck_in_progress.py`

Use the existing GraphQL pattern in `tools/sprint.py`. Pull project items with Status = "In progress", look at content (issue/PR), check `find_branch_with_issue_ref` for any commit since `now - stale_days`. If none, emit a post in `#blockers` tagging the assignee.

- [ ] **Step 15.1: Write the failing test**

Create `bot/tests/test_jobs_kind_stuck_in_progress.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.jobs import Job, KindContext
from jarvis.jobs.kinds.stuck_in_progress import handle


def _ctx(*, sprint_nodes, has_recent_commit):
    settings = MagicMock()
    settings.github_repo = "tsuki-works/niko"
    settings.github_project_id = "PVT_kwDOEIgWQM4BVBdK"

    gh = MagicMock()
    gh.graphql = AsyncMock(return_value={
        "node": {"items": {"nodes": sprint_nodes}},
    })
    async def fake_get(path, params=None):
        if path == "/search/commits":
            return {"items": [{"commit": {"committer": {"date": "2099-01-01T00:00:00Z"}}}] if has_recent_commit else []}
        return None
    gh.get = AsyncMock(side_effect=fake_get)

    return KindContext(
        job=Job(name="stuck_in_progress", kind="stuck_in_progress",
                cron="* * * * *", channel="#blockers", params={"stale_days": 3}),
        discord_channel=MagicMock(),
        github_client=gh,
        anthropic_client=MagicMock(),
        state=MagicMock(),
        now=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        settings=settings,
        logger=MagicMock(),
    )


def _node(*, number, title, status, assignee):
    return {
        "id": f"node-{number}",
        "content": {"title": title, "url": "u", "number": number,
                    "assignees": {"nodes": [{"login": assignee}] if assignee else []}},
        "fieldValues": {"nodes": [
            {"name": status,
             "field": {"name": "Status"}},
        ]},
    }


@pytest.mark.asyncio
async def test_emits_when_no_recent_commits():
    nodes = [_node(number=42, title="ship X", status="In progress", assignee="MeetDigrajkar")]
    result = await handle(_ctx(sprint_nodes=nodes, has_recent_commit=False))
    assert len(result.posts) == 1
    msg = result.posts[0].content
    assert "⏳" in msg
    assert "#42" in msg
    assert "<@" in msg or "MeetDigrajkar" in msg


@pytest.mark.asyncio
async def test_skips_when_recent_commit():
    nodes = [_node(number=42, title="x", status="In progress", assignee="a")]
    result = await handle(_ctx(sprint_nodes=nodes, has_recent_commit=True))
    assert result.posts == []


@pytest.mark.asyncio
async def test_skips_done_items():
    nodes = [_node(number=42, title="x", status="Done", assignee="a")]
    result = await handle(_ctx(sprint_nodes=nodes, has_recent_commit=False))
    assert result.posts == []
```

- [ ] **Step 15.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_stuck_in_progress.py -v
```

Expected: ImportError.

- [ ] **Step 15.3: Implement the kind**

Create `bot/jarvis/jobs/kinds/stuck_in_progress.py`:

```python
"""stuck_in_progress — flags Project items in 'In progress' with no recent commits."""

from __future__ import annotations

from datetime import timedelta

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import find_branch_with_issue_ref
from jarvis.jobs.kinds import register_kind
from jarvis.jobs.team import mention

_QUERY = """
query($id: ID!) {
  node(id: $id) {
    ... on ProjectV2 {
      items(first: 100) {
        nodes {
          id
          content {
            ... on Issue { title url number assignees(first: 5) { nodes { login } } }
            ... on PullRequest { title url number assignees(first: 5) { nodes { login } } }
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


def _flatten_status(item: dict) -> str | None:
    for fv in (item.get("fieldValues") or {}).get("nodes") or []:
        if (fv.get("field") or {}).get("name") == "Status":
            return fv.get("name")
    return None


async def handle(ctx: KindContext) -> KindResult:
    project_id = getattr(ctx.settings, "github_project_id", None)
    repo = getattr(ctx.settings, "github_repo", "tsuki-works/niko")
    stale_days = int(ctx.job.params.get("stale_days", 3))
    if not project_id:
        return KindResult(posts=[], summary="no project_id configured")

    data = await ctx.github_client.graphql(_QUERY, variables={"id": project_id})
    nodes = (((data or {}).get("node") or {}).get("items") or {}).get("nodes") or []

    since = ctx.now - timedelta(days=stale_days)
    posts: list[PlannedPost] = []
    today = ctx.now.date().isoformat()

    for item in nodes:
        if _flatten_status(item) != "In progress":
            continue
        content = item.get("content") or {}
        number = content.get("number")
        if number is None:
            continue
        recent = await find_branch_with_issue_ref(ctx.github_client, repo, number, since=since)
        if recent:
            continue
        assignees = ((content.get("assignees") or {}).get("nodes") or [])
        first_login = assignees[0]["login"] if assignees else None
        title = content.get("title") or ""
        url = content.get("url") or ""
        posts.append(PlannedPost(
            content=f"⏳ {mention(first_login)} Issue #{number} has been 'In progress' for {stale_days}d+ with no recent commits — anything blocking? {title} {url}",
            dedup_key=f"item-{item.get('id')}_{today}",
        ))

    return KindResult(posts=posts, summary=f"{len(posts)} stuck item(s)")


register_kind("stuck_in_progress", handle)
```

- [ ] **Step 15.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_stuck_in_progress.py -v
```

Expected: 3 passed.

- [ ] **Step 15.5: Commit**

```bash
git add bot/jarvis/jobs/kinds/stuck_in_progress.py bot/tests/test_jobs_kind_stuck_in_progress.py
git commit -m "feat(bot): jobs - stuck_in_progress kind"
```

---

## Task 16: Kind — `digest_via_agent`

**Files:**
- Create: `bot/jarvis/jobs/kinds/digest_via_agent.py`
- Create: `bot/tests/test_jobs_kind_digest_via_agent.py`

Two-stage:
1. Build a deterministic data brief from `params["sources"]` (sprint, recent_commits, open_prs, merged_prs).
2. Send to Anthropic with `tools=[]`, `max_tokens=600`, a per-prompt system message keyed by `params["polish_prompt"]`. On Anthropic error, fall back to the data brief.

- [ ] **Step 16.1: Write the failing test**

Create `bot/tests/test_jobs_kind_digest_via_agent.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.jobs import Job, KindContext
from jarvis.jobs.kinds.digest_via_agent import _build_data_brief, handle


def test_build_data_brief_renders_sections_for_present_data():
    brief = _build_data_brief({
        "sprint": {"items": [{"title": "Ship X", "number": 1, "status": "In progress"}]},
        "recent_commits": [{"sha": "abcd", "title": "fix(x)", "author": "Meet"}],
        "open_prs": [{"number": 5, "title": "T", "user": {"login": "Meet"}}],
    })
    assert "Sprint" in brief
    assert "Ship X" in brief
    assert "fix(x)" in brief
    assert "PR #5" in brief


def _ctx(polish_text="polished!", anthropic_raises=False):
    job = Job(
        name="morning", kind="digest_via_agent", cron="* * * * *",
        channel="#weekly-sync",
        params={"sources": ["sprint", "recent_commits"], "lookback_hours": 24,
                "polish_prompt": "morning_sprint_brief"},
    )
    gh = MagicMock()
    gh.graphql = AsyncMock(return_value={"node": {"items": {"nodes": []}}})
    gh.get = AsyncMock(return_value=[])

    anth = MagicMock()
    if anthropic_raises:
        anth.messages = MagicMock()
        anth.messages.create = AsyncMock(side_effect=RuntimeError("anthropic 503"))
    else:
        msg = MagicMock()
        msg.content = [MagicMock(text=polish_text)]
        anth.messages = MagicMock()
        anth.messages.create = AsyncMock(return_value=msg)

    settings = MagicMock()
    settings.github_repo = "tsuki-works/niko"
    settings.github_project_id = "PVT_x"

    return KindContext(
        job=job, discord_channel=MagicMock(), github_client=gh, anthropic_client=anth,
        state=MagicMock(),
        now=datetime(2026, 5, 6, 9, 0, tzinfo=timezone.utc),
        settings=settings, logger=MagicMock(),
    )


@pytest.mark.asyncio
async def test_returns_polished_post_on_anthropic_success():
    ctx = _ctx(polish_text="✨ here's your brief")
    result = await handle(ctx)
    assert len(result.posts) == 1
    assert "✨ here's your brief" in result.posts[0].content


@pytest.mark.asyncio
async def test_falls_back_to_data_brief_on_anthropic_error():
    ctx = _ctx(anthropic_raises=True)
    result = await handle(ctx)
    assert len(result.posts) == 1
    # Plain data brief — shouldn't contain "polished!"
    assert "Sprint" in result.posts[0].content or "Recent commits" in result.posts[0].content
```

- [ ] **Step 16.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_digest_via_agent.py -v
```

Expected: ImportError.

- [ ] **Step 16.3: Implement the kind**

Create `bot/jarvis/jobs/kinds/digest_via_agent.py`:

```python
"""digest_via_agent — deterministic data brief + constrained LLM polish.

Used by morning_sprint_brief and end_of_week_recap. The Anthropic call
explicitly passes tools=[] so the model can NEVER call tools — it only
polishes the data we hand it.
"""

from __future__ import annotations

import logging

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import list_open_prs
from jarvis.jobs.kinds import register_kind

logger = logging.getLogger(__name__)

_MAX_TOKENS = 600
_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPTS: dict[str, str] = {
    "morning_sprint_brief": (
        "You polish a daily standup brief for a 4-person engineering team's Discord. "
        "Stay tight (≤200 words). Use plain Markdown headings + bullets. "
        "NEVER invent facts, PR numbers, or names. NEVER call tools — you don't have any. "
        "If the data is empty, say so honestly."
    ),
    "end_of_week_recap": (
        "You polish a Friday afternoon recap for a 4-person engineering team's Discord. "
        "Lead with what shipped this week, then carry-over items. ≤250 words. "
        "Plain Markdown bullets. NEVER invent facts. NEVER call tools."
    ),
}

_GRAPHQL = """
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


async def _gather_sources(ctx: KindContext) -> dict:
    sources = ctx.job.params.get("sources", [])
    repo = getattr(ctx.settings, "github_repo", "tsuki-works/niko")
    project_id = getattr(ctx.settings, "github_project_id", None)
    out: dict = {}

    if "sprint" in sources and project_id:
        data = await ctx.github_client.graphql(_GRAPHQL, variables={"id": project_id})
        nodes = (((data or {}).get("node") or {}).get("items") or {}).get("nodes") or []
        items = []
        for n in nodes:
            content = n.get("content") or {}
            status = None
            for fv in (n.get("fieldValues") or {}).get("nodes") or []:
                if (fv.get("field") or {}).get("name") == "Status":
                    status = fv.get("name")
            items.append({
                "number": content.get("number"),
                "title": content.get("title"),
                "status": status,
            })
        out["sprint"] = {"items": items}

    if "recent_commits" in sources:
        commits = await ctx.github_client.get(
            f"/repos/{repo}/commits", params={"sha": "master", "per_page": 20}
        )
        out["recent_commits"] = [
            {
                "sha": (c.get("sha") or "")[:8],
                "title": (c.get("commit", {}).get("message") or "").split("\n", 1)[0],
                "author": c.get("commit", {}).get("author", {}).get("name"),
            }
            for c in (commits or [])
        ]

    if "open_prs" in sources:
        out["open_prs"] = await list_open_prs(ctx.github_client, repo)

    if "merged_prs" in sources:
        prs = await ctx.github_client.get(
            f"/repos/{repo}/pulls",
            params={"state": "closed", "per_page": 30, "sort": "updated", "direction": "desc"},
        )
        out["merged_prs"] = [p for p in (prs or []) if p.get("merged_at")]

    return out


def _build_data_brief(data: dict) -> str:
    parts: list[str] = []
    sprint = data.get("sprint")
    if sprint and sprint.get("items"):
        parts.append("**Sprint**")
        for it in sprint["items"]:
            parts.append(f" • #{it.get('number')} [{it.get('status') or '?'}] {it.get('title') or ''}")
    commits = data.get("recent_commits")
    if commits:
        parts.append("\n**Recent commits**")
        for c in commits[:10]:
            parts.append(f" • `{c.get('sha')}` {c.get('title')} ({c.get('author')})")
    prs = data.get("open_prs")
    if prs:
        parts.append("\n**Open PRs**")
        for p in prs[:10]:
            author = (p.get('user') or {}).get('login') or '?'
            parts.append(f" • PR #{p.get('number')} {p.get('title')} ({author})")
    merged = data.get("merged_prs")
    if merged:
        parts.append("\n**Merged this period**")
        for p in merged[:10]:
            parts.append(f" • PR #{p.get('number')} {p.get('title')}")
    return "\n".join(parts) if parts else "(no data — check back later)"


async def handle(ctx: KindContext) -> KindResult:
    data = await _gather_sources(ctx)
    brief = _build_data_brief(data)
    polish_key = ctx.job.params.get("polish_prompt", "morning_sprint_brief")
    system_prompt = _SYSTEM_PROMPTS.get(polish_key, _SYSTEM_PROMPTS["morning_sprint_brief"])

    try:
        msg = await ctx.anthropic_client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system_prompt,
            tools=[],
            messages=[{"role": "user", "content": f"{brief}\n\nWrite a short Discord-friendly summary."}],
        )
        polished = "".join(getattr(b, "text", "") for b in (msg.content or []))
        if not polished.strip():
            polished = brief
    except Exception:  # noqa: BLE001 — fall back to data brief
        logger.exception("digest polish failed; using deterministic brief")
        polished = brief

    return KindResult(posts=[PlannedPost(content=polished)], summary=polish_key)


register_kind("digest_via_agent", handle)
```

- [ ] **Step 16.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_kind_digest_via_agent.py -v
```

Expected: 3 passed.

- [ ] **Step 16.5: Commit**

```bash
git add bot/jarvis/jobs/kinds/digest_via_agent.py bot/tests/test_jobs_kind_digest_via_agent.py
git commit -m "feat(bot): jobs - digest_via_agent kind"
```

---

## Task 17: Manifest — `manifest.py`

**Files:**
- Create: `bot/jarvis/jobs/manifest.py`
- Create: `bot/tests/test_jobs_manifest.py`

- [ ] **Step 17.1: Write the failing test**

Create `bot/tests/test_jobs_manifest.py`:

```python
from __future__ import annotations

# Importing kinds populates the registry; importing manifest then validates.
import jarvis.jobs.kinds.approved_pr_not_merged  # noqa: F401
import jarvis.jobs.kinds.ci_red_pr_nudge  # noqa: F401
import jarvis.jobs.kinds.dependabot_pair_check  # noqa: F401
import jarvis.jobs.kinds.digest_via_agent  # noqa: F401
import jarvis.jobs.kinds.pr_review_nudge  # noqa: F401
import jarvis.jobs.kinds.stuck_in_progress  # noqa: F401

from jarvis.jobs.manifest import JOBS
from jarvis.jobs.scheduler import validate_manifest


def test_v1_manifest_has_seven_jobs():
    assert len(JOBS) == 7
    names = {j.name for j in JOBS}
    assert names == {
        "morning_sprint_brief", "pr_review_nudge", "approved_pr_not_merged",
        "ci_red_pr_nudge", "dependabot_pair_check", "stuck_in_progress",
        "end_of_week_recap",
    }


def test_v1_manifest_validates():
    validate_manifest(JOBS)
```

- [ ] **Step 17.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_manifest.py -v
```

Expected: ImportError.

- [ ] **Step 17.3: Implement `manifest.py`**

Create `bot/jarvis/jobs/manifest.py`:

```python
"""v1 manifest — seven jobs covering the team's most painful workflow gaps."""

from __future__ import annotations

from jarvis.jobs import Job

JOBS: list[Job] = [
    Job(
        name="morning_sprint_brief",
        kind="digest_via_agent",
        cron="0 9 * * 1-5",
        channel="#weekly-sync",
        params={
            "sources": ["sprint", "recent_commits", "open_prs"],
            "lookback_hours": 24,
            "polish_prompt": "morning_sprint_brief",
        },
    ),
    Job(
        name="pr_review_nudge",
        kind="pr_review_nudge",
        cron="0 10-18/4 * * 1-5",
        channel="#code-review",
        params={"min_age_hours": 4, "dedup_window": "1d"},
    ),
    Job(
        name="approved_pr_not_merged",
        kind="approved_pr_not_merged",
        cron="0 10-18/3 * * 1-5",
        channel="#code-review",
        params={"min_age_after_approval_hours": 2, "dedup_window": "12h"},
    ),
    Job(
        name="ci_red_pr_nudge",
        kind="ci_red_pr_nudge",
        cron="0 10-18/2 * * 1-5",
        channel="#code-review",
        params={"dedup_window": "6h"},
    ),
    Job(
        name="dependabot_pair_check",
        kind="dependabot_pair_check",
        cron="30 9 * * 1-5",
        channel="#code-review",
        params={
            "pairs": [
                ["react", "react-dom"],
                ["@types/react", "@types/react-dom"],
                ["eslint", "@typescript-eslint/parser", "@typescript-eslint/eslint-plugin"],
            ],
        },
    ),
    Job(
        name="stuck_in_progress",
        kind="stuck_in_progress",
        cron="0 11 * * 1-5",
        channel="#blockers",
        params={"stale_days": 3, "dedup_window": "1d"},
    ),
    Job(
        name="end_of_week_recap",
        kind="digest_via_agent",
        cron="0 16 * * 5",
        channel="#milestones-updates",
        params={
            "sources": ["sprint", "recent_commits", "merged_prs"],
            "lookback_hours": 168,
            "polish_prompt": "end_of_week_recap",
        },
    ),
]
```

- [ ] **Step 17.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_manifest.py -v
```

Expected: 2 passed.

- [ ] **Step 17.5: Commit**

```bash
git add bot/jarvis/jobs/manifest.py bot/tests/test_jobs_manifest.py
git commit -m "feat(bot): jobs - v1 manifest (7 jobs)"
```

---

## Task 18: Manual-trigger CLI — `run.py`

**Files:**
- Create: `bot/jarvis/jobs/run.py`
- Create: `bot/tests/test_jobs_run_cli.py`

The CLI:
1. Loads `Settings`, builds dependencies (no Discord gateway start).
2. Creates a minimal "fake" Discord client whose `get_channel(id)` returns an object with a printable `send(content)` (so local dev sees the post in stdout).
3. Resolves the named job from `JOBS`, builds `JobExecutor`, runs once, exits.

- [ ] **Step 18.1: Write the failing test**

Create `bot/tests/test_jobs_run_cli.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarvis.jobs import Job
from jarvis.jobs.run import _resolve_job, run_named


def test_resolve_job_finds_by_name():
    j = _resolve_job([Job(name="x", kind="k", cron="* * * * *", channel="#c")], "x")
    assert j.name == "x"


def test_resolve_job_unknown_raises():
    with pytest.raises(KeyError):
        _resolve_job([], "ghost")


@pytest.mark.asyncio
async def test_run_named_invokes_executor():
    with patch("jarvis.jobs.run._build_executor") as mk:
        executor = MagicMock()
        executor.run = AsyncMock()
        mk.return_value = executor
        with patch("jarvis.jobs.run.JOBS", [Job(name="x", kind="k", cron="* * * * *", channel="#c")]):
            await run_named("x")
        executor.run.assert_awaited_once()
```

- [ ] **Step 18.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_run_cli.py -v
```

Expected: ImportError.

- [ ] **Step 18.3: Implement `run.py`**

Create `bot/jarvis/jobs/run.py`:

```python
"""CLI: python -m jarvis.jobs.run <name>

Builds the same dependency graph as main.py, but instead of starting the
Discord gateway, uses a print-only fake channel for local debug. Runs the
named job once and exits. Useful for iterating on prompts and templates.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from anthropic import AsyncAnthropic
from google.cloud.firestore import AsyncClient as AsyncFirestoreClient

# Import all kinds so KIND_REGISTRY is populated by side-effect.
import jarvis.jobs.kinds.approved_pr_not_merged  # noqa: F401
import jarvis.jobs.kinds.ci_red_pr_nudge  # noqa: F401
import jarvis.jobs.kinds.dependabot_pair_check  # noqa: F401
import jarvis.jobs.kinds.digest_via_agent  # noqa: F401
import jarvis.jobs.kinds.pr_review_nudge  # noqa: F401
import jarvis.jobs.kinds.stuck_in_progress  # noqa: F401

from jarvis.config import get_settings
from jarvis.github_client import AsyncGitHubClient
from jarvis.jobs import Job
from jarvis.jobs.executor import JobExecutor
from jarvis.jobs.manifest import JOBS
from jarvis.jobs.self_report import SelfReporter
from jarvis.logging_setup import configure_logging

logger = logging.getLogger(__name__)


class _PrintChannel:
    async def send(self, content: str) -> None:
        print(f"\n=== POST ===\n{content}\n============")


class _FakeDiscordClient:
    def get_channel(self, _cid: int) -> Any:
        return _PrintChannel()


def _resolve_job(jobs: list[Job], name: str) -> Job:
    for j in jobs:
        if j.name == name:
            return j
    raise KeyError(f"no job named {name!r}; available: {[j.name for j in jobs]}")


def _build_executor() -> JobExecutor:
    settings = get_settings()
    anth = AsyncAnthropic(api_key=settings.anthropic_api_key)
    fs_kwargs = {"project": settings.gcp_project_id} if settings.gcp_project_id else {}
    fs = AsyncFirestoreClient(**fs_kwargs)
    gh = AsyncGitHubClient(token=settings.github_token or "")
    fake_discord = _FakeDiscordClient()
    self_reporter = SelfReporter(fake_discord)
    return JobExecutor(
        discord_client=fake_discord,
        github_client=gh,
        anthropic_client=anth,
        firestore_client=fs,
        self_reporter=self_reporter,
        settings=settings,
    )


async def run_named(name: str) -> None:
    job = _resolve_job(JOBS, name)
    executor = _build_executor()
    await executor.run(job)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m jarvis.jobs.run <job-name>", file=sys.stderr)
        sys.exit(2)
    configure_logging("INFO")
    asyncio.run(run_named(sys.argv[1]))


if __name__ == "__main__":
    main()
```

- [ ] **Step 18.4: Run test to confirm it passes**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_jobs_run_cli.py -v
```

Expected: 3 passed.

- [ ] **Step 18.5: Commit**

```bash
git add bot/jarvis/jobs/run.py bot/tests/test_jobs_run_cli.py
git commit -m "feat(bot): jobs - manual-trigger CLI (jarvis.jobs.run)"
```

---

## Task 19: Wire scheduler into `main.py`

**Files:**
- Modify: `bot/jarvis/main.py`
- Modify: `bot/tests/test_main.py` (extend, don't rewrite)

Goal: after the gateway is ready, validate the manifest, build executor + scheduler, start it. On shutdown, also stop the scheduler. Boot self-report fires once.

- [ ] **Step 19.1: Update tests in `test_main.py`**

Open `bot/tests/test_main.py`. Find the existing `_build_handler` test scaffolding. Append:

```python
from jarvis.jobs import Job


def test_main_imports_jobs_subsystem_without_error():
    # Side-effect: importing main should populate the kind registry.
    import jarvis.main  # noqa: F401
    from jarvis.jobs.kinds import KIND_REGISTRY
    assert "pr_review_nudge" in KIND_REGISTRY
    assert "digest_via_agent" in KIND_REGISTRY
```

- [ ] **Step 19.2: Run test to confirm it fails**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_main.py::test_main_imports_jobs_subsystem_without_error -v
```

Expected: FAIL because `jarvis.main` doesn't import the kinds yet.

- [ ] **Step 19.3: Modify `main.py` — imports + scheduler wiring**

In `bot/jarvis/main.py`:

(a) Add side-effect imports at the top so the kind registry is populated:

```python
# Side-effect imports: registering kinds with KIND_REGISTRY.
import jarvis.jobs.kinds.approved_pr_not_merged  # noqa: F401
import jarvis.jobs.kinds.ci_red_pr_nudge  # noqa: F401
import jarvis.jobs.kinds.dependabot_pair_check  # noqa: F401
import jarvis.jobs.kinds.digest_via_agent  # noqa: F401
import jarvis.jobs.kinds.pr_review_nudge  # noqa: F401
import jarvis.jobs.kinds.stuck_in_progress  # noqa: F401
```

(b) Add to the existing imports:

```python
from jarvis.jobs.executor import JobExecutor
from jarvis.jobs.manifest import JOBS
from jarvis.jobs.scheduler import build_scheduler, validate_manifest
from jarvis.jobs.self_report import SelfReporter
```

(c) Modify `run()` to build the executor, scheduler, and self-reporter; start scheduler after gateway ready; stop on shutdown. Insert after `app = build_app(...)` and before the `gateway_task = asyncio.create_task(...)` line:

```python
    # --- scheduled jobs subsystem ---
    self_reporter = SelfReporter(bot)
    executor = JobExecutor(
        discord_client=bot,
        github_client=github_client,  # may be None if no GITHUB_TOKEN — kinds will short-circuit
        anthropic_client=...,          # captured below
        firestore_client=firestore_client,
        self_reporter=self_reporter,
        settings=settings,
    )
```

…this is awkward because `anthropic_client`, `github_client`, `firestore_client` are local to `_build_handler`. **Refactor: lift those constructions out of `_build_handler` and return them**, OR construct them again at the `run()` scope.

Cleanest refactor: have `_build_handler` accept the three clients as kwargs and return both the `OnMessageHandler` and the scheduler-prep data. To minimize diff, instead pass the clients up via a small mutable closure.

Concretely, replace `_build_handler(settings)` with `_build_handler(settings, *, anthropic_client, firestore_client, github_client, github_repo)`, and construct the clients in `run()`:

```python
async def run() -> None:
    settings: Settings = get_settings()
    configure_logging(settings.jarvis_log_level)
    logger.info("jarvis starting commit_sha=%s", settings.commit_sha or "(unset)")

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required.")
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    fs_kwargs = {"project": settings.gcp_project_id} if settings.gcp_project_id else {}
    firestore_client = AsyncFirestoreClient(**fs_kwargs)
    github_client = AsyncGitHubClient(token=settings.github_token) if settings.github_token else None

    handler = _build_handler(
        settings,
        anthropic_client=anthropic_client,
        firestore_client=firestore_client,
        github_client=github_client,
    )
    bot = JarvisBot(guild_id=settings.discord_guild_id, on_message_handler=handler)
    # ... existing on_ready wrapping ...

    self_reporter = SelfReporter(bot)
    executor = JobExecutor(
        discord_client=bot,
        github_client=github_client,
        anthropic_client=anthropic_client,
        firestore_client=firestore_client,
        self_reporter=self_reporter,
        settings=settings,
    )

    async def start_scheduler_after_ready():
        await bot.wait_until_ready()
        try:
            validate_manifest(JOBS)
        except Exception:
            logger.exception("manifest validation failed; scheduler disabled")
            await self_reporter.boot(commit_sha=settings.commit_sha, job_count=0)
            return
        sched = build_scheduler(executor, JOBS)
        sched.start()
        await self_reporter.boot(commit_sha=settings.commit_sha, job_count=len(sched.get_jobs()))
        # keep a reference to prevent GC
        bot._scheduler = sched  # type: ignore[attr-defined]

    scheduler_task = asyncio.create_task(start_scheduler_after_ready(), name="scheduler-startup")
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
        for task in done:
            task.result()
    finally:
        sched_attr = getattr(bot, "_scheduler", None)
        if sched_attr is not None:
            try:
                sched_attr.shutdown(wait=False)
            except Exception:
                logger.exception("scheduler shutdown failed")
        try:
            await bot.close()
        except Exception:
            logger.exception("jarvis bot.close() raised during shutdown")
        if not scheduler_task.done():
            scheduler_task.cancel()
```

Update `_build_handler` signature (add the kwargs); remove the duplicate client construction inside; pass `anthropic_client`, `firestore_client`, `github_client` through (the function already used those names locally — just become parameters).

- [ ] **Step 19.4: Run the new test plus existing main tests to confirm nothing regresses**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests/test_main.py -v
```

Expected: all existing tests + the new one pass. If a pre-existing test asserted `_build_handler` takes only `(settings)`, update its call site to pass the three clients (use `MagicMock()` for each).

- [ ] **Step 19.5: Run full bot test suite**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests -v
```

Expected: all green. Investigate any failure before committing.

- [ ] **Step 19.6: Commit**

```bash
git add bot/jarvis/main.py bot/tests/test_main.py
git commit -m "feat(bot): jobs - wire scheduler + executor + self-reporter into main"
```

---

## Task 20: Delete `jarvis-discord.yml` + update CLAUDE.md

**Files:**
- Delete: `.github/workflows/jarvis-discord.yml`
- Modify: `CLAUDE.md`

- [ ] **Step 20.1: Delete the workflow**

```bash
git rm .github/workflows/jarvis-discord.yml
```

- [ ] **Step 20.2: Update CLAUDE.md channel-IDs section**

Open `CLAUDE.md`. Find the "Useful channel IDs" paragraph (under the Discord integration section). Replace it with the canonical list (drops `#okrs-roadmap`, adds the new aliases the bot now references):

Find:

```
Useful channel IDs: `#code-review` = `1495194166886400021`, `#ci-alerts` = `1495194041246285857`, `#okrs-roadmap` = `1495192531766345919`, ...
```

Replace with:

```
Useful channel IDs: `#code-review` = `1495194166886400021`, `#ci-alerts` = `1495194041246285857`, `#weekly-sync` = `1499827602397859961`, `#milestones-updates` = `1495607520444551278`, `#decisions-log` = `1495192153947766885`, `#blockers` = `1495192657545396354`, `#general` (COMPANY) = `1495192027913130074`, `#shared-creds` = `1495461045622280382`, `#jarvis` = `1500002427389087787`, `#infra` = `1495193915362508911`, `#backend` = `1495193663628640256`, `#frontend` = `1495193789592113156`, `#demos` = `1499827733302349844` (use `/shared-creds` skill to fetch — never commit or memory-save credentials).
```

Below the Discord section, add a short note about the new subsystem (one paragraph):

```
- **Scheduled jobs subsystem (`bot/jarvis/jobs/`):** the bot runs APScheduler in-process and posts to the right channel based on signal type (`pr_review_nudge` → `#code-review`, `morning_sprint_brief` → `#weekly-sync`, `stuck_in_progress` → `#blockers`, etc.). `#jarvis` is the bot-meta channel — boot pings, job audit, failures. See `docs/superpowers/specs/2026-05-06-jarvis-scheduled-jobs-design.md`. Manually trigger any job locally with `PYTHONPATH=bot .venv/Scripts/python -m jarvis.jobs.run <job-name>`.
```

- [ ] **Step 20.3: Run full bot suite + grep for stale references**

```bash
PYTHONPATH=bot .venv/Scripts/python -m pytest bot/tests -v
```

```bash
grep -rn "okrs-roadmap" --include="*.py" --include="*.md" .
```

Expected: only matches in `docs/` historical files (sprint plans). No matches in `bot/` or `CLAUDE.md`.

- [ ] **Step 20.4: Commit**

```bash
git add -A .github/workflows/jarvis-discord.yml CLAUDE.md
git commit -m "chore(bot): jobs - delete jarvis-discord.yml + update CLAUDE.md channel list"
```

---

## Task 21: Final integration sweep

**Files:** none (verification only)

- [ ] **Step 21.1: Run the full backend + bot test suite**

```bash
.venv/Scripts/python -m pytest -v
```

Expected: all green. Investigate any regression.

- [ ] **Step 21.2: Smoke-import the main module**

```bash
PYTHONPATH=bot .venv/Scripts/python -c "import jarvis.main; from jarvis.jobs.scheduler import validate_manifest; from jarvis.jobs.manifest import JOBS; validate_manifest(JOBS); print(f'manifest ok: {len(JOBS)} jobs')"
```

Expected: `manifest ok: 7 jobs`.

- [ ] **Step 21.3: Manually trigger a kind locally (optional but recommended)**

If you have local `.env` with `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, GCP ADC:

```bash
PYTHONPATH=bot .venv/Scripts/python -m jarvis.jobs.run pr_review_nudge
```

Expected: prints any candidate posts to stdout (no Discord). Confirms the GitHub call path works end-to-end.

- [ ] **Step 21.4: Push the branch and open a draft PR**

```bash
git push -u origin feat/jarvis-scheduled-jobs-spec
gh pr create --draft --title "feat(bot): jarvis scheduled-jobs framework + 7 v1 jobs" --body "$(cat <<'EOF'
## Summary

Adds a generalized scheduled-jobs framework to the Jarvis bot and seven v1 jobs.

`#jarvis` becomes a bot-meta channel (boot pings + per-job audit + failures); jobs post to the right existing channel based on signal type.

Replaces `.github/workflows/jarvis-discord.yml` (which duplicated `#ci-alerts`).

Spec: `docs/superpowers/specs/2026-05-06-jarvis-scheduled-jobs-design.md`
Plan: `docs/superpowers/plans/2026-05-06-jarvis-scheduled-jobs.md`

## What landed

- Framework: `Job`, `KindContext`, `KindResult`, `PlannedPost`, `KIND_REGISTRY`, `JobExecutor`, `build_scheduler`, `validate_manifest`, `FirestoreJobState`, `SelfReporter`, channel + team modules, manual-trigger CLI.
- Six kinds: `pr_review_nudge`, `approved_pr_not_merged`, `ci_red_pr_nudge`, `dependabot_pair_check`, `stuck_in_progress`, `digest_via_agent`.
- Seven v1 jobs: morning sprint brief (#weekly-sync), Friday recap (#milestones-updates), 4 PR-related kinds (#code-review), stuck-in-progress (#blockers).
- Wired into `bot/jarvis/main.py` after gateway-ready; boot self-report fires on every restart.
- Deleted `.github/workflows/jarvis-discord.yml` and updated CLAUDE.md.

## Test plan

- [ ] `pytest -v` — all green
- [ ] `python -m jarvis.jobs.run pr_review_nudge` (locally) — prints any candidate posts
- [ ] After merge: `gcloud compute instances reset jarvis --zone us-west1-a`; observe boot ping in #jarvis
- [ ] Watch first scheduled fire (next weekday 09:00 ET) → morning_sprint_brief in #weekly-sync
- [ ] Confirm CI doesn't post the old PR-opened-in-bot/** notifications anymore

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: returns the PR URL.

- [ ] **Step 21.5: No commit needed**

Branch is already pushed; PR is created. Implementation complete.

---

## Self-review

This plan was reviewed inline. Spec coverage by section:

- §Architecture → Tasks 1–10 (deps, types, channels, team, state, self-report, registry, github queries, executor, scheduler).
- §Manifest schema → Task 2 + Task 17.
- §Job-kind registry (six kinds) → Tasks 11–16.
- §Channel routing + SelfReporter → Tasks 3, 4, 6.
- §Scheduler + dedup state → Tasks 5, 9, 10.
- §Manual-trigger CLI → Task 18.
- §Replacing jarvis-discord.yml → Task 20.
- §Testing approach → every kind/module has a test task; final sweep in Task 21.

No placeholders. Type names consistent (`KindResult`, `PlannedPost`, `KindContext` referenced uniformly across tasks). Method signatures (`merge_state`, `is_dedup_seen`, `mark_dedup_seen`, `register_kind`) match between definition and use.
