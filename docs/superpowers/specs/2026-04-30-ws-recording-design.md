# WebSocket-side call recording (replaces Twilio REST recording)

**Date:** 2026-04-30
**Issue:** #82 (Sprint 2.1 — Call quality optimization). Successor to PRs #127, #132, #133.
**Status:** Spec — awaiting implementation plan

---

## Context

Sprint 2.4 calls for call recordings playable from the dashboard's call detail page. The first attempt (PR #127) used Twilio's Recordings REST API, started from the WebSocket `start` event. PRs #132 + #133 chased timing fixes. All three approaches got the same `HTTP 404 / "requested resource not found"` from Twilio.

Root cause is documented Twilio behaviour: when a call is in `<Connect>` state, Twilio's voice REST API control is suspended for the duration of the connection. `recordings.create`, `calls.update(status="completed")`, and similar endpoints all return 404 mid-call. The 404 is not a timing race — there is no point in the `<Connect><Stream>` lifecycle when REST recording will work. Direct evidence:

- During an active `<Connect>` call: `POST /Calls/{sid}/Recordings.json` → 404
- After the same call completes: same POST → 400 / error code 21220 (`not eligible for recording`)
- `GET /Calls/{sid}.json` always succeeds — auth and resource path are correct

Auto-hangup (`_twilio_end_call_sync`) hits the same root cause; tracked separately.

This spec defines the replacement: capture the audio from the WebSocket Twilio is *already* sending, store it ourselves in GCS, and proxy it back through the existing dashboard contract.

---

## Decisions locked during brainstorming

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | Caller-only or both tracks? | **Both** (`tracks="both_tracks"` on `<Stream>`) | "We recorded the customer but not what we said back" is a weird artifact for QA / disputes. Twilio sends both via the same WS. |
| 2 | Storage format? | **WAV + 16-bit PCM (decoded from μ-law via Python stdlib `audioop`)** | Universal browser support, including Safari on iPad (restaurant operator surface). No `ffmpeg`, no third-party encoder. The μ-law→PCM decode is stdlib (single function call), <1 ms for a 5-min call. ~5 MB per 5-min stereo call. *(`audioop` is removed in Python 3.13; we're on 3.12 in prod. When we upgrade, swap in a 256-entry μ-law decode table — ~15 lines, no dep.)* |
| 3 | Playback URL — proxy or signed URL? | **Keep the existing proxy** | Tenant scoping stays in our FastAPI dep. Egress cost is rounding-error at our call volume. Switch to signed URLs later if it ever matters. |
| 4 | Mono mix or stereo? | **Stereo (caller=L, agent=R)** | Same code complexity, ~2× file size (still tiny). Restaurant staff can pan L/R for QA when both sides talk simultaneously. |
| 5 | Buffering pipeline? | **In-memory bytearray per call, upload at `stop`** | Memory footprint trivial at our scale. Streaming/resumable upload is 3× the code for marginal durability gain. /tmp on Cloud Run is tmpfs so spooling there saves nothing. |

---

## Architecture

One new module + targeted edits in three existing files. No new tenant model, no new auth path.

### New: `app/storage/recordings.py`

Single public function:

```python
def save_call_recording(
    *,
    call_sid: str,
    restaurant_id: str,
    inbound_audio: bytes,   # raw μ-law 8 kHz mono, caller side
    outbound_audio: bytes,  # raw μ-law 8 kHz mono, agent side
) -> tuple[str, int]:       # (gs:// URL, duration_seconds)
```

Internals:
1. `audioop.ulaw2lin(b, 2)` decodes each μ-law track to 16-bit linear PCM (Python stdlib).
2. Pad the shorter PCM track with `b"\x00"` (silence) to match the longer one.
3. Interleave the two PCM tracks — left=caller, right=agent — sample by sample.
4. Write a stereo 16-bit PCM @ 8 kHz WAV via the `wave` stdlib into a `BytesIO`.
5. Upload to `gs://{settings.recordings_bucket}/{restaurant_id}/{call_sid}.wav` via `google-cloud-storage` (`Blob.upload_from_string` of the bytes; content-type `audio/wav`).
6. Return `(gs_url, duration_seconds)` where duration = `len(longest_pcm) / 2 / 8000`.

Helper `_silent_skip_path()` returns the empty/None decision before calling GCS — keeps the function safe to invoke unconditionally.

### Edits in `app/telephony/router.py`

1. `_CallState` adds two `bytearray` fields:
   ```python
   inbound_audio: bytearray = field(default_factory=bytearray)
   outbound_audio: bytearray = field(default_factory=bytearray)
   ```
2. `voice()` passes `tracks="both_tracks"` on the `<Stream>`:
   ```python
   stream = connect.stream(url=f"wss://{host}/media-stream", tracks="both_tracks")
   ```
3. The `media` event branch dispatches base64-decoded bytes by `msg["media"]["track"]`:
   ```python
   payload = base64.b64decode(msg["media"]["payload"])
   track = msg["media"].get("track")
   if track == "inbound":
       state.inbound_audio.extend(payload)
       if dg_conn is not None:
           await dg_conn.send(payload)   # existing Deepgram forwarding stays here
   elif track == "outbound":
       state.outbound_audio.extend(payload)
   ```
   (Other track values are silently ignored — forward-compat.)
4. The WS `stop`/disconnect `finally` block, after `mark_call_ended`, calls `save_call_recording` via `asyncio.to_thread`, then `mark_recording_ready` with the returned GCS URL.
5. **Delete dead code** now that we no longer use Twilio's Recordings API:
   - `_start_recording_sync`
   - The `await asyncio.wait_for(asyncio.to_thread(_start_recording_sync, …))` block in `voice()`
   - `recording_status` endpoint and the `_TWILIO_RECORDING_URL_PREFIX` constant
   - `RequestValidator` import

### Edits in `app/main.py`

`get_call_recording` proxy:

- Reads `recording_url` from the session doc as before — but the value is now `gs://...` not `https://api.twilio.com/...`.
- Replace the `httpx.AsyncClient.get(...)` + Twilio Basic Auth path with `google.cloud.storage.Client().bucket(name).blob(path).download_as_bytes()` (running in `asyncio.to_thread`).
- Keep the existing Twilio-host allowlist in spirit by asserting `recording_url.startswith("gs://")` before parsing. Refuse anything else with `HTTPException(502, "invalid recording URL")`.
- Response media-type changes from `audio/mpeg` to `audio/wav`. Filename in `Content-Disposition` becomes `{call_sid}.wav`.

### Edits in `app/config.py`

```python
recordings_bucket: str = "niko-recordings"
```

Centralised so tests can override to a fake bucket name. No new env var; default is fine for prod and dev.

### Infra (one-time)

`scripts/setup-recordings-bucket.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
PROJECT=niko-tsuki
BUCKET=niko-recordings
REGION=us-central1
SA="347262010229-compute@developer.gserviceaccount.com"

gcloud storage buckets create "gs://${BUCKET}" \
  --project="${PROJECT}" --location="${REGION}" --uniform-bucket-level-access

cat > /tmp/lifecycle.json <<EOF
{"lifecycle":{"rule":[{"action":{"type":"Delete"},"condition":{"age":90}}]}}
EOF
gcloud storage buckets update "gs://${BUCKET}" --lifecycle-file=/tmp/lifecycle.json

gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${SA}" --role="roles/storage.objectAdmin"
```

Add to `requirements.txt`:

```
google-cloud-storage>=2.0,<3.0
```

---

## Data flow

1. Caller dials `+1 647 905 8093`. Twilio POSTs `/voice` with `CallSid=CA…`, `To=+16479058093`.
2. `voice()` resolves the tenant, returns TwiML:
   ```xml
   <Response><Connect><Stream url="wss://niko.../media-stream" tracks="both_tracks">
     <Parameter name="restaurant_id" value="twilight-family-restaurant"/>
   </Stream></Connect></Response>
   ```
3. Twilio opens the WS to `/media-stream`. `start` event fires; `_CallState` initialises with empty audio bytearrays alongside the existing fields.
4. Per `media` event: append the base64-decoded payload to the bytearray matching `media.track`. Inbound payloads also continue to be forwarded to Deepgram (existing STT pipeline unchanged).
5. `stop` event (or WS disconnect):
   ```python
   if state.call_sid and rid_for_close and (state.inbound_audio or state.outbound_audio):
       try:
           gs_url, duration = await asyncio.to_thread(
               save_call_recording,
               call_sid=state.call_sid,
               restaurant_id=rid_for_close,
               inbound_audio=bytes(state.inbound_audio),
               outbound_audio=bytes(state.outbound_audio),
           )
           await asyncio.to_thread(
               call_sessions.mark_recording_ready,
               state.call_sid, rid_for_close,
               recording_url=gs_url,
               recording_sid=state.call_sid,
               duration_seconds=duration,
           )
       except Exception:
           logger.exception(
               "recording: save/mark failed call_sid=%s", state.call_sid
           )
   ```
6. `mark_recording_ready` writes `recording_url` and emits a `recording_ready` event onto the call session doc. The dashboard's existing `onSnapshot` picks it up and renders the audio player.
7. User clicks play → `<audio>` requests `/api/calls/{call_sid}/recording` → Next.js proxies to FastAPI → `get_call_recording` looks up the session via `call_sessions.get_session(call_sid, tenant.restaurant_id)` (existing tenant scoping; cross-tenant returns 404), reads `recording_url`, downloads the blob from GCS via the runtime SA, returns `audio/wav` bytes.

---

## Error handling

| Failure | Behaviour |
|---|---|
| WS disconnects before `stop` (caller hangs up abruptly) | Existing `finally` block runs. We have whatever bytes arrived; same upload path executes. Recording is just shorter. |
| Tenant unresolved at upload time (`rid_for_close is None`) | Skip upload entirely. Same guard already protects `mark_call_ended`. Logged at WARNING. |
| GCS upload fails (perms, transient network, quota) | `save_call_recording` raises; the wrapping `try/except Exception` logs via `logger.exception(...)` and the call lifecycle still completes cleanly. No `recording_ready` event written; dashboard shows no audio player. |
| Empty buffers (call dropped on first ring; zero `media` events) | Both bytearrays empty → `if … or …:` guard skips upload; no Firestore write. |
| `audioop` / `wave` raises mid-encode | Same try/except as above. |
| Cloud Run instance dies mid-call | Recording for that one call is lost. Documented v1 limitation; instance death during a live WS is rare. |
| Dashboard proxy hits a missing GCS blob (Firestore says ready but blob 404s) | `get_call_recording` raises `HTTPException(status_code=404, detail="recording not available yet")`. |
| Two `media` events with the same timestamp on different tracks | Each appends to its own buffer independently. No cross-contamination. |
| Track-length skew (one side talked more than the other) | `save_call_recording` pads the shorter PCM track with `b"\x00"` (silence) before interleaving. Skew of tens of ms is acceptable for QA-and-disputes use. |

---

## Testing

### Unit — `tests/test_recordings_storage.py` (new)

- `test_save_call_recording_happy_path` — 1 second of inbound (8000 bytes of `0x00`) + 1 second of outbound (8000 bytes of `0x7F`); assert blob path is `twilight/CAtest.wav`, returned URL is `gs://niko-recordings/twilight/CAtest.wav`, duration is `1`. Mocks `google.cloud.storage.Client` so no network.
- `test_wav_header_is_well_formed` — pull the uploaded bytes off the mock; assert RIFF/WAVE magic, fmt chunk = 16-bit PCM @ 8000 Hz × 2 channels, byte-rate matches, data chunk size matches.
- `test_track_length_skew_padded_with_silence` — inbound = 100 ms, outbound = 500 ms; assert resulting WAV is 500 ms × 2 ch × 16-bit, the inbound channel after the 100 ms mark is zero-bytes.
- `test_empty_buffers_skip_upload` — both buffers empty; assert the GCS client was never called and the function returns early.
- `test_gcs_upload_failure_raises` — mock client raises `GoogleAPIError`; function re-raises so the WS handler can log + skip the Firestore write.

### Integration — extend `tests/test_telephony.py`

- `test_voice_emits_both_tracks_stream_parameter` — POST `/voice`, assert returned TwiML contains `tracks="both_tracks"` on the `<Stream>` verb.
- `test_media_stream_dispatches_audio_by_track` — drive WS through a fake call: `connected` → `start` → 2× `media` (inbound) → 2× `media` (outbound) → `stop`. Assert `save_call_recording` is called once with `inbound_audio` containing the two inbound payloads concatenated and `outbound_audio` containing the two outbound payloads. Mock `save_call_recording` and `mark_recording_ready` so no GCS / Firestore.
- `test_recording_skipped_when_buffers_empty` — `start` → `stop` with no `media` events; assert `save_call_recording` was *not* called and no `recording_ready` event was emitted.
- Existing tests touching `_start_recording_sync`, `recording_status`, signature validation, and host allowlisting are removed (now-dead code).

### Manual — post-deploy

- Place a test call to `+1 647 905 8093`. After hangup:
  - Cloud Run logs show `recording uploaded gs://niko-recordings/...`
  - Dashboard `<audio>` plays
  - Pan L/R independently to confirm caller is on left, agent on right

---

## Out of scope

- **MP3 transcode** — keep WAV/μ-law for v1; revisit when storage cost is real.
- **Signed-URL playback** — keep proxy until egress costs justify the swap.
- **Auto-hangup REST fix** — same `<Connect>`-blocks-REST root cause, but distinct mechanism (probably "send a special TwiML mark and let the WS shut the call down by closing"). Separate ticket.
- **Cross-instance durability** — accept the rare instance-death gap; add resumable upload only if real loss is observed.
- **Recording deletion when an order is deleted** — Firestore doc lifecycle isn't tied to GCS today; Phase 3 concern.
- **Per-tenant retention policies** — single 90-day bucket-level rule for v1; tenant-specific rules later if needed.
