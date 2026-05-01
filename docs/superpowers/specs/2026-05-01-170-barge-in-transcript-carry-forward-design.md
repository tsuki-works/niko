# Barge-In Transcript Carry-Forward (Design Spec)

**Date:** 2026-05-01
**Sprint:** 2.1 — Tuning conversational bot (#83)
**Tracking issue:** #170
**Status:** Approved (incorporates niko-reviewer feedback)
**Base commit:** `3daa211` (master)

## Goal

Stop silently dropping the caller's words when one final transcript arrives during the LLM phase of the previous turn. Two utterances ~1s apart must reach Haiku as one combined turn so the order captures both items.

## Bug

Real customer-impact regression on call `CAb1db16747ce2abb65d04c498e2b371ae` (2026-05-01 20:38:23). The caller said:

```
20:38:44  CALLER     i'll get one chicken fried rice
20:38:44  LLM_TURN   i'll get one chicken fried rice
20:38:45  CALLER     and a coke
20:38:45  LLM_TURN   and a coke
20:38:45  BARGE_IN
20:38:48  AGENT      Got it, one Coke. What size...
```

The chicken fried rice ($12.25) was silently dropped. The order was confirmed at $1.77 (one can of Coke) instead of the expected ~$13.99.

## Root cause

`_handle_final_transcript` in `app/telephony/router.py:589` cancels any in-flight LLM task whenever a new final transcript arrives. The cancel is correct policy — we don't want to keep streaming a now-stale reply — but the cleanup is incomplete.

`state.history` is updated **only** when the LLM turn yields `event.final` (`router.py:520`):

```python
elif event.final is not None:
    ...
    state.history = event.final.history
```

`asyncio.CancelledError` jumps over that branch, so the cancelled turn's user message — which `stream_reply` already appended internally via `_append_user_transcript` — never makes it back to `state.history`. The next turn fires with the new transcript only and a stale history.

The barge-in event itself (`router.py:573`) is just the receipt: `_run_llm_tts_turn`'s `except CancelledError` handler writes `kind="barge_in"` to the call session. It records that a cancel happened; it does not decide anything.

## Approach

**Carry the cancelled turn's transcript forward** on `_CallState`. On the next final transcript, prepend the carried text before spawning the new LLM turn. Clear the carry-forward when a turn completes successfully (the user message is now in `state.history`).

All changes are contained in `app/telephony/router.py`. No changes to `app/llm/client.py`, `stream_reply`, or history serialization.

### Why carry-forward over the alternatives

- **Eager-write to `state.history` in `_handle_final_transcript`** (issue's "Option B"): semantically cleaner — history reflects what the caller said the moment they say it. Touches `app/llm/client.py` to teach `stream_reply` an "already in history" path. Bigger blast radius for a sprint reliability fix; deferred.
- **STT-layer debounce** (bumping Deepgram `endpointing` / `utterance_end_ms`, or adding an application-level hold timer): adds latency to every reply on a sprint chasing latency targets. Doesn't fix correctness — only reduces the incidence of multi-final bursts. Out of scope.
- **Application-level debounce before firing the LLM** (cost optimization to collapse cancel storms into one turn): trades latency for token savings. Cancel storms are rare and cheap (~$0.001-0.005 per storm with prompt caching). Not worth +300ms on every reply.

### Why not address the cancel itself

The cancel is load-bearing. Issue #74 added barge-in deliberately so the agent stops talking when the caller speaks again. Delaying or skipping cancellation:

- Adds latency to genuine corrections ("wait, no, make that two").
- Still misses the case where cancel happens after first_audio (caller corrects mid-reply).
- Replaces one race condition with another.

The bug is in cleanup-on-cancel, not in the cancel decision.

## Detailed design

### State

`_CallState` (`router.py:270`) gains one field, placed at the end of the dataclass alongside the other Sprint 2.4 transfer-trigger accumulators:

```python
in_flight_transcript: str = ""
```

Holds the most recent transcript that was fed to an LLM turn but has not yet been persisted to `state.history`. Cleared after `event.final`.

### `_handle_final_transcript`

```python
async def _handle_final_transcript(text, state, websocket):
    interrupted = bool(state.llm_task and not state.llm_task.done())
    if interrupted:
        state.llm_task.cancel()
    # Carry forward — if any prior turn (cancelled or errored) left a
    # transcript on state without persisting it to history, prepend it.
    # The field is cleared by _run_llm_tts_turn only on event.final, so
    # a non-empty value here always means "user words from a prior turn
    # that never made it into history."
    if state.in_flight_transcript.strip():
        text = f"{state.in_flight_transcript} {text}".strip()
    silence_was_active = bool(state.silence_task and not state.silence_task.done())
    _cancel_silence_task(state)
    _abort_pending_hangup(state)
    if interrupted or silence_was_active:
        await clear_twilio_audio(websocket, state.stream_sid)
    state.in_flight_transcript = text
    state.llm_task = asyncio.create_task(
        _run_llm_tts_turn(text, state, websocket)
    )
    state.llm_task.add_done_callback(
        lambda _t: _arm_silence_watchdog(state, websocket)
    )
```

The carry-forward read is **unconditional on `interrupted`**. The original draft only read `in_flight_transcript` when cancelling, but that left a gap: if the prior turn errored (Anthropic 5xx, network drop) instead of being cancelled, `state.llm_task.done() == True`, `interrupted == False`, and the user's words from the errored turn were silently dropped on the next final — same failure mode #170 was meant to fix, just on a different code path. Reading the field unconditionally closes that gap. The `.strip()` guard is defense-in-depth against any future caller passing a whitespace-only string.

### `_run_llm_tts_turn`

The `event.final` branch (`router.py:503-520`) clears the carry-forward immediately after `state.history` is updated:

```python
elif event.final is not None:
    ...
    state.history = event.final.history
    state.order = event.final.order
    state.in_flight_transcript = ""
    ...
```

That ordering matters: the clear must be paired with the history write. If the turn is cancelled, `CancelledError` propagates before this branch, and `in_flight_transcript` survives — exactly what we want.

## Behavior — examples

### Single utterance, turn completes (today's happy path)

```
T1 "i want fries"           → in_flight_transcript = "i want fries"
turn 1 completes (final)    → state.history += [user="i want fries", assistant=...]
                            → in_flight_transcript = ""
T2 "and a coke" arrives     → spawn turn 2 with text="and a coke" (no prefix)
```

### Two utterances, second cancels first (the #170 bug)

```
T1 "chicken fried rice"     → in_flight_transcript = "chicken fried rice"
                            → spawn turn 1
T2 "and a coke" arrives     → cancel turn 1 (BARGE_IN logged)
                            → text = "chicken fried rice and a coke"
                            → in_flight_transcript = "chicken fried rice and a coke"
                            → spawn turn 2 with combined text
turn 2 completes (final)    → state.history += [user="chicken fried rice and a coke", assistant=...]
                            → in_flight_transcript = ""
```

### Chained cancels (rapid 3-utterance burst)

```
T1 "chicken fried rice"     → in_flight = "chicken fried rice"
T2 "and a coke"             → cancel; in_flight = "chicken fried rice and a coke"
T3 "and fries"              → cancel; in_flight = "chicken fried rice and a coke and fries"
caller pauses               → turn 3 completes; history captures full intent
```

### Greeting interruption

```
WS handler spawns greeting turn directly; in_flight_transcript stays "".
T1 "hi i want fries"        → cancel greeting turn (BARGE_IN logged)
                            → in_flight_transcript was empty, so prefix is blank
                            → spawn turn 1 with text="hi i want fries"
```

## Edge cases

- **Tool-result merge boundary.** `stream_reply` still calls `_append_user_transcript` once per turn with the (possibly combined) transcript. The synthetic `user:[tool_result]` merge path in `app/llm/client.py:227-250` is unaffected.
- **Whitespace.** `f"{a} {b}".strip()` collapses adjacent spaces; empty `in_flight_transcript` short-circuits with `if state.in_flight_transcript`.
- **Cancel + completion race.** asyncio cancellation is delivered at the next `await`. Once `cancel()` is called, the `event.final` branch cannot run, so the clear is skipped on cancelled turns. Carry-forward survives cancellations by construction.
- **Greeting transcript marker.** `GREETING_TRANSCRIPT = "[call started — greet the caller]"` (`router.py:45`) is spawned directly in the WS `start` handler, bypassing `_handle_final_transcript`. We do **not** set `in_flight_transcript` for the greeting. If the caller barges in on the greeting, the cancel happens but the carry-forward is empty (matching today's behavior — the greeting marker should not bleed into the caller's first utterance).
- **Voicemail / transfer turns.** Sprint 2.4 Track 2 added voicemail-prompt and transfer-trigger spawn paths. These do not call `_handle_final_transcript`; they fire after the call session ends or via dedicated `<Connect>` redirects. They neither read nor write `in_flight_transcript`, so the carry-forward state is irrelevant to them.

## Tests

New cases in `tests/test_telephony.py`. The existing `mock_pipeline` fixture patches `_open_deepgram_connection`, `speak`, and `stream_reply`, so all of these run in-process.

1. **`test_call_state_has_in_flight_transcript_field`** — Dataclass shape regression: `_CallState()` exposes `in_flight_transcript` defaulting to `""`.
2. **`test_cancelled_turn_transcript_carried_forward`** — Drive `_handle_final_transcript` with T1, then T2 before turn 1 completes; assert `_run_llm_tts_turn` is invoked the second time with text containing both T1 and T2. (The #170 bug repro.)
3. **`test_chained_cancels_accumulate_transcripts`** — Three rapid finals, each cancelling the prior turn; assert the third turn is invoked with all three concatenated.
4. **`test_run_llm_tts_turn_clears_in_flight_transcript_on_final`** — Drive `_run_llm_tts_turn` with a fake `stream_reply` that yields `event.final` immediately; assert `state.in_flight_transcript` is cleared when the turn completes.
5. **`test_errored_turn_carries_transcript_forward`** — Spawn a turn whose `_run_llm_tts_turn` raises; assert `in_flight_transcript` is preserved across the error and prepended to the next final transcript.
6. **`test_whitespace_only_in_flight_transcript_is_not_prepended`** — Manually seed `in_flight_transcript` to whitespace; assert the next turn fires with only the new text (no leading whitespace).

Existing tests (full call lifecycle, hangup grace, mark-echo, silence watchdog, sentence-streaming chunking) should remain green untouched.

## Acceptance criteria (from #170)

- [x] Two utterances within 1-2s of each other reach Haiku as one combined message — covered by test 2.
- [x] Order item from the first utterance is captured even when the second utterance barges in — covered by test 2's combined-text assertion.
- [x] Existing barge-in mid-spoken-reply still works — the cancel path is unchanged; only its cleanup adds carry-forward. Existing barge-in semantics are preserved.
- [x] Tests in `tests/test_telephony.py` cover both barge-in scenarios.

## Out of scope (per #170)

- **Deepgram endpointing / `utterance_end_ms` tuning.** Possible follow-up if telemetry shows multi-final bursts are common.
- **Application-level debounce.** Cost optimization, not correctness.
- **Preserving partial agent replies on cancel.** Today's behavior is to drop the partial reply; #170 does not change that.
- **"Are you finished?" probe** before responding to short transcripts.

## Telemetry / follow-ups

- The existing `barge_in` Firestore event already records each cancellation. After this PR ships, we can query the call_sessions collection to see how often barge-ins coincide with the carry-forward path, and whether cancel storms (≥3 cancels in <2s) are common enough to motivate a debounce or endpointing tweak.
- No new telemetry is added in this PR — keep the surface minimal.
- **Pre-existing concurrency gap** flagged during review: `_handle_final_transcript` is dispatched fire-and-forget from `Deepgram.on_transcript` (router.py: `loop.create_task(on_final(text))`), so two finals arriving sub-event-loop-quantum (~10ms) can produce concurrent handlers and corrupt `state.llm_task` and (now) `state.in_flight_transcript`. This PR does not introduce the race — the existing `state.llm_task` reassignment is already exposed — but a follow-up issue should track serializing `_handle_final_transcript` (an `asyncio.Lock` on `_CallState`, or a single-consumer queue) before any future barge-in tightening lands.
