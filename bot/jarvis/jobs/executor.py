"""JobExecutor — runs one Job invocation: dispatch → kind → post → state → report."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from jarvis.jobs import Job, KindContext, KindResult
from jarvis.jobs.channels import resolve as resolve_channel
from jarvis.jobs.kinds import KIND_REGISTRY
from jarvis.jobs.self_report import SelfReporter
from jarvis.jobs.state import FirestoreJobState

logger = logging.getLogger(__name__)

_DISCORD_MAX_MESSAGE = 2000


class JobExecutor:
    def __init__(
        self,
        *,
        discord_client: Any,
        github_client: Any,
        anthropic_client: Any,
        firestore_client: Any,
        self_reporter: SelfReporter,
        settings: Any,
        state_factory: Callable[[Any, str], Any] | None = None,
    ) -> None:
        self._discord = discord_client
        self._github = github_client
        self._anthropic = anthropic_client
        self._firestore = firestore_client
        self._self_reporter = self_reporter
        self._settings = settings
        self._state_factory = state_factory or (lambda fs, name: FirestoreJobState(fs, name))

    async def run(self, job: Job) -> None:
        log = logging.getLogger(f"jarvis.jobs.{job.name}")
        started = datetime.now(timezone.utc)
        log.info("job start: %s → %s", job.name, job.channel)
        state = self._state_factory(self._firestore, job.name)

        try:
            channel = resolve_channel(self._discord, job.channel)
            ctx = KindContext(
                job=job,
                discord_channel=channel,
                github_client=self._github,
                anthropic_client=self._anthropic,
                state=state,
                now=started,
                settings=self._settings,
                logger=log,
            )
            kind_fn = KIND_REGISTRY[job.kind]
            result: KindResult = await kind_fn(ctx)

            posted = 0
            for post in result.posts:
                if post.dedup_key and await state.is_dedup_seen(post.dedup_key):
                    continue
                try:
                    await self._send(channel, post.content)
                except Exception:  # noqa: BLE001
                    log.exception("post send failed; continuing with remaining posts")
                    continue
                if post.dedup_key:
                    await state.mark_dedup_seen(post.dedup_key, ttl=self._dedup_ttl(job))
                posted += 1

            await state.merge_state({
                **result.state_writes,
                "last_run_at": started,
                "last_status": "ok",
            })
            await self._self_reporter.job_ok(
                job, summary=f"{posted} post(s) → {job.channel} · {result.summary or 'ok'}"
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s failed", job.name)
            await state.merge_state({
                "last_run_at": started,
                "last_status": f"error: {type(exc).__name__}",
            })
            await self._self_reporter.job_error(job, exc)

    async def _send(self, channel: Any, content: str) -> None:
        if len(content) <= _DISCORD_MAX_MESSAGE:
            await channel.send(content)
            return
        for i in range(0, len(content), _DISCORD_MAX_MESSAGE):
            await channel.send(content[i : i + _DISCORD_MAX_MESSAGE])

    @staticmethod
    def _dedup_ttl(job: Job) -> timedelta:
        window = (job.params or {}).get("dedup_window", "1d")
        unit = window[-1]
        try:
            n = int(window[:-1])
        except ValueError:
            return timedelta(days=1)
        if unit == "m":
            return timedelta(minutes=n)
        if unit == "h":
            return timedelta(hours=n)
        if unit == "d":
            return timedelta(days=n)
        return timedelta(days=1)
