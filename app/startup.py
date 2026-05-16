"""FastAPI lifespan startup warmups (#192).

Run once per Cloud Run container boot:

- Prime the Anthropic prompt cache for every tenant with a Twilio
  number, so that tenant's T2 latency on the first inbound call is a
  cache read rather than a cache creation.
- Open the Deepgram Aura HTTPS connection so T1's first synth doesn't
  pay TCP+TLS setup.

All warmups are best-effort. Failures are logged and never raised —
nothing here is a deployment gate.
"""

from __future__ import annotations

import asyncio
import logging

from app.llm.warmup import prime_tenant_cache
from app.storage.restaurants import list_active_restaurants
from app.tts.warmup import warm_aura

logger = logging.getLogger(__name__)


async def run_startup_warmups() -> None:
    try:
        tenants = list_active_restaurants()
    except Exception:
        logger.warning(
            "startup: list_active_restaurants raised — proceeding with no tenant primers",
            exc_info=True,
        )
        tenants = []

    # Defensive filter: ``list_active_restaurants`` already excludes
    # tenants with empty ``twilio_phone``, but the test seam takes a
    # bare list and we want priming to be a one-line invariant — no
    # primer for tenants that can't receive calls.
    active = [t for t in tenants if t.twilio_phone]
    primer_tasks = [prime_tenant_cache(r) for r in active]
    primer_results = await asyncio.gather(*primer_tasks, return_exceptions=True)

    succeeded = sum(1 for r in primer_results if not isinstance(r, BaseException))
    failed = len(primer_results) - succeeded
    if failed:
        for tenant, result in zip(active, primer_results):
            if isinstance(result, BaseException):
                logger.warning(
                    "startup: primer raised for rid=%s — %s",
                    tenant.id,
                    result,
                )

    try:
        await warm_aura()
    except Exception:
        # warm_aura swallows its own exceptions; defense in depth.
        logger.warning("startup: aura warmup raised unexpectedly", exc_info=True)

    logger.info(
        "startup_primers tenants=%d succeeded=%d failed=%d",
        len(active),
        succeeded,
        failed,
    )
