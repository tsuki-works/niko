"""SelfReporter — middleware that posts to #jarvis on boot + after every job run.

Three hooks:
  - boot(commit_sha, job_count)     → 🟢 once at startup
  - job_ok(job, summary)            → ✅ after a successful run
  - job_error(job, exception)       → ❌ when a kind raised

All paths swallow failures (logged via the module logger) so a transient
Discord error in the self-report path can never take down a real job.
"""

from __future__ import annotations

import logging
from typing import Any

from jarvis.jobs import Job
from jarvis.jobs.channels import CHANNEL_IDS

logger = logging.getLogger(__name__)

_JARVIS_CHANNEL_ID = CHANNEL_IDS["#jarvis"]
_MAX_ERROR_MSG = 500


class SelfReporter:
    def __init__(self, discord_client: Any) -> None:
        self._client = discord_client

    async def boot(self, *, commit_sha: str, job_count: int) -> None:
        sha_short = (commit_sha or "unknown")[:7]
        await self._post(f"🟢 Jarvis online · commit `{sha_short}` · scheduler: {job_count} jobs")

    async def job_ok(self, job: Job, *, summary: str) -> None:
        await self._post(f"✅ `{job.name}` → {job.channel} · {summary}")

    async def job_error(self, job: Job, err: Exception) -> None:
        msg = f"{type(err).__name__}: {err}"[:_MAX_ERROR_MSG]
        await self._post(f"❌ `{job.name}` failed · {msg}")

    async def _post(self, content: str) -> None:
        try:
            ch = self._client.get_channel(_JARVIS_CHANNEL_ID)
            if ch is None:
                logger.warning("self-report skipped: #jarvis channel not in cache")
                return
            await ch.send(content)
        except Exception:  # noqa: BLE001
            logger.exception("self-report failed")
