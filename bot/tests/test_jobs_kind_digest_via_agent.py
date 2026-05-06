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
    # Plain data brief — empty sprint + commits → fallback message
    content = result.posts[0].content
    assert "no data" in content or "Sprint" in content or "Recent" in content
