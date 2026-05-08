"""Local-dev caller-audio dump.

Writes raw mulaw 8 kHz bytes from the inbound (caller) Twilio media
track to a flat file on local disk. Used to capture real-call audio
that we can then re-feed to Deepgram via ``scripts/replay_stt.py`` to
A/B different STT configurations (Flux vs Nova-2 vs Nova-3, varying
keyterm sets) without having to make repeated live calls.

This module is intentionally local-dev-only:
- ``open_caller_dump`` returns ``None`` when ``settings.niko_local_audio_dump_dir``
  is empty/unset (the production default), so the production code path
  pays zero cost.
- All filesystem failures are caught and logged; they never raise into
  the call loop.

File format: raw mulaw 8 kHz, no header. Same bytes Twilio's media
events deliver and Deepgram's ``send_media`` consumes — replay is a
byte-for-byte forward, no encode/decode round-trip.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class CallerAudioDump:
    """Append-only writer for one call's inbound mulaw stream.

    Constructed by ``open_caller_dump``. The class swallows IOErrors on
    ``append`` and ``close`` and flips an internal ``broken`` flag so
    subsequent ``append`` calls become no-ops — a disk-full mid-call
    must not break the live STT path.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._fh = open(path, "ab")
        self._broken = False

    @property
    def path(self) -> str:
        return self._path

    def append(self, mulaw_bytes: bytes) -> None:
        if self._broken or not mulaw_bytes:
            return
        try:
            self._fh.write(mulaw_bytes)
        except (OSError, ValueError):
            # OSError covers disk-full / permission-denied; ValueError
            # is what Python raises when the underlying file handle is
            # already closed. Either way the dump is dead — flip the
            # broken flag and stop writing for the rest of the call.
            logger.exception("audio_dump: append failed path=%s", self._path)
            self._broken = True
            try:
                self._fh.close()
            except (OSError, ValueError):
                pass

    def close(self) -> None:
        if self._broken:
            return
        try:
            self._fh.flush()
            self._fh.close()
        except (OSError, ValueError):
            logger.exception("audio_dump: close failed path=%s", self._path)
            self._broken = True


def open_caller_dump(call_sid: str) -> Optional[CallerAudioDump]:
    """Return a writer for this call, or ``None`` when disabled.

    Disabled cases (all return ``None``):
      - ``settings.niko_local_audio_dump_dir`` is empty or whitespace.
      - ``call_sid`` is empty (we can't name the file).
      - The configured path exists but is a regular file, not a dir.
      - The directory cannot be created (permission denied) or the
        file cannot be opened (permission denied, disk full).

    All ``OSError`` paths log at WARNING and return ``None`` so the call
    loop is never disrupted by a misconfigured local env.
    """
    dump_dir = (settings.niko_local_audio_dump_dir or "").strip()
    if not dump_dir:
        return None
    if not call_sid:
        return None

    try:
        os.makedirs(dump_dir, exist_ok=True)
    except OSError:
        logger.warning(
            "audio_dump: cannot create dump dir=%r — feature disabled for this call",
            dump_dir,
            exc_info=True,
        )
        return None

    if not os.path.isdir(dump_dir):
        logger.warning(
            "audio_dump: niko_local_audio_dump_dir=%r is not a directory — feature disabled",
            dump_dir,
        )
        return None

    started_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_sid = "".join(c for c in call_sid if c.isalnum() or c in ("-", "_"))
    filename = f"{safe_sid}_{started_at}.ulaw"
    path = os.path.join(dump_dir, filename)

    try:
        dump = CallerAudioDump(path)
    except OSError:
        logger.warning(
            "audio_dump: cannot open dump file=%r — feature disabled for this call",
            path,
            exc_info=True,
        )
        return None

    logger.info("audio_dump: caller dump opened path=%s call_sid=%s", path, call_sid)
    return dump
