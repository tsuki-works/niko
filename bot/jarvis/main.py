"""Bot entrypoint.

Runs the Discord gateway client and the FastAPI /healthz server on the
same asyncio event loop. If either subsystem exits or raises, the other
is cancelled and the exception (if any) is re-raised so the supervising
process exits non-zero.

Invoked via:

    python -m jarvis.main
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from jarvis.client import JarvisBot
from jarvis.config import Settings, get_settings
from jarvis.http.app import build_app
from jarvis.logging_setup import configure_logging

logger = logging.getLogger(__name__)


async def serve_http(app, port: int) -> None:
    """Run uvicorn against `app` on port until cancelled."""
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def run() -> None:
    settings: Settings = get_settings()
    configure_logging(settings.jarvis_log_level)
    logger.info("jarvis starting commit_sha=%s", settings.commit_sha or "(unset)")

    bot = JarvisBot(guild_id=settings.discord_guild_id)
    app = build_app(commit_sha=settings.commit_sha)

    gateway_task = asyncio.create_task(bot.start(settings.discord_bot_token), name="gateway")
    http_task = asyncio.create_task(serve_http(app, settings.jarvis_http_port), name="http")

    try:
        done, pending = await asyncio.wait(
            {gateway_task, http_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        # Re-raise the first exception from the completed tasks. Calling
        # task.result() (rather than `raise task.exception()`) preserves
        # the original traceback, so a gateway crash points at the
        # gateway frame instead of this loop.
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
