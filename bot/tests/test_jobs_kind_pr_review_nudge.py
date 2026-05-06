from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.jobs import Job, KindContext
from jarvis.jobs.kinds.pr_review_nudge import handle


def _ctx(prs):
    job = Job(name="pr_review_nudge", kind="pr_review_nudge", cron="* * * * *", channel="#code-review",
              params={"min_age_hours": 4})
    gh = MagicMock()
    gh.get = AsyncMock(return_value=prs)
    state = MagicMock()
    state.is_dedup_seen = AsyncMock(return_value=False)
    settings = MagicMock()
    settings.github_repo = "tsuki-works/niko"
    return KindContext(
        job=job,
        discord_channel=MagicMock(),
        github_client=gh,
        anthropic_client=MagicMock(),
        state=state,
        now=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        settings=settings,
        logger=MagicMock(),
    )


@pytest.mark.asyncio
async def test_emits_post_per_eligible_pr():
    six_hours_ago = "2026-05-06T06:00:00Z"
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
    too_recent = "2026-05-06T11:30:00Z"
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
    six_hours_ago = "2026-05-06T06:00:00Z"
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
