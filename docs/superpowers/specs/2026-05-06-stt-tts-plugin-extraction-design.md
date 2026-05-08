# STT/TTS plugin extraction — design

**Branch:** `feat/83-tune-conversational-bot`
**Related issues:** #83 (tune conversational bot); a new refactor-tracking issue to be opened once this spec lands.
**Status:** Approved design; ready for implementation plan.

## Context

`app/telephony/router.py` is 1,165 lines. A 70-line block of inline Deepgram STT (`_open_deepgram_connection` and its callbacks at lines 294–362) is welded into the WS handler, with the transcript callback closing over `_CallState` and emitting Firestore events directly. TTS lives in `app/tts/client.py` — already isolated, but with an `app.storage.recordings` import leaking into the synthesis path.

The user is about to do substantial conversational-quality tuning under #83 (Nova-3 retry, keyterm prompting, endpointing tweaks, possibly more). Each tuning change in the current shape is a router-shaped diff. The goal of this work is to make those tuning changes config-shaped instead.

## Goals

- Extract Deepgram STT out of `router.py` into a focused plugin module.
- Co-locate Deepgram TTS with STT under one vendor package.
- Introduce thin abstraction layers (`app/stt`, `app/tts`) so a second provider is additive, not a refactor.
- Preserve every existing behavior. Add one user-facing improvement: instant barge-in via VAD speech-started.
- Make conversational tuning a config-flip exercise (`STT_MODEL`, `STT_KEYTERMS`, `STT_ENDPOINTING_MS`, etc.).

## Non-goals

- **Multi-provider implementation.** Deepgram only, today. Selector seam exists; second impl arrives when there's a concrete need.
- **Per-restaurant overrides.** Global env vars. Firestore stays untouched in this push.
- **Auto-reconnect on STT WS drop.** Out of scope; logged + handled via existing silence watchdog as today.
- **TTS retry on 5xx.** Unchanged from today's behavior.
- **Recording integration changes.** Recording is disabled on this branch (no `RECORDINGS_BUCKET`); the architectural seam (`on_chunk` callback) is in place but not exercised.

## Module layout

```
app/
  stt/
    __init__.py        # get_stt() selector; re-exports STTProvider, TranscriptEvent, SpeechStartedEvent
    base.py            # Protocol + event dataclasses
  tts/
    __init__.py        # speak() selector; re-exports SpeakFunc
    base.py            # SpeakFunc Protocol
  deepgram/
    __init__.py        # shared: _api_key(), _DEEPGRAM_BASE
    stt.py             # class DeepgramSTT(STTProvider)
    tts.py             # speak() — body lifted from today's app/tts/client.py
```

**Deletions:** `app/tts/client.py` (body moved to `app/deepgram/tts.py`).

**Future vendor:** `app/elevenlabs/tts.py`, `app/whisper/stt.py`, etc. — each lives at `app/<vendor>/<capability>.py`, with a one-clause add to the relevant selector in `app/stt/__init__.py` or `app/tts/__init__.py`.

## STT contract

### Event types — `app/stt/base.py`

```python
@dataclass(frozen=True)
class SpeechStartedEvent:
    """VAD detected the caller began speaking. Fires before any transcript
    is available — used for instant barge-in (~50ms vs ~800ms waiting on
    a final transcript)."""
    at: float = 0.0   # optional Deepgram timestamp; 0 if SDK omits it

@dataclass(frozen=True)
class TranscriptEvent:
    text: str
    is_final: bool
    confidence: float

STTEvent = TranscriptEvent | SpeechStartedEvent
```

### Provider Protocol

```python
class STTProvider(Protocol):
    async def open(self) -> None:
        """Open the live STT connection. Raises on failure."""

    async def send(self, audio: bytes) -> None:
        """Forward one chunk of caller audio (mulaw 8 kHz from Twilio).
        Connection-level errors are caught internally and logged; the call
        does not die on transient send failures."""

    def events(self) -> AsyncIterator[STTEvent]:
        """Yield STTEvents until close() is called. Raises on connection
        error — the consumer is responsible for catching and recovering."""

    async def close(self) -> None:
        """Tear down the connection and signal events() to terminate."""
```

### `DeepgramSTT` implementation notes

- Bridges the SDK's callback world to the iterator world via one internal `asyncio.Queue` (unbounded — final transcripts arrive at human-conversation pace; even interim volume of 5–10/sec is trivial memory).
- Subscribes to three Deepgram events: `Transcript` (interim + final), `SpeechStarted`, `Error`.
- Existing log line preserved: `logger.info("transcript [%s] call_sid=%s text=%r", label, call_sid, text)`. This is the **only** place interim transcripts are surfaced — they're intentionally not emitted to Firestore (see Observability).
- `_on_error` pushes a private `_ErrorBox` sentinel onto the queue; `events()` raises when it dequeues one.
- `close()` pushes a private `_Closed` sentinel; `events()` returns when it dequeues one.

### Configuration

Seven new settings on `app/config.py`, plus two existing. All global (no per-restaurant overrides today):

| Setting | Default | Notes |
|---|---|---|
| `STT_PROVIDER` | `"deepgram"` | Selector key |
| `TTS_PROVIDER` | `"deepgram"` | Selector key |
| `STT_MODEL` | `"nova-2"` | Clean path to retry Nova-3 |
| `STT_ENDPOINTING_MS` | `800` | Today's tuned value |
| `STT_UTTERANCE_END_MS` | `1000` | Today's tuned value |
| `STT_KEYTERMS` | `[]` | Comma-separated; only sent when non-empty; requires Nova-3 |
| `STT_INSTANT_BARGE_IN` | `True` | Kill-switch for VAD-driven barge-in |
| `DEEPGRAM_TTS_MODEL` | (existing) | Aura voice |
| `DEEPGRAM_API_KEY` | (existing) | Required |

## TTS contract

`SpeakFunc` Protocol in `app/tts/base.py` describes the callable signature. Both `app/tts/__init__.py` (selector) and `app/deepgram/tts.py` (impl) match it.

```python
class SpeakFunc(Protocol):
    async def __call__(
        self,
        text: str,
        websocket: WebSocket,
        stream_sid: str,
        *,
        client: Optional[httpx.AsyncClient] = None,
        on_chunk: Optional[Callable[[bytes], None]] = None,
        on_first_byte: Optional[Callable[[], None]] = None,
    ) -> None: ...
```

### Why a free function, not a class

TTS today is stateless per call — `speak()` opens an HTTP request, streams audio, returns. The only "state" is a process-wide `httpx.AsyncClient` for connection pooling, which is already a module-level lazy singleton. Future HTTP-based TTS providers (ElevenLabs, OpenAI TTS, Cartesia) fit the same shape. Wrapping a stateless function in a class for "consistency" with the stateful STT provider would be ceremony with no payoff. Class-based TTS arrives only when a provider with genuine cross-call state arrives.

### Recording-session decoupling

The current `recording_session` parameter is replaced by an `on_chunk: Callable[[bytes], None] | None` callback. TTS no longer imports `app.storage.recordings`. The router builds the closure that appends to the recording session via a small helper:

```python
def _make_recording_chunk_handler(state: _CallState) -> Callable[[bytes], None] | None:
    if state.recording_session is None:
        return None
    rs = state.recording_session
    def _handle(chunk: bytes) -> None:
        try:
            recordings.append_chunks(rs, b"", chunk)
        except Exception:
            logger.exception("tts: recording append failed call_sid=%s", state.call_sid)
    return _handle
```

When `RECORDINGS_BUCKET` is unset (current branch state), `state.recording_session` is `None`, the helper returns `None`, `on_chunk` isn't fired, no audio is appended anywhere. Enabling recording later is a config flip, no code changes needed.

## Router consumer + unified barge-in

### `_consume_transcripts` — the new event consumer

A background task per call. Replaces the inline `on_transcript` callback closure. State mutation, Firestore emission, and dispatch into `_handle_final_transcript` all live here, in plain top-to-bottom code.

```python
async def _consume_transcripts(
    stt: STTProvider,
    state: _CallState,
    websocket: WebSocket,
) -> None:
    try:
        async for event in stt.events():
            if isinstance(event, SpeechStartedEvent):
                if not settings.stt_instant_barge_in:
                    continue
                if state.llm_task and not state.llm_task.done():
                    await _barge_in_now(state, websocket, trigger="vad")
                continue

            # event is a TranscriptEvent
            if not event.is_final:
                continue   # interims captured in plugin logs only

            state.last_caller_transcript = event.text
            if event.confidence < 0.5:
                state.consecutive_low_confidence_turns += 1
            else:
                state.consecutive_low_confidence_turns = 0

            _bg_call_event(
                state.call_sid, _state_rid(state),
                kind="transcript_final",
                text=event.text,
                detail={"text": event.text, "confidence": event.confidence},
            )
            await _handle_final_transcript(event.text, state, websocket)

    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("transcript consumer crashed call_sid=%s", state.call_sid)
```

### `_barge_in_now` helper — one entry point for both triggers

Today's barge-in pipeline is fully built (cancel + flush + watchdog + carry-forward + Firestore event), but only triggered by final-transcript arrival (~800–1800ms after the caller starts speaking). The helper extracts the common steps so the new VAD trigger can fire the same pipeline ~50ms after speech starts.

```python
async def _barge_in_now(
    state: _CallState,
    websocket: WebSocket,
    *,
    trigger: str,
) -> None:
    """Stop the bot mid-utterance.

    Three mechanical steps:
      1. Cancel the in-flight LLM/TTS task → halt audio generation.
      2. Cancel the silence watchdog → caller is speaking; 'are you still
         there?' would be wrong.
      3. Send Twilio 'clear' → flush already-buffered audio playback (#74).

    Note: the `barge_in` Firestore event is NOT emitted here. It's emitted
    by `_run_llm_tts_turn`'s existing CancelledError handler, which fires
    when the task we just cancelled actually receives the cancellation.
    Trigger information flows via `state.barge_in_trigger`, read and
    cleared inside that handler. This preserves today's invariant that
    `barge_in` events correspond to genuine task cancellations.
    """
    state.barge_in_trigger = trigger
    if state.llm_task and not state.llm_task.done():
        state.llm_task.cancel()
    _cancel_silence_task(state)
    await clear_twilio_audio(websocket, state.stream_sid)
```

`_CallState` gains a `barge_in_trigger: str | None = None` field. `_run_llm_tts_turn`'s `CancelledError` handler is updated to read and clear it:

```python
# inside _run_llm_tts_turn
except asyncio.CancelledError:
    trigger = state.barge_in_trigger or "unknown"
    state.barge_in_trigger = None
    logger.info("llm_turn cancelled (barge-in trigger=%s) call_sid=%s",
                trigger, state.call_sid)
    _bg_call_event(state.call_sid, _state_rid(state),
                   kind="barge_in",
                   detail={"trigger": trigger})
    raise
```

### How the two barge-in paths coexist

- **Fast path:** VAD speech-started → consumer calls `_barge_in_now(trigger="vad")`. ~50ms latency.
- **Fallback path:** final transcript arrives mid-turn → `_handle_final_transcript` calls `_barge_in_now(trigger="final_transcript")` (refactored to use the helper). Catches short utterances and missed-VAD cases.

Both paths produce a single `barge_in` Firestore event (emitted by `_run_llm_tts_turn`'s `CancelledError` handler when the cancellation propagates) with `trigger` in `detail`. The previously-considered `barge_in_speech` kind is dropped — one kind, two trigger values.

### `_handle_final_transcript` after the refactor

The carry-forward (`#170`) and new-task creation stay. The cancel/flush block splits into two branches: a true barge-in (when there's a running turn to interrupt) routes through `_barge_in_now`; a silence-resume (where no turn is running, just the watchdog) cancels the watchdog and flushes Twilio directly without setting the barge-in trigger or emitting a barge_in event.

```python
async def _handle_final_transcript(text, state, websocket):
    interrupted = bool(state.llm_task and not state.llm_task.done())
    if state.in_flight_transcript.strip():
        text = f"{state.in_flight_transcript} {text}".strip()
    silence_was_active = bool(state.silence_task and not state.silence_task.done())
    _abort_pending_hangup(state)

    if interrupted:
        await _barge_in_now(state, websocket, trigger="final_transcript")
    elif silence_was_active:
        # Caller resumed after a silence prompt — flush any leftover prompt
        # audio still buffered, but this isn't a barge-in.
        _cancel_silence_task(state)
        await clear_twilio_audio(websocket, state.stream_sid)

    state.in_flight_transcript = text
    state.llm_task = asyncio.create_task(_run_llm_tts_turn(text, state, websocket))
    state.llm_task.add_done_callback(lambda _t: _arm_silence_watchdog(state, websocket))
```

This matches today's emission semantics exactly: a `barge_in` event fires for and only for an actually-cancelled in-flight turn. Silence-resume produces no `barge_in` event, same as today.

### WS handler integration

Three touch points in `media_stream`:

```python
# on "start"
state.stt, state.stt_provider = get_stt(call_sid=state.call_sid)
await state.stt.open()
state.transcript_task = asyncio.create_task(
    _consume_transcripts(state.stt, state, websocket)
)

# on "media", inbound track
await state.stt.send(payload)

# in finally
if state.transcript_task and not state.transcript_task.done():
    state.transcript_task.cancel()
if state.stt is not None:
    await state.stt.close()
```

`_CallState` gains: `stt: STTProvider | None`, `stt_provider: str | None`, `transcript_task: asyncio.Task | None`. The `dg_conn` local variable disappears.

## Error handling

| Scenario | Behavior |
|---|---|
| STT can't open | `DeepgramSTT.open()` raises; WS handler emits `error` Firestore event, logs, closes call. |
| STT WS drops mid-call | Plugin pushes `_ErrorBox` → `events()` raises → consumer logs + exits. Silence watchdog fires after 10s. |
| `stt.send()` fails | Caught inside the plugin, logged, no-op. Call continues; transcript stream may dry up briefly. |
| TTS 5xx / connection refused | Unchanged — `_run_llm_tts_turn`'s exception handler catches, logs, emits `error` event. |
| Consumer task crashes | Bare `except Exception` logs + exits. Silence watchdog handles UX. |
| Provider misconfigured | `get_stt()` raises `ValueError` at `start` event; surfaces as `error` Firestore event. |

## Observability

- **No new Firestore event kinds.** Existing kinds (`start`, `stop`, `transcript_final`, `barge_in`, `silence_timeout`, `first_audio`, `agent_reply`, `error`, etc.) cover all observable states. `barge_in` gains a `trigger` field in `detail` for future dashboard filtering.
- **Interim transcripts in logs only.** Plugin emits `logger.info("transcript [interim] call_sid=%s text=%r")`. Queryable in Cloud Logging by `call_sid` for debugging mishears. No Firestore writes.
- **Existing log lines preserved** at the same call_sid format.
- **No `provider` field on events.** Speculative until a second provider exists.

## Testing strategy

### `FakeSTT` test fixture — `tests/fakes/stt.py`

The core testing primitive. Implements `STTProvider`, exposes a `feed(event)` method to inject events mid-test, plus `feed_error(exc)` to surface errors. Tests script call flows without touching the Deepgram SDK or network.

### Existing tests that change

- `tests/test_telephony.py`: `mock_pipeline` fixture migrates from patching `_open_deepgram_connection` to injecting `FakeSTT`. Five ad-hoc patch blocks in test functions collapse into the fixture.
- `tests/test_tts_client.py` → renamed to `tests/test_deepgram_tts.py`. Logic unchanged; import paths updated; one new test for the `on_chunk` callback shape.
- `test_clear_twilio_audio_*` tests stay green (helper unchanged).

### Net-new test files

- `tests/test_fake_stt.py` — ~5 tests of the fake itself.
- `tests/test_stt_deepgram.py` — ~9 tests of `DeepgramSTT` against a faked Deepgram SDK.
- `tests/test_transcript_consumer.py` — ~9 tests of `_consume_transcripts` against `FakeSTT`.
- `tests/test_barge_in_helper.py` — ~6 tests of `_barge_in_now`.
- `tests/test_provider_selector.py` — ~4 tests of `get_stt()` / `speak()` selectors.

### Not tested

- Live Deepgram WS — covered by test calls, not pytest.
- Twilio Media Stream protocol — already mocked in existing tests.
- Test-call call quality — human-in-the-loop, not automatable.

## Migration plan

### Phase α — extraction (7 atomic commits, each green)

1. **α-1** `feat(stt): add STTProvider protocol and event dataclasses` — `app/stt/base.py`, `app/tts/base.py`. Pure type definitions.
2. **α-2** `test(stt): add FakeSTT fixture for offline testing` — `tests/fakes/stt.py` + tests of the fake.
3. **α-3** `refactor(tts): move Deepgram TTS to app/deepgram/tts.py` — TTS body relocates; `app/tts/client.py` deleted; `recording_session` → `on_chunk`; 5 call sites switched.
4. **α-4** `feat(stt): implement DeepgramSTT plugin` — `app/deepgram/{__init__.py,stt.py}`. Not wired into router yet.
5. **α-5** `refactor(telephony): extract _barge_in_now helper` — helper introduced; `_handle_final_transcript` updated to call it (behavior identical).
6. **α-6** `feat(telephony): replace inline Deepgram with STTProvider` — wire `get_stt()` + `_consume_transcripts`; remove `_open_deepgram_connection`; migrate `mock_pipeline` fixture.
7. **α-7** `feat(telephony): instant barge-in via VAD speech-started` — subscribe `SpeechStarted`; consumer calls `_barge_in_now(trigger="vad")`; add `STT_INSTANT_BARGE_IN` kill-switch.

After α-7: structural extraction complete. Bot behavior identical to today **except** instant barge-in is on. First test call should sound the same but pause faster on interruption. If VAD misfires on real audio, `STT_INSTANT_BARGE_IN=False` reverts.

### Phase β — tuning (open-ended, judged by test calls)

Cheap iterations now that everything is config-driven:

| Knob | What changes |
|---|---|
| `STT_MODEL=nova-3` | Retry the reverted #199 model bump |
| `STT_KEYTERMS=...` | Send menu vocabulary (Nova-3) |
| `STT_ENDPOINTING_MS=600` (or 1000) | Trade responsiveness vs. mid-sentence false-finals |
| `STT_INSTANT_BARGE_IN=False` | Disable VAD trigger if twitchy |
| `DEEPGRAM_TTS_MODEL=...` | Try a different Aura voice |

Anything bigger than a config flip lands as its own α-style commit on the same branch.

### Rebase cadence

Rebase onto `master` weekly, more often if Dependabot churn or someone touches `app/telephony/router.py` / `app/storage/recordings.py` on master. Standard `git fetch && git rebase origin/master` once α-1 commits exist.

### Test-call discipline

- After α-3 (TTS moved): test call.
- After α-6 (STT moved): test call. Confirm transcripts flow, final-transcript barge-in works.
- After α-7 (instant barge-in): test call. Deliberately interrupt mid-bot-sentence; confirm bot stops in <500ms.
- After every β iteration: test call.

Recording stays off the whole branch.

### Merge criteria

1. All pytest tests green.
2. Pre-commit hooks pass.
3. Three consecutive clean test calls demonstrating the conversational quality goal of #83.
4. Master rebase clean.
5. Spec doc and PR description reference both #83 and the new refactor issue.

One fat PR at the end. PR description structures α (extraction list) separately from β (behavior changes).

## Risks

- **VAD false positives.** Background noise, coughs, or echo could trip speech-started and audibly cut the bot off mid-word. Mitigation: `STT_INSTANT_BARGE_IN=False` env var. If persistent, follow-up work adds "require interim transcript within N ms after speech-started before committing."
- **Long-lived branch drift.** Without weekly rebases, the eventual merge becomes a 100-commit reconciliation. Today's 28-behind rebase was painless; an 8-week-behind rebase with deps + CI rule churn won't be.
- **Recording over-representation when re-enabled** (pre-existing limitation): outbound TTS chunks get appended to the recording at send-time, but `clear_twilio_audio` may flush some before they play. Recording slightly over-represents the bot's actual playback. Acceptable today; documented for when recording comes back online.

## Deferred work

- Per-restaurant STT/TTS overrides (Firestore-backed).
- Auto-reconnect on STT WS drop.
- TTS retry on 5xx.
- Structured logging migration.
- Speculative LLM warm-up on stable interim transcripts.
- VAD-false-positive guard ("require interim within N ms").
- Live-call-watching dashboard view (would resurface interim Firestore emission).

## Open questions

None at design-approval time.
