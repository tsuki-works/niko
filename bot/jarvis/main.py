"""Bot entrypoint.

Constructs the dependency graph (Anthropic client, Firestore client,
ThreadMemory, OnMessageHandler) and starts the Discord gateway +
FastAPI /healthz on the same asyncio event loop.

If either subsystem exits or raises, the other is cancelled and the
exception (if any) is re-raised so the supervising process exits
non-zero.

Invoked via:

    python -m jarvis.main
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

import uvicorn
from anthropic import AsyncAnthropic
from google.cloud.firestore import AsyncClient as AsyncFirestoreClient

from jarvis.agent import respond as agent_respond
from jarvis.client import JarvisBot
from jarvis.config import Settings, get_settings
from jarvis.events import OnMessageHandler
from jarvis.github_client import AsyncGitHubClient
from jarvis.http.app import build_app
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


async def serve_http(app, port: int) -> None:
    """Run uvicorn against `app` on port until cancelled."""
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def _build_handler(settings: Settings) -> OnMessageHandler:
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is required for PR 2 chat. "
            "Set it in .env or Secret Manager."
        )
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    fs_kwargs = {}
    if settings.gcp_project_id:
        fs_kwargs["project"] = settings.gcp_project_id
    firestore_client = AsyncFirestoreClient(**fs_kwargs)
    memory = ThreadMemory(firestore_client)

    rate_limiter = InMemoryRateLimiter(
        max_per_window=20, window_seconds=3600.0
    )

    tool_registry: Optional[ToolRegistry] = None
    github_client = None

    # get_recent_messages doesn't need GitHub — register it
    # unconditionally so the bot can still ground replies in chat
    # history when GITHUB_TOKEN is unset.
    chat_only_registry = ToolRegistry()
    chat_only_registry.register(build_get_recent_messages_tool())

    if settings.github_token:
        github_client = AsyncGitHubClient(token=settings.github_token)
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
        tool_registry.register(
            build_search_repo_docs_tool(docs_root=Path("docs"))
        )
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
        logger.info(
            "tool registry: %s", ", ".join(tool_registry.names())
        )
    else:
        tool_registry = chat_only_registry
        logger.info(
            "GITHUB_TOKEN not set — running with only chat tools: %s",
            ", ".join(tool_registry.names()),
        )

    async def agent_fn(
        *, system_prompt, history, user_message, tool_registry, tool_context
    ):
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

    # We don't know our own user id until on_ready fires. Capture it
    # there and replace the placeholder. For now bot_user_id=0 — the
    # router will simply not match it, which means the bot ignores
    # everything until on_ready replaces it.
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


async def run() -> None:
    settings: Settings = get_settings()
    configure_logging(settings.jarvis_log_level)
    logger.info("jarvis starting commit_sha=%s", settings.commit_sha or "(unset)")

    handler = _build_handler(settings)
    bot = JarvisBot(
        guild_id=settings.discord_guild_id,
        on_message_handler=handler,
    )
    # discord.Client doesn't expose its user id until on_ready. Wrap
    # the existing on_ready so the handler's bot_user_id is updated as
    # soon as the gateway delivers it. Until that happens the handler's
    # initial bot_user_id=0 means the router never matches a mention,
    # so any too-early message is harmlessly ignored.
    # Guard with hasattr: test stubs that replace JarvisBot don't have on_ready.
    if hasattr(bot, "on_ready"):
        original_on_ready = bot.on_ready

        async def patched_on_ready():
            await original_on_ready()
            if bot.user is not None:
                handler.set_bot_user_id(bot.user.id)
                logger.info("jarvis bot_user_id captured: %d", bot.user.id)

        bot.on_ready = patched_on_ready  # type: ignore[method-assign]

    app = build_app(commit_sha=settings.commit_sha)

    gateway_task = asyncio.create_task(
        bot.start(settings.discord_bot_token), name="gateway"
    )
    http_task = asyncio.create_task(
        serve_http(app, settings.jarvis_http_port), name="http"
    )

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
        try:
            await bot.close()
        except Exception:  # noqa: BLE001 — close() is best-effort on shutdown
            logger.exception("jarvis bot.close() raised during shutdown")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
