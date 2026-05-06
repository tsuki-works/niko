from __future__ import annotations

from datetime import datetime
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

    captured: dict = {}

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
    state.is_dedup_seen = AsyncMock(side_effect=[True, False])
    result = KindResult(
        posts=[
            PlannedPost(content="A", dedup_key="ka"),
            PlannedPost(content="B", dedup_key="kb"),
        ]
    )
    executor, channel, _, _, _ = _fake_executor(state=state, kind_result=result)
    await executor.run(_job())
    assert channel.send.await_count == 1
    state.mark_dedup_seen.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_writes_state_and_self_reports_ok():
    result = KindResult(
        posts=[PlannedPost(content="hi")], summary="1 nudge", state_writes={"foo": 1}
    )
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
    await executor.run(job)
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
