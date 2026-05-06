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
    job = Job(
        name="dependabot_pair_check",
        kind="dependabot_pair_check",
        cron="* * * * *",
        channel="#code-review",
        params={"pairs": pairs},
    )
    gh = MagicMock()
    gh.get = AsyncMock(return_value=prs)
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
async def test_emits_post_when_paired_prs_open():
    prs = [
        {
            "number": 10,
            "title": "Bumps react from 19.1.0 to 19.2.5",
            "html_url": "u/10",
            "user": {"login": "dependabot[bot]"},
        },
        {
            "number": 11,
            "title": "Bumps react-dom from 19.1.0 to 19.2.5",
            "html_url": "u/11",
            "user": {"login": "dependabot[bot]"},
        },
    ]
    result = await handle(_ctx(prs, pairs=[["react", "react-dom"]]))
    assert len(result.posts) == 1
    msg = result.posts[0].content
    assert "📦" in msg
    assert "PR #10" in msg and "PR #11" in msg


@pytest.mark.asyncio
async def test_no_post_when_only_one_of_pair_open():
    prs = [
        {
            "number": 10,
            "title": "Bumps react from 19.1.0 to 19.2.5",
            "html_url": "u/10",
            "user": {"login": "dependabot[bot]"},
        }
    ]
    result = await handle(_ctx(prs, pairs=[["react", "react-dom"]]))
    assert result.posts == []
