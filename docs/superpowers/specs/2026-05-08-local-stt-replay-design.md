# Local Caller-Audio Dump + STT Replay Tool — Design

**Date:** 2026-05-08
**Author:** Sandeep (with Claude)
**Status:** Design — pending implementation plan
**Related:** `docs/superpowers/specs/2026-05-06-deepgram-flux-stt-investigation.md`

---

## Problem

A real call on 2026-05-08 (`CA4fe24cdd06641e1cc0d7e4a81514c60d`) showed Deepgram Flux mis-transcribing the caller's opening utterance:

| Caller said | Flux returned |
|---|---|
| "Can I place an order for pickup?" | `"I cannot place an order for pickup."` |

The LLM and downstream pipeline behaved correctly given that bad input — the failure is in STT. A second attempt at the same phrase later in the same call transcribed correctly, suggesting the bug is sensitive to first-turn conditions (cold-start audio, weak language-model prior on common ordering phrasing, possible TTS-tail bleed).

This is the same class of error already documented in the 2026-05-06 Flux investigation ("coke" → "smoke", "pepper shrimp" → "pepper soup"): the open-domain English LM picks a more frequent everyday phrase over the restaurant-context interpretation.

We have one data point. Before changing production STT, we need a way to:
1. Capture caller audio from real local calls in a format we can re-feed to Deepgram.
2. Sweep that audio through multiple STT configurations (model + keyterms) and compare outputs side-by-side.

GCS-uploaded recordings exist but are gated by IAM that the local dev box doesn't have. The fastest iteration loop is local capture → local replay.

## Goals

- Capture inbound (caller-side) audio from a live local call to a local file, in a format byte-for-byte compatible with Deepgram's streaming input.
- Provide a CLI replay tool that streams a captured file through Deepgram with configurable model + keyterms and prints transcripts.
- Support a sweep mode that runs the same audio through N model+keyterm configurations and prints a comparison table.
- Stay **local-dev-only**. No production behavior change. No PII surface in shared infra.

## Non-goals

- Production capture, retention, or playback. Existing GCS recording path remains the production answer.
- Capturing the agent (outbound) audio. The bug is in caller-side recognition.
- Choosing a fix for the Flux misrecognition. This spec builds the measuring instrument; the fix is decided from data in a separate PR.
- Reviving the v1 (Nova) STT in production. Replay talks to Deepgram directly without touching the production STT class.

## Architecture

Three pieces:

### 1. `app/dev/audio_dump.py` (new module)

Pure-function module that owns the local-dump file lifecycle.

```python
def open_caller_dump(call_sid: str) -> Optional["CallerAudioDump"]: ...

class CallerAudioDump:
    def append(self, mulaw_bytes: bytes) -> None: ...
    def close(self) -> None: ...
```

- `open_caller_dump` returns `None` when `settings.niko_local_audio_dump_dir` is empty/unset (production default).
- When set, it ensures the directory exists and opens an append-mode file at `{dir}/{call_sid}_{started_at_iso}.ulaw`.
- All filesystem failures (permission, disk full, bad path) are caught and logged at WARNING. The function returns `None` on failure — never raises into the call loop.
- File format: **raw mulaw 8 kHz, no header**. Same bytes Twilio's media events deliver and Flux's `send_media` consumes. Replay is byte-for-byte forward — no encode/decode in the testing loop.

### 2. Wire-in: `app/telephony/router.py`

Three additions, all gated on `state.caller_dump is not None`:

- On `start` event, after `state.call_sid` is resolved: `state.caller_dump = open_caller_dump(state.call_sid)`.
- On `media` event with `track == "inbound"`: `state.caller_dump.append(payload)`.
- In WS finally block, before STT close: `if state.caller_dump: state.caller_dump.close()`.

`_CallState` gets one new field: `caller_dump: Optional["CallerAudioDump"] = None`.

### 3. `scripts/replay_stt.py` (new CLI)

Standalone diagnostic tool. Talks to Deepgram directly via `AsyncDeepgramClient`, **does not import `app.deepgram.stt`**. Production STT path is untouched.

CLI surface:

```
python scripts/replay_stt.py PATH.ulaw [options]

Options:
  --model {flux-general-en,nova-2,nova-3-general}   default: flux-general-en
  --keyterms term1,term2,...                        default: empty (open-domain)
  --pace {realtime,fast}                            default: realtime
  --sweep CONFIG.json                               run a config matrix
```

Single-config mode dispatches based on `--model`:
- `flux-general-en` → `listen.v2.connect`, translate `TurnInfo` events
- `nova-2` / `nova-3-general` → `listen.v1.connect`, translate `Results` / `UtteranceEnd` events

Both code paths print interim and final transcripts to stdout as they arrive, then send close-stream and drain the final EOT/utterance-end before exiting.

`--pace realtime` sleeps 20 ms between 160-byte frames (matches a live call, exercises Flux's prosody-aware turn detection accurately). `--pace fast` blasts as fast as the socket accepts (faster iteration when only the final transcript matters).

Sweep mode reads a JSON file with N configurations and runs each against the same audio file:

```json
[
  {"model": "flux-general-en", "keyterms": []},
  {"model": "flux-general-en", "keyterms": ["Niko's Pizza"]},
  {"model": "flux-general-en", "keyterms": ["Niko's Pizza", "pickup", "delivery", "Can I"]},
  {"model": "nova-2", "keyterms": []},
  {"model": "nova-3-general", "keyterms": ["Niko's Pizza", "pickup"]}
]
```

Output is a single comparison table: model, keyterms (count), first final transcript, confidence. Full per-utterance transcripts available with `--verbose`.

## Configuration

One new field in `app/config.py:Settings`:

```python
niko_local_audio_dump_dir: Optional[str] = None
```

Mirrors the existing `niko_dev_endpoints` dev-only-flag pattern. Empty/unset → feature dormant. Recommended local value: `./dev_recordings`.

`.env` documentation gets one new line. No production env changes.

## Gitignore

Add `dev_recordings/` to `.gitignore`. The env var owns the actual path; this just covers the suggested default.

## Tests

`tests/test_audio_dump.py` (new):
- `open_caller_dump` returns `None` when env unset.
- `open_caller_dump` returns a writer when env set; subsequent `append` writes bytes verbatim; `close` closes the file.
- Non-existent directory is created on first open.
- Permission denied path (or any IOError) returns `None` and logs — does not raise.

No tests for `scripts/replay_stt.py`. It's a thin imperative wrapper around Deepgram + file I/O; manual exercise on a real recording is the verification.

Existing telephony tests already cover the WS handler. Confirm the new dump branch doesn't break them; add one test case where `caller_dump` is set and verify `append` is called for inbound media events.

## Failure modes and behavior

- Disk full / permission denied during `append`: catch, log at WARNING, set an internal `broken=True` flag, no-op subsequent appends. The call continues normally.
- `niko_local_audio_dump_dir` points at a path that's a file (not a directory): caught at `open_caller_dump`, returns `None`.
- WS handler crashes mid-call: the WS finally block calls `caller_dump.close()`; the file is left at whatever bytes were flushed. Partial files are still replayable.
- Replay script API key missing: fail loud (`SystemExit` with a clear message). It's a dev tool; no fallback behavior.

## What this enables (the iteration loop)

1. Set `NIKO_LOCAL_AUDIO_DUMP_DIR=./dev_recordings` in local `.env`.
2. Make a local test call. A `.ulaw` file appears in `dev_recordings/`.
3. Run `scripts/replay_stt.py dev_recordings/<file>.ulaw --sweep configs/stt_first_turn.json`.
4. Read the comparison table. Whichever (model, keyterms) configuration recovers the correct transcript with the highest confidence is the candidate fix.
5. The followup PR is *one of*:
   - Add ordering-phrase keyterms to `app/restaurants/keyterms.py` (cheap, stays on Flux).
   - Reopen the Flux migration decision and restore Nova in production (bigger, needs a separate spec).

Both are explicitly out of scope for this spec.

## Out of scope / explicit deferrals

- Capturing or replaying outbound (agent) audio. Doable with a parallel `outbound_dump`, but not needed for this bug.
- Production audio capture path. The GCS recording path is the production answer; we don't replicate it locally.
- A diff-mode CLI flag (`--expected "..."`) that pass/fails the script for CI. Possible follow-up if we ever want to lock first-turn behavior into CI.
- A web UI for visualizing sweep results. Stdout table is enough for the immediate diagnostic loop.
