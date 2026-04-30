"""WS-side call recording: encode + resumable GCS upload + signed URLs.

The /media-stream WS hands raw μ-law payloads (per Twilio media event) to
``append_chunks``. We decode each side to 16-bit linear PCM, interleave
L=caller / R=agent, encode incrementally to MP3 via lameenc, and PUT
~256 KB chunks to a GCS resumable upload session held on a per-call
``RecordingUploadSession`` object.

Replaces the broken Twilio-REST recording approach (PRs #127, #132, #133).
See ``docs/superpowers/specs/2026-04-30-ws-recording-design.md``.
"""

from __future__ import annotations

import logging
import struct
import time

import requests

logger = logging.getLogger(__name__)


# G.711 μ-law → 16-bit signed PCM decode table (256 entries).
# stdlib ``audioop`` was removed in Python 3.13; we ship the table
# directly so there is no runtime dependency. Generated once at import
# time from the standard G.711 μ-law algorithm.
def _build_ulaw_table() -> list[int]:
    table: list[int] = []
    for byte in range(256):
        # Invert all bits (G.711 complement convention)
        byte = ~byte & 0xFF
        sign = byte & 0x80
        exp = (byte >> 4) & 0x07
        mantissa = byte & 0x0F
        magnitude = ((mantissa << 1) | 1) << exp
        # Add bias (33) applied during encode — subtract here to invert
        magnitude = magnitude + 33 - 33  # net zero; keep for clarity
        # The pre-bias that μ-law encoding adds is folded into exp/mantissa;
        # the standard decode gives:
        #   linear = sign * ((mantissa | 0x10) << (exp + 3)) - 132
        # (ITU-T G.711, Appendix — simplified decoder)
        linear = ((mantissa | 0x10) << (exp + 3)) - 132
        if sign:
            linear = -linear
        # Clamp to int16 range
        if linear > 32767:
            linear = 32767
        elif linear < -32768:
            linear = -32768
        table.append(linear)
    return table


_ULAW_TABLE: list[int] = _build_ulaw_table()


def _ulaw2lin_16(mu_law_bytes: bytes) -> bytes:
    """Decode G.711 μ-law bytes to 16-bit signed little-endian PCM.

    Drop-in replacement for ``audioop.ulaw2lin(data, 2)`` that works on
    Python 3.13+ where ``audioop`` is no longer in the stdlib.
    """
    return struct.pack(f"<{len(mu_law_bytes)}h", *(_ULAW_TABLE[b] for b in mu_law_bytes))


def _compute_pcm_pair(inbound_mu_law: bytes, outbound_mu_law: bytes) -> bytes:
    """Decode each μ-law track to 16-bit PCM, pad the shorter side with
    PCM silence, and interleave L=inbound / R=outbound. Returns stereo
    16-bit little-endian PCM ready to feed the MP3 encoder.

    Pure function; no I/O. Keeps the hot-path math testable in isolation.
    """
    if not inbound_mu_law and not outbound_mu_law:
        return b""

    inbound_pcm = _ulaw2lin_16(inbound_mu_law)
    outbound_pcm = _ulaw2lin_16(outbound_mu_law)

    n_in = len(inbound_pcm) // 2
    n_out = len(outbound_pcm) // 2
    n = max(n_in, n_out)

    inbound_pcm = inbound_pcm + b"\x00\x00" * (n - n_in)
    outbound_pcm = outbound_pcm + b"\x00\x00" * (n - n_out)

    out = bytearray(n * 4)
    for i in range(n):
        out[i * 4 : i * 4 + 2] = inbound_pcm[i * 2 : i * 2 + 2]
        out[i * 4 + 2 : i * 4 + 4] = outbound_pcm[i * 2 : i * 2 + 2]
    return bytes(out)


import lameenc

# Encoder constants. LAME quality levels are 0-9 (0 best, 9 worst).
# 2 is the standard "good" preset and runs faster than 0 with no audible
# difference at 32 kbps on phone audio.
_MP3_BITRATE_KBPS = 32
_MP3_QUALITY = 2
_PCM_SAMPLE_RATE = 8000  # Twilio media is 8 kHz μ-law
_PCM_CHANNELS = 2        # we encode the stereo (caller=L, agent=R) mix


def _make_encoder() -> "lameenc.Encoder":
    """Build a lameenc.Encoder configured for our telephony pipeline.

    Bound per-call (each RecordingUploadSession owns its own encoder
    instance; encoders are not safe to share across calls because they
    carry internal state).
    """
    enc = lameenc.Encoder()
    enc.set_bit_rate(_MP3_BITRATE_KBPS)
    enc.set_in_sample_rate(_PCM_SAMPLE_RATE)
    enc.set_channels(_PCM_CHANNELS)
    enc.set_quality(_MP3_QUALITY)
    return enc


from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from google.api_core.exceptions import NotFound
from google.cloud import storage as gcs

from app.config import settings


@dataclass
class RecordingUploadSession:
    """Per-call state for a resumable GCS upload of an MP3 stream."""
    call_sid: str
    restaurant_id: str
    blob_name: str
    upload_url: str
    encoder: "lameenc.Encoder"
    pending_mp3: bytearray = field(default_factory=bytearray)
    total_bytes_uploaded: int = 0
    total_pcm_samples: int = 0  # per-channel sample count; drives duration
    broken: bool = False


# 256 KB — minimum non-final chunk size for GCS resumable uploads.
_GCS_CHUNK_BYTES = 256 * 1024


_storage_client_singleton: gcs.Client | None = None


def _get_storage_client() -> gcs.Client:
    """Lazy singleton. Cloud Run's runtime SA picks up ambient creds."""
    global _storage_client_singleton
    if _storage_client_singleton is None:
        _storage_client_singleton = gcs.Client()
    return _storage_client_singleton


def begin_recording(
    *, call_sid: str, restaurant_id: str, retention_days: int
) -> RecordingUploadSession:
    """Create a new GCS resumable upload session for this call.

    Sets the blob's ``custom_time`` to ``now() + retention_days`` so the
    bucket lifecycle rule (``daysSinceCustomTime: 0``) deletes the blob
    on its scheduled date — per-tenant retention without per-tenant
    bucket rules.
    """
    blob_name = f"{restaurant_id}/{call_sid}.mp3"
    bucket = _get_storage_client().bucket(settings.recordings_bucket)
    blob = bucket.blob(blob_name)
    upload_url = blob.create_resumable_upload_session(content_type="audio/mpeg")
    blob.custom_time = datetime.now(timezone.utc) + timedelta(days=retention_days)

    return RecordingUploadSession(
        call_sid=call_sid,
        restaurant_id=restaurant_id,
        blob_name=blob_name,
        upload_url=upload_url,
        encoder=_make_encoder(),
    )


def append_chunks(
    session: RecordingUploadSession,
    inbound_mu_law: bytes,
    outbound_mu_law: bytes,
) -> None:
    """Decode + interleave + encode + buffer; flush a chunk when the
    pending MP3 buffer reaches the 256 KB GCS-minimum.

    No-op once ``session.broken`` is True (set by `_put_chunk` after two
    consecutive failures).
    """
    if session.broken:
        return

    pcm = _compute_pcm_pair(inbound_mu_law, outbound_mu_law)
    if not pcm:
        return

    # Track per-channel sample count for duration calc.
    # Stereo PCM-16 = 4 bytes per (per-channel) sample-pair.
    session.total_pcm_samples += len(pcm) // 4

    mp3 = session.encoder.encode(pcm)
    if mp3:
        session.pending_mp3.extend(mp3)

    while len(session.pending_mp3) >= _GCS_CHUNK_BYTES:
        n = (len(session.pending_mp3) // _GCS_CHUNK_BYTES) * _GCS_CHUNK_BYTES
        chunk = bytes(session.pending_mp3[:n])
        del session.pending_mp3[:n]
        _put_chunk(session, chunk, is_final=False, total=None)


def _put_chunk(
    session: RecordingUploadSession,
    chunk: bytes,
    *,
    is_final: bool,
    total: int | None,
) -> None:
    """PUT one resumable-upload chunk to the session URL.

    Builds the ``Content-Range`` header from the session's current
    ``total_bytes_uploaded``. Retries once on 5xx with a 0.5 s pause; on
    second failure, marks the session broken and stops further uploads.
    GCS returns 308 ("Resume Incomplete") for a successful non-final
    chunk and 200/201 for the final, so accept all three.
    """
    start = session.total_bytes_uploaded
    end = start + len(chunk) - 1
    total_str = str(total) if (is_final and total is not None) else "*"
    headers = {"Content-Range": f"bytes {start}-{end}/{total_str}"}

    for attempt in range(2):
        try:
            resp = requests.put(
                session.upload_url, data=chunk, headers=headers, timeout=30.0
            )
        except Exception:
            logger.exception(
                "recording: chunk PUT raised call_sid=%s attempt=%d",
                session.call_sid, attempt,
            )
            resp = None

        ok = resp is not None and resp.status_code in (200, 201, 308)
        if ok:
            session.total_bytes_uploaded += len(chunk)
            return
        if attempt == 0:
            time.sleep(0.5)
            continue
        session.broken = True
        logger.error(
            "recording: chunk PUT failed twice — session broken call_sid=%s status=%s",
            session.call_sid,
            resp.status_code if resp else "(no response)",
        )
        return


def finalize_recording(
    session: RecordingUploadSession,
) -> tuple[str, int]:
    """Flush the encoder + send the final chunk with a known total length.

    Returns ``(gs:// URL, duration_seconds)``. If the session never had
    any audio (zero PCM samples), DELETEs the resumable session URL and
    returns ``("", 0)`` so the caller can skip the Firestore write.
    Returns ``("", 0)`` on a broken session too.
    """
    if session.broken:
        return ("", 0)

    if session.total_pcm_samples == 0:
        # No data — cancel the resumable session so GCS doesn't keep an
        # orphan around for 7 days.
        try:
            requests.delete(session.upload_url, timeout=10.0)
        except Exception:
            logger.exception(
                "recording: failed to cancel empty session call_sid=%s",
                session.call_sid,
            )
        return ("", 0)

    # Flush the encoder tail. lameenc raises RuntimeError if flush() is
    # called before any encode() call, so guard against that.
    try:
        tail = session.encoder.flush()
    except RuntimeError:
        tail = b""
    if tail:
        session.pending_mp3.extend(tail)

    final_chunk = bytes(session.pending_mp3)
    session.pending_mp3.clear()
    total = session.total_bytes_uploaded + len(final_chunk)

    _put_chunk(session, final_chunk, is_final=True, total=total)
    if session.broken:
        return ("", 0)

    duration_seconds = session.total_pcm_samples // _PCM_SAMPLE_RATE
    return (
        f"gs://{settings.recordings_bucket}/{session.blob_name}",
        duration_seconds,
    )


def delete_recording(*, call_sid: str, restaurant_id: str) -> None:
    """Delete the recording blob for one call. Idempotent: if the blob
    is already gone, return cleanly. All other errors propagate so the
    HTTP handler can decide how to surface them."""
    blob_name = f"{restaurant_id}/{call_sid}.mp3"
    bucket = _get_storage_client().bucket(settings.recordings_bucket)
    blob = bucket.blob(blob_name)
    try:
        blob.delete()
    except NotFound:
        logger.info(
            "recording: delete on missing blob (idempotent) call_sid=%s", call_sid
        )


