"""Bot logging configuration.

A single function that configures the root logger. Designed to be safe
to call more than once (handler dedup) so test ordering doesn't matter.
JSON logging is intentionally deferred until we ship to GCE and start
ingesting via Cloud Logging — at that point a structured formatter
gets wired up here without changing any callers.
"""

from __future__ import annotations

import logging

_HANDLER_TAG = "_jarvis_stream_handler"


def configure_logging(level: str = "INFO") -> None:
    resolved = getattr(logging, level.upper(), None)
    if not isinstance(resolved, int):
        resolved = logging.INFO

    root = logging.getLogger()
    root.setLevel(resolved)

    has_ours = any(getattr(h, _HANDLER_TAG, False) for h in root.handlers)
    if not has_ours:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)
