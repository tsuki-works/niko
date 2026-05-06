"""CLI: python -m jarvis.jobs.run <name>

Builds the same dependency graph as main.py, but instead of starting the
Discord gateway, uses a print-only fake channel for local debug. Runs the
named job once and exits. Useful for iterating on prompts and templates.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from anthropic import AsyncAnthropic
from google.cloud.firestore import AsyncClient as AsyncFirestoreClient

# Side-effect: importing kinds populates KIND_REGISTRY.
import jarvis.jobs.kinds.approved_pr_not_merged  # noqa: F401
import jarvis.jobs.kinds.ci_red_pr_nudge  # noqa: F401
import jarvis.jobs.kinds.dependabot_pair_check  # noqa: F401
import jarvis.jobs.kinds.digest_via_agent  # noqa: F401
import jarvis.jobs.kinds.pr_review_nudge  # noqa: F401
import jarvis.jobs.kinds.stuck_in_progress  # noqa: F401

from jarvis.config import get_settings
from jarvis.github_client import AsyncGitHubClient
from jarvis.jobs import Job
from jarvis.jobs.executor import JobExecutor
from jarvis.jobs.manifest import JOBS
from jarvis.jobs.self_report import SelfReporter
from jarvis.logging_setup import configure_logging

logger = logging.getLogger(__name__)


class _PrintChannel:
    async def send(self, content: str) -> None:
        print(f"\n=== POST ===\n{content}\n============")


class _FakeDiscordClient:
    def get_channel(self, _cid: int) -> Any:
        return _PrintChannel()


def _resolve_job(jobs: list[Job], name: str) -> Job:
    for j in jobs:
        if j.name == name:
            return j
    raise KeyError(f"no job named {name!r}; available: {[j.name for j in jobs]}")


def _build_executor() -> JobExecutor:
    settings = get_settings()
    anth = AsyncAnthropic(api_key=settings.anthropic_api_key)
    fs_kwargs = {"project": settings.gcp_project_id} if settings.gcp_project_id else {}
    fs = AsyncFirestoreClient(**fs_kwargs)
    gh = AsyncGitHubClient(token=settings.github_token or "")
    fake_discord = _FakeDiscordClient()
    self_reporter = SelfReporter(fake_discord)
    return JobExecutor(
        discord_client=fake_discord,
        github_client=gh,
        anthropic_client=anth,
        firestore_client=fs,
        self_reporter=self_reporter,
        settings=settings,
    )


async def run_named(name: str) -> None:
    job = _resolve_job(JOBS, name)
    executor = _build_executor()
    await executor.run(job)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m jarvis.jobs.run <job-name>", file=sys.stderr)
        sys.exit(2)
    configure_logging("INFO")
    asyncio.run(run_named(sys.argv[1]))


if __name__ == "__main__":
    main()
