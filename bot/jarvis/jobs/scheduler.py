"""Scheduler builder + manifest validator."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from jarvis.jobs import Job
from jarvis.jobs.channels import CHANNEL_IDS
from jarvis.jobs.kinds import KIND_REGISTRY

logger = logging.getLogger(__name__)


class ManifestValidationError(ValueError):
    pass


def validate_manifest(jobs: list[Job]) -> None:
    seen: set[str] = set()
    for job in jobs:
        if job.name in seen:
            raise ManifestValidationError(f"duplicate job name: {job.name}")
        seen.add(job.name)

        if job.kind not in KIND_REGISTRY:
            raise ManifestValidationError(
                f"job {job.name}: unknown kind '{job.kind}' (registered: {sorted(KIND_REGISTRY)})"
            )
        if job.channel not in CHANNEL_IDS:
            raise ManifestValidationError(f"job {job.name}: unknown channel '{job.channel}'")
        try:
            CronTrigger.from_crontab(job.cron, timezone=job.timezone)
        except Exception as e:  # noqa: BLE001
            raise ManifestValidationError(f"job {job.name}: invalid cron '{job.cron}' ({e})") from e


def build_scheduler(executor, jobs: list[Job]) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone="UTC")
    for job in jobs:
        if not job.enabled:
            logger.info("skipping disabled job: %s", job.name)
            continue
        trigger = CronTrigger.from_crontab(job.cron, timezone=job.timezone)
        sched.add_job(
            executor.run,
            trigger,
            args=[job],
            id=job.name,
            name=job.name,
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )
    return sched
