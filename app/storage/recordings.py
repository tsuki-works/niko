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


import lameenc

# Encoder constants. LAME quality levels are 0-9 (0 best, 9 worst).
# 2 is the standard "good" preset and runs faster than 0 with no audible
# difference at 32 kbps on phone audio.
_MP3_BITRATE_KBPS = 32
_MP3_QUALITY = 2
_PCM_SAMPLE_RATE = 8000  # Twilio media is 8 kHz μ-law
_PCM_CHANNELS = 1        # caller + agent summed to mono in _mix_pcm_streams


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
    """Per-call state for buffering raw PCM until finalize.

    Inbound and outbound bytes arrive in *separate* ``append_chunks``
    calls (one per WS media event for inbound; one per TTS chunk for
    outbound). Encoding mid-call would force a time-multiplexed
    concat — caller-bytes-then-agent-bytes — which sounds choppy
    because it isn't a real overlap. Instead we buffer raw PCM for
    each side, mix at finalize, then encode + upload in one shot.

    Trade-off: one big PUT at the end vs streaming chunks. Lose
    cross-pod-death durability (recording for that call is gone if
    the pod dies before finalize). Acceptable for v1 since instance
    death during a live WS is rare.
    """
    call_sid: str
    restaurant_id: str
    blob_name: str
    retention_days: int
    inbound_pcm: bytearray = field(default_factory=bytearray)
    outbound_pcm: bytearray = field(default_factory=bytearray)
    broken: bool = False


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
    """Create a new buffering session for this call.

    No GCS I/O yet — the upload happens at finalize when the encoded
    MP3 is ready. ``retention_days`` is stored on the session and
    applied to the blob's ``custom_time`` at upload.
    """
    return RecordingUploadSession(
        call_sid=call_sid,
        restaurant_id=restaurant_id,
        blob_name=f"{restaurant_id}/{call_sid}.mp3",
        retention_days=retention_days,
    )


def append_chunks(
    session: RecordingUploadSession,
    inbound_mu_law: bytes,
    outbound_mu_law: bytes,
) -> None:
    """Buffer raw PCM bytes for each side independently.

    Inbound bytes flow continuously from the WS (~1 chunk per 20 ms);
    outbound bytes only arrive while the agent is speaking. To keep
    them aligned in time, every outbound chunk is preceded by silence
    padding up to the current inbound length — so when we mix at
    finalize, sample N on each side corresponds to ~the same wall-clock
    moment.
    """
    if session.broken:
        return

    if inbound_mu_law:
        session.inbound_pcm.extend(_ulaw2lin_16(inbound_mu_law))

    if outbound_mu_law:
        # Pad outbound to current inbound position so the agent's voice
        # lands at roughly the wall-clock moment it was generated.
        gap_bytes = len(session.inbound_pcm) - len(session.outbound_pcm)
        if gap_bytes > 0:
            session.outbound_pcm.extend(b"\x00\x00" * (gap_bytes // 2))
        session.outbound_pcm.extend(_ulaw2lin_16(outbound_mu_law))


def _mix_pcm_streams(inbound: bytes, outbound: bytes) -> bytes:
    """Sample-wise sum of two int16 PCM streams, clipped to int16.

    Pads the shorter side with PCM silence first so the result is the
    full length of the longer side — important because the inbound
    stream is continuous (Twilio sends silence frames too) but the
    outbound stream is bursty (only present during agent speech).
    """
    n_in = len(inbound) // 2
    n_out = len(outbound) // 2
    n = max(n_in, n_out)
    if n == 0:
        return b""
    inbound = inbound + b"\x00\x00" * (n - n_in)
    outbound = outbound + b"\x00\x00" * (n - n_out)

    out = bytearray(n * 2)
    for i in range(n):
        a = struct.unpack_from("<h", inbound, i * 2)[0]
        b = struct.unpack_from("<h", outbound, i * 2)[0]
        s = a + b
        if s > 32767:
            s = 32767
        elif s < -32768:
            s = -32768
        struct.pack_into("<h", out, i * 2, s)
    return bytes(out)


def _upload_blob(
    *, blob_name: str, mp3_bytes: bytes, retention_days: int
) -> None:
    """One-shot blob upload with custom_time set for per-tenant retention."""
    bucket = _get_storage_client().bucket(settings.recordings_bucket)
    blob = bucket.blob(blob_name)
    blob.custom_time = datetime.now(timezone.utc) + timedelta(days=retention_days)
    blob.upload_from_string(mp3_bytes, content_type="audio/mpeg")


def finalize_recording(
    session: RecordingUploadSession,
) -> tuple[str, int]:
    """Mix the two PCM buffers, encode to MP3, upload as a single blob.

    Returns ``(gs:// URL, duration_seconds)``. If no audio was captured
    (empty session) or anything fails, returns ``("", 0)`` so the
    caller can skip the Firestore write.
    """
    if session.broken:
        return ("", 0)

    if not session.inbound_pcm and not session.outbound_pcm:
        return ("", 0)

    try:
        mixed = _mix_pcm_streams(bytes(session.inbound_pcm), bytes(session.outbound_pcm))
        if not mixed:
            return ("", 0)

        encoder = _make_encoder()
        mp3 = encoder.encode(mixed) + encoder.flush()

        _upload_blob(
            blob_name=session.blob_name,
            mp3_bytes=mp3,
            retention_days=session.retention_days,
        )
    except Exception:
        logger.exception(
            "recording: finalize/upload failed call_sid=%s", session.call_sid
        )
        session.broken = True
        return ("", 0)

    duration_seconds = (len(mixed) // 2) // _PCM_SAMPLE_RATE
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


def generate_signed_url(
    *, call_sid: str, restaurant_id: str, ttl_minutes: int = 30
) -> str:
    """Return a V4 signed GET URL for the recording blob. TTL defaults
    to 30 minutes — long enough for a typical playback session, short
    enough that a leaked URL ages out fast.

    On Cloud Run the runtime credentials are
    ``compute_engine.Credentials`` — they only carry an OAuth token, no
    private key, so V4 signing must be routed through the IAM
    ``signBlob`` API. We pass ``service_account_email`` and
    ``access_token`` to ``generate_signed_url``; google-cloud-storage
    detects them and routes the signing call to ``iam.googleapis.com``.
    The runtime SA must hold ``roles/iam.serviceAccountTokenCreator``
    on itself for that to work — granted by
    ``scripts/setup-recordings-bucket.sh``.

    Local dev with an ADC service-account JSON file (which DOES carry a
    private key) still works: ``ServiceAccountCredentials`` exposes
    ``service_account_email`` too, and ``generate_signed_url`` prefers
    local signing when a key is available.
    """
    import google.auth
    from google.auth.transport import requests as _gauth_requests

    blob_name = f"{restaurant_id}/{call_sid}.mp3"
    bucket = _get_storage_client().bucket(settings.recordings_bucket)
    blob = bucket.blob(blob_name)

    credentials, _project = google.auth.default()
    credentials.refresh(_gauth_requests.Request())

    return blob.generate_signed_url(
        version="v4",
        method="GET",
        expiration=timedelta(minutes=ttl_minutes),
        service_account_email=getattr(credentials, "service_account_email", None),
        access_token=getattr(credentials, "token", None),
    )


