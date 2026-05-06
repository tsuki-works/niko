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
