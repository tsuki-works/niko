"""Unit tests for app.storage.recordings.

Hot-path helpers (mix + decode) are pure and need no mocking. The
upload + signed-URL tests mock ``google.cloud.storage`` so no network
call escapes.

Note: stdlib ``audioop`` was removed in Python 3.13. Prod targets 3.12;
locally we run 3.13, so tests use the module's own ``_ulaw2lin_16``
helper for expected-value assertions instead of ``audioop.ulaw2lin``.
"""

import struct


# ---------------------------------------------------------------------------
# _ulaw2lin_16 (forward-compat shim for audioop.ulaw2lin)
# ---------------------------------------------------------------------------


def test_ulaw2lin_16_decodes_two_bytes():
    """Sanity: lookup-table decode produces 2 bytes per μ-law byte."""
    from app.storage.recordings import _ulaw2lin_16

    assert len(_ulaw2lin_16(b"\xff\xff")) == 4   # 2 samples × 2 bytes
    assert len(_ulaw2lin_16(b"")) == 0


# ---------------------------------------------------------------------------
# _mix_pcm_streams (pure mix at finalize)
# ---------------------------------------------------------------------------


def test_mix_pcm_streams_sums_aligned_samples():
    """Two PCM streams of equal length: each output sample is the
    int16-clipped sum of the two input samples."""
    from app.storage.recordings import _mix_pcm_streams

    a = struct.pack("<hh", 100, 200)
    b = struct.pack("<hh", 50, -25)
    out = _mix_pcm_streams(a, b)

    assert struct.unpack("<hh", out) == (150, 175)


def test_mix_pcm_streams_clips_overflow():
    """Sums above int16 max clip to 32767; sums below int16 min clip to -32768.
    Prevents wrap-around pops when both speakers are loud at once."""
    from app.storage.recordings import _mix_pcm_streams

    a = struct.pack("<h", 30000)
    b = struct.pack("<h", 30000)
    assert struct.unpack("<h", _mix_pcm_streams(a, b))[0] == 32767

    a = struct.pack("<h", -30000)
    b = struct.pack("<h", -30000)
    assert struct.unpack("<h", _mix_pcm_streams(a, b))[0] == -32768


def test_mix_pcm_streams_pads_shorter_side_with_silence():
    """Outbound is bursty (only during agent speech) while inbound is
    continuous. Mixing pads the shorter side with zero PCM so the
    longer side is preserved unchanged past the overlap."""
    from app.storage.recordings import _mix_pcm_streams

    inbound = struct.pack("<hhh", 100, 200, 300)
    outbound = struct.pack("<h", 50)
    out = _mix_pcm_streams(inbound, outbound)

    assert struct.unpack("<hhh", out) == (150, 200, 300)


def test_mix_pcm_streams_handles_empty():
    from app.storage.recordings import _mix_pcm_streams

    assert _mix_pcm_streams(b"", b"") == b""
    a = struct.pack("<h", 42)
    assert struct.unpack("<h", _mix_pcm_streams(a, b""))[0] == 42
    assert struct.unpack("<h", _mix_pcm_streams(b"", a))[0] == 42


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


def test_make_encoder_is_mono():
    """Encoder is configured for mono input — the mix produced by
    ``_mix_pcm_streams`` is a single channel."""
    from app.storage.recordings import _make_encoder

    enc = _make_encoder()
    pcm = b"\x00" * (8000 * 2)   # 1 second of mono PCM silence
    mp3 = enc.encode(pcm)
    mp3 += enc.flush()

    assert len(mp3) >= 2 and mp3[0] == 0xFF and (mp3[1] & 0xE0) == 0xE0, (
        f"no MP3 frame sync found in {bytes(mp3[:32])!r}"
    )
    assert 500 < len(mp3) < 10000


# ---------------------------------------------------------------------------
# begin_recording — pure-Python now, no GCS I/O
# ---------------------------------------------------------------------------


def test_begin_recording_creates_session_with_blob_name_and_retention():
    """Session is created with the right blob path and retention.
    No GCS calls at begin — the upload happens at finalize."""
    from app.storage import recordings

    session = recordings.begin_recording(
        call_sid="CAtest", restaurant_id="rid1", retention_days=7
    )

    assert session.call_sid == "CAtest"
    assert session.restaurant_id == "rid1"
    assert session.blob_name == "rid1/CAtest.mp3"
    assert session.retention_days == 7
    assert session.broken is False
    assert session.inbound_pcm == bytearray()
    assert session.outbound_pcm == bytearray()


# ---------------------------------------------------------------------------
# append_chunks — buffers each side separately, with outbound alignment
# ---------------------------------------------------------------------------


def test_append_chunks_extends_inbound_buffer():
    from app.storage import recordings

    session = recordings.begin_recording(
        call_sid="CAt", restaurant_id="rid", retention_days=90
    )
    recordings.append_chunks(session, b"\xff" * 8, b"")

    # 8 μ-law bytes → 16 PCM bytes (2 bytes per sample)
    assert len(session.inbound_pcm) == 16
    assert len(session.outbound_pcm) == 0


def test_append_chunks_pads_outbound_to_inbound_position():
    """When an outbound (TTS) chunk arrives, it gets positioned at the
    current inbound length first — that's how we keep the agent's voice
    aligned to wall-clock time without per-chunk timestamps."""
    from app.storage import recordings

    session = recordings.begin_recording(
        call_sid="CAt", restaurant_id="rid", retention_days=90
    )
    # Caller silence for "100 samples" arrives first.
    recordings.append_chunks(session, b"\xff" * 100, b"")
    assert len(session.inbound_pcm) == 200   # 100 samples × 2 bytes
    assert len(session.outbound_pcm) == 0

    # Now the agent says something — outbound chunk = 5 samples of TTS.
    recordings.append_chunks(session, b"", b"\x80" * 5)

    # Outbound buffer should now be: 100 samples of silence + 5 samples of TTS.
    assert len(session.outbound_pcm) == (100 + 5) * 2
    # First 100 samples are PCM silence (0).
    for i in range(100):
        assert struct.unpack_from("<h", session.outbound_pcm, i * 2)[0] == 0


def test_append_chunks_skips_when_session_broken():
    from app.storage import recordings

    session = recordings.begin_recording(
        call_sid="CAt", restaurant_id="rid", retention_days=90
    )
    session.broken = True
    recordings.append_chunks(session, b"\xff" * 100, b"\x80" * 100)

    assert session.inbound_pcm == bytearray()
    assert session.outbound_pcm == bytearray()


def test_append_chunks_handles_empty_payloads():
    from app.storage import recordings

    session = recordings.begin_recording(
        call_sid="CAt", restaurant_id="rid", retention_days=90
    )
    recordings.append_chunks(session, b"", b"")

    assert session.inbound_pcm == bytearray()
    assert session.outbound_pcm == bytearray()


# ---------------------------------------------------------------------------
# finalize_recording — mix, encode, single-blob upload
# ---------------------------------------------------------------------------


def test_finalize_recording_mixes_encodes_and_uploads(monkeypatch):
    """Happy path: buffers contain audio, finalize mixes them, encodes
    once, uploads as a single blob, returns gs:// URL + duration."""
    from datetime import datetime, timedelta, timezone
    from app.storage import recordings

    captured: dict = {}

    fake_blob = type("FakeBlob", (), {})()
    fake_blob.custom_time = None
    def fake_upload(data, content_type):
        captured["data"] = data
        captured["content_type"] = content_type
    fake_blob.upload_from_string = fake_upload

    fake_bucket = type("FakeBucket", (), {})()
    def get_blob(name):
        captured["blob_name"] = name
        return fake_blob
    fake_bucket.blob = get_blob

    fake_client = type("FakeClient", (), {})()
    fake_client.bucket = lambda name: fake_bucket

    monkeypatch.setattr(recordings, "_get_storage_client", lambda: fake_client)

    session = recordings.begin_recording(
        call_sid="CAt", restaurant_id="rid", retention_days=7
    )
    # Simulate 1 second of overlapping audio: feed the agent (outbound)
    # chunk *first*, while inbound is still empty, so the alignment
    # logic doesn't shift it. Then feed 1 second of caller audio.
    recordings.append_chunks(session, b"", b"\x80" * 8000)
    recordings.append_chunks(session, b"\xff" * 8000, b"")

    before = datetime.now(timezone.utc)
    url, duration = recordings.finalize_recording(session)
    after = datetime.now(timezone.utc)

    assert url == "gs://niko-recordings/rid/CAt.mp3"
    # 1 second of audio at 8 kHz mono.
    assert duration == 1
    assert captured["blob_name"] == "rid/CAt.mp3"
    assert captured["content_type"] == "audio/mpeg"
    # Output is real MP3 bytes
    assert captured["data"][0] == 0xFF and (captured["data"][1] & 0xE0) == 0xE0
    # custom_time is set to now() + retention_days
    assert before + timedelta(days=7) - timedelta(seconds=2) <= fake_blob.custom_time <= after + timedelta(days=7)


def test_finalize_recording_returns_empty_when_no_audio(monkeypatch):
    """A session with no audio (call dropped before any media event)
    returns ("", 0) without touching GCS."""
    from app.storage import recordings

    monkeypatch.setattr(
        recordings, "_get_storage_client",
        lambda: (_ for _ in ()).throw(AssertionError("must not touch GCS")),
    )

    session = recordings.begin_recording(
        call_sid="CAt", restaurant_id="rid", retention_days=90
    )
    url, duration = recordings.finalize_recording(session)

    assert url == ""
    assert duration == 0


def test_finalize_recording_skips_when_broken(monkeypatch):
    from app.storage import recordings

    monkeypatch.setattr(
        recordings, "_get_storage_client",
        lambda: (_ for _ in ()).throw(AssertionError("must not touch GCS on broken")),
    )

    session = recordings.begin_recording(
        call_sid="CAt", restaurant_id="rid", retention_days=90
    )
    session.inbound_pcm.extend(b"\x00" * 100)
    session.broken = True

    url, duration = recordings.finalize_recording(session)
    assert url == ""
    assert duration == 0


def test_finalize_recording_swallows_upload_failure(monkeypatch):
    """If the upload fails, finalize logs and returns empty rather than
    raising — the call lifecycle has already completed and we don't
    want to crash the WS finally."""
    from app.storage import recordings

    fake_blob = type("FakeBlob", (), {})()
    fake_blob.custom_time = None
    def fake_upload(data, content_type):
        raise RuntimeError("upload exploded")
    fake_blob.upload_from_string = fake_upload

    fake_bucket = type("FakeBucket", (), {})()
    fake_bucket.blob = lambda name: fake_blob

    fake_client = type("FakeClient", (), {})()
    fake_client.bucket = lambda name: fake_bucket

    monkeypatch.setattr(recordings, "_get_storage_client", lambda: fake_client)

    session = recordings.begin_recording(
        call_sid="CAt", restaurant_id="rid", retention_days=90
    )
    session.inbound_pcm.extend(b"\x00" * 1000)

    url, duration = recordings.finalize_recording(session)

    assert url == ""
    assert duration == 0
    assert session.broken is True


# ---------------------------------------------------------------------------
# delete_recording (unchanged from prior PRs)
# ---------------------------------------------------------------------------


def test_delete_recording_calls_blob_delete(monkeypatch):
    from app.storage import recordings

    deleted: list[str] = []

    fake_blob = type("FakeBlob", (), {})()
    fake_blob.delete = lambda: deleted.append("called")

    fake_bucket = type("FakeBucket", (), {})()
    fake_bucket.blob = lambda name: (deleted.append(name) or fake_blob)

    fake_client = type("FakeClient", (), {})()
    fake_client.bucket = lambda name: fake_bucket

    monkeypatch.setattr(recordings, "_get_storage_client", lambda: fake_client)

    recordings.delete_recording(call_sid="CAt", restaurant_id="rid")

    assert deleted == ["rid/CAt.mp3", "called"]


def test_delete_recording_idempotent_on_404(monkeypatch):
    from google.api_core.exceptions import NotFound
    from app.storage import recordings

    fake_blob = type("FakeBlob", (), {})()
    def raise_notfound():
        raise NotFound("gone")
    fake_blob.delete = raise_notfound

    fake_bucket = type("FakeBucket", (), {})()
    fake_bucket.blob = lambda name: fake_blob

    fake_client = type("FakeClient", (), {})()
    fake_client.bucket = lambda name: fake_bucket

    monkeypatch.setattr(recordings, "_get_storage_client", lambda: fake_client)

    # Should NOT raise.
    recordings.delete_recording(call_sid="CAt", restaurant_id="rid")


# ---------------------------------------------------------------------------
# generate_signed_url (unchanged from PR #138)
# ---------------------------------------------------------------------------


def test_generate_signed_url_uses_v4_get_30min_and_iam_signblob(monkeypatch):
    """Cloud Run runtime credentials (compute_engine.Credentials) lack a
    private key, so V4 signing must route through IAM signBlob. We pass
    ``service_account_email`` and ``access_token`` to
    ``generate_signed_url``; google-cloud-storage uses them to call
    iam.googleapis.com instead of trying to sign locally."""
    from datetime import timedelta
    from types import SimpleNamespace
    from app.storage import recordings

    captured: dict = {}

    fake_blob = type("FakeBlob", (), {})()
    def fake_signed(**kwargs):
        captured.update(kwargs)
        return "https://signed.googleapis.com/?sig=fake"
    fake_blob.generate_signed_url = fake_signed

    fake_bucket = type("FakeBucket", (), {})()
    def get_blob(name):
        captured["blob_name"] = name
        return fake_blob
    fake_bucket.blob = get_blob

    fake_client = type("FakeClient", (), {})()
    fake_client.bucket = lambda name: fake_bucket

    monkeypatch.setattr(recordings, "_get_storage_client", lambda: fake_client)

    fake_creds = SimpleNamespace(
        service_account_email="runtime-sa@niko-tsuki.iam.gserviceaccount.com",
        token="oauth-access-token-fake",
        refresh=lambda _request: None,
    )
    import google.auth as gauth_mod
    monkeypatch.setattr(gauth_mod, "default", lambda: (fake_creds, "niko-tsuki"))
    from google.auth.transport import requests as _gauth_req
    monkeypatch.setattr(_gauth_req, "Request", lambda: object())

    url = recordings.generate_signed_url(call_sid="CAt", restaurant_id="rid")

    assert url == "https://signed.googleapis.com/?sig=fake"
    assert captured["blob_name"] == "rid/CAt.mp3"
    assert captured["version"] == "v4"
    assert captured["method"] == "GET"
    assert captured["expiration"] == timedelta(minutes=30)
    assert captured["service_account_email"] == "runtime-sa@niko-tsuki.iam.gserviceaccount.com"
    assert captured["access_token"] == "oauth-access-token-fake"
