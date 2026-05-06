"""Deepgram vendor package — STT and TTS implementations co-located.

The package exists so per-vendor configuration (API key reader, base URL,
shared HTTP client) can live in one place and be consumed by both
``stt.py`` and ``tts.py``. The router never imports from here directly;
consumers route through ``app/stt`` and ``app/tts``.
"""

from __future__ import annotations

from app.config import settings


_DEEPGRAM_BASE = "https://api.deepgram.com/v1"


def _api_key() -> str:
    """Return the Deepgram API key, raising a clear error when missing.

    Both halves of the Deepgram package call this lazily so importing
    ``app.deepgram`` never crashes environments where the key isn't set.
    """
    key = settings.deepgram_api_key
    if not key:
        raise RuntimeError(
            "DEEPGRAM_API_KEY not set — cannot reach Deepgram. "
            "Fetch credentials via /shared-creds."
        )
    return key
