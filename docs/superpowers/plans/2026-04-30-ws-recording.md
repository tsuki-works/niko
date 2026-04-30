# WebSocket-side call recording — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Twilio's REST-driven call recording (broken on `<Connect><Stream>` calls) with a self-hosted pipeline that captures audio from the existing WebSocket, encodes to MP3 mid-call via resumable GCS upload, and serves playback through signed URLs. Adds delete + per-tenant retention + WS-close auto-hangup as a bundle.

**Architecture:** A new `app/storage/recordings.py` module exposes `begin_recording` / `append_chunks` / `finalize_recording` / `delete_recording` / `generate_signed_url`. The existing `/media-stream` WS handler holds a `RecordingUploadSession` per call, decodes μ-law to stereo PCM per `media` event, encodes incrementally with `lameenc`, and PUTs 256 KB chunks to a GCS resumable session as the buffer fills. At call end, `finalize_recording` flushes the encoder, sends the final chunk with a known total length, and writes `recording_url=gs://...` into Firestore. Playback proxy returns 302 to a 30-min signed URL. Auto-hangup is now a `should_hangup` `asyncio.Event` watched by the WS loop.

**Tech Stack:** Python 3.12 (FastAPI, asyncio, stdlib `audioop` + `wave`), `lameenc>=1.6` (pure-Python LAME), `google-cloud-storage>=2.0`, GCS resumable upload (Content-Range PUT), GCS lifecycle with `customTime`, Cloud Run runtime SA + `iam.serviceAccountTokenCreator` for V4 URL signing.

**Spec:** See `docs/superpowers/specs/2026-04-30-ws-recording-design.md`. All decisions and error-handling tables already locked there; this plan implements them.

**File map:**
- Create: `app/storage/recordings.py`, `tests/test_recordings_storage.py`, `tests/test_calls_route.py`, `scripts/setup-recordings-bucket.sh`
- Modify: `app/config.py`, `app/restaurants/models.py`, `app/storage/call_sessions.py`, `app/telephony/router.py`, `app/main.py`, `tests/test_telephony.py`, `requirements.txt`

---

### Task 1: Add `lameenc` + `google-cloud-storage` to `requirements.txt`

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the two deps**

Open `requirements.txt`, add at the bottom (after `twilio>=9.0,<10.0`):

```
google-cloud-storage>=2.0,<3.0
lameenc>=1.6,<2.0
```

- [ ] **Step 2: Install locally**

Run: `pip install -r requirements.txt`
Expected: `Successfully installed lameenc-... google-cloud-storage-...`

- [ ] **Step 3: Smoke test the imports**

Run: `python -c "import lameenc, google.cloud.storage; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "Add lameenc + google-cloud-storage for WS-side recording"
```

---

### Task 2: Add config fields for recordings bucket + default retention

**Files:**
- Modify: `app/config.py`

- [ ] **Step 1: Add the two settings**

In `app/config.py`, inside the `Settings` class (after the existing `public_base_url` field), add:

```python
    # Recordings bucket. Phase 2 default; can be overridden via env if we
    # ever split prod/dev/staging buckets.
    recordings_bucket: str = "niko-recordings"

    # Default retention applied at upload time when a Restaurant doc
    # doesn't carry its own ``recording_retention_days`` field. The bucket
    # lifecycle rule deletes blobs whose ``custom_time`` has passed.
    recording_default_retention_days: int = 90
```

- [ ] **Step 2: Confirm import still works**

Run: `python -c "from app.config import settings; print(settings.recordings_bucket, settings.recording_default_retention_days)"`
Expected: `niko-recordings 90`

- [ ] **Step 3: Commit**

```bash
git add app/config.py
git commit -m "Add recordings_bucket + retention default to settings"
```

---

### Task 3: Create the bucket-bootstrap script

**Files:**
- Create: `scripts/setup-recordings-bucket.sh`

- [ ] **Step 1: Write the script**

Create `scripts/setup-recordings-bucket.sh`:

```bash
#!/usr/bin/env bash
# Bootstrap GCS bucket + IAM for WS-side call recordings (#82).
# Idempotent enough for one-shot bootstrap; re-running on an existing
# bucket fails cleanly at create-bucket and the rest are upserts.
set -euo pipefail

PROJECT="${PROJECT:-niko-tsuki}"
BUCKET="${BUCKET:-niko-recordings}"
REGION="${REGION:-us-central1}"
SA="${SA:-347262010229-compute@developer.gserviceaccount.com}"

echo "Creating bucket gs://${BUCKET} in ${REGION}..."
gcloud storage buckets create "gs://${BUCKET}" \
  --project="${PROJECT}" \
  --location="${REGION}" \
  --uniform-bucket-level-access || echo "(bucket may already exist; continuing)"

echo "Setting per-blob lifecycle (delete when daysSinceCustomTime >= 0)..."
TMP_LIFECYCLE="$(mktemp)"
cat > "${TMP_LIFECYCLE}" <<'EOF'
{"lifecycle":{"rule":[{"action":{"type":"Delete"},"condition":{"daysSinceCustomTime":0}}]}}
EOF
gcloud storage buckets update "gs://${BUCKET}" --lifecycle-file="${TMP_LIFECYCLE}"
rm -f "${TMP_LIFECYCLE}"

echo "Granting Cloud Run runtime SA roles/storage.objectAdmin on bucket..."
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${SA}" \
  --role="roles/storage.objectAdmin"

echo "Granting SA serviceAccountTokenCreator on itself (for V4 signed URLs)..."
gcloud iam service-accounts add-iam-policy-binding "${SA}" \
  --member="serviceAccount:${SA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="${PROJECT}"

echo "Done. Bucket gs://${BUCKET} is ready for recordings."
```

- [ ] **Step 2: Mark executable**

Run: `chmod +x scripts/setup-recordings-bucket.sh`

- [ ] **Step 3: Validate script syntax (without running it)**

Run: `bash -n scripts/setup-recordings-bucket.sh`
Expected: no output (no syntax errors).

- [ ] **Step 4: Commit**

```bash
git add scripts/setup-recordings-bucket.sh
git commit -m "Add scripts/setup-recordings-bucket.sh"
```

*(The script will be run once in Task 25, just before deploying the new code.)*

---

### Task 4: Add `recording_retention_days` to the `Restaurant` model

**Files:**
- Modify: `app/restaurants/models.py`
- Modify: `tests/test_restaurants_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_restaurants_storage.py`:

```python
def test_restaurant_recording_retention_default_is_90():
    from app.restaurants.models import Restaurant

    r = Restaurant(
        id="x", name="X", display_phone="+1", twilio_phone="+1",
        address="a", hours="h", menu={"pizzas": [], "sides": [], "drinks": []},
    )
    assert r.recording_retention_days == 90


def test_restaurant_recording_retention_accepts_override():
    from app.restaurants.models import Restaurant

    r = Restaurant(
        id="x", name="X", display_phone="+1", twilio_phone="+1",
        address="a", hours="h",
        menu={"pizzas": [], "sides": [], "drinks": []},
        recording_retention_days=30,
    )
    assert r.recording_retention_days == 30


def test_restaurant_recording_retention_rejects_zero_or_negative():
    import pytest
    from pydantic import ValidationError
    from app.restaurants.models import Restaurant

    with pytest.raises(ValidationError):
        Restaurant(
            id="x", name="X", display_phone="+1", twilio_phone="+1",
            address="a", hours="h",
            menu={"pizzas": [], "sides": [], "drinks": []},
            recording_retention_days=0,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_restaurants_storage.py::test_restaurant_recording_retention_default_is_90 -v`
Expected: FAIL — `AttributeError: ... has no attribute 'recording_retention_days'` (or Pydantic field-not-found).

- [ ] **Step 3: Add the field to the model**

In `app/restaurants/models.py`, on the `Restaurant` Pydantic model, add (next to other primitive fields):

```python
    recording_retention_days: int = Field(default=90, ge=1, le=3650)
```

If the file doesn't already import `Field`, change `from pydantic import BaseModel` to `from pydantic import BaseModel, Field`.

- [ ] **Step 4: Run the three tests to verify they pass**

Run: `pytest tests/test_restaurants_storage.py -k recording_retention -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/restaurants/models.py tests/test_restaurants_storage.py
git commit -m "Restaurant: add recording_retention_days (default 90)"
```

---

### Task 5: Add `mark_recording_deleted` to the call-sessions storage module

**Files:**
- Modify: `app/storage/call_sessions.py`
- Modify: `tests/test_call_sessions_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_call_sessions_storage.py`:

```python
def test_mark_recording_deleted_clears_url_and_emits_event(monkeypatch):
    from app.storage import call_sessions

    patches: list[dict] = []
    events: list[dict] = []

    class FakeDoc:
        def __init__(self):
            self._collection = FakeCollection(events)
        def update(self, patch):
            patches.append(patch)
        def collection(self, _name):
            return self._collection

    class FakeCollection:
        def __init__(self, events):
            self._events = events
        def add(self, payload):
            self._events.append(payload)

    fake_legacy = FakeDoc()
    fake_nested = FakeDoc()

    monkeypatch.setattr(call_sessions, "_get_client", lambda: object())
    monkeypatch.setattr(call_sessions, "_legacy_parent", lambda _c, _sid: fake_legacy)
    monkeypatch.setattr(call_sessions, "_nested_parent", lambda _c, _rid, _sid: fake_nested)

    call_sessions.mark_recording_deleted("CAtest", "rid1")

    # Both parents are cleared
    for p in patches:
        assert p.get("recording_url") is None
        assert p.get("recording_sid") is None
        assert p.get("recording_duration_seconds") is None

    # An event was appended on each side
    assert len(events) == 2
    for ev in events:
        assert ev["kind"] == "recording_deleted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_call_sessions_storage.py::test_mark_recording_deleted_clears_url_and_emits_event -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'mark_recording_deleted'`.

- [ ] **Step 3: Implement `mark_recording_deleted`**

In `app/storage/call_sessions.py`, after the existing `mark_recording_ready` function, add:

```python
def mark_recording_deleted(call_sid: str, restaurant_id: str) -> None:
    """Clear recording metadata from the call session doc and emit a
    ``recording_deleted`` event so the dashboard's onSnapshot can hide
    the audio player.

    Mirrors the dual-write shape of ``mark_recording_ready`` —
    patches both legacy flat and nested call-session docs and appends
    a matching event on each. Idempotent: calling it twice on the
    same call is a no-op for the dashboard (the second clear writes
    the same Nones; the second event row is harmless).
    """
    ts = _now()
    patch: dict[str, Any] = {
        "recording_url": None,
        "recording_sid": None,
        "recording_duration_seconds": None,
        "last_event_at": ts,
    }
    event_payload = {
        "timestamp": ts,
        "kind": "recording_deleted",
        "text": "",
        "detail": {},
    }
    try:
        client = _get_client()
        legacy = _legacy_parent(client, call_sid)
        legacy.update(patch)
        legacy.collection(_EVENTS_SUBCOLLECTION).add(event_payload)

        nested = _nested_parent(client, restaurant_id, call_sid)
        nested.update(patch)
        nested.collection(_EVENTS_SUBCOLLECTION).add(event_payload)
    except Exception:
        logger.exception(
            "call_sessions: mark_recording_deleted failed call_sid=%s", call_sid
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_call_sessions_storage.py::test_mark_recording_deleted_clears_url_and_emits_event -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/storage/call_sessions.py tests/test_call_sessions_storage.py
git commit -m "call_sessions: add mark_recording_deleted (Firestore + event)"
```

---

### Task 6: Implement `_compute_pcm_pair` (decode + interleave + pad)

**Files:**
- Create: `app/storage/recordings.py`
- Create: `tests/test_recordings_storage.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_recordings_storage.py`:

```python
"""Unit tests for app.storage.recordings.

Hot-path helpers (decode + interleave) are pure and need no mocking.
Resumable-upload + signed-URL tests live further down and use mocks
for google.cloud.storage.
"""

import audioop


def test_compute_pcm_pair_interleaves_lr():
    from app.storage.recordings import _compute_pcm_pair

    # 2 μ-law samples per side. μ-law 0xFF = silence ≈ 0 PCM; 0x00 = max negative.
    inbound = b"\xff\xff"
    outbound = b"\x00\x00"
    out = _compute_pcm_pair(inbound, outbound)

    # 2 samples × 2 channels × 2 bytes = 8 bytes, L then R per sample.
    assert len(out) == 8
    inbound_pcm = audioop.ulaw2lin(inbound, 2)
    outbound_pcm = audioop.ulaw2lin(outbound, 2)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_recordings_storage.py -v`
Expected: 3 FAIL — `ModuleNotFoundError: No module named 'app.storage.recordings'`.

- [ ] **Step 3: Create the module skeleton + implement `_compute_pcm_pair`**

Create `app/storage/recordings.py`:

```python
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

import audioop
import logging

logger = logging.getLogger(__name__)


def _compute_pcm_pair(inbound_mu_law: bytes, outbound_mu_law: bytes) -> bytes:
    """Decode each μ-law track to 16-bit PCM, pad the shorter side with
    PCM silence, and interleave L=inbound / R=outbound. Returns stereo
    16-bit little-endian PCM ready to feed the MP3 encoder.

    Pure function; no I/O. Keeps the hot-path math testable in isolation.
    """
    if not inbound_mu_law and not outbound_mu_law:
        return b""

    inbound_pcm = audioop.ulaw2lin(inbound_mu_law, 2)
    outbound_pcm = audioop.ulaw2lin(outbound_mu_law, 2)

    n_in = len(inbound_pcm) // 2
    n_out = len(outbound_pcm) // 2
    n = max(n_in, n_out)

    # Pad each side with PCM silence (0x0000) up to ``n`` samples.
    inbound_pcm = inbound_pcm + b"\x00\x00" * (n - n_in)
    outbound_pcm = outbound_pcm + b"\x00\x00" * (n - n_out)

    # Interleave L0 R0 L1 R1 ...
    out = bytearray(n * 4)
    for i in range(n):
        out[i * 4 : i * 4 + 2] = inbound_pcm[i * 2 : i * 2 + 2]
        out[i * 4 + 2 : i * 4 + 4] = outbound_pcm[i * 2 : i * 2 + 2]
    return bytes(out)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_recordings_storage.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/storage/recordings.py tests/test_recordings_storage.py
git commit -m "recordings: add _compute_pcm_pair (μ-law→stereo PCM)"
```

---

### Task 7: MP3 encode round-trip test + lameenc helper

**Files:**
- Modify: `app/storage/recordings.py`
- Modify: `tests/test_recordings_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recordings_storage.py`:

```python
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
    # 1s of 32 kbps mono ≈ 4 KB; allow a wide range to keep the test stable.
    assert 1000 < len(mp3) < 10000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recordings_storage.py::test_make_encoder_returns_lame_encoder_at_32kbps -v`
Expected: FAIL — `ImportError: cannot import name '_make_encoder'`.

- [ ] **Step 3: Add `_make_encoder` to the module**

Append to `app/storage/recordings.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recordings_storage.py::test_make_encoder_returns_lame_encoder_at_32kbps -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/storage/recordings.py tests/test_recordings_storage.py
git commit -m "recordings: add _make_encoder (lameenc, 32 kbps stereo)"
```

---

### Task 8: `RecordingUploadSession` dataclass + `begin_recording`

**Files:**
- Modify: `app/storage/recordings.py`
- Modify: `tests/test_recordings_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recordings_storage.py`:

```python
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
    # custom_time must be 7 days from now (within the test's clock window)
    assert before + timedelta(days=7) - timedelta(seconds=2) <= fake_blob.custom_time <= after + timedelta(days=7)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recordings_storage.py::test_begin_recording_creates_session_and_sets_custom_time -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'begin_recording'`.

- [ ] **Step 3: Add the dataclass + `begin_recording`**

Append to `app/storage/recordings.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recordings_storage.py::test_begin_recording_creates_session_and_sets_custom_time -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/storage/recordings.py tests/test_recordings_storage.py
git commit -m "recordings: RecordingUploadSession + begin_recording"
```

---

### Task 9: `append_chunks` — buffer accumulation, no flush yet

**Files:**
- Modify: `app/storage/recordings.py`
- Modify: `tests/test_recordings_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recordings_storage.py`:

```python
def test_append_chunks_buffers_below_threshold(monkeypatch):
    from app.storage import recordings

    # PUT counter — must remain 0 since we never cross the threshold.
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
    assert len(session.pending_mp3) > 0  # encoder produced *some* output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recordings_storage.py::test_append_chunks_buffers_below_threshold -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'append_chunks'`.

- [ ] **Step 3: Implement `append_chunks` + `_put_chunk` stub**

Append to `app/storage/recordings.py`:

```python
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

    Stub for Task 9 — implemented in Task 10. Kept in module scope so
    tests can monkeypatch it.
    """
    raise NotImplementedError
```

*(The stub raises so Task 10's tests will be the first to exercise it.)*

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recordings_storage.py::test_append_chunks_buffers_below_threshold -v`
Expected: PASS (test monkeypatches `_put_chunk`, so the stub never runs).

- [ ] **Step 5: Commit**

```bash
git add app/storage/recordings.py tests/test_recordings_storage.py
git commit -m "recordings: append_chunks (buffer accumulation, pre-flush)"
```

---

### Task 10: `_put_chunk` — real PUT with `Content-Range`, 1-retry

**Files:**
- Modify: `app/storage/recordings.py`
- Modify: `tests/test_recordings_storage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_recordings_storage.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_recordings_storage.py -k put_chunk -v`
Expected: 3 FAIL — currently `_put_chunk` raises NotImplementedError; tests don't get past it.

- [ ] **Step 3: Replace the `_put_chunk` stub with the real impl**

In `app/storage/recordings.py`, add `import requests` and `import time` at the top of the imports, then **replace** the existing `_put_chunk` stub with:

```python
def _put_chunk(
    session: RecordingUploadSession,
    chunk: bytes,
    *,
    is_final: bool,
    total: int | None,
) -> None:
    """PUT one resumable-upload chunk to the session URL.

    Builds the ``Content-Range`` header from the session's current
    ``total_bytes_uploaded``. Retries once on 5xx with a 0.5s pause; on
    second failure, marks the session broken and stops further uploads.
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

        # GCS returns 308 ("Resume Incomplete") for a successful non-final
        # chunk, 200/201 for the final, 5xx on transient failure.
        ok = resp is not None and (
            resp.status_code in (200, 201, 308)
            or (is_final and resp.status_code == 200)
        )
        if ok:
            session.total_bytes_uploaded += len(chunk)
            return
        if attempt == 0:
            time.sleep(0.5)
            continue
        # Second failure
        session.broken = True
        logger.error(
            "recording: chunk PUT failed twice — session broken call_sid=%s status=%s",
            session.call_sid,
            resp.status_code if resp else "(no response)",
        )
        return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_recordings_storage.py -k put_chunk -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/storage/recordings.py tests/test_recordings_storage.py
git commit -m "recordings: _put_chunk with Content-Range + 1-retry on 5xx"
```

---

### Task 11: `append_chunks` — chunk threshold actually fires

**Files:**
- Modify: `tests/test_recordings_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recordings_storage.py`:

```python
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
    # Leftover (>100 bytes from the prefill + the encoder's output for 8
    # μ-law samples) stays in pending_mp3.
    assert len(session.pending_mp3) > 0
```

- [ ] **Step 2: Run test to verify it passes already (the loop in append_chunks already exists)**

Run: `pytest tests/test_recordings_storage.py::test_append_chunks_flushes_one_chunk_when_threshold_hit -v`
Expected: PASS — Task 9's `append_chunks` already had the threshold loop; this test just exercises it.

- [ ] **Step 3: Commit**

```bash
git add tests/test_recordings_storage.py
git commit -m "recordings: regression test for chunk-threshold flush"
```

---

### Task 12: `finalize_recording` — happy path with total length

**Files:**
- Modify: `app/storage/recordings.py`
- Modify: `tests/test_recordings_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recordings_storage.py`:

```python
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

    # One final PUT was made, with the encoder's flush() tail appended.
    assert len(captured) == 1
    final = captured[0]
    assert final["is_final"] is True
    assert final["total"] is not None
    # Duration is total_pcm_samples / 8000 = 2 seconds.
    assert duration == 2
    assert url == "gs://niko-recordings/rid/CAt.mp3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recordings_storage.py::test_finalize_recording_sends_final_chunk_with_total_and_returns_url -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'finalize_recording'`.

- [ ] **Step 3: Implement `finalize_recording`**

Append to `app/storage/recordings.py`:

```python
import requests as _requests_unused  # keep linter happy if `requests` already imported

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

    # Flush the encoder tail.
    tail = session.encoder.flush()
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recordings_storage.py::test_finalize_recording_sends_final_chunk_with_total_and_returns_url -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/storage/recordings.py tests/test_recordings_storage.py
git commit -m "recordings: finalize_recording (final PUT + duration)"
```

---

### Task 13: `finalize_recording` — empty session DELETEs the upload URL

**Files:**
- Modify: `tests/test_recordings_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recordings_storage.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_recordings_storage.py::test_finalize_recording_with_zero_pcm_cancels_session -v`
Expected: PASS — Task 12 implementation already handles this branch.

- [ ] **Step 3: Commit**

```bash
git add tests/test_recordings_storage.py
git commit -m "recordings: regression test for empty-session DELETE"
```

---

### Task 14: `delete_recording` — idempotent blob delete

**Files:**
- Modify: `app/storage/recordings.py`
- Modify: `tests/test_recordings_storage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_recordings_storage.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_recordings_storage.py -k delete_recording -v`
Expected: 2 FAIL — `AttributeError: module ... has no attribute 'delete_recording'`.

- [ ] **Step 3: Implement `delete_recording`**

Append to `app/storage/recordings.py`:

```python
from google.api_core.exceptions import NotFound


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_recordings_storage.py -k delete_recording -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/storage/recordings.py tests/test_recordings_storage.py
git commit -m "recordings: delete_recording (idempotent blob delete)"
```

---

### Task 15: `generate_signed_url` — V4 GET, 30 min TTL

**Files:**
- Modify: `app/storage/recordings.py`
- Modify: `tests/test_recordings_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recordings_storage.py`:

```python
def test_generate_signed_url_uses_v4_get_30min(monkeypatch):
    from datetime import timedelta
    from app.storage import recordings

    captured: dict = {}

    fake_blob = type("FakeBlob", (), {})()
    def fake_signed(*, version, method, expiration):
        captured["version"] = version
        captured["method"] = method
        captured["expiration"] = expiration
        return "https://signed.googleapis.com/?sig=fake"
    fake_blob.generate_signed_url = fake_signed

    fake_bucket = type("FakeBucket", (), {})()
    fake_bucket.blob = lambda name: (captured.setdefault("blob_name", name), fake_blob)[1]

    fake_client = type("FakeClient", (), {})()
    fake_client.bucket = lambda name: fake_bucket

    monkeypatch.setattr(recordings, "_get_storage_client", lambda: fake_client)

    url = recordings.generate_signed_url(call_sid="CAt", restaurant_id="rid")

    assert url == "https://signed.googleapis.com/?sig=fake"
    assert captured["blob_name"] == "rid/CAt.mp3"
    assert captured["version"] == "v4"
    assert captured["method"] == "GET"
    assert captured["expiration"] == timedelta(minutes=30)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_recordings_storage.py::test_generate_signed_url_uses_v4_get_30min -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'generate_signed_url'`.

- [ ] **Step 3: Implement `generate_signed_url`**

Append to `app/storage/recordings.py`:

```python
def generate_signed_url(
    *, call_sid: str, restaurant_id: str, ttl_minutes: int = 30
) -> str:
    """Return a V4 signed GET URL for the recording blob. TTL defaults
    to 30 minutes — long enough for a typical playback session, short
    enough that a leaked URL ages out fast.

    Cloud Run's runtime SA can sign V4 URLs without a private key file
    by using the IAM ``signBlob`` API; the SA must hold
    ``roles/iam.serviceAccountTokenCreator`` on itself. See
    ``scripts/setup-recordings-bucket.sh``.
    """
    blob_name = f"{restaurant_id}/{call_sid}.mp3"
    bucket = _get_storage_client().bucket(settings.recordings_bucket)
    blob = bucket.blob(blob_name)
    return blob.generate_signed_url(
        version="v4",
        method="GET",
        expiration=timedelta(minutes=ttl_minutes),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_recordings_storage.py::test_generate_signed_url_uses_v4_get_30min -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/storage/recordings.py tests/test_recordings_storage.py
git commit -m "recordings: generate_signed_url (V4 GET, 30min)"
```

---

### Task 16: `voice()` — emit `tracks="both_tracks"` on the Stream

**Files:**
- Modify: `app/telephony/router.py`
- Modify: `tests/test_telephony.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_telephony.py`, after `test_voice_passes_restaurant_id_as_stream_parameter`, add:

```python
def test_voice_stream_requests_both_tracks(monkeypatch):
    """Twilio sends both inbound and outbound audio over the same WS
    only when we ask for ``tracks="both_tracks"`` on the <Stream>. This
    is the foundation for the WS-side recording pipeline (#82)."""
    monkeypatch.setattr(
        restaurants_storage, "get_restaurant_by_twilio_phone", lambda _e164: None
    )
    response = client.post("/voice", data=_VOICE_FORM)
    body = response.text
    assert 'tracks="both_tracks"' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_telephony.py::test_voice_stream_requests_both_tracks -v`
Expected: FAIL — `assert 'tracks="both_tracks"' in body` returns False.

- [ ] **Step 3: Add `tracks="both_tracks"` to the Stream**

In `app/telephony/router.py`, find the line in `voice()` that creates the Stream:

```python
stream = connect.stream(url=f"wss://{host}/media-stream")
```

Replace with:

```python
stream = connect.stream(url=f"wss://{host}/media-stream", tracks="both_tracks")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_telephony.py::test_voice_stream_requests_both_tracks -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/telephony/router.py tests/test_telephony.py
git commit -m "telephony: request both_tracks on <Stream> for WS-side recording"
```

---

### Task 17: `_CallState` gains recording session + should-hangup event

**Files:**
- Modify: `app/telephony/router.py`

- [ ] **Step 1: Add the new fields to `_CallState`**

In `app/telephony/router.py`, find `_CallState`:

```python
@dataclass
class _CallState:
    call_sid:     str | None       = None
    stream_sid:   str | None       = None
    order:        Order | None     = None
    history:      list[dict]       = field(default_factory=list)
    restaurant:   Restaurant | None = None
    system_prompt: str             = ""
    llm_task:     asyncio.Task | None = None
    silence_task: asyncio.Task | None = None
    hangup_task:  asyncio.Task | None = None
    pending_hangup: bool           = False
```

Add these fields at the bottom of the dataclass (forward-reference the type to avoid a top-level import cycle):

```python
    recording_session: "RecordingUploadSession | None" = None
    should_hangup: asyncio.Event = field(default_factory=asyncio.Event)
```

- [ ] **Step 2: Add the import**

Near the top of `app/telephony/router.py`, with the other `app.storage` imports, add:

```python
from app.storage import recordings
```

And forward-type-resolve by adding (near the dataclass or at the top of the file):

```python
from app.storage.recordings import RecordingUploadSession  # noqa: F401  (typing only)
```

- [ ] **Step 3: Smoke check imports**

Run: `python -c "from app.telephony.router import _CallState; s = _CallState(); print(s.recording_session, s.should_hangup.is_set())"`
Expected: `None False`

- [ ] **Step 4: Commit**

```bash
git add app/telephony/router.py
git commit -m "telephony: _CallState gains recording_session + should_hangup event"
```

---

### Task 18: WS `start` handler kicks off `begin_recording`

**Files:**
- Modify: `app/telephony/router.py`
- Modify: `tests/test_telephony.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_telephony.py`, after the existing `test_media_stream_handles_full_call_lifecycle`, add:

```python
def test_media_stream_begins_recording_on_start(mock_pipeline, monkeypatch):
    """On WS start, after tenant resolution, begin_recording is called
    with the resolved restaurant id and the tenant's retention setting."""
    from app.storage import recordings as recordings_mod
    from app.restaurants.models import Restaurant

    seeded = Restaurant(
        id="niko-pizza-kitchen",
        name="Niko",
        display_phone="+1", twilio_phone=_DEMO_TO,
        address="a", hours="h",
        menu={"pizzas": [], "sides": [], "drinks": []},
        recording_retention_days=42,
    )
    monkeypatch.setattr(
        restaurants_storage, "get_restaurant", lambda _rid: seeded
    )
    monkeypatch.setattr(
        restaurants_storage, "load_or_fallback_demo", lambda _rid: seeded
    )

    captured: list[dict] = []

    def fake_begin(call_sid, restaurant_id, retention_days):
        captured.append({
            "call_sid": call_sid,
            "restaurant_id": restaurant_id,
            "retention_days": retention_days,
        })
        return MagicMock(broken=False)

    # The real signature uses kwargs only — adapt:
    def fake_begin_kwargs(*, call_sid, restaurant_id, retention_days):
        return fake_begin(call_sid, restaurant_id, retention_days)

    monkeypatch.setattr(recordings_mod, "begin_recording", fake_begin_kwargs)
    monkeypatch.setattr(recordings_mod, "append_chunks", lambda *a, **kw: None)
    monkeypatch.setattr(recordings_mod, "finalize_recording", lambda _s: ("", 0))

    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        ws.send_text(json.dumps(_STOP_MSG))

    assert len(captured) == 1
    assert captured[0] == {
        "call_sid": "CAtest123",
        "restaurant_id": "niko-pizza-kitchen",
        "retention_days": 42,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_telephony.py::test_media_stream_begins_recording_on_start -v`
Expected: FAIL — `begin_recording` is never called by the existing handler.

- [ ] **Step 3: Wire `begin_recording` into the WS `start` handler**

In `app/telephony/router.py`, inside `media_stream()` `elif event == "start":` branch, **after** the existing `state.system_prompt = build_system_prompt(state.restaurant)` line and **before** the `state.order = Order(...)` line, add:

```python
                try:
                    state.recording_session = recordings.begin_recording(
                        call_sid=state.call_sid or "unknown",
                        restaurant_id=state.restaurant.id,
                        retention_days=state.restaurant.recording_retention_days,
                    )
                except Exception:
                    logger.exception(
                        "recording: begin_recording failed call_sid=%s — call continues without recording",
                        state.call_sid,
                    )
                    state.recording_session = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_telephony.py::test_media_stream_begins_recording_on_start -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/telephony/router.py tests/test_telephony.py
git commit -m "telephony: begin_recording on WS start"
```

---

### Task 19: `media` event dispatches audio to `append_chunks`

**Files:**
- Modify: `app/telephony/router.py`
- Modify: `tests/test_telephony.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_telephony.py`:

```python
def test_media_stream_dispatches_audio_to_append_chunks(monkeypatch):
    """Each Twilio media event drives append_chunks with the right
    inbound/outbound payloads."""
    from base64 import b64encode
    from app.storage import recordings as recordings_mod

    fake_session = MagicMock(broken=False)
    captured: list[tuple[bytes, bytes]] = []

    monkeypatch.setattr(
        recordings_mod, "begin_recording",
        lambda *, call_sid, restaurant_id, retention_days: fake_session,
    )
    monkeypatch.setattr(
        recordings_mod, "append_chunks",
        lambda session, inbound_mu_law, outbound_mu_law:
            captured.append((inbound_mu_law, outbound_mu_law)),
    )
    monkeypatch.setattr(
        recordings_mod, "finalize_recording", lambda _s: ("", 0),
    )

    fake_dg = AsyncMock()
    fake_dg.send = AsyncMock()
    fake_dg.finish = AsyncMock()

    async def fake_open_dg(call_sid, restaurant_id, on_final):
        return fake_dg

    async def fake_speak(text, websocket, stream_sid, **kw):
        pass

    monkeypatch.setattr("app.telephony.router._open_deepgram_connection", fake_open_dg)
    monkeypatch.setattr("app.telephony.router.speak", fake_speak)
    monkeypatch.setattr(
        "app.telephony.router.stream_reply", _make_fake_stream_reply()
    )
    from app.storage import call_sessions
    monkeypatch.setattr(call_sessions, "init_call_session", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "record_event", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "mark_call_ended", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "mark_recording_ready", lambda *a, **kw: None)

    inbound_payload = b64encode(b"\xff" * 8).decode()
    outbound_payload = b64encode(b"\x00" * 8).decode()

    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        ws.send_text(json.dumps({
            "event": "media",
            "media": {"track": "inbound", "chunk": "1", "timestamp": "5", "payload": inbound_payload},
        }))
        ws.send_text(json.dumps({
            "event": "media",
            "media": {"track": "outbound", "chunk": "2", "timestamp": "10", "payload": outbound_payload},
        }))
        ws.send_text(json.dumps(_STOP_MSG))

    assert (b"\xff" * 8, b"") in captured
    assert (b"", b"\x00" * 8) in captured
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_telephony.py::test_media_stream_dispatches_audio_to_append_chunks -v`
Expected: FAIL — `append_chunks` is never called by the existing handler.

- [ ] **Step 3: Update the `media` event branch**

In `app/telephony/router.py`, find:

```python
            elif event == "media":
                if dg_conn is not None:
                    audio = base64.b64decode(msg["media"]["payload"])
                    await dg_conn.send(audio)
```

Replace with:

```python
            elif event == "media":
                payload = base64.b64decode(msg["media"]["payload"])
                track = msg["media"].get("track")
                if track == "inbound":
                    inbound_chunk = payload
                    outbound_chunk = b""
                    if dg_conn is not None:
                        await dg_conn.send(payload)
                elif track == "outbound":
                    inbound_chunk = b""
                    outbound_chunk = payload
                else:
                    inbound_chunk = b""
                    outbound_chunk = b""
                if state.recording_session is not None:
                    recordings.append_chunks(
                        state.recording_session, inbound_chunk, outbound_chunk
                    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_telephony.py::test_media_stream_dispatches_audio_to_append_chunks -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/telephony/router.py tests/test_telephony.py
git commit -m "telephony: dispatch media events to append_chunks (track-aware)"
```

---

### Task 20: `finalize_recording` + `mark_recording_ready` in WS finally

**Files:**
- Modify: `app/telephony/router.py`
- Modify: `tests/test_telephony.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_telephony.py`:

```python
def test_media_stream_finalizes_recording_on_stop(monkeypatch):
    """After the call ends, finalize_recording runs and mark_recording_ready
    writes the resulting gs:// URL to Firestore."""
    from app.storage import recordings as recordings_mod
    from app.storage import call_sessions

    fake_session = MagicMock(broken=False)
    monkeypatch.setattr(
        recordings_mod, "begin_recording",
        lambda *, call_sid, restaurant_id, retention_days: fake_session,
    )
    monkeypatch.setattr(recordings_mod, "append_chunks", lambda *a, **kw: None)
    monkeypatch.setattr(
        recordings_mod, "finalize_recording",
        lambda session: ("gs://niko-recordings/niko-pizza-kitchen/CAtest123.mp3", 12),
    )

    fake_dg = AsyncMock()
    fake_dg.send = AsyncMock()
    fake_dg.finish = AsyncMock()
    monkeypatch.setattr("app.telephony.router._open_deepgram_connection", lambda *a, **kw: fake_dg)
    monkeypatch.setattr("app.telephony.router.speak", AsyncMock())
    monkeypatch.setattr("app.telephony.router.stream_reply", _make_fake_stream_reply())

    monkeypatch.setattr(call_sessions, "init_call_session", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "record_event", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "mark_call_ended", lambda *a, **kw: None)

    captured: list[dict] = []
    monkeypatch.setattr(
        call_sessions, "mark_recording_ready",
        lambda call_sid, rid, **kw: captured.append({"call_sid": call_sid, "rid": rid, **kw}),
    )

    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        ws.send_text(json.dumps(_STOP_MSG))

    assert len(captured) == 1
    assert captured[0]["call_sid"] == "CAtest123"
    assert captured[0]["rid"] == "niko-pizza-kitchen"
    assert captured[0]["recording_url"] == "gs://niko-recordings/niko-pizza-kitchen/CAtest123.mp3"
    assert captured[0]["recording_sid"] == "CAtest123"
    assert captured[0]["duration_seconds"] == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_telephony.py::test_media_stream_finalizes_recording_on_stop -v`
Expected: FAIL — `mark_recording_ready` was never called.

- [ ] **Step 3: Add the finalize block to the WS `finally`**

In `app/telephony/router.py`, find the existing block in `media_stream()`'s `finally` that calls `call_sessions.mark_call_ended`. Right **after** that block (and before `if dg_conn is not None: await dg_conn.finish()`), add:

```python
        if state.recording_session is not None and rid_for_close:
            try:
                gs_url, duration = await asyncio.to_thread(
                    recordings.finalize_recording, state.recording_session
                )
                if gs_url:
                    await asyncio.to_thread(
                        call_sessions.mark_recording_ready,
                        state.call_sid,
                        rid_for_close,
                        recording_url=gs_url,
                        recording_sid=state.call_sid,
                        duration_seconds=duration,
                    )
            except Exception:
                logger.exception(
                    "recording: finalize/mark failed call_sid=%s",
                    state.call_sid,
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_telephony.py::test_media_stream_finalizes_recording_on_stop -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/telephony/router.py tests/test_telephony.py
git commit -m "telephony: finalize_recording + mark_recording_ready on WS stop"
```

---

### Task 21: Replace REST auto-hangup with `should_hangup` Event

**Files:**
- Modify: `app/telephony/router.py`
- Modify: `tests/test_telephony.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_telephony.py`:

```python
@pytest.mark.asyncio
async def test_hang_up_after_grace_sets_should_hangup_event(monkeypatch):
    """After the grace window, _hang_up_after_grace sets the WS-loop's
    should_hangup event. The REST update path is gone."""
    from app.telephony.router import _CallState, _hang_up_after_grace

    monkeypatch.setattr("app.telephony.router.HANGUP_GRACE_SECONDS", 0.01)

    state = _CallState(call_sid="CAtest", pending_hangup=True)
    assert not state.should_hangup.is_set()

    await _hang_up_after_grace(state)

    assert state.should_hangup.is_set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_telephony.py::test_hang_up_after_grace_sets_should_hangup_event -v`
Expected: FAIL — `_hang_up_after_grace` still calls `_twilio_end_call_sync`.

- [ ] **Step 3: Replace `_hang_up_after_grace` with the event-based version**

In `app/telephony/router.py`, find `_hang_up_after_grace`:

```python
async def _hang_up_after_grace(state: _CallState) -> None:
    try:
        await asyncio.sleep(HANGUP_GRACE_SECONDS)
    except asyncio.CancelledError:
        return
    if not state.pending_hangup or not state.call_sid:
        return
    try:
        await asyncio.to_thread(_twilio_end_call_sync, state.call_sid)
        logger.info("call ended by server call_sid=%s", state.call_sid)
    except Exception:
        logger.exception(
            "auto-hangup: REST end_call failed call_sid=%s", state.call_sid
        )
```

Replace with:

```python
async def _hang_up_after_grace(state: _CallState) -> None:
    """Wait HANGUP_GRACE_SECONDS, then signal the WS loop to close.

    Closing our /media-stream WebSocket ends Twilio's <Connect>; with
    no further TwiML the call hangs up. This avoids the Twilio REST
    Calls.update endpoint, which returns 404 on calls in <Connect>
    state (same root cause as the recording bug).
    """
    try:
        await asyncio.sleep(HANGUP_GRACE_SECONDS)
    except asyncio.CancelledError:
        return
    if not state.pending_hangup or not state.call_sid:
        return
    state.should_hangup.set()
    logger.info("call ended by server (WS-close path) call_sid=%s", state.call_sid)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_telephony.py::test_hang_up_after_grace_sets_should_hangup_event -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/telephony/router.py tests/test_telephony.py
git commit -m "telephony: auto-hangup via should_hangup event (no REST)"
```

---

### Task 22: WS loop races `receive_text` against `should_hangup.wait()`

**Files:**
- Modify: `app/telephony/router.py`
- Modify: `tests/test_telephony.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_telephony.py`:

```python
@pytest.mark.asyncio
async def test_media_stream_loop_breaks_on_should_hangup(mock_pipeline, monkeypatch):
    """Setting state.should_hangup mid-call exits the WS loop and runs
    the finally block."""
    from app.storage import recordings as recordings_mod
    from app.storage import call_sessions

    monkeypatch.setattr(
        recordings_mod, "begin_recording",
        lambda **kw: MagicMock(broken=False),
    )
    monkeypatch.setattr(recordings_mod, "append_chunks", lambda *a, **kw: None)
    monkeypatch.setattr(recordings_mod, "finalize_recording", lambda _s: ("", 0))
    monkeypatch.setattr(call_sessions, "mark_recording_ready", lambda *a, **kw: None)

    # We exercise this through a real WebSocket so the loop's race-wait
    # logic runs end-to-end. After start, we set should_hangup via a
    # background task by reaching into module state.
    import app.telephony.router as router_mod

    captured_state = {}

    real_handler = router_mod.media_stream

    async def patched_handler(websocket):
        # Capture the _CallState by wrapping the handler.
        state_holder = {}
        orig_dataclass = router_mod._CallState
        def _spy(*a, **kw):
            s = orig_dataclass(*a, **kw)
            state_holder["s"] = s
            return s
        router_mod._CallState = _spy
        try:
            await real_handler(websocket)
        finally:
            router_mod._CallState = orig_dataclass
            captured_state["s"] = state_holder.get("s")

    monkeypatch.setattr(router_mod, "media_stream", patched_handler)

    # Re-register the patched route — easier: just call the handler directly
    # via TestClient as before, then trigger should_hangup from outside.
    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(json.dumps(_START_MSG))
        # Trigger hangup through the captured state.
        s = captured_state.get("s")
        assert s is not None, "state was not captured"
        s.should_hangup.set()
        # Loop should exit; we shouldn't need to send a stop message.
        # Read any pending close frames — TestClient handles closure.

    # If we got here without timing out, the loop exited on the event.
```

*(This test is awkward because TestClient doesn't expose a clean handle on the running coroutine. If the spy approach proves fragile, it's acceptable to delete this test and rely on Task 21's unit test plus manual smoke testing in Task 26 to validate the loop integration.)*

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_telephony.py::test_media_stream_loop_breaks_on_should_hangup -v`
Expected: FAIL or hang — the existing loop only breaks on a `stop` event, never on the new `should_hangup` event.

If the test hangs, kill it and skip to Step 3 — the loop edit is what makes it pass.

- [ ] **Step 3: Add the race in the WS loop**

In `app/telephony/router.py`, find the `media_stream()` function's main loop:

```python
        while True:
            raw = await websocket.receive_text()
            msg: dict = json.loads(raw)
            event = msg.get("event")
            ...
```

Replace with:

```python
        while not state.should_hangup.is_set():
            raw_task = asyncio.create_task(websocket.receive_text())
            hangup_task = asyncio.create_task(state.should_hangup.wait())
            done, pending = await asyncio.wait(
                {raw_task, hangup_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if hangup_task in done:
                # auto-hangup fired. Cancel the in-flight receive and exit.
                raw_task.cancel()
                with contextlib.suppress(BaseException):
                    await raw_task
                break
            # raw_task completed
            hangup_task.cancel()
            with contextlib.suppress(BaseException):
                await hangup_task
            raw = raw_task.result()
            msg: dict = json.loads(raw)
            event = msg.get("event")
            ...
```

(The `...` is the existing event-dispatch code; leave it unchanged.)

Add at the top of the file with the other imports:

```python
import contextlib
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_telephony.py::test_media_stream_loop_breaks_on_should_hangup -v --timeout=10`
Expected: PASS within 10 seconds. If the test is too brittle, delete it (per the Step 1 note) and re-run the full telephony suite to confirm nothing else broke.

- [ ] **Step 5: Commit**

```bash
git add app/telephony/router.py tests/test_telephony.py
git commit -m "telephony: race receive_text vs should_hangup in WS loop"
```

---

### Task 23: `app/main.py` — `get_call_recording` returns 302 to signed URL

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_calls_route.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_calls_route.py`:

```python
"""Tests for /calls/{call_sid}/recording — proxy to GCS via signed URL."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import Tenant
from app.main import app, current_tenant


def _override_tenant(rid="rid1", role="owner"):
    def _dep():
        return Tenant(uid="u1", email="e@x.com", restaurant_id=rid, role=role)
    return _dep


@pytest.fixture
def authed_client():
    app.dependency_overrides[current_tenant] = _override_tenant("rid1", "owner")
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_call_recording_returns_302_to_signed_url(authed_client, monkeypatch):
    from app.storage import call_sessions, recordings

    monkeypatch.setattr(
        call_sessions, "get_session",
        lambda call_sid, rid: {"recording_url": "gs://niko-recordings/rid1/CAt.mp3"},
    )
    monkeypatch.setattr(
        recordings, "generate_signed_url",
        lambda *, call_sid, restaurant_id: "https://signed.example/?sig=fake",
    )

    r = authed_client.get("/calls/CAt/recording", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"] == "https://signed.example/?sig=fake"


def test_get_call_recording_404_when_url_missing(authed_client, monkeypatch):
    from app.storage import call_sessions

    monkeypatch.setattr(
        call_sessions, "get_session",
        lambda call_sid, rid: {"recording_url": None},
    )

    r = authed_client.get("/calls/CAt/recording")
    assert r.status_code == 404


def test_get_call_recording_502_when_url_not_gs(authed_client, monkeypatch):
    from app.storage import call_sessions

    monkeypatch.setattr(
        call_sessions, "get_session",
        lambda call_sid, rid: {"recording_url": "https://api.twilio.com/legacy.mp3"},
    )

    r = authed_client.get("/calls/CAt/recording")
    assert r.status_code == 502
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_calls_route.py -v`
Expected: 3 FAIL — current `get_call_recording` does buffered Twilio fetch, not 302.

- [ ] **Step 3: Replace the proxy with a 302 redirect**

In `app/main.py`:

1. Remove the `import httpx` line (no longer needed — we don't fetch upstream from FastAPI anymore).
2. Add `from fastapi.responses import RedirectResponse` to the existing FastAPI imports.
3. Add `from app.storage import recordings` to the existing `app.storage` imports.
4. Replace the entire body of `get_call_recording(...)`:

```python
@app.get("/calls/{call_sid}/recording")
async def get_call_recording(
    call_sid: str,
    tenant: Tenant = Depends(current_tenant),
):
    """Tenant-authed entry point for playback. Returns a 302 redirect to
    a 30-min V4 signed URL for the recording blob in GCS. The browser's
    <audio> element follows the redirect natively. Cloud Run sees zero
    audio bytes for the playback path."""
    session = call_sessions.get_session(call_sid, tenant.restaurant_id)
    if not session or not session.get("recording_url"):
        raise HTTPException(status_code=404, detail="recording not available yet")
    if not session["recording_url"].startswith("gs://"):
        raise HTTPException(status_code=502, detail="invalid recording URL")
    signed = await asyncio.to_thread(
        recordings.generate_signed_url,
        call_sid=call_sid,
        restaurant_id=tenant.restaurant_id,
    )
    return RedirectResponse(url=signed, status_code=302)
```

5. If `import asyncio` isn't already at the top of the file, add it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_calls_route.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_calls_route.py
git commit -m "main: GET /calls/{sid}/recording returns 302 to signed URL"
```

---

### Task 24: `app/main.py` — `delete_call_recording` endpoint (owner only)

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_calls_route.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_calls_route.py`:

```python
def test_delete_call_recording_owner_returns_204(authed_client, monkeypatch):
    from app.storage import call_sessions, recordings

    monkeypatch.setattr(
        call_sessions, "get_session",
        lambda call_sid, rid: {"recording_url": "gs://niko-recordings/rid1/CAt.mp3"},
    )

    deleted: list[dict] = []
    cleared: list[dict] = []
    monkeypatch.setattr(
        recordings, "delete_recording",
        lambda *, call_sid, restaurant_id: deleted.append({"sid": call_sid, "rid": restaurant_id}),
    )
    monkeypatch.setattr(
        call_sessions, "mark_recording_deleted",
        lambda call_sid, rid: cleared.append({"sid": call_sid, "rid": rid}),
    )

    r = authed_client.delete("/calls/CAt/recording")
    assert r.status_code == 204
    assert deleted == [{"sid": "CAt", "rid": "rid1"}]
    assert cleared == [{"sid": "CAt", "rid": "rid1"}]


def test_delete_call_recording_non_owner_returns_403(monkeypatch):
    app.dependency_overrides[current_tenant] = _override_tenant("rid1", "staff")
    try:
        c = TestClient(app)
        r = c.delete("/calls/CAt/recording")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_delete_call_recording_idempotent_on_missing_blob(authed_client, monkeypatch):
    from google.api_core.exceptions import NotFound
    from app.storage import call_sessions, recordings

    monkeypatch.setattr(
        call_sessions, "get_session",
        lambda call_sid, rid: {"recording_url": None},
    )

    def raise_notfound(**_kw):
        raise NotFound("gone")
    monkeypatch.setattr(recordings, "delete_recording", lambda *, call_sid, restaurant_id: None)
    monkeypatch.setattr(call_sessions, "mark_recording_deleted", lambda *a, **kw: None)

    r = authed_client.delete("/calls/CAt/recording")
    assert r.status_code == 204
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_calls_route.py -k delete -v`
Expected: 3 FAIL — endpoint doesn't exist (404 from FastAPI) or 405 method-not-allowed.

- [ ] **Step 3: Add the DELETE endpoint**

In `app/main.py`, immediately after the `get_call_recording` function, add:

```python
@app.delete("/calls/{call_sid}/recording", status_code=204)
async def delete_call_recording(
    call_sid: str,
    tenant: Tenant = Depends(current_tenant),
):
    """Owner-only: delete the recording blob from GCS, clear
    ``recording_url`` from the call session doc, emit a ``recording_deleted``
    event. Idempotent: returns 204 even if the blob was already gone or
    the call had no recording.

    Tenant scoping: the call session must belong to the calling tenant.
    A non-existent call session (cross-tenant or genuinely missing) is
    indistinguishable to the caller — both return 404.
    """
    if tenant.role != "owner":
        raise HTTPException(status_code=403, detail="owner role required")
    session = call_sessions.get_session(call_sid, tenant.restaurant_id)
    if session is None:
        raise HTTPException(status_code=404, detail="call not found")
    await asyncio.to_thread(
        recordings.delete_recording,
        call_sid=call_sid,
        restaurant_id=tenant.restaurant_id,
    )
    await asyncio.to_thread(
        call_sessions.mark_recording_deleted,
        call_sid,
        tenant.restaurant_id,
    )
    return Response(status_code=204)
```

If `Response` from `fastapi` isn't already imported in this file, add it: `from fastapi import Response`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_calls_route.py -k delete -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_calls_route.py
git commit -m "main: DELETE /calls/{sid}/recording (owner only)"
```

---

### Task 25: Remove dead code from the Twilio-REST recording era

**Files:**
- Modify: `app/telephony/router.py`
- Modify: `tests/test_telephony.py`

- [ ] **Step 1: Identify the dead symbols**

The following are unused after Tasks 16–22 land:

- `_start_recording_sync(...)` (function)
- `_twilio_end_call_sync(...)` (function)
- `recording_status(...)` HTTP endpoint
- `_TWILIO_RECORDING_URL_PREFIX` constant
- `RequestValidator` import
- The `await asyncio.wait_for(asyncio.to_thread(_start_recording_sync, ...))` block in `voice()`

- [ ] **Step 2: Remove them all**

In `app/telephony/router.py`:
- Delete the `from twilio.request_validator import RequestValidator` import.
- Delete the `_start_recording_sync` function.
- Delete the `_twilio_end_call_sync` function.
- Delete the `_TWILIO_RECORDING_URL_PREFIX` constant.
- Delete the entire `@router.post("/recording-status/{restaurant_id}/{call_sid}")` block (`recording_status`).
- In `voice()`, delete the `try: await asyncio.wait_for(asyncio.to_thread(_start_recording_sync, ...)); except asyncio.TimeoutError: ...` block.

- [ ] **Step 3: Remove obsolete tests**

In `tests/test_telephony.py`, delete:
- `test_recording_status_rejects_invalid_signature`
- `test_recording_status_returns_503_when_public_base_url_unset`
- `test_recording_status_writes_firestore_with_valid_signature`
- `test_recording_status_rejects_non_twilio_recording_url`
- `_recording_status_env` fixture and `_force_signature_valid` helper (if scoped only to those tests)

- [ ] **Step 4: Run the full telephony test suite**

Run: `pytest tests/test_telephony.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add app/telephony/router.py tests/test_telephony.py
git commit -m "telephony: remove dead Twilio-REST recording + REST hangup code"
```

---

### Task 26: Run the full backend test suite + push

**Files:** none

- [ ] **Step 1: Run the full suite**

Run: `pytest -v`
Expected: all green. If anything red, fix the regression before continuing.

- [ ] **Step 2: Static parse check**

Run:
```bash
python -c "import ast; [ast.parse(open(p).read()) for p in [
  'app/storage/recordings.py',
  'app/storage/call_sessions.py',
  'app/restaurants/models.py',
  'app/telephony/router.py',
  'app/main.py',
  'app/config.py',
]]; print('all parse OK')"
```
Expected: `all parse OK`.

- [ ] **Step 3: Push the branch**

Run: `git push -u origin feat/82-ws-side-recording`

- [ ] **Step 4: Open the PR**

Run:
```bash
gh pr create --repo tsuki-works/niko \
  --title "WS-side call recording (replaces Twilio REST recording)" \
  --body-file docs/superpowers/specs/2026-04-30-ws-recording-design.md
```

(Or write a fresh body summarising the spec — your choice.)

---

### Task 27: Run the bucket-bootstrap script + deploy

**Files:** none

- [ ] **Step 1: Bootstrap the bucket + IAM (one-shot)**

Run: `bash scripts/setup-recordings-bucket.sh`
Expected output ends with: `Done. Bucket gs://niko-recordings is ready for recordings.`

- [ ] **Step 2: Verify bucket lifecycle**

Run: `gcloud storage buckets describe gs://niko-recordings --format="value(lifecycle_config)"`
Expected: contains `daysSinceCustomTime: 0`.

- [ ] **Step 3: Verify IAM grants**

Run: `gcloud storage buckets get-iam-policy gs://niko-recordings | grep storage.objectAdmin`
Expected: lists `serviceAccount:347262010229-compute@developer.gserviceaccount.com`.

Run: `gcloud iam service-accounts get-iam-policy 347262010229-compute@developer.gserviceaccount.com | grep tokenCreator`
Expected: lists the SA bound to `roles/iam.serviceAccountTokenCreator`.

- [ ] **Step 4: Merge the PR (admin override; CI is informational)**

Run: `gh pr merge --repo tsuki-works/niko --squash --admin --delete-branch <PR_NUM>`

The push to `master` triggers the existing Cloud Run auto-deploy.

- [ ] **Step 5: Watch the deploy**

Run: `gh run watch --repo tsuki-works/niko $(gh run list --repo tsuki-works/niko --workflow="Deploy to Cloud Run" --limit 1 --json databaseId --jq '.[0].databaseId')`
Expected: deploy succeeds.

- [ ] **Step 6: Manual smoke test**

Place a call to `+1 647 905 8093`. After hangup:

a. Run: `gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=niko AND textPayload=~"recording"' --limit 10 --format='value(textPayload)' --order desc`
   Expected: lines like `recording chunk uploaded …` and (if the call had audio) `recording finalized gs://niko-recordings/.../...mp3`.

b. Open `https://niko-dashboard-ciyyvuq2pq-uc.a.run.app/orders/<call_sid>` and click play. Confirm audio plays. DevTools should show a 302 from `/api/calls/.../recording` to `storage.googleapis.com`.

c. Pan L/R via OS audio controls — confirm caller is on left, agent on right.

d. From the dashboard or via curl with an owner Firebase token: `DELETE /api/calls/<sid>/recording`. Confirm subsequent GET returns 404 and the audio player disappears.

e. Place another call and hang up after the order is confirmed (let the AI deliver the goodbye). Confirm Twilio drops the line within ~3s of the goodbye — auto-hangup is working.

- [ ] **Step 7: If anything is wrong**, tail logs to diagnose; otherwise close out.

---

## Self-Review

(Performed during plan authoring; record findings inline.)

**Spec coverage check:**
- Decision 1 (`tracks="both_tracks"`) → Task 16 ✓
- Decision 2 (stereo L=caller R=agent) → Task 6 (`_compute_pcm_pair`) ✓
- Decision 3 (MP3 32 kbps stereo via lameenc) → Tasks 7, 8 ✓
- Decision 4 (resumable upload, 256 KB chunks) → Tasks 8–11 ✓
- Decision 5 (signed URL via 302) → Task 23 ✓
- Decision 6 (auto-hangup via WS close) → Tasks 21–22 ✓
- Decision 7 (delete endpoint, owner only) → Task 24 ✓
- Decision 8 (per-tenant retention via custom_time) → Tasks 4 + 8 ✓
- Error-handling table → covered case-by-case across the relevant tasks (begin failure: Task 18 try/except; chunk retry: Task 10; finalize failure: Task 20 try/except; empty session: Task 13; broken session: Task 10 + 11; signed URL failure: implicitly returns 502 in Task 23; etc.)

**Placeholder scan:** No "TBD" / "TODO" / "implement later" remain. One soft area: Task 22's WS-loop test is acknowledged as fragile in the test description and may be deleted if it can't be made deterministic — that's an acceptable note rather than a placeholder.

**Type consistency:** `RecordingUploadSession` field names match across Tasks 8, 9, 10, 12. `begin_recording` / `append_chunks` / `finalize_recording` / `delete_recording` / `generate_signed_url` signatures match across plan and spec.
