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
