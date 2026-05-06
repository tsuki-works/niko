from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from jarvis.jobs import Job
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
    job = Job(
        name="pr_review_nudge", kind="pr_review_nudge", cron="* * * * *", channel="#code-review"
    )
    await reporter.job_ok(job, summary="2 post(s) → #code-review")
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
    await reporter.boot(commit_sha="x", job_count=0)


@pytest.mark.asyncio
async def test_self_report_swallows_missing_channel():
    client = MagicMock()
    client.get_channel = MagicMock(return_value=None)
    reporter = SelfReporter(client)
    await reporter.boot(commit_sha="x", job_count=0)
