# Telephony router modularization

**Issue:** [tsuki-works/niko#251](https://github.com/tsuki-works/niko/issues/251)
**Branch:** `refactor/251-telephony-router-split`
**Base:** `feat/83-tune-conversational-bot` — this refactor depends on the STTProvider extraction and instant-barge-in work landing first. The 1293-line `router.py` analysed below is the post-feat/83 file. PR target should be feat/83 (or master once feat/83 merges).
**Type:** Structural refactor — no behavior change.

## Problem

`app/telephony/router.py` is 1293 lines and mixes ~10 concerns in one file:

- TwiML HTTP endpoints (`/voice`, `/voice/stream-ended`, `/voice/transfer-result`, `/voice/voicemail-recorded`, `/voice/voicemail-transcription`)
- The `/media-stream` WebSocket event loop (start/media/mark/stop dispatch)
- `_CallState` dataclass
- LLM-turn streaming + chunking (`_run_llm_tts_turn`, `_should_flush_chunk`, hard/soft break thresholds)
- STT consumer (`_consume_transcripts`)
- Auto-hangup machinery (mark-echo, grace window, timeout fallback)
- Barge-in (`_barge_in_now`)
- Silence watchdog
- Twilio-specific WS protocol primitives (`clear_twilio_audio`, `send_end_of_call_mark`)
- Goodbye-detection heuristic + Firestore-event helper

Recent telephony work (#170, #151, #114, #78, #74, instant barge-in via VAD) is being delivered into a single increasingly-tangled file. Reading or editing any one concern requires scrolling through the others.

## Goal

Split the file along its real boundary — vendor-specific Twilio I/O vs vendor-neutral call orchestration — without introducing new abstractions and without changing behavior.

## Non-goals

- **No `TelephonyProvider` ABC.** Single-vendor today; designing an abstraction against one concrete is a guess. The interface emerges when a second provider arrives.
- **No `CallSession` class refactor.** Possible follow-up; out of scope here. `_CallState` stays a dataclass; the orchestration helpers stay as module-level functions taking `(state, websocket, ...)`.
- **No public-API changes.** FastAPI endpoint paths, params, and response shapes unchanged.
- **No behavior changes.** Existing tests pass without modification beyond import-path updates.
- **No decorative fragmentation.** Two-line helper modules (`turn.py`, `events.py`) explicitly rejected during brainstorming. Pure helpers live next to the code that uses them.

## Proposed structure

```
app/telephony/
  router.py            # FastAPI endpoints + WS event-loop only
  session.py           # _CallState + all orchestration helpers
  voicemail_twiml.py   # existing — unchanged
  transfer_triggers.py # existing — unchanged

app/twilio/
  __init__.py          # exports + Twilio REST recording fetch
  twiml.py             # TwiML response builders
  media_stream.py      # send_clear, send_mark — outgoing WS protocol primitives
```

### File roles

**`app/telephony/router.py`** (~250 lines)
FastAPI endpoint shells. Each HTTP handler parses the form, calls a TwiML builder from `app/twilio/twiml.py`, returns `Response`. The `/media-stream` WS handler runs the start/media/mark/stop dispatch loop and the cleanup `finally`, delegating per-event work to functions in `session.py`. No call orchestration logic here, no TwiML XML construction here.

**`app/telephony/session.py`** (~800 lines)
The bulk of today's `router.py` minus the FastAPI shells and Twilio I/O:

- `_CallState` dataclass
- Chunking constants + `_should_flush_chunk`
- Goodbye constants + `_looks_like_goodbye`
- `_bg_call_event` + `_state_rid`
- `_make_recording_chunk_handler`
- Silence watchdog: `_silence_watchdog`, `_cancel_silence_task`, `_arm_silence_watchdog`
- Auto-hangup: `_hang_up_after_grace`, `_hang_up_after_mark_timeout`, `_abort_pending_hangup`
- Barge-in: `_barge_in_now`
- Transcript consumer: `_consume_transcripts`
- LLM turn: `_run_llm_tts_turn`, `_handle_final_transcript`
- `_resolve_restaurant_for_voice`

Helpers continue to take `(state, websocket, ...)`. They call into `app/twilio/media_stream.py` (`send_clear`, `send_mark`) instead of writing JSON envelopes inline.

**`app/twilio/__init__.py`** (~40 lines)
Re-exports the public Twilio surface (`twiml`, `media_stream`). Holds `download_recording(url, account_sid, auth_token)` for `/voice/voicemail-recorded` — small enough that a dedicated `recordings.py` would be ceremony.

**`app/twilio/twiml.py`** (~120 lines)
Pure functions returning `VoiceResponse` (or its `str`-encoding):

- `voice_twiml(restaurant, ws_host)` — `<Connect><Stream>` with `restaurant_id` parameter
- `unconfigured_hangup_twiml()` — "this number is not configured"
- `closed_hangup_twiml()` — "we're closed; call back during business hours"
- `transfer_twiml(fallback_phone, call_sid, rid)` — `<Dial>` with action callback
- `empty_twiml()` — empty `VoiceResponse()` for hangup paths

No side effects, easy to snapshot-test. `router.py` imports from here.

**`app/twilio/media_stream.py`** (~80 lines)
The two outgoing Twilio Media Stream WS frames that today live as inline `websocket.send_json` calls in `router.py`:

- `send_clear(websocket, stream_sid)` — flush Twilio's audio buffer (#74)
- `send_mark(websocket, stream_sid, name)` — append a named mark for buffer-drain detection (#78)

Both are tiny but capture the only outgoing Twilio-shaped JSON literals. `session.py`'s `_barge_in_now` and `_run_llm_tts_turn` import from here. Incoming events (`start`, `media`, `mark`, `stop`) stay parsed inline in `router.py`'s WS handler — typed wrappers are speculative until a second provider forces a real shape difference.

## Mapping (where each thing moves)

| Current (`router.py`) | Destination |
|---|---|
| `SILENCE_TIMEOUT_SECONDS`, `SILENCE_PROMPT`, `GREETING_TRANSCRIPT` | `session.py` |
| `END_OF_CALL_MARK`, `HANGUP_GRACE_SECONDS`, `MARK_ECHO_TIMEOUT_SECONDS` | `session.py` |
| `_HARD_BREAKS`, `_SOFT_BREAKS`, `_MIN_CHUNK_CHARS`, `_should_flush_chunk` | `session.py` |
| `_GOODBYE_PATTERNS`, `_looks_like_goodbye` | `session.py` |
| `_bg_call_event`, `_state_rid` | `session.py` |
| `_CallState` | `session.py` |
| `_make_recording_chunk_handler` | `session.py` |
| `_silence_watchdog`, `_cancel_silence_task`, `_arm_silence_watchdog` | `session.py` |
| `_hang_up_after_grace`, `_hang_up_after_mark_timeout`, `_abort_pending_hangup` | `session.py` |
| `_barge_in_now` | `session.py` |
| `_consume_transcripts` | `session.py` |
| `_run_llm_tts_turn`, `_handle_final_transcript` | `session.py` |
| `_resolve_restaurant_for_voice` | `session.py` |
| `clear_twilio_audio` (rewritten) | `app/twilio/media_stream.py` as `send_clear` |
| `send_end_of_call_mark` (rewritten) | `app/twilio/media_stream.py` as `send_mark` |
| TwiML construction in `voice` / `stream_ended` / `transfer_result` / voicemail handlers | `app/twilio/twiml.py` |
| Twilio REST recording download in `voicemail_recorded` | `app/twilio/__init__.py` (`download_recording`) |
| `@router.post("/voice")` and the four other HTTP endpoints | `router.py` (shells only) |
| `@router.websocket("/media-stream")` event-loop body | `router.py` (still the dispatch shell, calls into `session.py`) |
| `_TRANSFER_STATUS_MAP`, `_UNCONFIGURED_TWIML_MESSAGE` | Move with the consumer (status map → `router.py`; message → `app/twilio/twiml.py`) |

## Test impact

Current tests that import internals (verified on `feat/83-tune-conversational-bot`):

- `tests/test_telephony.py`: `from app.telephony.router import _MIN_CHUNK_CHARS, _should_flush_chunk`
- `tests/test_barge_in_helper.py`: `from app.telephony.router import _CallState, _barge_in_now`
- `tests/test_transcript_consumer.py`: `from app.telephony.router import _CallState, _consume_transcripts`

All three update from `app.telephony.router` to `app.telephony.session`. No test logic changes.

`tests/test_voice.py` exercises `/voice` via TestClient — public surface unchanged, no edits expected.

## Risk + validation

**Risk:** low–medium. Mechanical move; strong existing coverage (`tests/test_telephony.py` 1892 lines, plus targeted barge-in / transcript-consumer / voice tests). Recent active tuning (instant-barge-in via VAD just landed) means the diff lands near hot code — care needed to avoid an accidental rebase conflict on whoever's iterating next.

**Validation:**

1. Full pytest suite passes with import paths updated.
2. `pytest tests/test_telephony.py tests/test_barge_in_helper.py tests/test_transcript_consumer.py tests/test_voice.py -v` — telephony-focused subset green.
3. Diff review: every moved function moved verbatim (no logic edits hidden in the move).
4. Manual smoke via the dev call flow (one inbound test call, listen for: greeting plays, barge-in works, silence prompt fires, order confirmation triggers auto-hangup).

## Out of scope (deliberate)

- `CallSession` class refactor — possible follow-up issue.
- `TelephonyProvider` ABC — wait for vendor #2.
- Splitting `session.py` into finer modules (`turn.py`, `events.py`, `hangup.py`, etc.) — rejected as decorative during brainstorming. Revisit if `session.py` becomes hard to navigate after this lands.
- Typed wrappers around incoming Twilio WS events (`StartFrame`, `MediaFrame`, etc.) — speculative; defer.
- Moving SMS Twilio code (`app/sms/client.py`) into `app/twilio/`. Unrelated to the router refactor; do separately if at all.
