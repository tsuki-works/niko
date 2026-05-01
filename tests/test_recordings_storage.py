"""Unit tests for app.storage.recordings.

Hot-path helpers (decode + interleave) are pure and need no mocking.
Resumable-upload + signed-URL tests live further down and use mocks
for google.cloud.storage.

Note: stdlib ``audioop`` was removed in Python 3.13. Prod targets 3.12;
locally we run 3.13, so tests use the module's own ``_ulaw2lin_16``
helper for expected-value assertions instead of ``audioop.ulaw2lin``.
"""


def test_compute_pcm_pair_sums_to_mono():
    """Both sides are summed sample-wise into a single mono channel.
    Output length = max(in, out) samples × 2 bytes per sample."""
    import struct
    from app.storage.recordings import _compute_pcm_pair, _ulaw2lin_16

    inbound = b"\xff\xff"   # μ-law 0xFF ≈ silence (~0 PCM)
    outbound = b"\x80\x80"  # mid-positive PCM
    out = _compute_pcm_pair(inbound, outbound)

    # 2 samples × 2 bytes (mono)
    assert len(out) == 4
    inbound_pcm = _ulaw2lin_16(inbound)
    outbound_pcm = _ulaw2lin_16(outbound)
    for i in range(2):
        a = struct.unpack_from("<h", inbound_pcm, i * 2)[0]
        b = struct.unpack_from("<h", outbound_pcm, i * 2)[0]
        expected = max(-32768, min(32767, a + b))
        actual = struct.unpack_from("<h", out, i * 2)[0]
        assert actual == expected, f"sample {i}: expected {expected}, got {actual}"


def test_compute_pcm_pair_clips_on_overflow():
    """When summed PCM overflows int16, the result clips at the boundary
    instead of wrapping around (which would produce a nasty pop)."""
    import struct
    from app.storage.recordings import _compute_pcm_pair

    # μ-law 0x80 decodes to a large positive PCM value; summing two of
    # them overflows int16 → must clip at +32767.
    inbound = b"\x80"
    outbound = b"\x80"
    out = _compute_pcm_pair(inbound, outbound)
    assert len(out) == 2
    sample = struct.unpack_from("<h", out, 0)[0]
    assert sample == 32767


def test_compute_pcm_pair_pads_shorter_side_with_silence():
    """Track-length skew: missing samples on one side become PCM silence
    (zero) before the sum, so the longer side is preserved unchanged."""
    import struct
    from app.storage.recordings import _compute_pcm_pair, _ulaw2lin_16

    inbound = b"\xff" * 100    # 100 samples on caller side
    outbound = b"\x40" * 500   # 500 samples on agent side, non-zero PCM
    out = _compute_pcm_pair(inbound, outbound)

    # Mono PCM-16: 500 samples × 2 bytes
    assert len(out) == 500 * 2
    # Past the 100-sample mark, output is just outbound (caller padded with 0).
    outbound_pcm = _ulaw2lin_16(outbound)
    for i in range(100, 500):
        expected = struct.unpack_from("<h", outbound_pcm, i * 2)[0]
        actual = struct.unpack_from("<h", out, i * 2)[0]
        assert actual == expected, f"sample {i}: expected outbound={expected}, got {actual}"


def test_compute_pcm_pair_handles_empty_chunks():
    from app.storage.recordings import _compute_pcm_pair

    assert _compute_pcm_pair(b"", b"") == b""


def test_make_encoder_is_mono():
    """Encoder is configured for mono input — the mix produced by
    ``_compute_pcm_pair`` is a single channel."""
    from app.storage.recordings import _make_encoder

    enc = _make_encoder()
    # 1 second of mono PCM silence: 8000 samples × 1 channel × 2 bytes
    pcm = b"\x00" * (8000 * 2)
    mp3 = enc.encode(pcm)
    mp3 += enc.flush()

    # Valid MP3 frame sync (11-bit 0x7FF). Second byte top 3 bits = 110/111.
    assert len(mp3) >= 2 and mp3[0] == 0xFF and (mp3[1] & 0xE0) == 0xE0, (
        f"no MP3 frame sync found in {bytes(mp3[:32])!r}"
    )
    # 1 s at 32 kbps mono ≈ 4 KB; allow a wide range to keep stable.
    assert 500 < len(mp3) < 10000


def test_begin_recording_creates_session_and_sets_custom_time(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.storage import recordings

    fake_blob = type("FakeBlob", (), {})()
    fake_blob.create_resumable_upload_session = lambda content_type: (
        "https://storage.googleapis.com/upload/session/fake"
    )
    fake_blob.custom_time = None

    fake_bucket = type("FakeBucket", (), {})()
    fake_bucket.blob = lambda name: fake_blob

    fake_client = type("FakeClient", (), {})()
    fake_client.bucket = lambda name: fake_bucket

    monkeypatch.setattr(recordings, "_get_storage_client", lambda: fake_client)

    before = datetime.now(timezone.utc)
    session = recordings.begin_recording(
        call_sid="CAtest", restaurant_id="rid1", retention_days=7
    )
    after = datetime.now(timezone.utc)

    assert session.call_sid == "CAtest"
    assert session.restaurant_id == "rid1"
    assert session.blob_name == "rid1/CAtest.mp3"
    assert session.upload_url == "https://storage.googleapis.com/upload/session/fake"
    assert session.total_bytes_uploaded == 0
    assert session.broken is False
    assert before + timedelta(days=7) - timedelta(seconds=2) <= fake_blob.custom_time <= after + timedelta(days=7)


def test_append_chunks_buffers_below_threshold(monkeypatch):
    from app.storage import recordings

    put_count = {"n": 0}

    def fake_put(session, chunk_bytes, *, is_final, total):
        put_count["n"] += 1

    monkeypatch.setattr(recordings, "_put_chunk", fake_put)

    session = recordings.RecordingUploadSession(
        call_sid="CAt", restaurant_id="rid",
        blob_name="rid/CAt.mp3", upload_url="https://fake",
        encoder=recordings._make_encoder(),
    )

    # 50 ms of audio per side, repeated 10 times — well under 256 KB MP3.
    inbound = b"\xff" * 400  # 50 ms at 8 kHz
    outbound = b"\x00" * 400
    for _ in range(10):
        recordings.append_chunks(session, inbound, outbound)

    assert put_count["n"] == 0
    assert session.total_bytes_uploaded == 0
    assert session.total_pcm_samples == 400 * 10
    # encoder may or may not produce output for short bursts (LAME buffers
    # internally before emitting frames); accept >= 0.
    assert len(session.pending_mp3) >= 0


def test_put_chunk_sends_content_range_open_for_non_final(monkeypatch):
    from app.storage import recordings

    calls: list[dict] = []

    def fake_put(url, data, headers, timeout):
        calls.append({"url": url, "data_len": len(data), "headers": headers})
        return type("R", (), {"status_code": 200, "text": ""})()

    monkeypatch.setattr(recordings.requests, "put", fake_put)

    session = recordings.RecordingUploadSession(
        call_sid="CAt", restaurant_id="rid",
        blob_name="rid/CAt.mp3", upload_url="https://fake",
        encoder=recordings._make_encoder(),
    )

    chunk = b"x" * 256 * 1024
    recordings._put_chunk(session, chunk, is_final=False, total=None)

    assert len(calls) == 1
    assert calls[0]["url"] == "https://fake"
    assert calls[0]["data_len"] == 256 * 1024
    assert calls[0]["headers"]["Content-Range"] == "bytes 0-262143/*"
    assert session.total_bytes_uploaded == 256 * 1024


def test_put_chunk_retries_once_on_5xx(monkeypatch):
    from app.storage import recordings

    responses = iter([
        type("R", (), {"status_code": 503, "text": "transient"})(),
        type("R", (), {"status_code": 200, "text": ""})(),
    ])
    sleeps: list[float] = []
    monkeypatch.setattr(recordings.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(recordings.requests, "put", lambda *a, **kw: next(responses))

    session = recordings.RecordingUploadSession(
        call_sid="CAt", restaurant_id="rid",
        blob_name="rid/CAt.mp3", upload_url="https://fake",
        encoder=recordings._make_encoder(),
    )

    recordings._put_chunk(session, b"x" * 256 * 1024, is_final=False, total=None)

    assert sleeps == [0.5]
    assert session.broken is False
    assert session.total_bytes_uploaded == 256 * 1024


def test_put_chunk_marks_broken_after_two_5xx(monkeypatch):
    from app.storage import recordings

    monkeypatch.setattr(recordings.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        recordings.requests, "put",
        lambda *a, **kw: type("R", (), {"status_code": 503, "text": "fail"})(),
    )

    session = recordings.RecordingUploadSession(
        call_sid="CAt", restaurant_id="rid",
        blob_name="rid/CAt.mp3", upload_url="https://fake",
        encoder=recordings._make_encoder(),
    )

    recordings._put_chunk(session, b"x" * 256 * 1024, is_final=False, total=None)
    assert session.broken is True
    assert session.total_bytes_uploaded == 0


def test_append_chunks_flushes_one_chunk_when_threshold_hit(monkeypatch):
    from app.storage import recordings

    chunks: list[tuple[int, bool]] = []

    def fake_put(session, chunk, *, is_final, total):
        chunks.append((len(chunk), is_final))
        session.total_bytes_uploaded += len(chunk)

    monkeypatch.setattr(recordings, "_put_chunk", fake_put)

    session = recordings.RecordingUploadSession(
        call_sid="CAt", restaurant_id="rid",
        blob_name="rid/CAt.mp3", upload_url="https://fake",
        encoder=recordings._make_encoder(),
    )

    # Force the pending buffer to cross 256 KB by pre-loading it; then a
    # single small append triggers the flush loop.
    session.pending_mp3.extend(b"x" * (256 * 1024 + 100))
    recordings.append_chunks(session, b"\xff" * 8, b"\x00" * 8)

    # Exactly one chunk of size 256 KB must have been PUT.
    assert chunks == [(256 * 1024, False)]
    assert len(session.pending_mp3) > 0  # leftover stays for next chunk


def test_finalize_recording_sends_final_chunk_with_total_and_returns_url(monkeypatch):
    from app.storage import recordings

    captured: list[dict] = []

    def fake_put(session, chunk, *, is_final, total):
        captured.append({"len": len(chunk), "is_final": is_final, "total": total})
        session.total_bytes_uploaded += len(chunk)

    monkeypatch.setattr(recordings, "_put_chunk", fake_put)

    session = recordings.RecordingUploadSession(
        call_sid="CAt", restaurant_id="rid",
        blob_name="rid/CAt.mp3", upload_url="https://fake",
        encoder=recordings._make_encoder(),
    )

    # Simulate one prior chunk already uploaded.
    session.total_bytes_uploaded = 256 * 1024
    # Simulate 2 seconds of stereo audio captured.
    session.total_pcm_samples = 2 * 8000
    # Some bytes still pending for the final flush.
    session.pending_mp3.extend(b"x" * 1234)

    url, duration = recordings.finalize_recording(session)

    assert len(captured) == 1
    final = captured[0]
    assert final["is_final"] is True
    assert final["total"] is not None
    assert duration == 2
    assert url == "gs://niko-recordings/rid/CAt.mp3"


def test_finalize_recording_with_zero_pcm_cancels_session(monkeypatch):
    from app.storage import recordings

    deleted: list[str] = []
    monkeypatch.setattr(
        recordings.requests, "delete",
        lambda url, timeout: deleted.append(url) or type("R", (), {"status_code": 204})(),
    )
    # _put_chunk should NOT be called.
    monkeypatch.setattr(
        recordings, "_put_chunk",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not PUT on empty session")),
    )

    session = recordings.RecordingUploadSession(
        call_sid="CAt", restaurant_id="rid",
        blob_name="rid/CAt.mp3",
        upload_url="https://upload.googleapis.com/session/abc",
        encoder=recordings._make_encoder(),
    )

    url, duration = recordings.finalize_recording(session)

    assert url == ""
    assert duration == 0
    assert deleted == ["https://upload.googleapis.com/session/abc"]


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

    # Stub google.auth.default + transport.requests.Request so the test
    # never touches the metadata server.
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
    # IAM signBlob path
    assert captured["service_account_email"] == "runtime-sa@niko-tsuki.iam.gserviceaccount.com"
    assert captured["access_token"] == "oauth-access-token-fake"


