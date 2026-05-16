# Cold-Start Anthropic Warmup + TTS-Only Greetings — Design

**Issue:** [#192](https://github.com/tsuki-works/niko/issues/192)
**Date:** 2026-05-16
**Author:** Sandeep
**Status:** Draft — awaiting implementation

## Problem

Tonight's staged-call data for #186 measured T1 first-audio at 700–1244 ms, the worst latency moment of the entire call, on the most predictable turn. The greeting is one of N pre-known sentences per restaurant — nothing about it requires LLM intelligence. Two compounding costs hit T1:

- Anthropic prompt-cache *creation* on the first call (we pay `cache_creation`, not `cache_read`).
- Deepgram Aura's first-byte cost on a freshly-opened TTS connection.

T2 — the caller's first real conversational turn — also pays the full `cache_creation` cost because the rolling cache breakpoint from T1 has not yet been established in a way the cache layer can reuse for the new prefix.

## Goals

1. T1 first-audio drops to "Aura time-to-first-byte only" — no LLM in the critical path for the greeting.
2. T2 (caller's first real reply) hits the Anthropic prompt cache instead of paying `cache_creation`.
3. Fix the `name = "Restaurant"` placeholder leak by making the greeting deterministic per tenant.
4. Robust to Cloud Run scaling to 0 and to >1h gaps between calls.
5. No new infrastructure — no Cloud Scheduler, no separate APScheduler process, no GCS asset path.

## Non-Goals

- LLM-generated greetings, time-of-day variants, multi-language greetings.
- Pre-rendered greeting *audio* in GCS (the original #192 plan). Using live Aura synth on each call instead — text-only persistence.
- Cloud Run min-instances change (#180). Complementary but tracked separately.
- A scheduled keep-warm cron. The `/voice` webhook acts as the per-call safety net.

## Approach

Two independent levers, both essential to this design:

1. **Greeting becomes TTS-only.** Restaurant doc gains `greetings: list[str]`. On `media-stream start`, pick one (or fall back to a hardcoded template against `name`) and stream it through Aura. No LLM call on T1.
2. **Anthropic cache is primed before the LLM is needed.** A `max_tokens=1` "primer" call runs at FastAPI startup for every tenant, and again from the `/voice` HTTP webhook on every inbound call. The primer writes the system-prompt block to the prompt cache; T2's real call reads it.

The `/voice` primer is the load-bearing piece: Twilio's `/voice` → `/media-stream start` handshake gives us ~300–500 ms of free head-start. That window is enough for the primer to land at Anthropic before T2 needs the cache, regardless of Cloud Run container lifecycle. The startup primer is belt-and-suspenders for warm containers.

A small Aura warmup at startup (single-character synth, discarded) keeps Deepgram's HTTPS connection ready so T1's first-byte doesn't pay TCP+TLS setup.

## Call Timeline (After Change)

```
Twilio /voice webhook
  ├─ resolve tenant by To= number
  ├─ fire primer task (max_tokens=1, system prompt cached) ── fire & forget
  └─ return TwiML (Twilio connects WS) ───────────────────────┐
                                                              │ ~300-500ms
Twilio /media-stream WebSocket                                ▼
  ├─ start event                                          [primer hits Anthropic, writes cache]
  │   ├─ load restaurant
  │   ├─ greeting_text = random.choice(restaurant.greetings)
  │   │                  if restaurant.greetings else
  │   │                  f"Hi, thanks for calling {restaurant.name}. How can I help you?"
  │   ├─ speak(greeting_text) via Aura                ◄── T1: TTS-only, no LLM
  │   └─ seed history with synthetic user + assistant turn
  │
  └─ caller speaks → STT final → _run_llm_tts_turn(transcript) ◄── T2: cache read
```

Startup hook (per Cloud Run container boot):

```
FastAPI lifespan startup:
  ├─ for each tenant where twilio_phone != "":
  │     fire primer (max_tokens=1)  — gathered, exceptions logged
  └─ fire Aura warmup (1-char synth to a discard sink)
```

## Data Model

`app/restaurants/models.py` — single field addition:

```python
class Restaurant(BaseModel):
    ...
    greetings: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("greetings")
    @classmethod
    def _validate_greetings(cls, v: list[str]) -> list[str]:
        cleaned = [g.strip() for g in v]
        for g in cleaned:
            if not g:
                raise ValueError("greeting entries must be non-empty")
        return cleaned
```

Default `[]` preserves every existing Firestore doc — no migration needed.

## Code Surface

### Greeting playback

**`app/telephony/session.py`** — new helper `_play_greeting(state, websocket)`:

- `text = random.choice(state.restaurant.greetings) if state.restaurant.greetings else f"Hi, thanks for calling {state.restaurant.name}. How can I help you?"`
- `await speak(text, websocket, state.stream_sid, on_chunk=_make_recording_chunk_handler(state))`
- Seeds `state.history` with the synthetic prior turn so T2 sees the same "call started → I greeted → caller responds" pattern Claude is used to:
  ```python
  state.history = [
      {"role": "user", "content": GREETING_TRANSCRIPT},
      {"role": "assistant", "content": [{"type": "text", "text": text}]},
  ]
  ```
- Arms the silence watchdog after `speak` returns (whether it succeeded or raised).
- Catches and logs `speak` exceptions — does not propagate.

**`app/telephony/router.py`** — `media-stream start` block:

- Delete the `state.llm_task = asyncio.create_task(_run_llm_tts_turn(GREETING_TRANSCRIPT, state, websocket))` line and its `add_done_callback`.
- Replace with `await _play_greeting(state, websocket)`.
- The constant `GREETING_TRANSCRIPT` stays — still used inside `_play_greeting` for the synthetic-user seed.

### Primer

**`app/llm/warmup.py`** — new module:

```python
async def prime_tenant_cache(restaurant: Restaurant) -> None:
    """Fire one max_tokens=1 LLM call that writes the system prompt to Anthropic's cache.

    Used by:
    - FastAPI startup, for every tenant with a Twilio phone number.
    - /voice webhook, for every inbound call's resolved tenant.

    Swallows all exceptions; logs at WARNING on failure. Never raises.
    """
```

Request shape:
- `model = settings.anthropic_model`
- `max_tokens = 1`
- `system = _system_cache_block(build_system_prompt(restaurant))` — same helper the real call uses, so the cached prefix matches exactly.
- `tools = [UPDATE_ORDER_TOOL]` — must match the real call's tools (tools sit before system in Anthropic's cached prefix order, per #176).
- `messages = [{"role": "user", "content": "ping"}]`
- Uses the pooled `_get_async_client()` singleton (#175).

On success, logs `INFO primer completed rid=<id> latency_ms=<n> cache_creation_tokens=<n> cache_read_tokens=<n>`.

### `/voice` safety-net primer

**`app/telephony/router.py`** — `/voice` handler:

After `_resolve_restaurant_for_voice(to_e164)` returns a non-None tenant and before the TwiML response is returned:

```python
asyncio.create_task(prime_tenant_cache(restaurant))
```

The task is fire-and-forget. The TwiML response is not delayed. If the tenant is unknown (resolver returns `None`), no primer is scheduled — we don't have a system prompt to prime against.

### Startup hook

**`app/main.py`** — FastAPI `lifespan` startup:

- Iterate `restaurants_storage.iter_restaurants_with_phone()` (new thin wrapper if it doesn't exist; otherwise fold into the lifespan handler directly).
- `await asyncio.gather(*[prime_tenant_cache(r) for r in tenants], return_exceptions=True)` — exceptions captured per tenant, never crash startup.
- `await warm_aura()` — small synth to establish the Deepgram HTTPS/2 connection.
- Final log line: `INFO startup_primers tenants=<N> succeeded=<n> failed=<n>`.

### Aura warmup

**`app/tts/warmup.py`** (or inline in `app/deepgram/tts.py` — exact location decided when reading the existing TTS code during implementation):

- Single function `async def warm_aura() -> None`.
- Issues a tiny synth ("a") to Deepgram, discards the bytes.
- Swallows + logs exceptions.

The intent is HTTPS-connection establishment, not anything user-visible.

### Onboarding capture

- `.claude/skills/onboard-restaurant/SKILL.md` — append a step asking the operator for 2–3 greeting variants (free-form text).
- `restaurants/<rid>.json` — schema gains `greetings`.
- `scripts/provision_restaurant.py` — passes `greetings` through to `save_restaurant()`. Pydantic handles validation; no new logic.

### What goes away

- The `_run_llm_tts_turn(GREETING_TRANSCRIPT, ...)` call on `media-stream start` and its `add_done_callback` wiring. There is no longer a code path where Claude generates the first audio.

## Cache TTL — Why We're Not Bumping It

The `_system_cache_block` cache_control stays at the default 5-minute TTL. Walking through the math:

- The `/voice` primer fires ~300–500 ms before T1. When T2 wants to read the cache, the entry is < 1 minute old. 5 min TTL is plenty.
- Within a single call, each LLM turn refreshes the entry's TTL on read. A typical 2–3 minute call never sees expiry.
- 1h TTL only buys *cost savings across calls* (a primer in the same hour pays `cache_read` instead of `cache_creation`). Latency for the real call is unchanged because the primer wrote the cache < 500 ms ago either way.

At Phase 2 traffic the cost savings are pennies and not worth the beta-header dance. Defer to a follow-up once we observe real-traffic primer cache-miss rates.

The `_with_rolling_cache_breakpoint` cache_control also stays at 5 min — the rolling breakpoint is single-use (turn N writes, turn N+1 reads, then turn N+1 writes a new entry that supersedes it), so a longer TTL adds write cost without unlocking extra reads.

## Failure Modes

| # | Failure | Impact | Handling |
|---|---------|--------|----------|
| 1 | Primer LLM call fails (network, 5xx, key) | T2 pays `cache_creation`, same as today | Swallow, log `WARNING primer failed rid=<id>`. T1 unaffected — no LLM in critical path. |
| 2 | Primer too slow; T2 races it at Anthropic | Both treated as concurrent creations; double spend, no functional break | Nothing. Graceful degradation; not 100 % T2 cache-hit rate expected. |
| 3 | Aura fails on greeting synth | Caller hears dead air | Catch in `_play_greeting`, log, let silence watchdog handle cleanup. Same failure surface as today's LLM-greet path. |
| 4 | `name == "Restaurant"` and `greetings == []` | Default template renders the placeholder | Firestore data fix; not the code's job. |
| 5 | Empty / whitespace greeting in `greetings` | Pydantic rejects at `save_restaurant` time | Field validator. |
| 6 | Startup primer fails for some tenants | Some get warm cache, others don't | `asyncio.gather(..., return_exceptions=True)`; log per-tenant outcome; never crash startup. |
| 7 | Tenant added after container start | No startup primer for them | `/voice` primer covers it on first call. |
| 8 | Cloud Run cold start | Startup + `/voice` primer race | Anthropic resolves it; ~one extra creation per cold-start; not worth defending against. |

No `voice_primer_enabled` killswitch. The warmup is part of how T2 hits cache; making it toggleable invites "it's mysteriously slow today, did someone flip the env var?" debugging. Either it's there or the PR is reverted.

## Observability

**New log lines (this PR adds):**
- `/voice`: `INFO primer scheduled rid=<id> call_sid=<sid>`
- `prime_tenant_cache`: `INFO primer completed rid=<id> latency_ms=<n> cache_creation_tokens=<n> cache_read_tokens=<n>` or `WARNING primer failed rid=<id> reason=<msg>`
- `_play_greeting`: `INFO greeting_played rid=<id> source=greetings_list idx=<n>` or `source=default_template`
- Startup: `INFO startup_primers tenants=<N> succeeded=<n> failed=<n>`

**Free reuse:** `AnthropicLLM.stream_reply` already emits a `StreamEvent.timing` per call with `cache_read_tokens` / `cache_creation_tokens` / `ttft_seconds` (#175). The dashboard's call audit already surfaces these. The validation table writes itself from existing log lines.

## Testing Strategy

| Module | New / Updated Tests |
|--------|---------------------|
| `tests/test_restaurants_model.py` | `greetings` field: default `[]`, accepts 1/3/5 entries, rejects 6 (cap), rejects empty / whitespace-only, strips whitespace. |
| `tests/test_telephony_session.py` (new or extension) | `_play_greeting` with non-empty list picks via `random.choice` (mocked); with empty list uses default template; seeds history correctly; swallows `speak` exceptions; arms silence watchdog. |
| `tests/test_llm_warmup.py` (new) | `prime_tenant_cache` request shape (`max_tokens=1`, system block cached, tools present, `messages=[{user, "ping"}]`); uses singleton client; swallows `APIError`; logs latency on success. |
| `tests/test_telephony_router.py` | `/voice` schedules but does not await the primer; primer's exception does not propagate to the response; unknown tenant → no primer. |
| `tests/test_main_startup.py` (new or existing) | Startup iterates tenants with phones, skips empty-phone, survives individual primer failures; Aura warmup fired exactly once. |
| `tests/test_tts_warmup.py` (new) | `warm_aura` fires one synth, swallows Deepgram failure, app still boots. |
| Existing telephony tests | Update `media-stream start` assertions: `_play_greeting` is called; no `state.llm_task` from greeting; silence watchdog armed directly. |

**Not tested:** Anthropic actually serving back `cache_read` — no in-process API surface to assert against. Covered end-to-end by the validation step in the PR description.

**TDD ordering** (becomes the implementation plan):
1. `Restaurant.greetings` field + tests.
2. `prime_tenant_cache` + tests.
3. `_play_greeting` + tests.
4. `/voice` primer scheduling + tests.
5. Startup hook + tests.
6. Rewire `media-stream start` (delete LLM-greet path, call `_play_greeting`) + update existing tests.
7. Manual: populate Twilight's `greetings` in Firestore.
8. Manual: 3+ staged calls before and 3+ after for the validation table.

## Rollout

1. Implementation lands as a single commit on `feat/192-prerendered-greetings-warmup` after the smoke test passes (this is Sandeep's standard workflow — no commit/push until local validation greenlights).
2. **Pre-merge baseline on `master`**: 3+ staged calls. Record T1 first-audio (ms), T2 first-audio (ms), T2 `cache_read_tokens` vs `cache_creation_tokens`.
3. Manually populate Twilight Family Restaurant's `greetings` in Firestore. Reference variants:
   - "Hi, thanks for calling Twilight Family Restaurant. How can I help you?"
   - "Hello, this is Twilight Family Restaurant. What can I get for you?"
   - "Hey, Twilight Family Restaurant, what can I help you with?"
4. Deploy the branch to dev (local ngrok works for staged-call validation).
5. **Post-merge measurement on `feat/192`**: 3+ staged calls. Same metrics + a new one — `/voice` → `media-stream start` interval (ms), to confirm the primer head-start window.
6. Paste before/after table into the PR body.
7. Decision (see criteria below) → merge or revise.
8. Production deploy via existing master → Cloud Run pipeline.
9. Watch first 24 h of real calls in Cloud Run logs — filter `greeting_played` and `primer completed`.

## Decision Criteria

- **Pass — merge:**
  - T1 first-audio drops by ≥ 500 ms (expecting 800–1200 ms since the LLM is gone from T1 entirely; < 500 ms suggests Aura cold start is the new bottleneck).
  - T2 shows `cache_read_tokens > 0` on at least 2 of 3 calls — proof the primer is doing its job.
  - Default-template fallback verified on a synthetic test tenant with empty `greetings`.
- **Marginal — discuss:**
  - T1 drops 200–500 ms. Primer may be racing, or Aura's connection isn't warm enough. Document the numbers; decide whether to ship and fortify in a follow-up.
- **Fail — don't merge:**
  - T2 still pays `cache_creation` on most calls. The primer's prefix isn't matching the real call's prefix. Investigate before merging. Likely culprits: token-level differences in how the system prompt is rendered between primer and real call, or an Anthropic-side quirk with concurrent writes.

## Watch-For

- **Aura's first-byte latency on T1.** Old code paid Aura cold start *during* the LLM stream — hidden behind the LLM's TTFT. New code pays Aura first on every call. The startup warmup should mitigate, but the first call after a long container idle may still see Aura's reconnect cost. Track in the staged-call table.
- **Whoever lands #122 (time-of-day in system prompt).** If the timestamp is injected into the cached prefix, every primer and every real call sees a different prefix and the cache never hits. Coordinate so the timestamp lives in the user message or after the cache breakpoint, not inside the system block.

## Follow-Ups (Out of Scope)

- **#180 — Cloud Run min-instances=1 + cpu-boost.** Complementary; closes the gap between Cloud Run container cold start and the primer firing.
- **1h cache TTL** — cost optimization for bursty traffic. Re-evaluate after two weeks of observed primer cache-miss rates from real traffic.
- **GCS-cached greeting audio** (the original issue's approach) — only if live Aura synth on call connect turns out to be the latency bottleneck after this PR ships.
- **More variants or time-of-day variants** — Phase 2+ work; explicitly out of scope per the issue.

## Done When

- [ ] `greetings: list[str]` on `Restaurant` with `field_validator` + `max_length=5`.
- [ ] `_play_greeting` helper replaces the LLM-greet path on `media-stream start`.
- [ ] `prime_tenant_cache` exists and is called from `/voice` and FastAPI startup.
- [ ] `warm_aura` fires at startup.
- [ ] All new tests pass; existing telephony tests updated.
- [ ] Twilight Firestore doc has 2–3 hand-written greetings.
- [ ] Before/after table in the PR body shows ≥ 500 ms T1 reduction AND T2 cache hits.
- [ ] Listening pass confirms greeting variants sound natural.
- [ ] Default-template fallback verified on a tenant with empty `greetings`.

## Related

- #83 — Sprint 2.1 parent (Tuning conversational bot).
- #186 / #189 — prompt tuning for period-terminated openers; staged-call A/B surfaced this opportunity.
- #175 — pooled `AsyncAnthropic` singleton; primer reuses it.
- #176 — system-prompt prompt caching; primer writes to the same cache key.
- #180 — Cloud Run cold-start mitigation; complementary follow-up.
- #154 — TTS comma chunking + persistent Aura client; same plumbing the warmup reuses.
