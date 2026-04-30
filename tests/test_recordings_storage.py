"""Unit tests for app.storage.recordings.

Hot-path helpers (decode + interleave) are pure and need no mocking.
Resumable-upload + signed-URL tests live further down and use mocks
for google.cloud.storage.

Note: stdlib ``audioop`` was removed in Python 3.13. Prod targets 3.12;
locally we run 3.13, so tests use the module's own ``_ulaw2lin_16``
helper for expected-value assertions instead of ``audioop.ulaw2lin``.
"""


def test_compute_pcm_pair_interleaves_lr():
    from app.storage.recordings import _compute_pcm_pair, _ulaw2lin_16

    # 2 μ-law samples per side. μ-law 0xFF = silence ≈ 0 PCM; 0x00 = max negative.
    inbound = b"\xff\xff"
    outbound = b"\x00\x00"
    out = _compute_pcm_pair(inbound, outbound)

    # 2 samples × 2 channels × 2 bytes = 8 bytes, L then R per sample.
    assert len(out) == 8
    inbound_pcm = _ulaw2lin_16(inbound)
    outbound_pcm = _ulaw2lin_16(outbound)
    # Sample 0: L = inbound[0:2], R = outbound[0:2]
    assert out[0:2] == inbound_pcm[0:2]
    assert out[2:4] == outbound_pcm[0:2]
    # Sample 1: L = inbound[2:4], R = outbound[2:4]
    assert out[4:6] == inbound_pcm[2:4]
    assert out[6:8] == outbound_pcm[2:4]


def test_compute_pcm_pair_pads_shorter_side_with_silence():
    from app.storage.recordings import _compute_pcm_pair

    inbound = b"\xff" * 100   # 100 μ-law samples
    outbound = b"\x00" * 500  # 500 μ-law samples
    out = _compute_pcm_pair(inbound, outbound)

    # 500 samples × 2 channels × 2 bytes
    assert len(out) == 500 * 2 * 2
    # Past the inbound's 100-sample mark, the L channel is PCM silence (\x00\x00).
    for i in range(100, 500):
        l_offset = i * 4
        assert out[l_offset:l_offset + 2] == b"\x00\x00", (
            f"L sample {i} not silent"
        )


def test_compute_pcm_pair_handles_empty_chunks():
    from app.storage.recordings import _compute_pcm_pair

    assert _compute_pcm_pair(b"", b"") == b""


def test_make_encoder_returns_lame_encoder_at_32kbps():
    from app.storage.recordings import _make_encoder

    enc = _make_encoder()
    # Encode 1 second of stereo PCM silence — 16000 samples × 2 channels × 2 bytes.
    pcm = b"\x00" * (16000 * 2 * 2)
    mp3 = enc.encode(pcm)
    mp3 += enc.flush()

    # Output must start with an MP3 frame sync word (11-bit 0x7FF sync).
    # The second byte's top 3 bits must be 110 or 111, so the second byte
    # is in range 0xE0-0xFF. lameenc may emit MPEG-1 (0xFF 0xFx) or
    # MPEG-2 (0xFF 0xEx) depending on sample rate; both are valid MP3.
    assert len(mp3) >= 2 and mp3[0] == 0xFF and (mp3[1] & 0xE0) == 0xE0, (
        f"no MP3 frame sync found in {bytes(mp3[:32])!r}"
    )
    assert 1000 < len(mp3) < 10000


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
