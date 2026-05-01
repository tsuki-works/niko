# TTS comma-chunking + persistent Aura client — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut sentence-completion wait by flushing TTS at commas (with a min-length gate) and remove per-`speak()` TLS handshakes by reusing a module-level `httpx.AsyncClient`.

**Architecture:** Two surgical changes in two files. `app/telephony/router.py` gains a pure helper `_should_flush_chunk(delta, buffered_chars) -> bool` that returns True on `.?!` (always) or on `,;:—` when the buffered chunk is ≥ `_MIN_CHUNK_CHARS` (=20). The chunking site at `_run_llm_tts_turn` calls the helper instead of the inline `endswith` check. `app/tts/client.py` gains a module-level lazy `httpx.AsyncClient` returned by `_get_client()`; `speak()` uses it when no `client=` kwarg is passed and skips the per-call `aclose()`.

**Tech Stack:** FastAPI, `httpx`, `pytest` + `pytest-asyncio` (explicit `@pytest.mark.asyncio` markers — no `asyncio_mode=auto`).

**Spec:** No standalone spec doc — design captured in conversation and approved. Two changes ranked A and B in the call-pipeline analysis on 2026-05-01.

**File map:**
- Modify: `app/telephony/router.py`, `app/tts/client.py`, `tests/test_tts_client.py`
- Modify: `tests/test_telephony.py` (one new test for chunking)

---

### Task 0: Create the feature branch

**Files:** none (git only)

The current working branch is `feat/146-instrument-first-audio-latency` and has uncommitted `app/llm/client.py` + `app/telephony/router.py` work in flight for that issue. We do NOT pile this work on top — fresh branch off `master`.

- [ ] **Step 1: Verify there's nothing local that would be lost**

Run: `git status`
Expected: only the #146 modifications shown in the original status (`.claude/settings.json`, `app/llm/client.py`, `app/telephony/router.py`, `dashboard/components/calls/call-timeline.tsx`, `dashboard/lib/formatters/call-timeline.ts`, `dashboard/tests/call-timeline-formatter.test.ts`, `tests/test_llm_client.py`).

- [ ] **Step 2: Stash the in-flight work so master is clean**

Run: `git stash push -u -m "wip-146-before-tts-chunking"`
Expected: `Saved working directory and index state ...`

- [ ] **Step 3: Branch off master**

Run: `git checkout master && git pull origin master && git checkout -b feat/tts-comma-chunking-persistent-client`
Expected: `Switched to a new branch 'feat/tts-comma-chunking-persistent-client'`.

- [ ] **Step 4: Confirm working tree clean**

Run: `git status`
Expected: `nothing to commit, working tree clean`.

---

### Task 1: Add `_should_flush_chunk` helper to router

**Files:**
- Modify: `app/telephony/router.py` (add constants + helper near the top, before `_CallState`)
- Modify: `tests/test_telephony.py` (add a unit-test class for the helper at end of file)

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `tests/test_telephony.py`:

```python
# ---------------------------------------------------------------------------
# _should_flush_chunk — TTS chunking logic
# ---------------------------------------------------------------------------

from app.telephony.router import _should_flush_chunk, _MIN_CHUNK_CHARS


def test_flush_on_period_regardless_of_length():
    """Sentence terminators always flush, even on a very short buffer."""
    assert _should_flush_chunk(".", buffered_chars=3) is True
    assert _should_flush_chunk("up.", buffered_chars=3) is True


def test_flush_on_question_mark_and_exclamation():
    assert _should_flush_chunk("?", buffered_chars=5) is True
    assert _should_flush_chunk("!", buffered_chars=5) is True


def test_no_flush_on_comma_below_min_length():
    """Short comma-ended chunks (e.g. 'Got it,') keep buffering — we
    don't want a TTS round-trip for two-word fragments."""
    assert _should_flush_chunk(",", buffered_chars=7) is False
    assert _should_flush_chunk("it,", buffered_chars=7) is False


def test_flush_on_comma_at_or_above_min_length():
    """Once the buffer crosses _MIN_CHUNK_CHARS, a comma flushes so the
    caller hears the first half of a long sentence sooner."""
    assert _MIN_CHUNK_CHARS == 20
    assert _should_flush_chunk(",", buffered_chars=_MIN_CHUNK_CHARS) is True
    assert _should_flush_chunk("up,", buffered_chars=33) is True


def test_flush_on_other_soft_breaks():
    """Semicolons, colons, and em dashes are also natural prosody
    breaks — gated by the same min-length rule."""
    assert _should_flush_chunk(";", buffered_chars=25) is True
    assert _should_flush_chunk(":", buffered_chars=25) is True
    assert _should_flush_chunk("—", buffered_chars=25) is True
    assert _should_flush_chunk(";", buffered_chars=10) is False


def test_no_flush_on_plain_text_delta():
    """Mid-word deltas never flush, regardless of length."""
    assert _should_flush_chunk(" coming", buffered_chars=100) is False
    assert _should_flush_chunk("a", buffered_chars=5) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telephony.py -k _should_flush_chunk -v`
Expected: 6 tests fail with `ImportError` on `_should_flush_chunk` / `_MIN_CHUNK_CHARS`.

- [ ] **Step 3: Add the helper to `app/telephony/router.py`**

Insert immediately after the existing module-level constants block (after `MARK_ECHO_TIMEOUT_SECONDS = 8.0` at router.py:57 and before the `_GOODBYE_PATTERNS` tuple):

```python
# Chunking thresholds for TTS handoff (#XXX). Sentence terminators
# always flush; soft breaks (commas, semicolons, colons, em dashes)
# only flush once the buffered chunk is ≥ _MIN_CHUNK_CHARS so that
# fragments like "Got it," don't become their own Aura round-trip.
# 20 chars ≈ "One Chicken Fried Rice coming up," length when the
# 4/26 Twilight call's longest "over budget" turn would have hit.
_HARD_BREAKS = (".", "?", "!")
_SOFT_BREAKS = (",", ";", ":", "—")
_MIN_CHUNK_CHARS = 20


def _should_flush_chunk(delta: str, buffered_chars: int) -> bool:
    """True if the current text-delta should close a TTS chunk.

    ``delta`` is the latest streamed text fragment from Anthropic;
    ``buffered_chars`` is the total length of all deltas accumulated
    since the last flush (i.e. the chunk we'd ship if we flushed now).
    """
    if delta.endswith(_HARD_BREAKS):
        return True
    if delta.endswith(_SOFT_BREAKS) and buffered_chars >= _MIN_CHUNK_CHARS:
        return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telephony.py -k _should_flush_chunk -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/telephony/router.py tests/test_telephony.py
git commit -m "tts: add _should_flush_chunk helper for comma-aware chunking

Pure-function helper that returns True on hard breaks (.?!) or on
soft breaks (,;:—) once the buffered chunk crosses 20 chars.
Wired into _run_llm_tts_turn in the next commit."
```

---

### Task 2: Wire `_should_flush_chunk` into the streaming loop

**Files:**
- Modify: `app/telephony/router.py:419` (the `if event.text_delta.endswith((".", "?", "!"))` block inside `_run_llm_tts_turn`)
- Modify: `tests/test_telephony.py` (one integration-style test that drives a multi-delta stream and checks chunk count)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_telephony.py` (placement: with the existing media-stream tests, near the `_make_fake_stream_reply` helper):

```python
def _make_fake_stream_reply_deltas(*deltas: str, final_text: str = ""):
    """Yield each delta string as a separate StreamEvent — lets us
    drive the chunking logic with realistic multi-event streams."""
    final = final_text or "".join(deltas)

    async def fake(*, transcript, history, order, **kw):
        for d in deltas:
            yield StreamEvent(text_delta=d)
        yield StreamEvent(
            final=LLMResponse(reply_text=final, order=order, history=history)
        )

    return fake


def test_run_llm_tts_turn_flushes_at_long_comma_clause(monkeypatch, mock_pipeline):
    """A delta sequence that builds up to 'One Chicken Fried Rice coming up,'
    should flush at the comma (≥20 chars buffered), then ship the rest at
    the period — total 2 chunks."""
    chunks_spoken: list[str] = []

    async def capture_speak(text, websocket, stream_sid, **kw):
        chunks_spoken.append(text)

    monkeypatch.setattr("app.telephony.router.speak", capture_speak)
    monkeypatch.setattr(
        "app.telephony.router.stream_reply",
        _make_fake_stream_reply_deltas(
            "One Chicken Fried Rice coming up,",
            " what size would you like?",
        ),
    )

    with client.websocket_connect("/media-stream") as ws:
        ws.send_json(_START_MSG)
        ws.send_json(_STOP_MSG)

    # Greeting turn ships once (single delta no terminators in the test
    # fake — flushed at end-of-stream as remainder). Caller turn here
    # produces 2 chunks: comma flush + period flush.
    assert "One Chicken Fried Rice coming up," in chunks_spoken
    assert "what size would you like?" in chunks_spoken


def test_run_llm_tts_turn_does_not_flush_at_short_comma(monkeypatch, mock_pipeline):
    """'Got it,' is below the 20-char threshold — it must keep buffering
    until the period and ship as a single chunk."""
    chunks_spoken: list[str] = []

    async def capture_speak(text, websocket, stream_sid, **kw):
        chunks_spoken.append(text)

    monkeypatch.setattr("app.telephony.router.speak", capture_speak)
    monkeypatch.setattr(
        "app.telephony.router.stream_reply",
        _make_fake_stream_reply_deltas("Got it,", " moving on."),
    )

    with client.websocket_connect("/media-stream") as ws:
        ws.send_json(_START_MSG)
        ws.send_json(_STOP_MSG)

    # Single chunk — comma did NOT flush, period did.
    combined = " ".join(chunks_spoken)
    assert "Got it, moving on." in combined
    # No chunk should be just "Got it,"
    assert "Got it," not in chunks_spoken
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telephony.py -k "comma_clause or short_comma" -v`
Expected: both fail — current code only flushes on `.?!`, so the comma clause test sees a single combined chunk and the short-comma test will likely pass coincidentally OR fail depending on order of operations. Confirm both behaviors before continuing.

- [ ] **Step 3: Replace the inline flush condition**

In `app/telephony/router.py`, locate the streaming loop in `_run_llm_tts_turn` (around line 414-431). Replace:

```python
            if event.text_delta is not None:
                if first_text_at is None:
                    first_text_at = time.monotonic()
                text_buffer.append(event.text_delta)
                full_reply_parts.append(event.text_delta)
                if event.text_delta.endswith((".", "?", "!")):
                    chunk = "".join(text_buffer).strip()
                    text_buffer.clear()
                    if chunk and state.stream_sid:
                        if first_speak:
                            _record_first_audio()
                            first_speak = False
                        await speak(
                            chunk,
                            websocket,
                            state.stream_sid,
                            recording_session=state.recording_session,
                        )
```

with:

```python
            if event.text_delta is not None:
                if first_text_at is None:
                    first_text_at = time.monotonic()
                text_buffer.append(event.text_delta)
                full_reply_parts.append(event.text_delta)
                buffered_chars = sum(len(p) for p in text_buffer)
                if _should_flush_chunk(event.text_delta, buffered_chars):
                    chunk = "".join(text_buffer).strip()
                    text_buffer.clear()
                    if chunk and state.stream_sid:
                        if first_speak:
                            _record_first_audio()
                            first_speak = False
                        await speak(
                            chunk,
                            websocket,
                            state.stream_sid,
                            recording_session=state.recording_session,
                        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telephony.py -v`
Expected: full telephony suite passes (the new tests + all existing).

- [ ] **Step 5: Commit**

```bash
git add app/telephony/router.py tests/test_telephony.py
git commit -m "tts: flush TTS chunks at commas once buffer hits 20 chars

Cuts sentence-completion wait on long replies. The 5/1 Twilight call
'One Chicken Fried Rice coming up, what size would you like?' was
+512ms over the LLM's first text token — now it flushes at the comma
and the caller hears audio that much sooner."
```

---

### Task 3: Persistent `httpx.AsyncClient` in `app/tts/client.py`

**Files:**
- Modify: `app/tts/client.py` (replace per-call client construction with module-level lazy singleton)
- Modify: `tests/test_tts_client.py` (add tests for the singleton path)

- [ ] **Step 1: Write the failing tests**

Add at the end of `tests/test_tts_client.py`:

```python
# ---------------------------------------------------------------------------
# _get_client — module-level persistent httpx.AsyncClient (#XXX)
# ---------------------------------------------------------------------------

import app.tts.client as tts_module


@pytest.fixture(autouse=True)
def _reset_default_client():
    """Reset the module-level singleton between tests so one test's
    instance doesn't leak into another. The real process never needs
    this — the singleton is intentionally long-lived."""
    yield
    tts_module._default_client = None


def test_get_client_returns_same_instance_across_calls():
    c1 = tts_module._get_client()
    c2 = tts_module._get_client()
    assert c1 is c2


def test_get_client_constructs_with_expected_timeouts():
    import httpx
    c = tts_module._get_client()
    assert isinstance(c, httpx.AsyncClient)
    # httpx.Timeout exposes per-stage attributes; the values match what
    # the per-call client used to set.
    assert c.timeout.connect == 5.0
    assert c.timeout.read == 10.0
    assert c.timeout.write == 5.0
    assert c.timeout.pool == 5.0


@pytest.mark.asyncio
async def test_speak_uses_default_client_when_none_passed(monkeypatch):
    """When ``client`` is not passed, speak() must reuse the singleton —
    NOT construct a fresh client per call (the whole point of this
    change is to skip the TLS handshake)."""
    chunks = [b"\xab"]
    fake_default = make_mock_client(chunks)
    ws = make_mock_websocket()

    # Pre-populate the singleton with our mock so speak() picks it up.
    tts_module._default_client = fake_default

    await speak("Hello", ws, stream_sid="MZ123")

    fake_default.stream.assert_called_once()
    # And the singleton was NOT closed at the end of the call —
    # persistent across speak() invocations is the whole point.
    assert tts_module._default_client is fake_default


@pytest.mark.asyncio
async def test_speak_does_not_close_default_client(monkeypatch):
    """The singleton lives for the process lifetime. ``aclose()`` must
    not be called from inside speak(), even on the success path."""
    chunks = [b"\xab"]
    fake_default = make_mock_client(chunks)
    fake_default.aclose = AsyncMock()
    ws = make_mock_websocket()

    tts_module._default_client = fake_default

    await speak("Hello", ws, stream_sid="MZ123")

    fake_default.aclose.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tts_client.py -v`
Expected: the four new tests fail with `AttributeError: module 'app.tts.client' has no attribute '_get_client'` / `_default_client`.

- [ ] **Step 3: Update `app/tts/client.py`**

Replace the per-call construction. At the top of the module (after the existing `_DEEPGRAM_BASE = ...` line at tts/client.py:26), add:

```python
# Process-wide reusable client. Constructing an httpx.AsyncClient costs
# a TLS handshake on every speak() call; reusing one across the whole
# process keeps the connection pool warm so subsequent sentence chunks
# skip the handshake. Lazy-initialised so importing this module never
# spins up sockets at startup. Tests reset this between cases via a
# fixture; the real process never needs to.
_default_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _default_client
    if _default_client is None:
        _default_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        )
    return _default_client
```

Then replace the body of `speak()` from `created_client = client is None` (tts/client.py:87) through the end. The relevant section:

```python
    created_client = client is None
    _client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    )

    try:
        async with _client.stream(
            ...
            ):
                # body unchanged
    finally:
        if created_client:
            await _client.aclose()
```

becomes:

```python
    _client = client if client is not None else _get_client()

    async with _client.stream(
        "POST", url, headers=headers, params=params, json=body
    ) as response:
        if response.status_code != 200:
            error_body = await response.aread()
            logger.error(
                "tts: Deepgram returned %d stream_sid=%s body=%s",
                response.status_code,
                stream_sid,
                error_body.decode(errors="replace")[:200],
            )
            raise RuntimeError(
                f"Deepgram returned {response.status_code}: "
                f"{error_body.decode(errors='replace')}"
            )

        async for chunk in response.aiter_bytes():
            if not chunk:
                continue
            payload = base64.b64encode(chunk).decode()
            try:
                await websocket.send_json(
                    {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": payload},
                    }
                )
            except WebSocketDisconnect:
                logger.info("tts: websocket disconnected mid-stream stream_sid=%s", stream_sid)
                return
            if recording_session is not None:
                try:
                    from app.storage import recordings as _recordings
                    _recordings.append_chunks(
                        recording_session, b"", chunk
                    )
                except Exception:
                    logger.exception(
                        "tts: failed to feed chunk into recording session "
                        "stream_sid=%s",
                        stream_sid,
                    )
```

The `try/finally` with `created_client` and `aclose()` is fully removed — singleton closure is the OS's job at process exit.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tts_client.py -v`
Expected: full file passes — both the new four tests and the existing eight (the existing tests pass `client=` so they bypass the singleton entirely).

- [ ] **Step 5: Commit**

```bash
git add app/tts/client.py tests/test_tts_client.py
git commit -m "tts: reuse a single httpx.AsyncClient across speak() calls

Each speak() call used to spin up a fresh AsyncClient and TLS-handshake
into Deepgram, then aclose at end. With sentence-chunking turning every
turn into 1-3 speak() calls the cumulative cost was real. Lazy
module-level singleton; tests still inject via the existing client=
kwarg."
```

---

### Task 4: Run the full suite + lint

**Files:** none (verification only)

- [ ] **Step 1: Run all backend tests**

Run: `pytest tests/ -v`
Expected: all green. Pay attention to `test_tts_integration.py` if it exists — confirm it doesn't depend on the per-call `aclose()` behaviour. (It uses `client=` kwarg so it should be fine.)

- [ ] **Step 2: Push the branch**

```bash
git push -u origin feat/tts-comma-chunking-persistent-client
```

- [ ] **Step 3: Open the PR**

```bash
gh pr create --title "tts: comma chunking + persistent Aura client" --body "$(cat <<'EOF'
## Summary
- Flushes TTS chunks at soft breaks (`,;:—`) once the buffered text crosses 20 chars, in addition to the existing `.?!` rule. Long replies (e.g. "One Chicken Fried Rice coming up, what size?") now reach the caller in two chunks instead of one — first audio shaves the time the model spent finishing the sentence.
- Reuses a module-level `httpx.AsyncClient` for Deepgram Aura instead of constructing one per `speak()` call. With sentence-chunking turning each turn into multiple TTS round trips, the per-call TLS handshake was adding 50-150ms each.

Came out of analysing the 2026-05-01 Twilight call (CAc11f0745…) where turn #3 was 1026ms first-audio (over budget); 512ms of that was the model finishing the sentence after first text token.

## Test plan
- [ ] `pytest tests/test_telephony.py -v` — chunking helper unit tests + two integration cases (long-comma flush, short-comma no-flush).
- [ ] `pytest tests/test_tts_client.py -v` — singleton identity, expected timeouts, default-client wiring, no aclose.
- [ ] Live test call against staging — confirm a multi-clause reply reaches the caller faster than the same wording on master.
EOF
)"
```

Expected: PR URL printed.

- [ ] **Step 4: Restore the stashed #146 work**

After the PR is opened (so we don't conflate the two), get back to the in-flight branch:

```bash
git checkout feat/146-instrument-first-audio-latency
git stash pop
```

Expected: the original modifications restored under the in-flight branch.

---

## Self-review notes

- **Spec coverage:** Both A (chunking) and B (persistent client) from the conversation design have a task. ✓
- **Placeholder scan:** Two `(#XXX)` markers in code comments — these are placeholders for the eventual issue/PR number once the PR is opened. Replace with the actual PR number before merge, or drop the marker. Acceptable for a plan; flag it during review.
- **Type consistency:** Helper signature `_should_flush_chunk(delta: str, buffered_chars: int) -> bool` is used identically in tests and call site. `_get_client()` returns `httpx.AsyncClient` and is referenced as such everywhere. ✓
- **Threshold value:** `_MIN_CHUNK_CHARS = 20` is asserted in one test (`test_flush_on_comma_at_or_above_min_length`) so a future bump triggers a deliberate test update rather than a silent regression. ✓
