"""Bot entrypoint.

Constructs the dependency graph (Anthropic client, Firestore client,
ThreadMemory, OnMessageHandler) and starts the Discord gateway +
FastAPI /healthz on the same asyncio event loop. Also boots the
APScheduler-driven jobs subsystem after the gateway is ready, then
posts a self-report into #jarvis.

If either subsystem exits or raises, the other is cancelled and the
exception (if any) is re-raised so the supervising process exits
non-zero.

Invoked via:

    python -m jarvis.main
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any, Optional

import uvicorn
from anthropic import AsyncAnthropic
from google.cloud.firestore import AsyncClient as AsyncFirestoreClient

# Side-effect: importing kinds populates KIND_REGISTRY so the manifest
# validates at startup. Keep these imports — without them the scheduler
# refuses to start.
import jarvis.jobs.kinds.approved_pr_not_merged  # noqa: F401
import jarvis.jobs.kinds.ci_red_pr_nudge  # noqa: F401
import jarvis.jobs.kinds.dependabot_pair_check  # noqa: F401
import jarvis.jobs.kinds.digest_via_agent  # noqa: F401
import jarvis.jobs.kinds.pr_review_nudge  # noqa: F401
import jarvis.jobs.kinds.stuck_in_progress  # noqa: F401
from jarvis.agent import respond as agent_respond
from jarvis.client import JarvisBot
from jarvis.config import Settings, get_settings
from jarvis.events import OnMessageHandler
from jarvis.github_client import AsyncGitHubClient
from jarvis.http.app import build_app
from jarvis.jobs.executor import JobExecutor
from jarvis.jobs.manifest import JOBS
from jarvis.jobs.scheduler import build_scheduler, validate_manifest
from jarvis.jobs.self_report import SelfReporter
from jarvis.logging_setup import configure_logging
from jarvis.memory import ThreadMemory
from jarvis.ratelimit import InMemoryRateLimiter
from jarvis.stream_writer import stream_to_discord
from jarvis.system_prompt import build_system_prompt
from jarvis.tools import ToolContext, ToolRegistry
from jarvis.tools.chat import build_get_recent_messages_tool
from jarvis.tools.docs import build_search_repo_docs_tool
from jarvis.tools.github import (
    build_get_issue_tool,
    build_get_pr_tool,
    build_get_recent_commits_tool,
    build_open_issue_tool,
)
from jarvis.tools.sprint import build_get_current_sprint_tool

logger = logging.getLogger(__name__)

# Subset of tsuki-works/niko's actual labels that bot-filed issues are
# allowed to carry. Triage labels (duplicate/invalid/wontfix) and
# community markers (good first issue, help wanted) are deliberately
# omitted — those are for human triage, not bot-filed issues.
_OPEN_ISSUE_LABEL_ALLOWLIST = ["bug", "enhancement", "documentation", "question"]


def _detect_commit_sha() -> str:
    """Return `git rev-parse HEAD` of the bot's repo, or "" on failure.

    Used as a fallback when `Settings.commit_sha` (env `COMMIT_SHA`) is
    unset — covers the fast-deploy path (`git pull && systemctl restart`)
    that doesn't re-run `infra/jarvis/startup.sh` and so doesn't refresh
    `/etc/jarvis/env`.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        return result.stdout.strip()
    except Exception:  # noqa: BLE001 — best-effort; absence is non-fatal
        return ""


async def serve_http(app, port: int) -> None:
    """Run uvicorn against `app` on port until cancelled."""
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def _build_handler(
    settings: Settings,
    *,
    anthropic_client: Optional[Any] = None,
    firestore_client: Optional[Any] = None,
    github_client: Optional[Any] = None,
) -> OnMessageHandler:
    """Build the OnMessageHandler.

    Clients can be passed in (run() does this so the same instances are
    shared with the scheduler subsystem). If omitted, they're built
    locally — kept for backwards-compat with older tests that patch
    only `_build_handler`.
    """
    if anthropic_client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required for PR 2 chat. Set it in .env or Secret Manager."
            )
        anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    if firestore_client is None:
        fs_kwargs = {}
        if settings.gcp_project_id:
            fs_kwargs["project"] = settings.gcp_project_id
        firestore_client = AsyncFirestoreClient(**fs_kwargs)

    memory = ThreadMemory(firestore_client)

    rate_limiter = InMemoryRateLimiter(max_per_window=20, window_seconds=3600.0)

    tool_registry: Optional[ToolRegistry] = None

    chat_only_registry = ToolRegistry()
    chat_only_registry.register(build_get_recent_messages_tool())

    if github_client is None and settings.github_token:
        github_client = AsyncGitHubClient(token=settings.github_token)

    if github_client is not None:
        tool_registry = ToolRegistry()
        tool_registry.register(
            build_get_current_sprint_tool(
                github_client=github_client,
                project_id=settings.github_project_id,
            )
        )
        tool_registry.register(
            build_get_recent_commits_tool(
                github_client=github_client,
                repo=settings.github_repo,
            )
        )
        tool_registry.register(build_search_repo_docs_tool(docs_root=Path("docs")))
        tool_registry.register(
            build_get_pr_tool(
                github_client=github_client,
                repo=settings.github_repo,
            )
        )
        tool_registry.register(
            build_get_issue_tool(
                github_client=github_client,
                repo=settings.github_repo,
            )
        )
        tool_registry.register(
            build_open_issue_tool(
                github_client=github_client,
                repo=settings.github_repo,
                allowed_labels=_OPEN_ISSUE_LABEL_ALLOWLIST,
            )
        )
        tool_registry.register(build_get_recent_messages_tool())
        logger.info("tool registry: %s", ", ".join(tool_registry.names()))
    else:
        tool_registry = chat_only_registry
        logger.info(
            "GITHUB_TOKEN not set — running with only chat tools: %s",
            ", ".join(tool_registry.names()),
        )

    async def agent_fn(*, system_prompt, history, user_message, tool_registry, tool_context):
        async for d in agent_respond(
            anthropic_client=anthropic_client,
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
            tool_registry=tool_registry,
            tool_context=tool_context,
        ):
            yield d

    def make_tool_context(message: Any) -> ToolContext:
        return ToolContext(
            guild=getattr(message, "guild", None),
            github_client=github_client,
            github_repo=settings.github_repo,
            github_project_id=settings.github_project_id,
            docs_root=Path("docs"),
        )

    return OnMessageHandler(
        bot_user_id=0,
        memory=memory,
        agent_fn=agent_fn,
        system_prompt_fn=build_system_prompt,
        stream_writer_fn=stream_to_discord,
        rate_limiter=rate_limiter,
        tool_registry=tool_registry,
        tool_context_factory=make_tool_context,
    )


def _build_clients(settings: Settings) -> tuple[Any, Any, Any]:
    """Construct (anthropic, firestore, github) — extracted so tests can patch
    one function instead of three module-level classes."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required.")
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    fs_kwargs = {"project": settings.gcp_project_id} if settings.gcp_project_id else {}
    firestore_client = AsyncFirestoreClient(**fs_kwargs)
    github_client = (
        AsyncGitHubClient(token=settings.github_token) if settings.github_token else None
    )
    return anthropic_client, firestore_client, github_client


async def run() -> None:
    settings: Settings = get_settings()
    configure_logging(settings.jarvis_log_level)
    commit_sha = settings.commit_sha or _detect_commit_sha()
    logger.info("jarvis starting commit_sha=%s", commit_sha or "(unset)")

    anthropic_client, firestore_client, github_client = _build_clients(settings)

    handler = _build_handler(
        settings,
        anthropic_client=anthropic_client,
        firestore_client=firestore_client,
        github_client=github_client,
    )
    bot = JarvisBot(guild_id=settings.discord_guild_id, on_message_handler=handler)

    # discord.Client doesn't expose its user id until on_ready. Wrap
    # the existing on_ready so the handler's bot_user_id is updated as
    # soon as the gateway delivers it. Until that happens the handler's
    # initial bot_user_id=0 means the router never matches a mention,
    # so any too-early message is harmlessly ignored.
    if hasattr(bot, "on_ready"):
        original_on_ready = bot.on_ready

        async def patched_on_ready():
            await original_on_ready()
            if bot.user is not None:
                handler.set_bot_user_id(bot.user.id)
                logger.info("jarvis bot_user_id captured: %d", bot.user.id)

        bot.on_ready = patched_on_ready  # type: ignore[method-assign]

    # --- scheduled jobs subsystem ---
    self_reporter = SelfReporter(bot)
    executor = JobExecutor(
        discord_client=bot,
        github_client=github_client,
        anthropic_client=anthropic_client,
        firestore_client=firestore_client,
        self_reporter=self_reporter,
        settings=settings,
    )

    async def start_scheduler_after_ready() -> None:
        # Fake gateways in tests don't expose wait_until_ready — guard so
        # those tests don't AttributeError here.
        if hasattr(bot, "wait_until_ready"):
            # bot.start() is running concurrently; it hasn't yet initialised
            # the client's _ready event so wait_until_ready() raises
            # RuntimeError("Client has not been properly initialised") if we
            # call it too early. Poll until login has progressed past that
            # gate, then await readiness normally.
            ready_ok = False
            for _ in range(100):  # ~10s of 100ms ticks
                try:
                    await bot.wait_until_ready()
                    ready_ok = True
                    break
                except RuntimeError:
                    await asyncio.sleep(0.1)
                except Exception:  # noqa: BLE001
                    logger.exception("wait_until_ready raised; scheduler disabled")
                    return
            if not ready_ok:
                logger.error("gateway never became ready; scheduler disabled")
                return
        try:
            validate_manifest(JOBS)
        except Exception:  # noqa: BLE001
            logger.exception("manifest validation failed; scheduler disabled")
            await self_reporter.boot(commit_sha=commit_sha, job_count=0)
            return
        sched = build_scheduler(executor, JOBS)
        sched.start()
        await self_reporter.boot(commit_sha=commit_sha, job_count=len(sched.get_jobs()))
        bot._scheduler = sched  # type: ignore[attr-defined]

    app = build_app(commit_sha=commit_sha)

    # Start the gateway BEFORE the scheduler poller so bot.start() has a chance
    # to begin login (sets the internal _ready event) before
    # start_scheduler_after_ready() calls wait_until_ready().
    gateway_task = asyncio.create_task(bot.start(settings.discord_bot_token), name="gateway")
    scheduler_task = asyncio.create_task(start_scheduler_after_ready(), name="scheduler-startup")
    http_task = asyncio.create_task(serve_http(app, settings.jarvis_http_port), name="http")

    try:
        done, pending = await asyncio.wait(
            {gateway_task, http_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    finally:
        sched_attr = getattr(bot, "_scheduler", None)
        if sched_attr is not None:
            try:
                sched_attr.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                logger.exception("scheduler shutdown failed")
        if not scheduler_task.done():
            scheduler_task.cancel()
            try:
                await scheduler_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        try:
            await bot.close()
        except Exception:  # noqa: BLE001 — close() is best-effort on shutdown
            logger.exception("jarvis bot.close() raised during shutdown")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
