# Telephony Router Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `app/telephony/router.py` (1293 lines) into focused modules — vendor-specific Twilio I/O in `app/twilio/`, vendor-neutral orchestration in `app/telephony/session.py`, FastAPI shells + WS event-loop in a slimmed `app/telephony/router.py`. Mirrors the existing `app/deepgram/` pattern.

**Architecture:** Geographic split, no new abstractions, no behavior changes. Mechanical move of code; existing test suite verifies behavior preservation.

**Tech Stack:** Python 3.13, FastAPI, asyncio, Twilio TwiML SDK (`twilio.twiml.voice_response`).

**Spec:** `docs/superpowers/specs/2026-05-06-telephony-router-modularization-design.md` (PR #252).

**Branch:** `refactor/251-telephony-router-split` (already created off `feat/83-tune-conversational-bot`).

**Note on TDD:** This is a behavior-preserving refactor — no new tests needed. The discipline is "tests pass at every commit boundary." Each task runs the focused telephony test subset and only commits if green.

---

## Pre-flight

- [ ] **Step 1: Verify branch state**

```bash
git branch --show-current
```

Expected: `refactor/251-telephony-router-split`.

- [ ] **Step 2: Verify baseline tests pass**

```bash
pytest tests/test_telephony.py tests/test_voice.py tests/test_barge_in_helper.py tests/test_transcript_consumer.py -q
```

Expected: all pass. If any fail, stop — the baseline is broken and the refactor would mask it.

---

## Task 1: Extract Twilio WS protocol primitives

Goal: pull `clear_twilio_audio` and `send_end_of_call_mark` out of `router.py` into `app/twilio/media_stream.py`. They're the only two outgoing Twilio-shaped JSON literals the orchestration layer emits.

**Files:**
- Create: `app/twilio/__init__.py`
- Create: `app/twilio/media_stream.py`
- Modify: `app/telephony/router.py`

- [ ] **Step 1: Create the package marker**

`app/twilio/__init__.py`:

```python
"""Twilio vendor module.

Holds Twilio-specific I/O — TwiML response builders, Media Stream
WebSocket protocol primitives, and REST helpers — kept separate from
the vendor-neutral call orchestration in app/telephony/. Mirrors the
app/deepgram/ pattern.

Consumers that need vendor-agnostic call logic should import from
app/telephony/, not from here. Anything that touches a Twilio JSON
envelope, TwiML XML, or Twilio's REST API lives under this package.
"""

from __future__ import annotations
```

- [ ] **Step 2: Create `media_stream.py`**

`app/twilio/media_stream.py`:

```python
"""Twilio Media Stream WS protocol primitives — outgoing frames only.

Incoming frame parsing (start/media/mark/stop) stays inline in the
WS event-loop in app/telephony/router.py until a second telephony
provider forces a real shape difference.
"""

from __future__ import annotations

import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


async def send_clear(websocket: WebSocket, stream_sid: str | None) -> None:
    """Tell Twilio to flush its audio buffer and stop playback (#74).

    Cancelling the LLM/TTS task only stops generation — bytes already in
    Twilio's buffer keep playing for 1-3 seconds. Twilio's clear event
    drops the buffer in ~80ms. Used by barge-in and post-silence cleanup.
    """
    if not stream_sid:
        return
    try:
        await websocket.send_json({"event": "clear", "streamSid": stream_sid})
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception(
            "clear: failed to send Twilio clear event stream_sid=%s",
            stream_sid,
        )


async def send_mark(
    websocket: WebSocket,
    stream_sid: str | None,
    name: str,
) -> bool:
    """Append a named mark to Twilio's outgoing media stream (#78).

    Twilio echoes the mark back over the WebSocket once its audio buffer
    drains past it — i.e. once the caller has heard everything we sent.
    The auto-hangup path uses this as the precise trigger to begin its
    grace window. Returns True if the send succeeded.
    """
    if not stream_sid:
        return False
    try:
        await websocket.send_json(
            {
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {"name": name},
            }
        )
        return True
    except WebSocketDisconnect:
        return False
    except Exception:
        logger.exception(
            "mark: failed to send mark name=%s stream_sid=%s",
            name,
            stream_sid,
        )
        return False
```

- [ ] **Step 3: Wire `router.py` to the new primitives**

In `app/telephony/router.py`:

1. Add the import near the top with the other `app.*` imports:

```python
from app.twilio.media_stream import send_clear, send_mark
```

2. **Delete** the existing `clear_twilio_audio` function definition (currently around lines 241-260).

3. **Delete** the existing `send_end_of_call_mark` function definition (currently around lines 141-164).

4. Replace the call sites:

In `_barge_in_now` (currently around line 289), change:

```python
await clear_twilio_audio(websocket, state.stream_sid)
```

to:

```python
await send_clear(websocket, state.stream_sid)
```

In `_handle_final_transcript` (currently around line 688), change:

```python
await clear_twilio_audio(websocket, state.stream_sid)
```

to:

```python
await send_clear(websocket, state.stream_sid)
```

In `_run_llm_tts_turn` (currently around line 615), change:

```python
sent = await send_end_of_call_mark(websocket, state.stream_sid)
```

to:

```python
sent = await send_mark(websocket, state.stream_sid, name=END_OF_CALL_MARK)
```

- [ ] **Step 4: Run focused tests**

```bash
pytest tests/test_telephony.py tests/test_barge_in_helper.py tests/test_transcript_consumer.py -q
```

Expected: all pass. `test_barge_in_helper.py` asserts on the JSON payload `{"event": "clear", ...}` so it verifies the new `send_clear` produces the same bytes.

- [ ] **Step 5: Commit**

```bash
git add app/twilio/__init__.py app/twilio/media_stream.py app/telephony/router.py
git commit -m "refactor(telephony): extract Twilio WS protocol primitives to app/twilio/ (#251)

Pulls clear_twilio_audio and send_end_of_call_mark out of router.py
into app/twilio/media_stream.py as send_clear and send_mark. These
are the only outgoing Twilio-shaped JSON frames the orchestration
emits; isolating them clears the path for the rest of the split.

No behavior change — the new functions reproduce the existing
WebSocketDisconnect handling and exception logging."
```

---

## Task 2: Extract TwiML response builders

Goal: pull all `VoiceResponse(...)` construction out of the FastAPI handlers in `router.py` into `app/twilio/twiml.py`. Handlers shrink to "parse form → call builder → return Response".

**Files:**
- Create: `app/twilio/twiml.py`
- Modify: `app/telephony/router.py`

- [ ] **Step 1: Create `twiml.py`**

`app/twilio/twiml.py`:

```python
"""TwiML response builders for the Twilio voice webhook surface.

Pure functions returning Twilio VoiceResponse objects. The FastAPI
handlers in app/telephony/router.py call these and wrap the result
in a fastapi.Response with media_type='application/xml'.

Kept separate so that:
- TwiML XML construction lives in one place (mirrors app/deepgram/);
- builders are easy to snapshot-test without spinning up FastAPI;
- the orchestration layer in app/telephony/ never imports from
  twilio.twiml directly.
"""

from __future__ import annotations

from twilio.twiml.voice_response import Connect, Dial, VoiceResponse

from app.restaurants.models import Restaurant


_UNCONFIGURED_TWIML_MESSAGE = (
    "Sorry, this number is not currently configured. Goodbye."
)
_CLOSED_TWIML_MESSAGE = (
    "Sorry, we're closed. Please call back during business hours."
)


def empty_twiml() -> VoiceResponse:
    """Empty <Response/>. Used for hangup-on-success paths and as a
    safe default when a Twilio callback can't be acted on."""
    return VoiceResponse()


def unconfigured_hangup_twiml() -> VoiceResponse:
    """Inbound call to a number that isn't mapped to any tenant."""
    twiml = VoiceResponse()
    twiml.say(_UNCONFIGURED_TWIML_MESSAGE)
    twiml.hangup()
    return twiml


def closed_hangup_twiml() -> VoiceResponse:
    """Defensive after-hours hangup for the rare case the voicemail
    flow can't run (e.g. CallSid missing on the inbound webhook)."""
    twiml = VoiceResponse()
    twiml.say(_CLOSED_TWIML_MESSAGE)
    twiml.hangup()
    return twiml


def voice_twiml(restaurant: Restaurant, ws_host: str) -> VoiceResponse:
    """Open a bidirectional Media Stream back to /media-stream and
    forward the resolved restaurant id via <Parameter> so the WS
    handler doesn't need to re-query Firestore."""
    twiml = VoiceResponse()
    connect = Connect(action="/voice/stream-ended", method="POST")
    # NOTE: <Connect><Stream> only supports the default ``inbound_track``;
    # passing ``track="both_tracks"`` makes Twilio reject the TwiML and
    # the call drops the moment the caller dismisses the trial-account
    # interstitial. To capture the agent's voice in the recording, the
    # /media-stream WS handler intercepts the TTS bytes we send out via
    # ``speak()`` and feeds them directly into the recording session.
    stream = connect.stream(url=f"wss://{ws_host}/media-stream")
    stream.parameter(name="restaurant_id", value=restaurant.id)
    twiml.append(connect)
    return twiml


def transfer_twiml(
    fallback_phone: str,
    call_sid: str,
    rid: str,
    *,
    timeout: int = 20,
) -> VoiceResponse:
    """Dial the tenant's fallback number, with action callback to
    /voice/transfer-result so we can record the outcome and cascade
    to voicemail on no-answer/busy/failed."""
    twiml = VoiceResponse()
    dial = Dial(
        action=f"/voice/transfer-result?call_sid={call_sid}&rid={rid}",
        method="POST",
        timeout=timeout,
    )
    dial.number(fallback_phone)
    twiml.append(dial)
    return twiml
```

- [ ] **Step 2: Wire `router.py` handlers to the builders**

In `app/telephony/router.py`:

1. Add the import:

```python
from app.twilio.twiml import (
    closed_hangup_twiml,
    empty_twiml,
    transfer_twiml,
    unconfigured_hangup_twiml,
    voice_twiml,
)
```

2. Remove the `_UNCONFIGURED_TWIML_MESSAGE` constant (now lives in `twiml.py`).

3. Remove `from twilio.twiml.voice_response import Connect, Dial, VoiceResponse` from the top of the file — no longer needed in router.

4. Rewrite the `voice` handler body. Replace the section starting `twiml = VoiceResponse()` and ending at `return Response(content=str(twiml), ...)` with:

```python
    if restaurant is None:
        logger.warning("voice: no restaurant for To=%s — rejecting call", to_e164 or "(missing)")
        return Response(
            content=str(unconfigured_hangup_twiml()),
            media_type="application/xml",
        )

    if not is_open_now(restaurant):
        # After-hours: skip the AI flow, drop straight to voicemail.
        if not call_sid:
            # Defensive: Twilio always posts CallSid. Without it, we
            # can't key the recording or call_session — bail.
            return Response(
                content=str(closed_hangup_twiml()),
                media_type="application/xml",
            )
        try:
            call_sessions.init_call_session(call_sid, restaurant.id)
        except Exception:
            logger.exception(
                "voice: init_call_session failed call_sid=%s rid=%s",
                call_sid,
                restaurant.id,
            )
        return Response(
            content=str(voicemail_response(call_sid, restaurant.id)),
            media_type="application/xml",
        )

    host = request.headers.get("host", "localhost:8000")
    return Response(
        content=str(voice_twiml(restaurant, host)),
        media_type="application/xml",
    )
```

5. In `stream_ended`, replace the three `Response(content=str(VoiceResponse()), ...)` returns with:

```python
return Response(content=str(empty_twiml()), media_type="application/xml")
```

And replace the `<Dial>` construction (currently `twiml = VoiceResponse(); dial = Dial(...); ... twiml.append(dial); return Response(content=str(twiml), ...)`) with:

```python
return Response(
    content=str(transfer_twiml(restaurant.fallback_phone, call_sid, rid)),
    media_type="application/xml",
)
```

6. In `transfer_result`, replace `Response(content=str(VoiceResponse()), ...)` with `Response(content=str(empty_twiml()), ...)` (two occurrences).

7. In `voicemail_recorded`, replace all five `Response(content=str(VoiceResponse()), ...)` returns with `Response(content=str(empty_twiml()), ...)`.

- [ ] **Step 3: Run focused tests**

```bash
pytest tests/test_telephony.py tests/test_voice.py -q
```

Expected: all pass. `test_voice.py` exercises the public `/voice` surface; `test_telephony.py` covers the WS handler.

- [ ] **Step 4: Commit**

```bash
git add app/twilio/twiml.py app/telephony/router.py
git commit -m "refactor(telephony): extract TwiML builders to app/twilio/twiml.py (#251)

Pure functions for the five TwiML responses the voice webhook
surface returns. Handlers in router.py shrink to form-parsing +
builder call + Response wrap. No behavior change."
```

---

## Task 3: Extract Twilio REST recording download

Goal: move the inline Twilio REST recording fetch out of `voicemail_recorded` into `app/twilio/__init__.py`. Currently the handler imports `recordings.upload_voicemail_from_twilio`, which already lives in `app/storage/recordings.py` and takes Twilio creds — so the actual change is small. The Twilio-specific *credentials check* and the `(account_sid, auth_token)` tuple construction move out of router.

**Files:**
- Modify: `app/twilio/__init__.py`
- Modify: `app/telephony/router.py`

- [ ] **Step 1: Add a credentialed-fetch helper to `app/twilio/__init__.py`**

Append to `app/twilio/__init__.py`:

```python
import logging

from app.config import settings
from app.storage import recordings as _recordings

logger = logging.getLogger(__name__)


def twilio_basic_auth() -> tuple[str, str] | None:
    """Return Twilio REST basic-auth tuple, or None when unconfigured.

    Centralised so the voicemail-recorded callback doesn't have to
    reach into ``settings.twilio_account_sid`` / ``twilio_auth_token``
    directly. Returns None (rather than raising) so the caller can
    log + degrade gracefully — voicemail upload is best-effort.
    """
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    if not sid or not token:
        return None
    return (sid, token)


def upload_voicemail(
    *,
    call_sid: str,
    restaurant_id: str,
    twilio_recording_url: str,
) -> str:
    """Download the voicemail recording from Twilio's REST and upload
    to GCS. Wraps app.storage.recordings.upload_voicemail_from_twilio
    with the Twilio creds resolved from settings.

    Raises RuntimeError if Twilio creds are missing — the caller is
    expected to check ``twilio_basic_auth()`` first if it wants to
    short-circuit gracefully.
    """
    auth = twilio_basic_auth()
    if auth is None:
        raise RuntimeError("Twilio credentials missing")
    return _recordings.upload_voicemail_from_twilio(
        call_sid=call_sid,
        restaurant_id=restaurant_id,
        twilio_recording_url=twilio_recording_url,
        auth=auth,
    )
```

- [ ] **Step 2: Wire `voicemail_recorded` to the helper**

In `app/telephony/router.py`, replace the block in `voicemail_recorded` that reads:

```python
if not settings.twilio_account_sid or not settings.twilio_auth_token:
    logger.error(
        "voicemail upload: twilio creds missing call_sid=%s",
        call_sid,
    )
    return Response(
        content=str(empty_twiml()),
        media_type="application/xml",
    )

try:
    gs_url = recordings.upload_voicemail_from_twilio(
        call_sid=call_sid,
        restaurant_id=rid,
        twilio_recording_url=recording_url,
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
    )
except Exception:
    ...
```

with:

```python
if app_twilio.twilio_basic_auth() is None:
    logger.error(
        "voicemail upload: twilio creds missing call_sid=%s",
        call_sid,
    )
    return Response(
        content=str(empty_twiml()),
        media_type="application/xml",
    )

try:
    gs_url = app_twilio.upload_voicemail(
        call_sid=call_sid,
        restaurant_id=rid,
        twilio_recording_url=recording_url,
    )
except Exception:
    logger.exception(
        "voicemail upload failed call_sid=%s sid=%s",
        call_sid,
        recording_sid,
    )
    return Response(
        content=str(empty_twiml()),
        media_type="application/xml",
    )
```

Add the import at the top of `router.py`:

```python
import app.twilio as app_twilio
```

(Aliased to `app_twilio` to make it clear at the call site that this is *our* package, not the third-party `twilio` SDK.)

- [ ] **Step 3: Run focused tests**

```bash
pytest tests/test_telephony.py tests/test_voice.py -q
```

Expected: all pass. (Voicemail upload is mocked in `test_telephony.py`'s pipeline fixture; the wiring change is covered by the existing test.)

- [ ] **Step 4: Commit**

```bash
git add app/twilio/__init__.py app/telephony/router.py
git commit -m "refactor(telephony): centralise Twilio REST creds + voicemail upload (#251)

Adds twilio_basic_auth() and upload_voicemail() helpers in
app/twilio/__init__.py so the voicemail-recorded webhook handler
doesn't have to dereference settings.twilio_account_sid /
twilio_auth_token directly. Behaviour preserved."
```

---

## Task 4: Move `_CallState` and orchestration helpers to `session.py`

Goal: this is the big one — move the bulk of `router.py` (everything except FastAPI shells and the WS event-loop dispatch) into `app/telephony/session.py`. Public test-imported names (`_CallState`, `_barge_in_now`, `_consume_transcripts`, `_should_flush_chunk`, `_MIN_CHUNK_CHARS`) become public from the new location. Test imports update.

**Files:**
- Create: `app/telephony/session.py`
- Modify: `app/telephony/router.py`
- Modify: `tests/test_barge_in_helper.py`
- Modify: `tests/test_transcript_consumer.py`
- Modify: `tests/test_telephony.py`

- [ ] **Step 1: Create `session.py` with the moved code**

Create `app/telephony/session.py` containing, in order, copied verbatim from `router.py`:

1. The module docstring (rewritten — see below).
2. All imports `router.py` needs for these helpers — minus FastAPI's `APIRouter, Request, Response` and minus `Connect, Dial, VoiceResponse`. Keep `WebSocket, WebSocketDisconnect`.
3. The constants block:
   - `SILENCE_TIMEOUT_SECONDS`, `SILENCE_PROMPT`, `GREETING_TRANSCRIPT`
   - `END_OF_CALL_MARK`, `HANGUP_GRACE_SECONDS`, `MARK_ECHO_TIMEOUT_SECONDS`
   - `_HARD_BREAKS`, `_SOFT_BREAKS`, `_MIN_CHUNK_CHARS`
   - `_GOODBYE_PATTERNS`
4. The pure helpers:
   - `_should_flush_chunk`
   - `_looks_like_goodbye`
5. The Firestore helper:
   - `_bg_call_event`
6. **`_CallState` dataclass.** Move verbatim. Keep all field comments.
7. The recording-handler factory: `_make_recording_chunk_handler`.
8. `_state_rid`.
9. Silence watchdog trio: `_silence_watchdog`, `_cancel_silence_task`, `_arm_silence_watchdog`.
10. Auto-hangup trio: `_hang_up_after_grace`, `_hang_up_after_mark_timeout`, `_abort_pending_hangup`.
11. Barge-in: `_barge_in_now`.
12. Transcript consumer: `_consume_transcripts`.
13. LLM turn: `_run_llm_tts_turn`, `_handle_final_transcript`.
14. Tenant resolver: `_resolve_restaurant_for_voice` (still needed by `voice` handler in router.py).

The new file's docstring:

```python
"""Call orchestration — vendor-neutral.

Owns _CallState and every helper that runs during the lifetime of an
active call: barge-in, hangup, silence, the LLM/TTS turn loop, and the
STT transcript consumer. The module knows about the abstract STT/TTS
provider interfaces in app/stt and app/tts but nothing about Twilio
specifics — those live in app/twilio/.

The FastAPI endpoints + WS event-loop dispatch live in
app/telephony/router.py. router.py imports from this module; this
module does not import from router.py.
"""
```

Imports the new file needs (build this list by reading the moved code):

```python
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect

from app.config import settings
from app.llm.client import stream_reply
from app.llm.prompts import build_system_prompt  # used by ws handler — see note
from app.orders.lifecycle import OrderNotReadyError, persist_on_confirm  # used by ws handler — see note
from app.orders.models import Order, OrderStatus
from app.restaurants.models import Restaurant
from app.restaurants.open_check import is_open_now  # used by voice handler — see note
from app.storage import call_sessions, recordings, restaurants as restaurants_storage
from app.storage.recordings import RecordingUploadSession  # noqa: F401  (typing only)
from app.stt import STTProvider, SpeechStartedEvent, TranscriptEvent
from app.twilio.media_stream import send_clear, send_mark
```

Notes on imports — some symbols (`build_system_prompt`, `OrderNotReadyError`, `persist_on_confirm`, `is_open_now`) are referenced from the WS handler in `router.py` not directly from helpers being moved. Re-check after the move: import only what `session.py` actually uses. Static analysis: a final `pyflakes app/telephony/session.py` must show zero unused imports.

Replace the inline call sites in `_barge_in_now` and `_run_llm_tts_turn` to use `send_clear` / `send_mark` (already done in Tasks 1, but verify these moved code blocks still reference the new names).

- [ ] **Step 2: Slim `router.py` to shells + WS event-loop**

Rewrite `app/telephony/router.py` to contain only:

1. Module docstring (rewritten — focused on the FastAPI surface).
2. Imports needed for the HTTP handlers and the WS dispatch.
3. The `router = APIRouter()` declaration.
4. `_TRANSFER_STATUS_MAP` (used by `transfer_result`).
5. The five HTTP handlers: `voice`, `stream_ended`, `transfer_result`, `voicemail_recorded`, `voicemail_transcription`.
6. The `media_stream` WebSocket handler.

Imports for the new `router.py`:

```python
from __future__ import annotations

import asyncio
import base64
import json
import logging

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect

import app.twilio as app_twilio
from app.config import settings
from app.llm.prompts import build_system_prompt
from app.orders.lifecycle import OrderNotReadyError, persist_on_confirm
from app.orders.models import Order
from app.restaurants.open_check import is_open_now
from app.storage import call_sessions, recordings
from app.storage import restaurants as restaurants_storage
from app.stt import get_stt
from app.telephony.session import (
    GREETING_TRANSCRIPT,
    END_OF_CALL_MARK,
    _CallState,
    _abort_pending_hangup,
    _arm_silence_watchdog,
    _bg_call_event,
    _cancel_silence_task,
    _consume_transcripts,
    _hang_up_after_grace,
    _make_recording_chunk_handler,
    _resolve_restaurant_for_voice,
    _run_llm_tts_turn,
    _state_rid,
)
from app.telephony.voicemail_twiml import voicemail_response
from app.tts import speak
from app.twilio.twiml import (
    closed_hangup_twiml,
    empty_twiml,
    transfer_twiml,
    unconfigured_hangup_twiml,
    voice_twiml,
)
```

Re-check after the rewrite: `pyflakes app/telephony/router.py` shows zero unused imports.

The HTTP handlers and WS event-loop body are *unchanged* from the post-Task-3 state — only the imports + the helper definitions move out.

- [ ] **Step 3: Update test imports**

`tests/test_telephony.py` — change:

```python
from app.telephony.router import _MIN_CHUNK_CHARS, _should_flush_chunk
```

to:

```python
from app.telephony.session import _MIN_CHUNK_CHARS, _should_flush_chunk
```

`tests/test_barge_in_helper.py` — change:

```python
from app.telephony.router import _CallState, _barge_in_now
```

to:

```python
from app.telephony.session import _CallState, _barge_in_now
```

`tests/test_transcript_consumer.py` — change:

```python
from app.telephony.router import _CallState, _consume_transcripts
```

to:

```python
from app.telephony.session import _CallState, _consume_transcripts
```

- [ ] **Step 4: Run focused tests**

```bash
pytest tests/test_telephony.py tests/test_voice.py tests/test_barge_in_helper.py tests/test_transcript_consumer.py -q
```

Expected: all pass.

- [ ] **Step 5: Verify line-count targets**

```bash
wc -l app/telephony/router.py app/telephony/session.py
```

Expected:
- `app/telephony/router.py` — between 200 and 350 lines (FastAPI shells + WS event-loop only).
- `app/telephony/session.py` — between 700 and 900 lines.

If either is wildly off, something didn't move (or got duplicated). Eyeball the diff before committing.

- [ ] **Step 6: Commit**

```bash
git add app/telephony/session.py app/telephony/router.py tests/test_telephony.py tests/test_barge_in_helper.py tests/test_transcript_consumer.py
git commit -m "refactor(telephony): move _CallState + orchestration helpers to session.py (#251)

Slims router.py to FastAPI shells + WS event-loop dispatch
(~250 lines). All call orchestration — barge-in, hangup, silence,
LLM turn, transcript consumer — now lives in session.py
(~800 lines). Test imports updated to the new module path.

No behavior change. Tests pass."
```

---

## Task 5: Final verification

Goal: run the full test suite, confirm the public surface is unchanged, and update PR #252 to reflect that the implementation has landed.

- [ ] **Step 1: Run the full pytest suite**

```bash
pytest -q
```

Expected: all pass. If the telephony-focused subset passed in Task 4 but the full suite fails, the failure is somewhere else (unrelated regression) — investigate before proceeding.

- [ ] **Step 2: Static check — no unused imports**

```bash
python -m pyflakes app/telephony/router.py app/telephony/session.py app/twilio/__init__.py app/twilio/media_stream.py app/twilio/twiml.py
```

Expected: no output (no unused imports, no undefined names).

- [ ] **Step 3: Public-surface diff check**

```bash
git diff feat/83-tune-conversational-bot..HEAD -- app/main.py
```

Expected: no diff. The FastAPI app mount is unchanged.

```bash
git diff feat/83-tune-conversational-bot..HEAD -- app/telephony/router.py | grep -E "^\+@router\.(post|websocket)"
```

Expected: no output (no new endpoints — same five POSTs and one WebSocket as before, with unchanged paths).

- [ ] **Step 4: Push and update PR**

```bash
git push origin refactor/251-telephony-router-split
```

Then update PR #252's title and body via `gh pr edit 252`. New title: `refactor(telephony): split router.py + carve app/twilio/ (#251)`. Body should describe the implementation, not just the spec.

```bash
gh pr edit 252 --repo tsuki-works/niko --title "refactor(telephony): split router.py + carve app/twilio/ (#251)" --body "$(cat <<'EOF'
## Summary

Splits app/telephony/router.py (1293 lines) along the Twilio-vs-orchestration boundary, mirroring the existing app/deepgram/ pattern.

- app/telephony/router.py — FastAPI shells + WS event-loop only (~250 lines)
- app/telephony/session.py — _CallState + orchestration helpers (~800 lines)
- app/twilio/twiml.py — TwiML response builders
- app/twilio/media_stream.py — send_clear, send_mark WS protocol primitives
- app/twilio/__init__.py — Twilio REST credential helpers + voicemail upload wrapper

## Non-goals (deliberate)

- No TelephonyProvider ABC — single vendor today.
- No CallSession class — possible follow-up.
- No public-API changes; no behavior changes.

Spec: docs/superpowers/specs/2026-05-06-telephony-router-modularization-design.md

Closes #251.

## Test plan

- [x] pytest tests/test_telephony.py tests/test_voice.py tests/test_barge_in_helper.py tests/test_transcript_consumer.py — all green
- [x] pyflakes on the touched files — no unused imports
- [x] git diff on app/main.py — no public-surface change
- [ ] Manual smoke via dev call flow (greeting plays, barge-in works, silence prompt fires, order confirmation triggers auto-hangup)
EOF
)"
```

- [ ] **Step 5: Manual smoke (deferred to reviewer)**

Manual smoke is left for the reviewer / merger to perform on the dev environment per the spec's validation step 4. Note this in the PR test plan so it isn't forgotten.

---

## Self-review checklist

Run through this list after the plan is written. Fix issues inline.

1. **Spec coverage** — every file role and mapping row in the spec corresponds to a task step:
   - `app/twilio/media_stream.py` (`send_clear`, `send_mark`) → Task 1.
   - `app/twilio/twiml.py` (5 builders) → Task 2.
   - `app/twilio/__init__.py` (REST helpers) → Task 3.
   - `app/telephony/session.py` (everything from the spec's mapping table marked `session.py`) → Task 4.
   - `app/telephony/router.py` slimming → Task 4 step 2.
   - Test import updates → Task 4 step 3.

2. **Placeholder scan** — no "TBD", "implement later", "similar to", "add appropriate handling". All code shown verbatim. ✓

3. **Type/name consistency:**
   - `send_clear(websocket, stream_sid)` — used in Tasks 1, 4. ✓
   - `send_mark(websocket, stream_sid, name)` — used in Tasks 1, 4. ✓
   - `_CallState` — referenced in Task 4 in import lists matching the dataclass move. ✓
   - `app_twilio` import alias — Tasks 3 and 4 both use the same alias. ✓
   - `END_OF_CALL_MARK` constant — moves to `session.py` in Task 4 and is re-imported by `router.py`. ✓

4. **Order check** — Tasks 1-3 are independent of Task 4 and can land in any order, but the plan runs them first because they reduce the size of the Task 4 diff.

5. **Atomicity** — each task ends with passing tests + a commit. No half-states.
