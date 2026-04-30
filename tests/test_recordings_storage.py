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

    # Output must contain at least one MP3 frame sync (0xFFE/0xFFF prefix).
    assert b"\xff\xfb" in mp3 or b"\xff\xfa" in mp3 or b"\xff\xf3" in mp3, (
        f"no MP3 frame sync found in {mp3[:32]!r}"
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
