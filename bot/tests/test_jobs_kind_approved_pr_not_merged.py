from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from jarvis.jobs import Job, KindContext
from jarvis.jobs.kinds.approved_pr_not_merged import handle


def _ctx(*, prs, reviews_by_pr, check_runs_by_sha):
    job = Job(
        name="approved_pr_not_merged",
        kind="approved_pr_not_merged",
        cron="* * * * *",
        channel="#code-review",
        params={"min_age_after_approval_hours": 2},
    )

    async def fake_get(path, params=None):
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
    settings = MagicMock()
    settings.github_repo = "tsuki-works/niko"
    return KindContext(
        job=job,
        discord_channel=MagicMock(),
        github_client=gh,
        anthropic_client=MagicMock(),
        state=MagicMock(),
        now=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        settings=settings,
        logger=MagicMock(),
    )


@pytest.mark.asyncio
async def test_emits_for_approved_green_pr():
    prs = [
        {
            "number": 200,
            "title": "Ship it",
            "html_url": "u",
            "user": {"login": "MeetDigrajkar"},
            "head": {"sha": "abc"},
        }
    ]
    reviews = {200: [{"state": "APPROVED", "submitted_at": "2026-05-06T08:00:00Z"}]}
    checks = {"abc": [{"name": "ci", "status": "completed", "conclusion": "success"}]}
    result = await handle(_ctx(prs=prs, reviews_by_pr=reviews, check_runs_by_sha=checks))
    assert len(result.posts) == 1
    assert "PR #200" in result.posts[0].content
    assert "✅" in result.posts[0].content


@pytest.mark.asyncio
async def test_skips_when_checks_red():
    prs = [
        {"number": 1, "title": "x", "html_url": "u", "user": {"login": "a"}, "head": {"sha": "abc"}}
    ]
    reviews = {1: [{"state": "APPROVED", "submitted_at": "2026-05-06T08:00:00Z"}]}
    checks = {"abc": [{"name": "ci", "status": "completed", "conclusion": "failure"}]}
    result = await handle(_ctx(prs=prs, reviews_by_pr=reviews, check_runs_by_sha=checks))
    assert result.posts == []


@pytest.mark.asyncio
async def test_skips_when_approval_too_recent():
    prs = [
        {"number": 1, "title": "x", "html_url": "u", "user": {"login": "a"}, "head": {"sha": "abc"}}
    ]
    reviews = {1: [{"state": "APPROVED", "submitted_at": "2026-05-06T11:00:00Z"}]}
    checks = {"abc": [{"name": "ci", "status": "completed", "conclusion": "success"}]}
    result = await handle(_ctx(prs=prs, reviews_by_pr=reviews, check_runs_by_sha=checks))
    assert result.posts == []
