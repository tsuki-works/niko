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
| 2 | Mono mix or stereo? | **Stereo (caller=L, agent=R)** | Same code complexity, ~2× file size (still tiny). Restaurant staff can pan L/R for QA when both sides talk simultaneously. |
| 3 | On-disk format? | **MP3 32 kbps stereo via Python `lameenc`** | 4–5× smaller than WAV (~1.2 MB per 5-min call vs ~5 MB). Pure-Python encoder — no ffmpeg, no system dep added to the Docker image. Universal browser playback (including Safari on iPad). Encodes incrementally so it pairs cleanly with resumable upload. At 8 kHz narrowband telephony, MP3 32 kbps is perceptually identical to source. *(μ-law→PCM decode uses stdlib `audioop`, which is removed in Python 3.13. Prod runs 3.12; when we upgrade, swap in a 256-entry decode table — ~15 lines, no dep.)* |
| 4 | Buffering & durability? | **Resumable GCS upload, 256 KB MP3 chunks streamed during the call, finalized at `stop`** | Survives Cloud Run pod death between chunks. Worst-case loss is one chunk (~64 s at 32 kbps MP3). Session URL stored on `_CallState`; pod death before *any* chunk uploads loses the recording for that call, which is rare enough to accept. |
| 5 | Playback URL? | **Signed URL (30 min TTL, V4) via 302 redirect from `/calls/{sid}/recording`** | Existing tenant-authed FastAPI endpoint stays as the entry point — it now issues a 302 to a freshly-signed GCS URL instead of streaming bytes. The dashboard `<audio>` element follows the 302 natively. No public surface (URLs are unguessable + short-lived). Saves ~all playback egress through Cloud Run. Cloud Run runtime SA needs `roles/iam.serviceAccountTokenCreator` on itself to sign V4 URLs without a key file. |
| 6 | Auto-hangup mechanism? | **Close the WebSocket server-side; let `<Connect>` end the call** | Same `<Connect>`-blocks-REST root cause as the recording bug. When our WS closes, Twilio's `<Connect>` ends; with no further TwiML the call hangs up. Replaces `_twilio_end_call_sync` REST call entirely. |
| 7 | Recording deletion? | **`DELETE /calls/{call_sid}/recording` endpoint (owner role only)** | Tenant-authed endpoint deletes the GCS blob, clears `recording_url` from the call session doc, emits a `recording_deleted` event. Backend-only in this spec — dashboard UI button is a follow-up frontend ticket once UX is decided. |
| 8 | Retention policy? | **Per-tenant via `recording_retention_days` field on Restaurant doc + GCS `customTime` per blob** | At upload time, `blob.custom_time = now() + retention_days`. Bucket lifecycle rule `daysSinceCustomTime: 0` deletes blobs whose customTime has passed. Each blob is effectively "scheduled to expire" on its own clock. Default 90 days; per-tenant override is one Firestore field. |

---

## Architecture

Two new modules + edits in four existing files. No new tenant model, no new auth path.

### New: `app/storage/recordings.py`

Three public functions:

```python
class RecordingUploadSession:
    """In-memory + GCS-side state for a single call's resumable upload."""
    call_sid: str
    restaurant_id: str
    blob_name: str                  # e.g. "twilight/CAtest.mp3"
    upload_url: str                 # GCS resumable session URL
    encoder: lameenc.Encoder        # MP3 encoder bound to this call
    pending_mp3: bytearray          # encoded MP3 bytes not yet uploaded
    total_bytes_uploaded: int       # cumulative MP3 bytes PUT to GCS so far
    total_pcm_samples: int          # cumulative PCM samples per channel — drives duration calc
    broken: bool                    # set if an upload chunk failed twice; further appends become no-ops

def begin_recording(
    *, call_sid: str, restaurant_id: str, retention_days: int
) -> RecordingUploadSession: ...

def append_chunks(
    session: RecordingUploadSession,
    inbound_mu_law: bytes,    # raw bytes from Twilio media event (track=inbound)
    outbound_mu_law: bytes,   # raw bytes from Twilio media event (track=outbound)
) -> None: ...

def finalize_recording(session: RecordingUploadSession) -> tuple[str, int]: ...
    # returns (gs:// URL, duration_seconds)

def delete_recording(call_sid: str, restaurant_id: str) -> None: ...

def generate_signed_url(
    *, call_sid: str, restaurant_id: str, ttl_minutes: int = 30
) -> str: ...
    # returns "https://storage.googleapis.com/...?X-Goog-Signature=..."
```

Internals — happy path:

1. **`begin_recording`**: creates the `lameenc.Encoder` (32 kbps, stereo, 8 kHz input rate); creates a GCS resumable upload session via `Blob.create_resumable_upload_session(content_type="audio/mpeg")`; sets `blob.custom_time = now() + retention_days` (per-tenant retention); stores the upload URL on the session object.
2. **`append_chunks`**: decodes each μ-law payload to PCM-16 via `audioop.ulaw2lin(_, 2)`, interleaves L/R per-sample into `session.pending_pcm`, and feeds it to `encoder.encode(...)` which produces MP3 bytes. The MP3 bytes accumulate in a separate `pending_mp3` buffer. When `pending_mp3` ≥ 256 KB (the GCS resumable-upload minimum chunk size — about 64 s of 32 kbps stereo audio), the buffer is sliced to a 256 KB-multiple, `PUT` to the resumable session URL with `Content-Range: bytes <start>-<end>/*`, and `total_bytes_uploaded` is advanced. The PUT runs via `asyncio.to_thread` so the call loop never blocks on it. The leftover (< 256 KB) stays in the buffer for the next chunk.
3. **`finalize_recording`**: appends `encoder.flush()` (the LAME tail) to `pending_mp3`, then PUTs the final chunk with `Content-Range: bytes <start>-<end>/<total>` — now we know the total length so the session closes. If `total_pcm_samples == 0` (no media events arrived), DELETE the resumable session URL and return `("", 0)` so the caller skips the Firestore write. Returns `(gs://{bucket}/{rid}/{sid}.mp3, total_pcm_samples / 8000)` for duration in seconds.
4. **`delete_recording`**: `Client().bucket(name).blob(f"{rid}/{sid}.mp3").delete()`. Idempotent — non-existent blob is a no-op.
5. **`generate_signed_url`**: uses `blob.generate_signed_url(version="v4", method="GET", expiration=timedelta(minutes=ttl_minutes))`. Cloud Run's runtime SA can sign URLs without a private key by using the IAM SignBlob workaround — the SA needs `roles/iam.serviceAccountTokenCreator` *on itself*. Granted as part of the bootstrap script.

Helper `_compute_pcm_pair(inbound_mu_law: bytes, outbound_mu_law: bytes) -> bytes` is the pure function at the core of `append_chunks` — it decodes each μ-law track via `audioop.ulaw2lin(_, 2)`, pads the shorter side with PCM silence (`b"\x00\x00"` per missing sample), and interleaves L/R as 16-bit little-endian samples. Returns the stereo PCM-16 byte string ready to feed to `encoder.encode(...)`. Easily unit-tested without GCS.

### Edits in `app/telephony/router.py`

1. `_CallState` adds:
   ```python
   recording_session: RecordingUploadSession | None = None
   should_hangup: asyncio.Event = field(default_factory=asyncio.Event)
   ```
2. `voice()` passes `tracks="both_tracks"` on the `<Stream>`:
   ```python
   stream = connect.stream(url=f"wss://{host}/media-stream", tracks="both_tracks")
   ```
3. WS `start` event handler: after the existing tenant resolution, call `recordings.begin_recording(...)` and store the result on `state.recording_session`. The retention days come from `state.restaurant.recording_retention_days` (added below). Wrap in try/except — failure here just disables recording for this call, doesn't break the call loop.
4. The `media` event branch dispatches by `msg["media"]["track"]`:
   ```python
   payload = base64.b64decode(msg["media"]["payload"])
   track = msg["media"].get("track")
   if track == "inbound":
       inbound_chunk = payload
       outbound_chunk = b""
       if dg_conn is not None:
           await dg_conn.send(payload)   # existing Deepgram STT forwarding
   elif track == "outbound":
       inbound_chunk = b""
       outbound_chunk = payload
   else:
       inbound_chunk = outbound_chunk = b""
   if state.recording_session is not None:
       recordings.append_chunks(
           state.recording_session, inbound_chunk, outbound_chunk
       )  # internal queue + threshold-driven background upload
   ```
   (Per-call chunk dispatch stays under ~1 ms — no awaits in the hot path; the actual chunk PUT happens in `asyncio.to_thread` inside `append_chunks` once 256 KB has accumulated.)
5. The WS `stop`/disconnect `finally` block: if `state.recording_session is not None`, call `await asyncio.to_thread(recordings.finalize_recording, state.recording_session)`, then `mark_recording_ready` with the returned GCS URL. Then close the WS (handled below).
6. **Replace `_twilio_end_call_sync` with WS-close**:
   - Delete `_twilio_end_call_sync` entirely.
   - `_hang_up_after_grace` no longer awaits a REST call. Instead, after the grace sleep, it calls `state.should_hangup.set()`. The main WS event loop checks this event after each `receive_text()` and breaks out of the loop, which causes the existing `finally` to run and the WS to close. Twilio's `<Connect>` ends when the WS closes; with no further TwiML the call hangs up.
   - Concretely the loop becomes:
     ```python
     while not state.should_hangup.is_set():
         raw_task = asyncio.create_task(websocket.receive_text())
         hangup_task = asyncio.create_task(state.should_hangup.wait())
         done, _ = await asyncio.wait(
             [raw_task, hangup_task], return_when=asyncio.FIRST_COMPLETED
         )
         if hangup_task in done:
             raw_task.cancel()
             break
         raw = raw_task.result()
         ...
     ```
7. **Delete dead code** now that we no longer use Twilio's Recordings or Calls.update APIs:
   - `_start_recording_sync`
   - The `await asyncio.wait_for(asyncio.to_thread(_start_recording_sync, …))` block in `voice()`
   - `recording_status` endpoint, `_TWILIO_RECORDING_URL_PREFIX`, `RequestValidator` import
   - `_twilio_end_call_sync`

### Edits in `app/main.py`

`get_call_recording` becomes a 302 redirect:
```python
@app.get("/calls/{call_sid}/recording")
async def get_call_recording(call_sid: str, tenant: Tenant = Depends(current_tenant)):
    session = call_sessions.get_session(call_sid, tenant.restaurant_id)
    if not session or not session.get("recording_url"):
        raise HTTPException(status_code=404, detail="recording not available yet")
    if not session["recording_url"].startswith("gs://"):
        raise HTTPException(status_code=502, detail="invalid recording URL")
    signed = await asyncio.to_thread(
        recordings.generate_signed_url,
        call_sid=call_sid, restaurant_id=tenant.restaurant_id,
    )
    return RedirectResponse(url=signed, status_code=302)
```

New `delete_call_recording` endpoint on the same path:
```python
@app.delete("/calls/{call_sid}/recording")
async def delete_call_recording(call_sid: str, tenant: Tenant = Depends(current_tenant)):
    if tenant.role != "owner":  # mirrors existing role gating
        raise HTTPException(status_code=403, detail="owner role required")
    session = call_sessions.get_session(call_sid, tenant.restaurant_id)
    if not session:
        raise HTTPException(status_code=404, detail="call not found")
    await asyncio.to_thread(
        recordings.delete_recording, call_sid, tenant.restaurant_id
    )
    await asyncio.to_thread(
        call_sessions.mark_recording_deleted, call_sid, tenant.restaurant_id
    )
    return Response(status_code=204)
```

`httpx` import goes away — we no longer fetch upstream from FastAPI; the browser fetches directly from GCS via the signed URL.

### Edits in `app/storage/call_sessions.py`

Add `mark_recording_deleted(call_sid, restaurant_id)`: clears `recording_url`/`recording_sid`/`recording_duration_seconds` from the parent doc and appends a `recording_deleted` event to the events subcollection. Mirrors the shape of `mark_recording_ready`.

### Edits in `app/restaurants/models.py`

Add field to the `Restaurant` model:
```python
recording_retention_days: int = Field(default=90, ge=1, le=3650)
```

`/restaurants/me` already serializes the full doc, so this becomes available to the dashboard for free if we ever build a per-tenant retention UI.

### Edits in `app/config.py`

```python
recordings_bucket: str = "niko-recordings"
recording_default_retention_days: int = 90  # used only if Restaurant doc lacks the field
```

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

# Per-tenant retention via custom_time. Each blob carries its own
# scheduled-deletion timestamp; this rule deletes blobs whose customTime
# has passed.
cat > /tmp/lifecycle.json <<'EOF'
{"lifecycle":{"rule":[{"action":{"type":"Delete"},"condition":{"daysSinceCustomTime":0}}]}}
EOF
gcloud storage buckets update "gs://${BUCKET}" --lifecycle-file=/tmp/lifecycle.json

# Cloud Run runtime SA needs read/write/delete on the bucket
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${SA}" --role="roles/storage.objectAdmin"

# Sign V4 URLs without a private-key file: SA must have iam.serviceAccountTokenCreator on itself
gcloud iam service-accounts add-iam-policy-binding "${SA}" \
  --member="serviceAccount:${SA}" --role="roles/iam.serviceAccountTokenCreator"
```

Add to `requirements.txt`:

```
google-cloud-storage>=2.0,<3.0
lameenc>=1.6,<2.0          # pure-Python LAME wrapper; no system ffmpeg
```

---

## Data flow

### Capture & upload (during the call)

1. Caller dials `+1 647 905 8093`. Twilio POSTs `/voice` with `CallSid=CA…`, `To=+16479058093`.
2. `voice()` resolves the tenant, returns TwiML:
   ```xml
   <Response><Connect><Stream url="wss://niko.../media-stream" tracks="both_tracks">
     <Parameter name="restaurant_id" value="twilight-family-restaurant"/>
   </Stream></Connect></Response>
   ```
3. Twilio opens WS to `/media-stream`. `start` event fires. After tenant resolution, `recordings.begin_recording(call_sid=…, restaurant_id=…, retention_days=state.restaurant.recording_retention_days)` runs:
   - Creates `lameenc.Encoder` (32 kbps, stereo, 8 kHz input).
   - Creates a GCS resumable upload session (`Blob.create_resumable_upload_session(content_type="audio/mpeg")`).
   - Sets `blob.custom_time = now() + timedelta(days=retention_days)`.
   - Returns a `RecordingUploadSession` stored on `state.recording_session`. On any failure here, log and continue — recording disabled for this call, call itself unaffected.
4. For each WS `media` event:
   - μ-law payload → PCM-16 via `audioop.ulaw2lin(_, 2)`.
   - Two-track interleave: inbound bytes go to L, outbound to R, missing-track padded with silence at the per-chunk level.
   - PCM appended to `session.pending_pcm`.
   - Inbound payloads continue to be forwarded to Deepgram (existing STT pipeline unchanged — only the inbound branch sends to dg_conn).
   - When `pending_pcm` reaches the chunk threshold (~256 KB stereo PCM ≈ ~16 s of audio), the slice is encoded through `encoder.encode(...)` to MP3 bytes and PUT to the resumable session URL via `asyncio.to_thread`. The PUT runs in the background; the call loop is never blocked on its completion.
5. WS `stop` (or disconnect / `should_hangup` set) → finally block:
   ```python
   if state.recording_session is not None:
       try:
           gs_url, duration = await asyncio.to_thread(
               recordings.finalize_recording, state.recording_session
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
               "recording: finalize/mark failed call_sid=%s", state.call_sid
           )
   ```
   `finalize_recording` flushes any remaining PCM through the encoder + appends `encoder.flush()` (LAME tail), PUTs the final chunk with `Content-Range: bytes <start>-<end>/<total>` (now we know the total size), closing the resumable session.
6. `mark_recording_ready` writes `recording_url=gs://...mp3` and emits a `recording_ready` event onto the call session doc. The dashboard's existing `onSnapshot` picks it up and renders the audio player.

### Playback

7. User clicks play → `<audio>` GETs `/api/calls/{call_sid}/recording` → Next.js proxies to FastAPI → `get_call_recording`:
   - Looks up the session via `call_sessions.get_session(call_sid, tenant.restaurant_id)` (existing tenant scoping; cross-tenant returns 404).
   - Asserts `recording_url` starts with `gs://`. Refuses anything else.
   - Calls `recordings.generate_signed_url(...)` (V4, 30-min TTL, GET method, signed via IAM `signBlob`).
   - Returns `302 Found` with `Location:` set to the signed URL.
8. Browser follows the 302 to GCS directly, downloads the MP3 bytes, plays them. Cloud Run sees zero audio bytes for the playback path.

### Auto-hangup

9. After order confirmation, `_run_llm_tts_turn` sends the `end_of_call` mark and sets `state.pending_hangup = True`. Twilio echoes the mark when its audio buffer drains; the WS `mark` handler schedules `_hang_up_after_grace`.
10. After the grace sleep (`HANGUP_GRACE_SECONDS = 3.0`), if `state.pending_hangup` is still set, `_hang_up_after_grace` calls `state.should_hangup.set()`.
11. The main WS `while not state.should_hangup.is_set()` loop wakes (it's `await`ing a `FIRST_COMPLETED` race between `receive_text` and `should_hangup.wait()`), breaks out, runs the `finally` block, and the WebSocket closes.
12. Twilio's `<Connect>` ends when our WS closes; with no further TwiML, the inbound call hangs up. Caller hears the line drop ~10–80 ms later.

### Recording deletion

13. Owner clicks "delete recording" → dashboard sends `DELETE /api/calls/{call_sid}/recording` → Next.js proxies → FastAPI's `delete_call_recording`:
    - `current_tenant` enforces auth + tenant scope; an additional `tenant.role == "owner"` check rejects non-owners with 403.
    - Calls `recordings.delete_recording(call_sid, tenant.restaurant_id)` (idempotent GCS delete).
    - Calls `call_sessions.mark_recording_deleted(call_sid, restaurant_id)` to clear `recording_url` and append a `recording_deleted` event.
    - Returns 204.
14. The dashboard's existing `onSnapshot` sees `recording_url` cleared and removes the audio player.

---

## Error handling

| Failure | Behaviour |
|---|---|
| `begin_recording` fails (GCS perms, IAM, transient) at WS `start` | Logged at ERROR; `state.recording_session` stays `None`; call proceeds without recording. |
| Per-chunk PUT fails (transient) | `append_chunks` retries the PUT once with exponential backoff inside the worker thread; on second failure, marks the session as broken and stops attempting further uploads. The call continues; no `recording_ready` event at end. |
| Cloud Run pod dies mid-call after some chunks have uploaded | Resumable upload session lives on GCS for ~7 days; the chunks already PUT remain. Without our final PUT (which carries the total length), GCS treats the session as orphaned and reaps it after the TTL. The dashboard never sees a `recording_ready` for that call. Acceptable — much better than losing the entire call as in v1. |
| Cloud Run pod dies mid-call before any chunks have uploaded | Recording for that call is lost. Same as v1. Rare. |
| WS disconnects before `stop` (caller hangs up abruptly) | Existing `finally` block runs `finalize_recording`. We have whatever PCM/MP3 has been encoded so far; the recording is just shorter. |
| `finalize_recording` fails (transient final PUT) | Logged at ERROR; no `recording_ready` written. The chunks are still on GCS as an orphaned session and get reaped after TTL. |
| Tenant unresolved at upload time (`rid_for_close is None`) | Skip finalize. Same guard already protects `mark_call_ended`. Logged at WARNING. |
| Empty buffers (call dropped on first ring; zero `media` events) | `state.recording_session` was created with the begin step but no chunks were appended. `finalize_recording` notices `total_bytes_uploaded == 0`, skips the final PUT, and marks the resumable session as cancelled (`DELETE` on the session URL). No Firestore write. |
| `audioop`/`lameenc`/`wave` raises mid-encode | The chunk worker logs the exception and marks the session broken. Call lifecycle finishes cleanly. |
| Track-length skew (one side talked more than the other within a chunk) | `_compute_pcm_pair` pads the shorter side with PCM silence per chunk. Skew of tens of ms is acceptable for QA use. |
| Two `media` events with the same timestamp on different tracks | Each is dispatched to its own track-side buffer independently. No cross-contamination. |
| `generate_signed_url` fails (IAM SignBlob denied, transient) | `get_call_recording` returns 502 with `detail="failed to generate playback URL"`. Caller can retry. |
| Dashboard playback hits an expired signed URL | Browser surfaces a load error; user reloads the page, the dashboard re-fetches `/calls/{sid}/recording`, gets a fresh redirect. UX-acceptable; we can shorten the TTL further later if needed. |
| `delete_call_recording` called with non-owner role | 403. Owner-only operation. |
| `delete_call_recording` called for a call with no recording | GCS delete is idempotent; `mark_recording_deleted` is idempotent (no-op if `recording_url` already absent). 204 returned either way. |
| `should_hangup.set()` triggered but WS already disconnected | Main loop already exited. `_hang_up_after_grace`'s `set()` is a no-op on a Set-already-set Event. Idempotent. |
| Caller speaks during the grace window | `_handle_final_transcript` calls `_abort_pending_hangup`, which clears `state.pending_hangup` and cancels `state.hangup_task`. `should_hangup` is never set; call continues. |
| `recording_retention_days` field missing from older Restaurant docs | Pydantic default of 90 applies on model load. No migration required. |

---

## Testing

### Unit — `tests/test_recordings_storage.py` (new)

**Encode + interleave (pure functions, no GCS):**
- `test_compute_pcm_pair_interleaves_lr` — 1 inbound chunk + 1 outbound chunk of equal length; assert output is sample-interleaved L/R/L/R.
- `test_compute_pcm_pair_pads_shorter_side` — inbound 100 ms, outbound 500 ms; assert L channel is zero-padded after the 100 ms mark.
- `test_compute_pcm_pair_handles_empty_chunks` — both empty; returns empty bytes.
- `test_mp3_encode_produces_decodable_frames` — feed a known sine wave through encode+flush; assert output starts with an MP3 frame sync and decodes (via `pydub` or just header parse) back to a stereo 8 kHz signal of the right length.

**Resumable upload (with mocked `requests.Session` for the PUT calls and mocked `google.cloud.storage.Client`):**
- `test_begin_recording_creates_session_and_sets_custom_time` — assert `Blob.create_resumable_upload_session` was called with `content_type="audio/mpeg"`, `blob.custom_time` set to `now() + retention_days`, and the returned session has the upload URL stored.
- `test_append_chunks_buffers_until_threshold` — feed 100 small PCM chunks each well below 256 KB; assert no PUT has fired yet.
- `test_append_chunks_flushes_when_threshold_hit` — feed enough PCM to cross the threshold; assert one PUT with `Content-Range: bytes 0-<n>/*` and the right MP3 byte content.
- `test_append_chunks_retries_once_on_transient_error` — mock first PUT returns 503, second 200; assert exactly two attempts and `total_bytes_uploaded` is updated.
- `test_append_chunks_marks_broken_after_two_failures` — mock both PUTs return 503; assert session marked broken and subsequent appends are no-ops.
- `test_finalize_recording_sends_total_length` — mock final PUT; assert the `Content-Range` is `bytes <start>-<end>/<total>` (with a concrete total, not `*`), and the returned URL is `gs://...`.
- `test_finalize_recording_with_zero_chunks_cancels_session` — no appends between begin and finalize; assert `DELETE` on the session URL was called and no Firestore write happened.

**Delete + signed URL:**
- `test_delete_recording_calls_blob_delete` — mock blob; assert `delete()` called once on `{rid}/{sid}.mp3`.
- `test_delete_recording_idempotent_on_404` — mock blob raises `NotFound`; function swallows it and returns normally.
- `test_generate_signed_url_uses_v4_get_30min` — mock `blob.generate_signed_url`; assert call kwargs `version="v4"`, `method="GET"`, `expiration=timedelta(minutes=30)`.

### Integration — `tests/test_telephony.py` (extended)

- `test_voice_emits_both_tracks_stream_parameter` — POST `/voice`, assert returned TwiML contains `tracks="both_tracks"` on the `<Stream>`.
- `test_media_stream_begins_recording_on_start` — drive WS through `connected` → `start`; assert `recordings.begin_recording` was called with the resolved tenant id and retention from the (mocked) Restaurant doc.
- `test_media_stream_dispatches_audio_by_track` — drive WS: `start` → 2× `media` (inbound) → 2× `media` (outbound) → `stop`. Assert `recordings.append_chunks` was called four times with the right inbound/outbound payloads, and `recordings.finalize_recording` was called once at the end.
- `test_media_stream_skips_finalize_when_no_session` — simulate `begin_recording` failure (raises); assert no `append_chunks` calls, no `finalize_recording`, no `mark_recording_ready`. Call still completes cleanly.
- `test_should_hangup_event_breaks_ws_loop` — start a fake call, externally `state.should_hangup.set()` after a few media events, assert the loop exits, the WS closes, and `finalize_recording` is called in the `finally`.
- Remove existing tests touching `_start_recording_sync`, `recording_status`, signature validation, host allowlisting, `_twilio_end_call_sync` — all now-dead code.

### Integration — `tests/test_orders_route.py` or new `tests/test_calls_route.py`

- `test_get_call_recording_returns_302_with_signed_url` — mock `recordings.generate_signed_url`; POST as authed tenant; assert 302 and `Location` header equals the mocked signed URL.
- `test_get_call_recording_404_when_recording_missing` — session has no `recording_url`; assert 404.
- `test_get_call_recording_502_when_url_not_gs` — Firestore session has a non-`gs://` URL (legacy data); assert 502.
- `test_get_call_recording_404_cross_tenant` — call_sid belongs to tenant A; tenant B's auth → 404 (existing behaviour, just reasserting it survives the rewrite).
- `test_delete_call_recording_owner_only_204` — owner-role authed user → 204, `delete_recording` and `mark_recording_deleted` both called.
- `test_delete_call_recording_non_owner_403` — staff-role user → 403; neither helper called.
- `test_delete_call_recording_idempotent_on_missing_blob` — call exists, blob already gone → 204.

### Manual — post-deploy

- **Recording capture + playback**: place a test call to `+1 647 905 8093`. After hangup:
  - Cloud Run logs show `recording chunk uploaded` lines mid-call and `recording finalized gs://niko-recordings/...mp3` at end.
  - Dashboard `<audio>` plays. DevTools network tab shows 302 from `/api/calls/.../recording` to a `storage.googleapis.com` signed URL.
  - Pan L/R to confirm caller is on left, agent on right.
- **Auto-hangup**: place a test call, complete an order, observe Twilio drops the line within ~3 s of order confirmation (no manual hangup needed).
- **Delete**: from the dashboard (or curl with an owner Firebase ID token), `DELETE /api/calls/{sid}/recording`. Audio player disappears within ~1 s; subsequent GET returns 404.
- **Per-tenant retention**: update one Restaurant doc to `recording_retention_days: 1`. Place a test call. Verify on GCS console that the resulting blob's `Custom time` is set to ~24 h from now (lifecycle deletion verifiable but not waited-on in this manual test).

---

## Out of scope (genuinely deferred)

- **Recording-deletion UI in the dashboard** — backend `DELETE` endpoint is in scope; the actual button + confirmation dialog on the call detail page is a separate frontend ticket once we know the exact UX.
- **Bulk delete** — "delete all recordings for tenant X older than Y" — not modelled. The bucket lifecycle rule + per-blob `customTime` already handles age-based bulk cleanup; one-off bulk operations can be done via gcloud for now.
- **Recording-deleted notification** — the `recording_deleted` event lands on the events subcollection; no email/SMS is sent. If that's needed later it's a separate ticket.
- **Custom MP3 bitrate per tenant** — single 32 kbps stereo for all calls. If a tenant later needs higher fidelity (unlikely for telephony narrowband), revisit.
- **Recording-resume across instance death** (i.e., somehow continuing the same recording session if the WS reconnects on a new pod) — Twilio doesn't reconnect calls across pod restarts, so this isn't physically possible. The resumable upload merely protects already-uploaded chunks, not the unwritten future.
