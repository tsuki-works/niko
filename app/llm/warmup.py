"""Anthropic prompt-cache primer (#192).

Goal: write the per-tenant system prompt to Anthropic's prompt cache
*before* the caller's first real turn (T2) needs it, so T2 reads the
cache instead of paying ``cache_creation``.

Fired twice for every call:
- Once at FastAPI startup, per tenant with a Twilio number (warm
  container case).
- Once from the ``/voice`` HTTP webhook, per inbound call (cold-start
  case — exploits the ~300-500 ms TwiML → WebSocket-connect window).

The call is ``max_tokens=1`` so it costs only the cached-prefix tokens.
All exceptions are swallowed — a failed primer means T2 pays
``cache_creation`` (today's behavior), nothing worse.
"""

from __future__ import annotations

import logging
import time

from app.config import settings
from app.llm.anthropic import (
    UPDATE_ORDER_TOOL,
    _get_async_client,
    _system_cache_block,
)
from app.llm.prompts import build_system_prompt
from app.restaurants.models import Restaurant

logger = logging.getLogger(__name__)


async def prime_tenant_cache(restaurant: Restaurant) -> None:
    """Fire one cache-priming Anthropic call for ``restaurant``.

    Returns ``None`` always — caller does not get a failure signal.
    Failures are logged and swallowed so a flaky primer never breaks the
    surrounding call flow.
    """
    system_prompt = build_system_prompt(restaurant)
    started = time.monotonic()
    try:
        client = _get_async_client()
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1,
            system=_system_cache_block(system_prompt),
            tools=[UPDATE_ORDER_TOOL],
            messages=[{"role": "user", "content": "ping"}],
        )
    except Exception as exc:
        logger.warning(
            "primer failed rid=%s reason=%s",
            restaurant.id,
            exc,
        )
        return None

    usage = getattr(response, "usage", None)
    cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    logger.info(
        "primer completed rid=%s latency_ms=%d cache_creation_tokens=%d cache_read_tokens=%d",
        restaurant.id,
        int((time.monotonic() - started) * 1000),
        cache_creation,
        cache_read,
    )
    return None
