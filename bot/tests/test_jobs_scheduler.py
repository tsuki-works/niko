from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from jarvis.jobs import Job
from jarvis.jobs.kinds import KIND_REGISTRY
from jarvis.jobs.scheduler import (
    ManifestValidationError,
    build_scheduler,
    validate_manifest,
)


def _kind_ok():
    async def _noop(ctx):
        return None

    KIND_REGISTRY["__noop"] = _noop  # type: ignore[assignment]


def test_validate_manifest_ok():
    _kind_ok()
    jobs = [Job(name="a", kind="__noop", cron="0 9 * * *", channel="#jarvis")]
    validate_manifest(jobs)


def test_validate_manifest_unknown_kind():
    with pytest.raises(ManifestValidationError, match="kind"):
        validate_manifest([Job(name="a", kind="ghost", cron="0 9 * * *", channel="#jarvis")])


def test_validate_manifest_unknown_channel():
    _kind_ok()
    with pytest.raises(ManifestValidationError, match="channel"):
        validate_manifest([Job(name="a", kind="__noop", cron="0 9 * * *", channel="#nope")])


def test_validate_manifest_bad_cron():
    _kind_ok()
    with pytest.raises(ManifestValidationError, match="cron"):
        validate_manifest([Job(name="a", kind="__noop", cron="not-a-cron", channel="#jarvis")])


def test_validate_manifest_duplicate_names():
    _kind_ok()
    with pytest.raises(ManifestValidationError, match="duplicate"):
        validate_manifest(
            [
                Job(name="a", kind="__noop", cron="0 9 * * *", channel="#jarvis"),
                Job(name="a", kind="__noop", cron="0 9 * * *", channel="#jarvis"),
            ]
        )


def test_build_scheduler_skips_disabled():
    _kind_ok()
    executor = MagicMock()
    jobs = [
        Job(name="on", kind="__noop", cron="0 9 * * *", channel="#jarvis"),
        Job(name="off", kind="__noop", cron="0 9 * * *", channel="#jarvis", enabled=False),
    ]
    sched = build_scheduler(executor, jobs)
    ids = {j.id for j in sched.get_jobs()}
    assert ids == {"on"}
