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
    settings = MagicMock()
    settings.github_repo = "tsuki-works/niko"
    return KindContext(
        job=Job(name="ci_red_pr_nudge", kind="ci_red_pr_nudge", cron="* * * * *", channel="#code-review"),
        discord_channel=MagicMock(),
        github_client=gh,
        anthropic_client=MagicMock(),
        state=MagicMock(),
        now=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        settings=settings,
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
