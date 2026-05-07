# Deepgram Flux STT Migration — Design

**Date:** 2026-05-06
**Author:** Sandeep (with Claude)
**Status:** Spec — ready for plan-writing
**Companion doc:** [`2026-05-06-deepgram-flux-stt-investigation.md`](./2026-05-06-deepgram-flux-stt-investigation.md) (research summary)

---

## Summary

Migrate live STT from Deepgram Nova-2 to Deepgram Flux English mono (`flux-general-en`) with per-tenant keyterm prompting computed from each restaurant's menu. Hard cutover — no Nova-2 fallback path is preserved. Bundled with `numerals=true`. `smart_format` stays off.

Flux's prosody-aware turn detection replaces Nova-2's silence-based endpointing, dropping confirmed-final transcript latency from 800–1800ms to ~260ms. Keyterm prompting (silently no-op'd on Nova-2) becomes the mechanism that fixes anecdotal misrecognitions like "coke→smoke" and "pepper shrimp→pepper soup."

The existing `STTProvider` protocol in `app/stt/base.py` is widened with two new vendor-neutral event types (`EarlyTurnEndEvent`, `TurnResumedEvent`) so Flux's speculation signals are exposed through the seam — but **this PR's consumer drops them.** Speculative LLM drafting on `EarlyTurnEndEvent` is a separate follow-up PR (see "Out of scope").

## Goals

1. Eliminate the menu-vocabulary recognition gap on Twilight calls.
2. Replace Nova-2 (no published forward roadmap) with a current-tier Deepgram model.
3. Reduce confirmed-final transcript latency.
4. Ship a vendor-neutral protocol shape that scales to a future Whisper or other provider.

## Non-goals

- Speculative LLM drafting on `EarlyTurnEndEvent` / cancellation on `TurnResumedEvent`. Events are exposed; consumer ignores them.
- Dashboard-driven keyterm editing.
- Persisting computed keyterms to Firestore.
- `smart_format=true` rollout.
- Word-level timestamps, diarization, redaction, pre-recorded Listen API.
- Voice Agent API (rejected in the investigation — conflicts with our menu validation + order state machine).
- Multi-tenant token-budget squeeze (no live tenant exceeds 500 tokens; revisit when one does).

## Settled design decisions

Each links back to a question debated during brainstorming.

| # | Decision | Why |
|---|---|---|
| D1 | **Hard cutover.** Replace `app/deepgram/stt.py` outright; delete Nova-2 model selection. Revert path is `git revert`. | Nova-2 is a dead end; one live tenant; 4-person team — dual-provider maintenance cost outweighs A/B safety. |
| D2 | **Migration + `numerals=true`.** `smart_format=false`. | Numerals are zero-risk for our pipeline (LLM handles either form natively). `smart_format` reshapes more transcript surface and offers no measurable benefit since we don't regex-parse transcripts. |
| D3 | **In-memory keyterm computation at call-open.** Pure function `compute_keyterms(menu, restaurant_name) -> list[str]`; result is logged then handed to Flux's `connect(keyterm=[...])`. No Firestore field, no menu schema change. | Persistence is only valuable when something else reads it; nothing does today. The dashboard PR that introduces an editor is the right place to introduce the schema. |
| D4 | **Auto-detect heuristic in code, no per-item menu tags.** Restaurant name is auto-included. | Heuristic deploys instantly across all tenants; menu schema stays untouched; Twilight needs no backfill. The investigation doc's prioritization rules drive the heuristic. |
| D5 | **Common-named events at the protocol layer, vendor translation inside the provider.** `app/stt/base.py` grows from 2 to 4 event types. Flux provider emits all four; Whisper (future) emits two. | Keeps the protocol vendor-neutral; Flux jargon (`EagerEndOfTurn`) does not appear at the seam. |
| D6 | **Consumer ignores `EarlyTurnEndEvent` / `TurnResumedEvent` in this PR.** Events are emitted by the Flux module and silently swallowed by the session loop. | Speculative drafting needs measurement (how often `EagerEndOfTurn` is right vs `TurnResumed`-cancelled) and a careful UX design (handling half-spoken bot replies that get cancelled). Ship the migration first; speculate second. |

## Architecture

### Event flow

`session.py:344-376`'s consumer loop sees the same two events it sees today (`SpeechStartedEvent`, `TranscriptEvent`) and adds one defensive branch:

```python
async for event in stt.events():
    if isinstance(event, SpeechStartedEvent):
        if state.llm_task and not state.llm_task.done():
            await _barge_in_now(state, websocket, trigger="vad")
        continue

    if isinstance(event, TranscriptEvent):
        if not event.is_final:
            continue
        # final transcript → LLM+TTS pipeline
        await _handle_final_transcript(event.text, state, websocket)
        continue

    # EarlyTurnEndEvent, TurnResumedEvent — fired by Flux,
    # consumed in a future speculative-drafting PR
    continue
```

### Per-call lifecycle

| Phase | Action | Source |
|---|---|---|
| WS `start` | Load `Restaurant`; build prompt; **compute keyterms**; open Flux connection. | `session.py` (existing call-start path; new call to `compute_keyterms`) |
| Per audio frame | Forward mulaw bytes. | `state.stt.send(audio)` |
| Per Flux event | Translate to common-named event; enqueue. | `app/deepgram/stt.py` (rewrite) |
| Per common-named event | Branch and react (or drop). | `session.py` consumer (one new defensive `continue`) |
| WS `stop` | `state.stt.close()` (Flux connection torn down). | `session.py` (existing) |

### Translation map (Flux wire → common-named event)

| Flux event | Translated to | Notes |
|---|---|---|
| `Connected` | (none — lifecycle) | Provider state only. |
| `TurnInfo(end_of_turn=False)` | `TranscriptEvent(is_final=False)` | Interim, logged only by consumer. |
| `TurnInfo(end_of_turn=True)` | `TranscriptEvent(is_final=True)` | The committed turn-end. THIS is what triggers `_handle_final_transcript`. |
| First-speech indication (TBD which Flux signal) | `SpeechStartedEvent` | Fast barge-in path. Implementation-time research item — see "Open items." |
| `EagerEndOfTurn` | `EarlyTurnEndEvent` | Emitted; consumer drops. |
| `TurnResumed` | `TurnResumedEvent` | Emitted; consumer drops. |
| `Close` | (none — lifecycle) | Provider state only. |

### Files that change

| File | Change |
|---|---|
| `app/deepgram/stt.py` | **Rewrite.** Switch from `DeepgramClient.listen.asynclive.v("1")` (callback-based v1) to `AsyncDeepgramClient.listen.v2.connect(...)` (async-context-manager v2). Translate Flux events into the common-named protocol. Drop the silence-based-endpointing knobs (Flux owns turn detection). Keep the internal queue + async iterator façade so the consumer interface is unchanged. |
| `app/stt/base.py` | Add `EarlyTurnEndEvent` and `TurnResumedEvent` dataclasses. Widen `STTEvent` union from 2 to 4 members. Update the docstring on `STTProvider`. |
| `app/restaurants/keyterms.py` | **NEW.** Pure function `compute_keyterms(menu: dict, restaurant_name: str) -> list[str]`. Heuristic ranks confusables, proper-noun dishes, brand drinks, and common modifiers; restaurant name always included. Capped well under 500 tokens (target ≤450 tokens — 50-token safety margin). See "Keyterm computation" below. |
| `app/telephony/session.py` | Two changes: (1) call `compute_keyterms` and pass the result into Flux; (2) add the trailing `continue` in the event loop to defensively drop `EarlyTurnEndEvent` / `TurnResumedEvent`. |
| `app/config.py` | Set `stt_model` default to `flux-general-en`. **Remove** `stt_endpointing_ms` and `stt_utterance_end_ms` (Flux owns turn detection — these have no analog). Keep `stt_keyterms` as a debug override: when non-empty, **replaces** the heuristic output entirely. (Augment-mode is YAGNI; revisit if a tenant-level use case appears.) Add `stt_numerals: bool = True`. |
| `requirements.txt` | Bump `deepgram-sdk` minimum version to whatever first exposes `AsyncDeepgramClient` and `listen.v2`. **Verification needed in plan** — current pin is `>=3.0,<4.0` and the local install is 3.11.0; Flux v2 surface likely requires v4. |
| `tests/test_stt_deepgram.py` | Update fixtures and translation tests for the Flux SDK shape. Add tests for emission of `EarlyTurnEndEvent` and `TurnResumedEvent`. |
| `tests/test_keyterms.py` | **NEW.** Token-budget cap, restaurant-name inclusion, prioritization edge cases. |
| `tests/test_telephony_router.py` (or session-tests) | Add a defensive case that asserts `EarlyTurnEndEvent` / `TurnResumedEvent` events flow through the consumer loop without behavioral effect. |
| `.env.example` | Document new defaults: `STT_MODEL=flux-general-en`. Remove `STT_ENDPOINTING_MS`, `STT_UTTERANCE_END_MS`. Add `STT_NUMERALS=true`. |

### Files explicitly NOT touched

- `app/stt/__init__.py` — selector seam already accommodates one provider; no second provider added.
- `app/telephony/router.py` — orchestration, barge-in, LLM/TTS turn loop are unchanged.
- `app/restaurants/menu_writes.py`, `app/restaurants/models.py` — no menu schema or storage change.
- `app/llm/prompts.py` — no prompt change. Numeral form ("two" vs "2") is invisible to Claude.
- `restaurants/*.json` — no per-tenant data migration.
- `app/tts/*` — Aura-2 unchanged.

## Keyterm computation

### Contract

```python
# app/restaurants/keyterms.py
def compute_keyterms(
    menu: dict,
    restaurant_name: str,
) -> list[str]:
    """Return a prioritized list of terms to bias Flux recognition toward,
    capped under the 500-token Deepgram limit (target ≤450 tokens for a
    50-token safety margin).

    Always includes restaurant_name first. Then ranks menu items by:
      1. Acoustically confusable items (Coke, Pepper Shrimp, Wonton, Lo Mein, ...)
      2. Proper-noun dishes the model is unlikely to know (Basha, Bánh Mì, ...)
      3. Brand drink names
      4. Common modifiers ("extra spicy", "no", "side of", "half", "whole")
    Skips items the model gets right cold (French Fries, Chicken Wings, ...).
    Skips redundant n-grams (if "Pepper Shrimp" is included, "Pepper Shrimp
    Fried Rice" is not).
    """
```

### Token-budget heuristic

We do not have access to Deepgram's tokenizer. Approximate token count as `ceil(word_count * 1.3)` — slightly conservative vs typical sub-word tokenizers. The plan should validate the heuristic against a few menus and decide whether to swap to `tiktoken`'s `cl100k_base` (closer but still inexact) or stick with the simpler estimate.

The function returns at the first term whose inclusion would push the running total over the safety budget. If `restaurant_name` alone exceeds budget — pathological — return only `[restaurant_name]` and log a warning.

### Logging

At call-start, log one line listing the keyterms passed to Flux (restaurant_id, term count, total estimated tokens, first 5 terms). This is the only audit surface until persistence ships.

### Failure mode

If Flux returns `Keyterm limit exceeded` on `connect`, the connection attempt fails. Rather than dropping the call, the provider retries `connect` once *without* the `keyterm` parameter, logs the budget miss with the offending term count for post-hoc fix-up, and proceeds in transcript-only mode. The conservative 50-token safety margin should make this path nearly unreachable; if we see it in production it means the heuristic underestimates tokens and needs tuning.

## Behavior parity walkthrough

Time-ordered for a representative call. Times are illustrative.

### Phase A — connection setup

| t | Event | Action |
|---|---|---|
| 0 | Twilio WS `start` | Router loads Restaurant + builds prompt. |
| +5ms | (in-process) | `compute_keyterms(menu, name)` → list, logged. |
| +10ms | Flux `Connected` | Flux WS open with `numerals=true, keyterm=[...]`. |
| +50ms | (greeting TTS) | Bot speaks. |

### Phase B — caller's first turn ("Hi, can I get a pepper shrimp?")

| t | Flux | Common-named | Consumer |
|---|---|---|---|
| 0 | first-speech signal | `SpeechStartedEvent` | Bot not mid-response → no barge-in. |
| 200ms | `TurnInfo(is_final=False)` | `TranscriptEvent(is_final=False)` | Interim — drop. |
| 600ms | `TurnInfo(is_final=False)` | `TranscriptEvent(is_final=False)` | Interim — drop. |
| 1100ms | `EagerEndOfTurn` | `EarlyTurnEndEvent` | **This PR: drop.** |
| 1360ms | `TurnInfo(end_of_turn=true, text="...pepper shrimp?")` | `TranscriptEvent(is_final=True)` | **Trigger `_handle_final_transcript`** → LLM+TTS. |

Confirmed-final latency end-of-speech to LLM trigger: ~260ms (vs 800–1800ms today).

### Phase C — caller barges in mid-bot ("Yeah, and one... uhh... coke please.")

| t | Flux | Common-named | Consumer |
|---|---|---|---|
| 0 | first-speech signal | `SpeechStartedEvent` | Bot IS mid-response → `_barge_in_now(trigger="vad")`. |
| 250ms | `TurnInfo(is_final=False)` | `TranscriptEvent(is_final=False)` | Interim — drop. |
| 600ms | `EagerEndOfTurn` (caller hesitated) | `EarlyTurnEndEvent` | **Drop.** |
| 850ms | `TurnResumed` (caller continued) | `TurnResumedEvent` | **Drop.** |
| 1400ms | `TurnInfo(is_final=False)` | `TranscriptEvent(is_final=False)` | Interim — drop. |
| 1900ms | `TurnInfo(end_of_turn=true)` | `TranscriptEvent(is_final=True)` | Trigger `_handle_final_transcript`. |

Net: barge-in path identical to today. Speculation-relevant events flow through but are silently dropped.

### Acceptance signals

A successful migration shows, on real Twilight calls:
- Final-transcript latency (caller-stop → `_handle_final_transcript`) drops below 500ms p50.
- Mishearings of menu items in Twilight's keyterm list are anecdotally absent or rare.
- Barge-in continues to fire promptly mid-bot-response (within the same envelope as today).
- No new error classes in call logs (`Keyterm limit exceeded`, malformed Flux events, SDK version errors).

## Testing

Unit:
- `app/restaurants/keyterms.py`: token-budget cap, restaurant-name always-first invariant, edge cases (empty menu, all-confusables menu, single-item menu, name longer than budget).
- `app/deepgram/stt.py`: each Flux event type translates to the expected common-named event; `EarlyTurnEndEvent` and `TurnResumedEvent` are emitted; lifecycle events are silently consumed.
- `app/stt/base.py`: dataclasses immutable, `STTEvent` union members.

Integration / end-to-end:
- `app/telephony/session.py` consumer loop drops `EarlyTurnEndEvent` and `TurnResumedEvent` without side effects; barge-in path on `SpeechStartedEvent` unchanged; `_handle_final_transcript` trigger on `TranscriptEvent(is_final=True)` unchanged.
- A simulated call delivering all four event types in time order produces the same observable behavior the consumer produces today.

## Rollout

Single PR. Hard cutover. Land on `master`, deploy to the running service, watch the next Twilight call.

Monitoring during the first day of live calls:
- Final-transcript latency.
- `Keyterm limit exceeded` errors in logs.
- Recognition accuracy on Twilight's known confusables (`coke`, `pepper shrimp`, `lo mein`, `wonton`, `basha`).
- Barge-in latency / false barge-ins / missed barge-ins.

If quality regresses, `git revert` is the rollback. There is no env flag to flip.

## Open items / risks

These need to be resolved during plan-writing or implementation, not before.

| # | Item | Resolution path |
|---|---|---|
| O1 | **Which Flux event maps to `SpeechStartedEvent`.** Flux's published event list is `Connected, TurnInfo, EagerEndOfTurn, TurnResumed, Close`. There may be no dedicated "user-speaking-now" event; if so, the first interim `TurnInfo` becomes the trigger (~150-250ms delay vs Nova-2's ~50ms VAD). This may degrade barge-in responsiveness. | Implementation-time empirical check. If degraded beyond acceptable, evaluate whether Flux supports a `vad_events`-equivalent or whether to layer a server-side VAD. |
| O2 | **`deepgram-sdk` minimum version.** Current pin: `>=3.0,<4.0`; local install: 3.11.0. The investigation cites `AsyncDeepgramClient` and `listen.v2` — likely v4. | Plan: verify via `pip show` + SDK changelog, bump the pin in `requirements.txt`. |
| O3 | **`Keyterm limit exceeded` error vs silent truncation.** Spec assumes Flux errors. Should be confirmed empirically; if Flux truncates instead, the safety margin is less critical. | Implementation-time. Either way, the conservative budget covers both. |
| O4 | **Token-counting heuristic accuracy.** `word_count * 1.3` is approximate. | Plan to gate against a small empirical check on Twilight's menu (estimated tokens vs Flux's reported behavior). |
| O5 | **Pricing verification.** Investigation flagged conflicting per-minute estimates from two summarizer sources; should be confirmed at Deepgram's pricing page before merge so we know the actual per-call delta. | Out-of-band; not a blocker for the plan. |

## Out of scope (follow-up work)

These are explicitly downstream PRs and should not be merged into this migration:

1. **Speculative LLM drafting** on `EarlyTurnEndEvent`, with cancellation on `TurnResumedEvent`. Requires its own UX spec for the "bot heard half a word and got cancelled" failure mode.
2. **Dashboard keyterm editor.** When the dashboard ships, this PR introduces both the Firestore schema for keyterms and the UI to edit them. Migration of existing tenants follows.
3. **`smart_format=true` experiment.** Run as a flagged A/B once a measurement harness exists.
4. **Multi-tenant token-budget squeeze.** When a real tenant onboards with a >500-token-equivalent menu, layer tighter prioritization or per-item tagging on top.
5. **Whisper (or other) STT provider.** When the time comes, the `app/stt/base.py` protocol is already vendor-neutral; the new provider implements `STTProvider` and only emits `SpeechStartedEvent` + `TranscriptEvent`.

## What's settled vs. what's open

**Settled (this spec is decisive):**
- Hard cutover to `flux-general-en`.
- `numerals=true`; `smart_format=false`.
- Common-named protocol with 4 event types; consumer uses 2.
- Auto-detect heuristic, in-memory at call-open, no persistence.
- No speculative drafting in this PR.

**Open (resolved during plan/implementation):**
- O1 — which Flux event seeds `SpeechStartedEvent`.
- O2 — `deepgram-sdk` version bump.
- O3 — Flux behavior on keyterm budget exceed.
- O4 — token-counting heuristic precision.
- O5 — pricing verification (out-of-band).

---

*Hand-off note: this is the spec. Plan-writing should produce step-by-step implementation tasks under `docs/superpowers/plans/2026-05-XX-deepgram-flux-stt-migration-plan.md` following the niko convention. Open items O1–O4 should be resolved as the first plan tasks; O5 is out-of-band and does not block.*
