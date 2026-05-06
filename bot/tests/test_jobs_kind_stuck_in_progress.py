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
