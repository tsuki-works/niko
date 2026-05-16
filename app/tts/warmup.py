"""Deepgram Aura connection warmup (#192).

Fires a one-character TTS synth at FastAPI startup so the HTTPS pool to
api.deepgram.com has a live socket before T1 happens. The actual audio
bytes are discarded; the only thing we care about is the TCP+TLS+HTTP2
handshake landing before the first real caller pays for it.

Failures are logged and swallowed — Deepgram blips at startup must not
prevent the app from booting, and T1's real synth has its own error
handling.
"""

from __future__ import annotations

import logging
import time

from app.config import settings
from app.deepgram import _DEEPGRAM_BASE, _api_key
from app.deepgram.tts import _get_client

logger = logging.getLogger(__name__)

_WARMUP_TEXT = "."


async def warm_aura() -> None:
    started = time.monotonic()
    try:
        key = _api_key()
    except Exception as exc:
        logger.warning("aura warmup failed: missing API key (%s)", exc)
        return

    url = f"{_DEEPGRAM_BASE}/speak"
    params = {
        "model": settings.deepgram_tts_model,
        "encoding": "mulaw",
        "sample_rate": "8000",
        "container": "none",
    }
    headers = {
        "Authorization": f"Token {key}",
        "Content-Type": "application/json",
    }

    try:
        client = _get_client()
        async with client.stream(
            "POST", url, headers=headers, params=params, json={"text": _WARMUP_TEXT}
        ) as response:
            if response.status_code != 200:
                logger.warning(
                    "aura warmup failed: Deepgram returned %d",
                    response.status_code,
                )
                return
            async for _ in response.aiter_bytes():
                pass
    except Exception as exc:
        logger.warning("aura warmup failed: %s", exc)
        return

    logger.info("aura warmup completed latency_ms=%d", int((time.monotonic() - started) * 1000))
