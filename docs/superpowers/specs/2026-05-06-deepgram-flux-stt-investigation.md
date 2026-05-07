# Deepgram Flux STT — Investigation Summary

**Date:** 2026-05-06
**Author:** Sandeep (with Claude, research-only session — no code changes)
**Status:** Direction agreed; not yet implemented. Hand off to next agent for spec → plan → implementation.

---

## Context

Real-world STT errors on recent calls (no logs retained, anecdotal from Sandeep):
- "**coke**" misheard as "**smoke**"
- "**pepper shrimp**" misheard as "**pepper soup**"

These are textbook acoustic-confusability cases on phone audio (mulaw 8 kHz band-limits to ~3.4 kHz, sibilants degrade). The root cause is that our STT has no language-model prior for "this is a restaurant ordering call for *this menu*" — it picks the more common everyday English phrase over the menu term.

We did a research/thinking session to evaluate what Deepgram offers to fix this and improve the voice-agent stack overall. Scope was deliberately Deepgram-only (sticking with our incumbent vendor).

## Current state (what `niko` ships today)

`app/deepgram/stt.py` + `app/config.py:40-46`:

| Setting | Value |
|---|---|
| Model | `nova-2` |
| Endpoint | `wss://api.deepgram.com/v1/listen` (`dg.listen.asynclive.v("1")`) |
| Encoding | mulaw, 8 kHz mono (Twilio media-stream native) |
| `interim_results` | true |
| `endpointing_ms` | 800 (silence-based turn end) |
| `utterance_end_ms` | 1000 (prosody-aware end-of-utterance) |
| `vad_events` | true → drives `SpeechStartedEvent` for instant barge-in |
| `keyterm` | env-driven, **empty by default** |

Turn-taking and barge-in live in `app/telephony/router.py` as a hand-rolled state machine layered on top of those Deepgram parameters and events.

### Critical bug-in-spirit

**Nova-2 silently ignores the `keyterm` parameter.** Keyterm prompting is Nova-3+ only (config.py:45 even comments this). The plumbing is wired but the model selection means it's a no-op. So today we have *no* mechanism to bias recognition toward menu vocabulary — every call is open-domain English.

## What's on the table from Deepgram

| Feature | What it does | Verdict for niko |
|---|---|---|
| **Nova-3 mono** | Newer model, supports keyterm prompting | Solves menu accuracy; doesn't change turn-taking latency |
| **Nova-3 multi** | 45+ languages, code-switching | Nice-to-have; defer unless tenant needs it |
| **Flux mono (`flux-general-en`)** | Nova-3-quality STT + native turn detection (~260 ms) + native barge-in | **Chosen path** |
| **Flux multi (`flux-general-multi`)** | Flux + ~10 languages | Defer — not enough language coverage to justify cost premium today |
| **`numerals=true`** | "two" → "2" in transcripts | Cheap orthogonal win, applicable on any model |
| **`smart_format=true`** | Auto-format prices, phone numbers, addresses | Tradeoff vs LLM word-form parsing; A/B later |
| **Word-level timestamps** | Per-word start/end | Could enable mid-word TTS interrupt; nice-to-have |
| **Pre-recorded Listen API** | Post-call summarization, sentiment, topic detection | Future dashboard feature; not on critical path |
| **Diarization** | Speaker separation | Overkill for 1:1 phone calls |
| **Redaction** | PII/PCI redaction | Only if/when we take card numbers by phone |
| **Voice Agent API** | Full STT+LLM+TTS bundle | **Reject** — conflicts with our menu-validation LLM and order state machine |
| **Self-hosted Deepgram** | On-prem deployment | Not relevant at our scale |

## Decision

**Migrate STT from Nova-2 live to Deepgram Flux English mono (`flux-general-en`) with per-tenant keyterm prompting sourced from each restaurant's menu JSON.**

### Why Flux over Nova-3 + keyterms

1. **Flux mono and Nova-3 mono are priced the same.** No premium for Flux's bundled features at the mono tier.
2. **Native turn detection** at ~260 ms vs our 800–1800 ms hand-rolled approach — meaningful per-turn latency win.
3. **Native barge-in handling** via `EagerEndOfTurn` / `TurnResumed` events — replaces the custom `vad_events` + `SpeechStartedEvent` plumbing in `router.py`.
4. **`EagerEndOfTurn`** lets us start drafting the LLM reply *before* the turn fully ends, with `TurnResumed` to cancel the draft if the caller resumes speaking.
5. **Same recognition quality** as Nova-3 (Flux uses Nova-3 accuracy level), so menu accuracy via keyterms is preserved.

### Why not stay on Nova-2

- Keyterms silently ignored → no fix for `coke→smoke` / `pepper shrimp→pepper soup`.
- Nova-2 is not on Deepgram's current published pricing page — likely on a deprecation track.
- We're paying maintenance cost on a model with no forward roadmap.

### Why not Voice Agent API

We have non-trivial menu validation, order-state, and Firestore logic between transcript and LLM. Delegating all of that to a bundled agent would force our prompts and tool-use into Deepgram's orchestration shape — not a tradeoff we want.

## Critical constraint: keyterm token cap

> **"Maximum 500 tokens across all keyterms per request. Exceeding returns: `Keyterm limit exceeded.`"**

Token ≠ word. A "token" is a vocabulary unit (word or sub-word piece). Working heuristic:
- "Coke" ≈ 1 token
- "Pepper Shrimp" ≈ 2 tokens
- "Stir Fry Mixed Vegetables with Tofu" ≈ 6–7 tokens
- Proper nouns ("Bánh Mì", "Basha") may be more if Deepgram's tokenizer doesn't know them

### Fit check against existing menus

| Menu | Items | Est. tokens | Fits 500-cap? |
|---|---|---|---|
| Niko's Pizza demo (`app/menu.py`) | 12 | ~40 | ✅ trivial |
| Twilight (`restaurants/twilight-family-restaurant.json`) | ~80 | ~370 | ✅ tight but ok |
| Hypothetical 250-item menu | 250+ | ~1200+ | ❌ needs prioritization |

### Prioritization strategy when cap is hit

When a menu exceeds 500 tokens, rank what to keep:

1. **Acoustically confusable items** (English-collision potential): Pepper Shrimp, Coke, Wonton, Lo-Mein, Chow Mein.
2. **Proper-noun dishes the model has likely never seen**: Basha, Bánh Mì, Horchata, Tikka Masala.
3. **Restaurant name** (caller may say it).
4. **Brand drink names** (Coke, Sprite, etc.).
5. **Common modifiers**: "extra spicy", "no", "side of", "half", "whole".
6. **Skip** items the model gets right cold (French Fries, Chicken Wings, Caesar Salad).
7. **Skip duplicates** — if "Pepper Shrimp" is in, "Pepper Shrimp Fried Rice" probably isn't needed (bigram already biased).

This is a pure function: `(menu_dict, restaurant_name) → list[str]` capped at 500 tokens. Natural home: `app/restaurants/keyterms.py`.

## Pricing summary

Two AI-summary sources during this session disagreed on absolute numbers but agreed on relative ordering. **Verify in a browser before commitment.**

| Tier | Source A ($/min PAYG) | Source B ($/min PAYG) |
|---|---|---|
| Nova-2 streaming | not on page | $0.0058 |
| Nova-3 mono streaming | $0.0048 | $0.0077 |
| Nova-3 multi streaming | $0.0058 | $0.0092 |
| **Flux mono streaming** | **$0.0065** | **$0.0077** |
| Flux multi streaming | $0.0078 | — |

Either way:
- Flux mono ≈ Nova-3 mono (same tier or near it).
- Flux is pennies/call premium over Nova-2 even in the more expensive estimate.
- Free $200 credit (no expiration) easily covers an A/B test before committing.
- Aura-2 TTS at $0.030/1k chars often costs more per call than STT — TTS, not STT, dominates the per-call Deepgram bill.

## Implementation surface (sketch — for the next agent to refine)

### SDK shape

Today (`app/deepgram/stt.py:57-58`):
```python
dg = DeepgramClient(_api_key())
self._conn = dg.listen.asynclive.v("1")
self._conn.on(LiveTranscriptionEvents.Transcript, self._on_transcript)
# ... start(options), send(audio), finish()
```

Flux:
```python
from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.listen.v2.types import ListenV2TurnInfo

client = AsyncDeepgramClient()  # picks up DEEPGRAM_API_KEY from env

async with client.listen.v2.connect(
    model="flux-general-en",
    encoding="mulaw",
    sample_rate=8000,
    keyterm=[...],  # per-tenant, ≤500 tokens
) as connection:
    connection.on(EventType.MESSAGE, on_message)
    # events: Connected, TurnInfo, EagerEndOfTurn, TurnResumed, Close
```

Package: `deepgram-sdk` (already in `requirements.txt`). **Verify minimum version exposes `AsyncDeepgramClient` and `listen.v2`** — current code uses the older `DeepgramClient` façade.

### Files that change

| File | Change |
|---|---|
| `app/deepgram/stt.py` | Rewrite for Flux (`AsyncDeepgramClient.listen.v2.connect`, new event vocabulary) |
| `app/stt/base.py` | Extend `STTProvider` protocol — add `EndOfTurnEvent`, `EagerEndOfTurnEvent`, `TurnResumedEvent` |
| `app/telephony/router.py` | Delegate turn detection + barge-in to Flux events; remove or deprecate the hand-rolled state machine layered on `endpointing_ms` / `utterance_end_ms` / `SpeechStartedEvent` |
| `app/config.py` | Add `stt_provider="deepgram-flux"` option (or similar). Deprecate or remove `stt_endpointing_ms` / `stt_utterance_end_ms` once Flux owns turn detection |
| `app/restaurants/keyterms.py` | **New.** Pure function `(menu_dict, restaurant_name) → list[str]` capped at 500 tokens, with confusability-based prioritization |
| `app/restaurants/menu_writes.py` | Optionally compute and cache keyterm list at menu-write time (vs. recomputing per-call) |
| `tests/test_stt_deepgram.py` | New tests for Flux event handling; keep backward-compat tests for Nova-2 path during rollout if we keep it env-flagged |
| `tests/` (new) | Test for `app/restaurants/keyterms.py` — token-budget ranking, edge cases |
| `requirements.txt` | Possibly bump `deepgram-sdk` minimum version |
| `.env.example` | Document `STT_PROVIDER=deepgram-flux` and any new env vars |

### Rollout plan (suggested)

1. Land the Flux provider behind an env flag (`STT_PROVIDER=deepgram-flux` vs current `deepgram`).
2. Run both side-by-side on a small fraction of calls; compare:
   - Menu-term recognition accuracy (the original `coke→smoke` motivation)
   - End-of-turn latency
   - Barge-in correctness (false barge-ins, missed barge-ins)
   - Call duration / TTFT
3. If green, flip default and remove the Nova-2 path.

## Open questions for the next agent

1. **Live pricing verification** — pull Deepgram's pricing page directly in a browser; resolve the discrepancy between session sources.
2. **Deepgram tokenizer for keyterm budget** — is there a public way to count tokens, or do we use a conservative heuristic (~1.3 × word count)? `tiktoken` is closer than word-counting but still not exact.
3. **Flux keyterm cap behavior** — does Flux truncate, error, or silently drop terms when we exceed 500 tokens? (Sandeep's note says it errors; verify.)
4. **`flux-general-multi` language list** — explicit list of the ~10 languages, mapped against our pilot tenant demand.
5. **`EagerEndOfTurn` semantics** — exactly when does Flux fire it, and how often does it cancel via `TurnResumed`? (i.e., what fraction of LLM drafts are wasted?) Worth measuring on real calls.
6. **`deepgram-sdk` min version** — does our current pinned version expose `AsyncDeepgramClient` and `listen.v2`? Check via `pip show deepgram` and the SDK changelog.
7. **Numerals + smart_format** — should we also turn these on as part of the migration, or hold them as separate experiments?
8. **Where keyterm computation lives** — at menu-write time (cached on the restaurant doc) or at call-open time (computed in router)? Cache is simpler at runtime; recomputation is simpler at code-change time. Lean: cache at menu-write, recompute on menu update.

## What to keep doing in `router.py` (Flux does NOT do)

- LLM orchestration (Anthropic Claude calls, prompt assembly).
- Order state machine (item parsing, validation against menu, totals).
- Firestore writes (call session, order lifecycle, recordings).
- Twilio integration (TwiML, recording status callbacks, transfer triggers).
- TTS (Deepgram Aura-2 today — separate product, no Flux change).
- The fallback case where Flux's turn detection misfires — keep a watchdog timer as defense-in-depth.

## What's settled vs. what's open

**Settled:**
- Direction is Flux English mono.
- Per-tenant keyterms from menu JSON.
- 500-token cap is the design constraint.
- Voice Agent API is rejected.
- Nova-2 is the past, not the present.

**Open / needs next-session attention:**
- All eight items in "Open questions" above.
- Spec → plan → implementation sequence (this doc is the spec input, not a plan).
- Whether to bundle `numerals=true` into the same migration or split it.

---

*Hand-off note for the next agent: This is a research summary, not an implementation plan. Use it as input to write a proper spec (and then plan) under `docs/superpowers/specs/` and `docs/superpowers/plans/` following the niko convention. The eight open questions above should be answered before plan-writing starts.*
