# STT/TTS Plugin Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract Deepgram STT and TTS out of `app/telephony/router.py` into a focused plugin layer (`app/stt/`, `app/tts/`, `app/deepgram/`) with a thin selector seam for future provider swaps, and add instant barge-in via VAD speech-started events.

**Architecture:** Two abstraction layers — `app/stt/` (live streaming STT contract) and `app/tts/` (per-utterance TTS contract). Vendor implementations live under `app/deepgram/`. Selectors in `app/stt/__init__.py` and `app/tts/__init__.py` pick a provider by env var. STT exposes an async-iterator events interface (TranscriptEvent + SpeechStartedEvent); the router's `_consume_transcripts` background task consumes events and is solely responsible for state mutation, Firestore emission, and barge-in dispatch.

**Tech Stack:** Python 3.11+, FastAPI, pytest, asyncio, Deepgram SDK v3.11, httpx, pydantic-settings. Existing patterns: print-style logging with call_sid, `_bg_call_event` for Firestore writes via `app.storage.call_sessions.record_event`.

**Spec:** `docs/superpowers/specs/2026-05-06-stt-tts-plugin-extraction-design.md`

**Issue:** [#250](https://github.com/tsuki-works/niko/issues/250) (refactor) and [#83](https://github.com/tsuki-works/niko/issues/83) (parent tuning).

**Branch:** `feat/83-tune-conversational-bot`. All α tasks land here as atomic commits. One PR at the end references both issues.

---

## File Structure

### Files created

| Path | Responsibility |
|---|---|
| `app/stt/__init__.py` | Exports `get_stt()`, `STTProvider`, `TranscriptEvent`, `SpeechStartedEvent` |
| `app/stt/base.py` | `STTProvider` Protocol; `TranscriptEvent`, `SpeechStartedEvent` dataclasses; `STTEvent` union |
| `app/tts/base.py` | `SpeakFunc` Protocol describing the TTS callable signature |
| `app/deepgram/__init__.py` | Shared: `_api_key()` reader, `_DEEPGRAM_BASE` constant |
| `app/deepgram/stt.py` | `DeepgramSTT` class implementing `STTProvider` |
| `app/deepgram/tts.py` | `speak()` implementation lifted from today's `app/tts/client.py`, with `recording_session` swapped for `on_chunk` |
| `tests/fakes/__init__.py` | Marker for the fakes package |
| `tests/fakes/stt.py` | `FakeSTT` test fixture |
| `tests/test_fake_stt.py` | Unit tests of the fake itself |
| `tests/test_stt_deepgram.py` | Unit tests of `DeepgramSTT` |
| `tests/test_transcript_consumer.py` | Unit tests of `_consume_transcripts` |
| `tests/test_barge_in_helper.py` | Unit tests of `_barge_in_now` |
| `tests/test_provider_selector.py` | Unit tests of `get_stt()` and TTS selector |
| `tests/test_deepgram_tts.py` | Renamed from `tests/test_tts_client.py` |

### Files modified

| Path | Change |
|---|---|
| `app/tts/__init__.py` | Add `speak()` selector dispatching by `settings.tts_provider` |
| `app/config.py` | Add `stt_provider`, `tts_provider`, `stt_model`, `stt_endpointing_ms`, `stt_utterance_end_ms`, `stt_keyterms`, `stt_instant_barge_in` settings |
| `app/telephony/router.py` | Remove `_open_deepgram_connection` and inline Deepgram code; add `_consume_transcripts`, `_barge_in_now`, `_make_recording_chunk_handler`; new fields on `_CallState`; update `media_stream` WS handler; update `_handle_final_transcript` |
| `tests/test_telephony.py` | Migrate `mock_pipeline` fixture to inject `FakeSTT`; collapse five ad-hoc patch blocks into the fixture |

### Files deleted

| Path | Reason |
|---|---|
| `app/tts/client.py` | Body relocated to `app/deepgram/tts.py`; no shim |
| `tests/test_tts_client.py` | Renamed to `tests/test_deepgram_tts.py` |

---

## Task 1: STTProvider Protocol and event dataclasses (α-1)

**Goal:** Pure type definitions — the contracts that everything else implements. No behavior, no tests.

**Files:**
- Create: `app/stt/__init__.py`
- Create: `app/stt/base.py`
- Create: `app/tts/base.py`

- [ ] **Step 1: Create `app/stt/base.py`**

```python
"""STT provider contract.

The router talks to STT through this interface; concrete providers
(today: Deepgram) live under app/<vendor>/stt.py. Future providers
implement the same Protocol and become a one-line addition to the
selector in app/stt/__init__.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, Union


@dataclass(frozen=True)
class SpeechStartedEvent:
    """VAD detected the caller began speaking. Fires before any transcript
    is available — used for instant barge-in (~50ms vs ~800ms waiting on
    a final transcript)."""

    at: float = 0.0  # optional Deepgram timestamp; 0 if SDK omits it


@dataclass(frozen=True)
class TranscriptEvent:
    """One recognition result from the STT provider. Interim results
    (``is_final=False``) are rewritten by subsequent events; only finals
    should drive behavior."""

    text: str
    is_final: bool
    confidence: float


STTEvent = Union[TranscriptEvent, SpeechStartedEvent]


class STTProvider(Protocol):
    """Live streaming STT contract.

    Lifecycle: ``open()`` → many ``send(audio)`` + ``async for`` over
    ``events()`` → ``close()``. Errors mid-stream raise out of
    ``events()``; the consumer decides whether to recover or end the call.
    """

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

- [ ] **Step 2: Create `app/stt/__init__.py`**

```python
"""Public entry point for the STT abstraction layer.

Re-exports the contract so callers do ``from app.stt import
TranscriptEvent`` instead of reaching into ``app.stt.base``. The
``get_stt()`` selector is added in a later task once a concrete
implementation exists.
"""

from app.stt.base import (
    STTEvent,
    STTProvider,
    SpeechStartedEvent,
    TranscriptEvent,
)

__all__ = [
    "STTEvent",
    "STTProvider",
    "SpeechStartedEvent",
    "TranscriptEvent",
]
```

- [ ] **Step 3: Create `app/tts/base.py`**

```python
"""TTS provider contract.

TTS is per-utterance and stateless across calls (an HTTP request that
streams audio bytes back). The contract is therefore a callable signature
rather than a class — same shape works for Deepgram Aura, ElevenLabs,
OpenAI TTS, and similar HTTP-streaming providers.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Protocol

import httpx
from fastapi import WebSocket


class SpeakFunc(Protocol):
    """Signature any TTS provider implementation must match.

    Args:
        text: LLM reply text to synthesize.
        websocket: Active Twilio Media Streams WebSocket.
        stream_sid: Twilio streamSid from the ``start`` event.
        client: Optional injected httpx.AsyncClient for tests.
        on_chunk: Optional zero-arg sync callable fired with each raw
            audio chunk (mulaw bytes) as it streams in. Used by callers
            that want a copy of the outbound audio (e.g., for recording).
            Exceptions are swallowed by the implementation.
        on_first_byte: Optional zero-arg sync callable fired exactly once
            when the first non-empty chunk arrives. Used to measure TTS
            network latency. Exceptions are swallowed.
    """

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

- [ ] **Step 4: Verify nothing breaks — run the existing test suite**

Run: `python -m pytest tests/ -x --tb=short -q`
Expected: all existing tests pass (we've only added new modules; nothing imports them yet).

- [ ] **Step 5: Commit**

```bash
git add app/stt/__init__.py app/stt/base.py app/tts/base.py
git commit -m "feat(stt): add STTProvider protocol and event dataclasses

Pure type definitions — contracts for the upcoming plugin layer.
STTProvider is implemented by app/deepgram/stt.py in a later commit;
SpeakFunc is matched by app/deepgram/tts.py. No behavior, no consumers
yet.

Refs #250."
```

---

## Task 2: FakeSTT test fixture (α-2)

**Goal:** A test double that implements `STTProvider` so consumer tests can script call flows without touching the Deepgram SDK or network.

**Files:**
- Create: `tests/fakes/__init__.py`
- Create: `tests/fakes/stt.py`
- Create: `tests/test_fake_stt.py`

- [ ] **Step 1: Create `tests/fakes/__init__.py` (empty file)**

```python
```

- [ ] **Step 2: Create `tests/fakes/stt.py`**

```python
"""FakeSTT — test double for app.stt.base.STTProvider.

Tests script events and assert on calls. The fake is intentionally
minimal: just enough plumbing to support the scenarios the real plugin
needs to handle (open, send, multi-event streams, close, error).

Usage:

    fake = FakeSTT(events=[TranscriptEvent("hi", True, 0.95)])
    await fake.open()
    async for event in fake.events():
        ...

    fake.feed(SpeechStartedEvent())             # inject mid-test
    fake.feed_error(RuntimeError("dropped"))    # surface error in events()
    await fake.close()
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

from app.stt.base import STTEvent


_CLOSED = object()


@dataclass
class _ErrorBox:
    exc: BaseException


class FakeSTT:
    """Implements STTProvider; lets tests feed scripted events."""

    def __init__(self, *, events=None) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self.opened = False
        self.closed = False
        self.sent: list[bytes] = []
        for ev in events or []:
            self._queue.put_nowait(ev)

    async def open(self) -> None:
        self.opened = True

    async def send(self, audio: bytes) -> None:
        self.sent.append(audio)

    async def events(self) -> AsyncIterator[STTEvent]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            if isinstance(item, _ErrorBox):
                raise item.exc
            yield item

    async def close(self) -> None:
        self.closed = True
        self._queue.put_nowait(_CLOSED)

    # Test-side helpers ----------------------------------------------------
    def feed(self, event: STTEvent) -> None:
        """Inject one event into the live stream."""
        self._queue.put_nowait(event)

    def feed_error(self, exc: BaseException) -> None:
        """Cause the next ``events()`` pull to raise ``exc``."""
        self._queue.put_nowait(_ErrorBox(exc))
```

- [ ] **Step 3: Write `tests/test_fake_stt.py`**

```python
"""Tests for tests/fakes/stt.py — the FakeSTT test double itself.

We test the fake because every other test in this push relies on it
behaving exactly like a real STTProvider should. A bug in the fake
would be a bug in dozens of consumer tests at once.
"""

from __future__ import annotations

import asyncio

import pytest

from app.stt.base import SpeechStartedEvent, TranscriptEvent
from tests.fakes.stt import FakeSTT


@pytest.mark.asyncio
async def test_open_marks_opened() -> None:
    fake = FakeSTT()
    await fake.open()
    assert fake.opened is True


@pytest.mark.asyncio
async def test_send_records_audio_chunks_in_order() -> None:
    fake = FakeSTT()
    await fake.send(b"chunk1")
    await fake.send(b"chunk2")
    assert fake.sent == [b"chunk1", b"chunk2"]


@pytest.mark.asyncio
async def test_events_yields_seeded_events_in_order() -> None:
    seeded = [
        TranscriptEvent("hi", False, 0.7),
        TranscriptEvent("hello", True, 0.95),
    ]
    fake = FakeSTT(events=seeded)
    await fake.open()

    received = []
    async def consume():
        async for event in fake.events():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let consumer drain seeded items
    await fake.close()
    await task

    assert received == seeded


@pytest.mark.asyncio
async def test_feed_injects_event_into_live_stream() -> None:
    fake = FakeSTT()
    await fake.open()

    received = []
    async def consume():
        async for event in fake.events():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    fake.feed(SpeechStartedEvent())
    fake.feed(TranscriptEvent("ok", True, 0.9))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert isinstance(received[0], SpeechStartedEvent)
    assert isinstance(received[1], TranscriptEvent)
    assert received[1].text == "ok"


@pytest.mark.asyncio
async def test_feed_error_raises_from_events() -> None:
    fake = FakeSTT()
    await fake.open()
    fake.feed_error(RuntimeError("dropped"))

    with pytest.raises(RuntimeError, match="dropped"):
        async for _event in fake.events():
            pass


@pytest.mark.asyncio
async def test_close_terminates_events_iterator() -> None:
    fake = FakeSTT()
    await fake.open()
    await fake.close()

    received = []
    async for event in fake.events():
        received.append(event)

    assert received == []
    assert fake.closed is True
```

- [ ] **Step 4: Run the new tests, expect FAIL (FakeSTT not yet importable)**

Run: `python -m pytest tests/test_fake_stt.py -v`
Expected: ImportError or ModuleNotFoundError on `tests.fakes.stt`. (Verify by message.)

If they pass without the fake existing, you have the wrong test file or stale `__pycache__`. Run `python -m pytest --cache-clear tests/test_fake_stt.py`.

- [ ] **Step 5: Re-run after `tests/fakes/stt.py` exists from Step 2**

Run: `python -m pytest tests/test_fake_stt.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add tests/fakes/__init__.py tests/fakes/stt.py tests/test_fake_stt.py
git commit -m "test(stt): add FakeSTT fixture for offline testing

Test double for STTProvider that lets tests script transcript events,
inject speech-started events, and surface connection errors — all
without touching the Deepgram SDK or network. Used by the consumer,
barge-in, and provider-selector tests in following commits.

Refs #250."
```

---

## Task 3: Move Deepgram TTS into vendor package (α-3)

**Goal:** Lift `app/tts/client.py` body into `app/deepgram/tts.py`, replace `recording_session` parameter with `on_chunk` callback, add the TTS selector at `app/tts/__init__.py`, update the five call sites in `router.py`, rename and update tests.

**Files:**
- Create: `app/deepgram/__init__.py`
- Create: `app/deepgram/tts.py`
- Modify: `app/tts/__init__.py`
- Modify: `app/config.py`
- Modify: `app/telephony/router.py`
- Delete: `app/tts/client.py`
- Rename: `tests/test_tts_client.py` → `tests/test_deepgram_tts.py`
- Modify: renamed test file (imports + recording_session → on_chunk)
- Create: `tests/test_provider_selector.py`

- [ ] **Step 1: Add `tts_provider` setting to `app/config.py`**

Edit `app/config.py`. Add inside `Settings` class, immediately after `deepgram_tts_model`:

```python
    # TTS provider selector. Today only "deepgram" is implemented; the
    # selector seam exists so a second provider becomes a one-line add
    # to app/tts/__init__.py.
    tts_provider: str = "deepgram"
```

- [ ] **Step 2: Create `app/deepgram/__init__.py`**

```python
"""Deepgram vendor package — STT and TTS implementations co-located.

The package exists so per-vendor configuration (API key reader, base URL,
shared HTTP client) can live in one place and be consumed by both
``stt.py`` and ``tts.py``. The router never imports from here directly;
consumers route through ``app/stt`` and ``app/tts``.
"""

from __future__ import annotations

from app.config import settings


_DEEPGRAM_BASE = "https://api.deepgram.com/v1"


def _api_key() -> str:
    """Return the Deepgram API key, raising a clear error when missing.

    Both halves of the Deepgram package call this lazily so importing
    ``app.deepgram`` never crashes environments where the key isn't set.
    """
    key = settings.deepgram_api_key
    if not key:
        raise RuntimeError(
            "DEEPGRAM_API_KEY not set — cannot reach Deepgram. "
            "Fetch credentials via /shared-creds."
        )
    return key
```

- [ ] **Step 3: Create `app/deepgram/tts.py` — body lifted from `app/tts/client.py`, with `recording_session` swapped for `on_chunk`**

```python
"""Deepgram Aura TTS implementation.

Streams Aura audio through Twilio Media Streams. Implements the SpeakFunc
contract from app/tts/base.py.

Why Deepgram Aura (over ElevenLabs):
  - Server-to-server design — no abuse detector that blocks Cloud Run egress.
  - Native ``mulaw`` 8 kHz output — drop-in for Twilio Media Streams.
  - Reuses the Deepgram API key already in use for STT.
"""

from __future__ import annotations

import base64
import logging
from typing import Callable, Optional

import httpx
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.deepgram import _DEEPGRAM_BASE, _api_key

logger = logging.getLogger(__name__)


# Process-wide reusable client (#151). Constructing an httpx.AsyncClient
# costs a TLS handshake on every speak() call; reusing one across the
# whole process keeps the connection pool warm so subsequent sentence
# chunks skip the handshake. Lazy-initialised so importing this module
# never spins up sockets at startup. Tests reset this between cases via
# a fixture; the real process never needs to.
_default_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _default_client
    if _default_client is None:
        _default_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        )
    return _default_client


async def speak(
    text: str,
    websocket: WebSocket,
    stream_sid: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    on_chunk: Optional[Callable[[bytes], None]] = None,
    on_first_byte: Optional[Callable[[], None]] = None,
) -> None:
    """Stream Deepgram Aura TTS audio back into the Twilio call.

    Requests ``encoding=mulaw`` at 8 kHz with no container — raw mulaw
    bytes that Twilio's Media Streams accepts directly. Each binary chunk
    is base64-encoded and sent as a Twilio ``media`` WebSocket event
    immediately, keeping latency low.
    """
    if not text.strip():
        return

    key = _api_key()
    model = settings.deepgram_tts_model
    url = f"{_DEEPGRAM_BASE}/speak"
    params = {
        "model": model,
        "encoding": "mulaw",
        "sample_rate": "8000",
        "container": "none",
    }

    headers = {
        "Authorization": f"Token {key}",
        "Content-Type": "application/json",
    }
    body = {"text": text}

    _client = client if client is not None else _get_client()
    first_byte_fired = False

    async with _client.stream("POST", url, headers=headers, params=params, json=body) as response:
        if response.status_code != 200:
            error_body = await response.aread()
            logger.error(
                "tts: Deepgram returned %d stream_sid=%s body=%s",
                response.status_code,
                stream_sid,
                error_body.decode(errors="replace")[:200],
            )
            raise RuntimeError(
                f"Deepgram returned {response.status_code}: {error_body.decode(errors='replace')}"
            )

        async for chunk in response.aiter_bytes():
            if not chunk:
                continue
            if not first_byte_fired and on_first_byte is not None:
                first_byte_fired = True
                try:
                    on_first_byte()
                except Exception:
                    logger.exception("tts: on_first_byte callback raised stream_sid=%s", stream_sid)
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
            if on_chunk is not None:
                try:
                    on_chunk(chunk)
                except Exception:
                    logger.exception("tts: on_chunk callback raised stream_sid=%s", stream_sid)
```

Note the differences from the original `app/tts/client.py`:
- `_DEEPGRAM_BASE` and `_api_key()` are imported from `app.deepgram` (shared with the future `app/deepgram/stt.py`).
- The `recording_session` parameter and its `app.storage.recordings` import are replaced by the more general `on_chunk` callback.
- Module docstring updated to "implementation" framing.

- [ ] **Step 4: Replace `app/tts/__init__.py` with the selector**

Overwrite `app/tts/__init__.py` (currently empty) with:

```python
"""Public entry point for the TTS abstraction layer.

Dispatches to the configured provider. Today only Deepgram is wired in;
adding ElevenLabs or another HTTP-streaming TTS is a one-clause addition
to ``speak()`` plus a new ``app/<vendor>/tts.py`` matching the SpeakFunc
contract from ``app/tts/base.py``.
"""

from __future__ import annotations

from typing import Callable, Optional

import httpx
from fastapi import WebSocket

from app.config import settings
from app.tts.base import SpeakFunc

__all__ = ["SpeakFunc", "speak"]


async def speak(
    text: str,
    websocket: WebSocket,
    stream_sid: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    on_chunk: Optional[Callable[[bytes], None]] = None,
    on_first_byte: Optional[Callable[[], None]] = None,
) -> None:
    """Synthesize ``text`` through the configured TTS provider and stream
    audio into the Twilio call via ``websocket``."""
    provider = settings.tts_provider
    if provider == "deepgram":
        from app.deepgram.tts import speak as _speak

        return await _speak(
            text,
            websocket,
            stream_sid,
            client=client,
            on_chunk=on_chunk,
            on_first_byte=on_first_byte,
        )
    raise ValueError(f"Unknown TTS provider: {provider}")
```

- [ ] **Step 5: Delete `app/tts/client.py`**

```bash
git rm app/tts/client.py
```

- [ ] **Step 6: Update import in `app/telephony/router.py:41`**

Edit `app/telephony/router.py`. Find:

```python
from app.tts.client import speak
```

Replace with:

```python
from app.tts import speak
```

- [ ] **Step 7: Add `_make_recording_chunk_handler` helper to `app/telephony/router.py`**

Find the `_state_rid` function (around line 365). Insert the new helper immediately before it:

```python
def _make_recording_chunk_handler(state: "_CallState") -> Callable[[bytes], None] | None:
    """Return a chunk handler that appends outbound TTS audio to the
    recording session, or None when no session is active.

    Returning None means ``speak()`` won't fire ``on_chunk`` at all,
    which is the desired behaviour when ``RECORDINGS_BUCKET`` is unset
    and ``state.recording_session`` therefore stays None.
    """
    if state.recording_session is None:
        return None
    rs = state.recording_session

    def _handle(chunk: bytes) -> None:
        try:
            recordings.append_chunks(rs, b"", chunk)
        except Exception:
            logger.exception(
                "tts: recording append failed call_sid=%s", state.call_sid
            )

    return _handle
```

- [ ] **Step 8: Update the five `speak(...)` call sites in `app/telephony/router.py`**

Each call site currently passes `recording_session=state.recording_session`. Replace with `on_chunk=_make_recording_chunk_handler(state)`.

Find each occurrence in `router.py` (lines ~377, ~487, ~505, ~1027 from the Step 6 grep) and convert. Example diff at line ~377:

```python
# Before
await speak(
    SILENCE_PROMPT,
    websocket,
    state.stream_sid,
    recording_session=state.recording_session,
)

# After
await speak(
    SILENCE_PROMPT,
    websocket,
    state.stream_sid,
    on_chunk=_make_recording_chunk_handler(state),
)
```

Repeat for all five call sites. Use `git diff app/telephony/router.py` to verify exactly five `recording_session=` removals and five `on_chunk=` additions.

- [ ] **Step 9: Rename `tests/test_tts_client.py` to `tests/test_deepgram_tts.py`**

```bash
git mv tests/test_tts_client.py tests/test_deepgram_tts.py
```

- [ ] **Step 10: Update imports and parameters inside `tests/test_deepgram_tts.py`**

Find every `from app.tts.client import` and replace with `from app.deepgram.tts import`. Find every `recording_session=` keyword argument in test calls to `speak(...)` and replace with `on_chunk=`. The corresponding test setup of mock recording sessions becomes a small inline `on_chunk` callback that records bytes into a list.

Example pattern: a test that previously did

```python
session = make_fake_recording_session()
await speak(text, ws, "MZ1", recording_session=session)
assert session.outbound_chunks == [b"hello"]
```

becomes

```python
captured: list[bytes] = []
await speak(text, ws, "MZ1", on_chunk=captured.append)
assert captured == [b"hello"]
```

Apply this pattern test-by-test. Don't change test names — keep the renames purely mechanical.

- [ ] **Step 11: Add a new test for `on_chunk` callback shape**

Append to `tests/test_deepgram_tts.py`:

```python
@pytest.mark.asyncio
async def test_on_chunk_receives_each_audio_chunk(monkeypatch):
    """Every non-empty body chunk Deepgram returns is forwarded to on_chunk."""
    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")

    chunks_seen: list[bytes] = []
    fake_chunks = [b"\x01\x02", b"\x03\x04", b"\x05"]

    async def fake_aiter_bytes():
        for c in fake_chunks:
            yield c

    response = AsyncMock()
    response.status_code = 200
    response.aiter_bytes = fake_aiter_bytes

    stream_cm = AsyncMock()
    stream_cm.__aenter__ = AsyncMock(return_value=response)
    stream_cm.__aexit__ = AsyncMock(return_value=None)

    fake_client = AsyncMock()
    fake_client.stream = MagicMock(return_value=stream_cm)

    ws = AsyncMock()
    ws.send_json = AsyncMock()

    await speak("hello", ws, "MZ123", client=fake_client, on_chunk=chunks_seen.append)

    assert chunks_seen == fake_chunks


@pytest.mark.asyncio
async def test_on_chunk_exceptions_are_swallowed(monkeypatch, caplog):
    """A buggy on_chunk callback never breaks a call."""
    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")

    async def fake_aiter_bytes():
        yield b"\x01"

    response = AsyncMock()
    response.status_code = 200
    response.aiter_bytes = fake_aiter_bytes

    stream_cm = AsyncMock()
    stream_cm.__aenter__ = AsyncMock(return_value=response)
    stream_cm.__aexit__ = AsyncMock(return_value=None)

    fake_client = AsyncMock()
    fake_client.stream = MagicMock(return_value=stream_cm)

    ws = AsyncMock()
    ws.send_json = AsyncMock()

    def bad(_chunk: bytes) -> None:
        raise RuntimeError("boom")

    # No exception escapes; the assertion is that this returns normally.
    await speak("hi", ws, "MZ123", client=fake_client, on_chunk=bad)
```

Add the imports at the top of the file if not already present:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.deepgram.tts import speak
```

- [ ] **Step 12: Create `tests/test_provider_selector.py` (TTS portion only — STT portion added in Task 6)**

```python
"""Tests for app/tts and app/stt selector functions.

Confirms the configured provider is dispatched to and unknown providers
raise. STT-side selector tests are added when get_stt() lands.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings


@pytest.mark.asyncio
async def test_speak_dispatches_to_deepgram_when_provider_is_deepgram(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "deepgram")
    fake_speak = AsyncMock()
    monkeypatch.setattr("app.deepgram.tts.speak", fake_speak)

    from app.tts import speak

    ws = MagicMock()
    await speak("hi", ws, "MZ1")
    fake_speak.assert_awaited_once()


@pytest.mark.asyncio
async def test_speak_raises_for_unknown_tts_provider(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "elevenlabs-not-implemented")
    from app.tts import speak

    ws = MagicMock()
    with pytest.raises(ValueError, match="Unknown TTS provider"):
        await speak("hi", ws, "MZ1")
```

- [ ] **Step 13: Run the full test suite**

Run: `python -m pytest tests/ -x --tb=short -q`
Expected: all tests pass. The renamed `test_deepgram_tts.py` runs in its new location; `test_telephony.py` still patches `_open_deepgram_connection` (we haven't removed it yet) but its `speak` patch path stays valid since `router.py` imports `speak` into its own namespace via `from app.tts import speak`.

If any `test_telephony.py` test fails because `monkeypatch.setattr("app.telephony.router.speak", fake_speak)` no longer hits the right object: confirm `from app.tts import speak` is at the top of `router.py` (Step 6). The patch path is namespace-relative, so it follows the binding in `router.py`'s module namespace.

- [ ] **Step 14: Commit**

```bash
git add app/config.py app/deepgram/__init__.py app/deepgram/tts.py app/tts/__init__.py app/telephony/router.py tests/test_deepgram_tts.py tests/test_provider_selector.py
git rm app/tts/client.py
git commit -m "refactor(tts): move Deepgram TTS to app/deepgram/tts.py

- Lift app/tts/client.py body into app/deepgram/tts.py
- Replace recording_session= parameter with general-purpose on_chunk
  callback; TTS no longer imports app.storage.recordings
- Add app/tts/__init__.py selector that dispatches by TTS_PROVIDER
- Add _make_recording_chunk_handler helper in router; pass on_chunk at
  the five call sites
- Rename tests/test_tts_client.py to tests/test_deepgram_tts.py and
  update imports + recording_session->on_chunk
- Add TTS-provider selector tests

Behaviour unchanged. Recording stays disabled on this branch
(RECORDINGS_BUCKET unset; state.recording_session is None;
_make_recording_chunk_handler returns None; on_chunk never fires).

Refs #250."
```

---

## Task 4: Implement DeepgramSTT plugin (α-4)

**Goal:** Concrete `STTProvider` for Deepgram. Bridges the SDK's callback API to the async-iterator contract via an internal queue. Not yet wired into `router.py`.

**Files:**
- Create: `app/deepgram/stt.py`
- Modify: `app/config.py`
- Create: `tests/test_stt_deepgram.py`

- [ ] **Step 1: Add STT settings to `app/config.py`**

Edit `app/config.py`. Add inside `Settings`, after `tts_provider`:

```python
    # STT provider selector. Today only "deepgram" is implemented.
    stt_provider: str = "deepgram"

    # Deepgram live STT options. Defaults match what was inline in
    # router.py before the plugin extraction; tuning is done by env var
    # rather than code change.
    stt_model: str = "nova-2"
    stt_endpointing_ms: int = 800
    stt_utterance_end_ms: int = 1000
    # Comma-separated keyterms. Only sent to Deepgram when non-empty,
    # and only respected by models that support keyterm prompting
    # (Nova-3 and later). Parsed lazily in app/deepgram/stt.py.
    stt_keyterms: str = ""
```

- [ ] **Step 2: Create `app/deepgram/stt.py`**

```python
"""Deepgram Nova live STT implementation.

Implements the STTProvider contract from app/stt/base.py. Bridges
Deepgram SDK's callback-based API onto the async-iterator interface
the router consumer expects, via one internal asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents

from app.config import settings
from app.deepgram import _api_key
from app.stt.base import STTEvent, SpeechStartedEvent, TranscriptEvent

logger = logging.getLogger(__name__)


_CLOSED = object()


@dataclass
class _ErrorBox:
    error: BaseException


def _parse_keyterms(raw: str) -> Optional[list[str]]:
    """Split STT_KEYTERMS env var into a list, or None when empty."""
    items = [t.strip() for t in raw.split(",") if t.strip()]
    return items or None


class DeepgramSTT:
    """Live Deepgram Nova STT provider.

    Lifecycle: ``open()`` opens the live WS and registers SDK callbacks
    that translate Deepgram events into STTEvents on an internal queue.
    ``send()`` forwards Twilio media-stream payloads. ``events()`` is an
    async generator that yields TranscriptEvent and SpeechStartedEvent
    objects until ``close()`` is called.
    """

    def __init__(self, *, call_sid: Optional[str] = None) -> None:
        self._call_sid = call_sid
        self._conn: Any = None
        self._queue: asyncio.Queue = asyncio.Queue()

    async def open(self) -> None:
        dg = DeepgramClient(_api_key())
        self._conn = dg.listen.asynclive.v("1")
        self._conn.on(LiveTranscriptionEvents.Transcript, self._on_transcript)
        self._conn.on(LiveTranscriptionEvents.Error, self._on_error)

        keyterms = _parse_keyterms(settings.stt_keyterms)

        # endpointing + utterance_end_ms together control how aggressively
        # Deepgram closes a turn. We picked 800/1000 after a 2026-04-26
        # Twilight test call where endpointing=300 fired ~7 false barge-ins
        # in 3 minutes — every micro-pause mid-sentence ("i would like to"
        # <breath> "have") was treated as a turn ending, and the AI kept
        # saying "take your time" because it thought the caller had spoken.
        # 800ms is Deepgram's recommended value for conversational flow;
        # utterance_end_ms=1000 layers a prosody-aware end-of-utterance
        # signal on top so we wait for "actually finished" instead of just
        # "stopped making noise".
        options = LiveOptions(
            model=settings.stt_model,
            encoding="mulaw",
            sample_rate=8000,
            channels=1,
            interim_results=True,
            endpointing=settings.stt_endpointing_ms,
            utterance_end_ms=settings.stt_utterance_end_ms,
            vad_events=True,
            keyterms=keyterms,
        )
        started = await self._conn.start(options)
        if not started:
            raise RuntimeError(
                f"Deepgram connection failed to start call_sid={self._call_sid}"
            )

    async def send(self, audio: bytes) -> None:
        if self._conn is None:
            return
        try:
            await self._conn.send(audio)
        except Exception:
            # Connection-level send failure: log and continue. The next
            # transcript will be incomplete; the silence watchdog absorbs
            # the resulting gap.
            logger.exception(
                "deepgram send failed call_sid=%s — call continues",
                self._call_sid,
            )

    async def events(self) -> AsyncIterator[STTEvent]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            if isinstance(item, _ErrorBox):
                raise RuntimeError(f"deepgram error: {item.error}")
            yield item

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.finish()
            except Exception:
                logger.exception(
                    "deepgram finish failed call_sid=%s", self._call_sid
                )
        self._queue.put_nowait(_CLOSED)

    # SDK callbacks ---------------------------------------------------
    async def _on_transcript(self, _self, result: Any, **_kwargs: Any) -> None:
        alt = result.channel.alternatives[0]
        text = alt.transcript.strip()
        if not text:
            return
        # Explicit None check — `or 1.0` would replace 0.0 (falsy) with
        # 1.0, masking a legitimate worst-case misheard signal.
        raw_confidence = getattr(alt, "confidence", 1.0)
        confidence = 1.0 if raw_confidence is None else raw_confidence

        is_final = bool(result.is_final)
        label = "final" if is_final else "interim"
        logger.info(
            "transcript [%s] call_sid=%s text=%r", label, self._call_sid, text
        )

        self._queue.put_nowait(
            TranscriptEvent(text=text, is_final=is_final, confidence=confidence)
        )

    async def _on_error(self, _self, error: Any, **_kwargs: Any) -> None:
        logger.error("deepgram error call_sid=%s error=%s", self._call_sid, error)
        self._queue.put_nowait(_ErrorBox(error))
```

Note: the `SpeechStarted` callback is **not** registered here yet. That happens in Task 7.

- [ ] **Step 3: Write `tests/test_stt_deepgram.py`**

```python
"""Tests for app/deepgram/stt.py — DeepgramSTT plugin.

The Deepgram SDK is the only thing mocked; everything else exercises
real plugin code (queue plumbing, callback wiring, options building).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.stt.base import TranscriptEvent


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """Every test needs the api key set so _api_key() doesn't raise."""
    from app.config import settings
    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")


@pytest.fixture
def fake_deepgram_client(monkeypatch):
    """Replace DeepgramClient inside app.deepgram.stt with a fake."""
    fake_conn = AsyncMock()
    fake_conn.send = AsyncMock()
    fake_conn.finish = AsyncMock()
    fake_conn.start = AsyncMock(return_value=True)
    fake_conn._handlers = {}

    def fake_on(event, handler):
        fake_conn._handlers[event] = handler

    fake_conn.on = MagicMock(side_effect=fake_on)

    fake_listen = MagicMock()
    fake_listen.asynclive.v = MagicMock(return_value=fake_conn)
    fake_client = MagicMock()
    fake_client.listen = fake_listen

    monkeypatch.setattr(
        "app.deepgram.stt.DeepgramClient",
        MagicMock(return_value=fake_client),
    )
    return fake_conn


@pytest.mark.asyncio
async def test_open_starts_connection_with_configured_options(
    fake_deepgram_client, monkeypatch,
):
    from app.config import settings
    from app.deepgram.stt import DeepgramSTT

    monkeypatch.setattr(settings, "stt_model", "nova-3")
    monkeypatch.setattr(settings, "stt_endpointing_ms", 600)
    monkeypatch.setattr(settings, "stt_utterance_end_ms", 1200)
    monkeypatch.setattr(settings, "stt_keyterms", "tikka,naan")

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()

    fake_deepgram_client.start.assert_awaited_once()
    options = fake_deepgram_client.start.await_args.args[0]
    assert options.model == "nova-3"
    assert options.endpointing == 600
    assert options.utterance_end_ms == 1200
    assert options.keyterms == ["tikka", "naan"]
    assert options.encoding == "mulaw"
    assert options.sample_rate == 8000


@pytest.mark.asyncio
async def test_keyterms_empty_string_yields_none(fake_deepgram_client, monkeypatch):
    from app.config import settings
    from app.deepgram.stt import DeepgramSTT

    monkeypatch.setattr(settings, "stt_keyterms", "")

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()

    options = fake_deepgram_client.start.await_args.args[0]
    assert options.keyterms is None


@pytest.mark.asyncio
async def test_open_raises_when_start_returns_false(fake_deepgram_client):
    from app.deepgram.stt import DeepgramSTT

    fake_deepgram_client.start = AsyncMock(return_value=False)
    stt = DeepgramSTT(call_sid="CAtest")
    with pytest.raises(RuntimeError, match="failed to start"):
        await stt.open()


@pytest.mark.asyncio
async def test_open_raises_when_api_key_missing(monkeypatch, fake_deepgram_client):
    from app.config import settings
    from app.deepgram.stt import DeepgramSTT

    monkeypatch.setattr(settings, "deepgram_api_key", None)
    stt = DeepgramSTT(call_sid="CAtest")
    with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY not set"):
        await stt.open()


@pytest.mark.asyncio
async def test_send_forwards_audio_to_sdk(fake_deepgram_client):
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    await stt.send(b"\x01\x02\x03")

    fake_deepgram_client.send.assert_awaited_once_with(b"\x01\x02\x03")


@pytest.mark.asyncio
async def test_send_swallows_sdk_exceptions(fake_deepgram_client, caplog):
    from app.deepgram.stt import DeepgramSTT

    fake_deepgram_client.send = AsyncMock(side_effect=RuntimeError("dropped"))
    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    # No exception escapes — log line proves we caught it.
    await stt.send(b"x")


@pytest.mark.asyncio
async def test_transcript_callback_emits_events_in_order(fake_deepgram_client):
    from deepgram import LiveTranscriptionEvents
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()

    handler = fake_deepgram_client._handlers[LiveTranscriptionEvents.Transcript]

    def make_result(text: str, is_final: bool, confidence: float):
        alt = SimpleNamespace(transcript=text, confidence=confidence)
        channel = SimpleNamespace(alternatives=[alt])
        return SimpleNamespace(channel=channel, is_final=is_final)

    await handler(stt, make_result("hi", False, 0.7))
    await handler(stt, make_result("hello", True, 0.95))

    received = []
    async def consume():
        async for event in stt.events():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await stt.close()
    await task

    assert received == [
        TranscriptEvent("hi", False, 0.7),
        TranscriptEvent("hello", True, 0.95),
    ]


@pytest.mark.asyncio
async def test_transcript_callback_skips_empty_text(fake_deepgram_client):
    from deepgram import LiveTranscriptionEvents
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    handler = fake_deepgram_client._handlers[LiveTranscriptionEvents.Transcript]

    alt = SimpleNamespace(transcript="   ", confidence=0.9)
    result = SimpleNamespace(
        channel=SimpleNamespace(alternatives=[alt]),
        is_final=True,
    )
    await handler(stt, result)

    received = []
    async def consume():
        async for event in stt.events():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await stt.close()
    await task

    assert received == []


@pytest.mark.asyncio
async def test_transcript_callback_normalizes_none_confidence(fake_deepgram_client):
    """Deepgram occasionally returns confidence=None; we replace with 1.0
    rather than 0.0 (which would mask worst-case misheard turns)."""
    from deepgram import LiveTranscriptionEvents
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    handler = fake_deepgram_client._handlers[LiveTranscriptionEvents.Transcript]

    alt = SimpleNamespace(transcript="ok", confidence=None)
    result = SimpleNamespace(
        channel=SimpleNamespace(alternatives=[alt]),
        is_final=True,
    )
    await handler(stt, result)

    received = []
    async def consume():
        async for event in stt.events():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await stt.close()
    await task

    assert len(received) == 1
    assert received[0].confidence == 1.0


@pytest.mark.asyncio
async def test_error_callback_surfaces_as_exception_from_events(fake_deepgram_client):
    from deepgram import LiveTranscriptionEvents
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    handler = fake_deepgram_client._handlers[LiveTranscriptionEvents.Error]
    await handler(stt, "ws closed unexpectedly")

    with pytest.raises(RuntimeError, match="deepgram error"):
        async for _event in stt.events():
            pass


@pytest.mark.asyncio
async def test_close_terminates_events_iterator(fake_deepgram_client):
    from app.deepgram.stt import DeepgramSTT

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    await stt.close()

    received = []
    async for event in stt.events():
        received.append(event)
    assert received == []
    fake_deepgram_client.finish.assert_awaited_once()
```

- [ ] **Step 4: Run the new tests, expect all pass**

Run: `python -m pytest tests/test_stt_deepgram.py -v`
Expected: 11 passed.

If a test fails on `options.keyterms` because the installed `deepgram` SDK version's `LiveOptions` doesn't accept `keyterms=`: the SDK is too old. Run `pip install --upgrade deepgram-sdk` and re-run. Spec assumes deepgram-sdk v3.11+ which supports the field.

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/deepgram/stt.py tests/test_stt_deepgram.py
git commit -m "feat(stt): implement DeepgramSTT plugin

DeepgramSTT translates the SDK's callback API into the async-iterator
contract the router consumer expects (TranscriptEvent + future
SpeechStartedEvent). Bridges via one internal asyncio.Queue. Open/send/
events/close lifecycle. Error callback surfaces as exception out of
events(); send() catches and logs SDK errors so transient issues don't
kill the call.

Adds STT_PROVIDER, STT_MODEL, STT_ENDPOINTING_MS, STT_UTTERANCE_END_MS,
STT_KEYTERMS to settings — defaults match the values inline in
router.py today, so behaviour is unchanged.

Not yet wired into router.py.

Refs #250."
```

---

## Task 5: Extract `_barge_in_now` helper (α-5)

**Goal:** Pull the cancel + flush + cancel-watchdog block out of `_handle_final_transcript` into a reusable helper, so the new VAD trigger (Task 7) can fire the same pipeline. Add `barge_in_trigger` field to `_CallState`. Update `_run_llm_tts_turn`'s `CancelledError` handler to read and clear it. Behavior is preserved exactly: a `barge_in` Firestore event still fires only on actual task cancellation.

**Files:**
- Modify: `app/telephony/router.py`
- Create: `tests/test_barge_in_helper.py`

- [ ] **Step 1: Add `barge_in_trigger` field to `_CallState` in `app/telephony/router.py`**

Find the `_CallState` dataclass (around line 250). Add the new field after `in_flight_transcript`:

```python
    # Set by _barge_in_now() before cancelling state.llm_task; read and
    # cleared by _run_llm_tts_turn's CancelledError handler when emitting
    # the barge_in Firestore event. None at all other times.
    barge_in_trigger: str | None = None
```

- [ ] **Step 2: Add `_barge_in_now` helper to `app/telephony/router.py`**

Find the `clear_twilio_audio` function (around line 237). Insert `_barge_in_now` immediately after it:

```python
async def _barge_in_now(
    state: "_CallState",
    websocket: WebSocket,
    *,
    trigger: str,
) -> None:
    """Stop the bot mid-utterance.

    Three mechanical steps:
      1. Cancel the in-flight LLM/TTS task → halt audio generation.
      2. Cancel the silence watchdog → caller is speaking; "are you still
         there?" would be wrong.
      3. Send Twilio 'clear' → flush already-buffered audio playback (#74).

    The barge_in Firestore event is NOT emitted here. It's emitted by
    _run_llm_tts_turn's existing CancelledError handler when the task we
    just cancelled actually receives the cancellation. Trigger
    information flows via state.barge_in_trigger, read and cleared
    inside that handler. This preserves today's invariant that barge_in
    events correspond to genuine task cancellations.
    """
    state.barge_in_trigger = trigger
    if state.llm_task and not state.llm_task.done():
        state.llm_task.cancel()
    _cancel_silence_task(state)
    await clear_twilio_audio(websocket, state.stream_sid)
```

- [ ] **Step 3: Update `_run_llm_tts_turn` `CancelledError` handler in `app/telephony/router.py`**

Find the existing handler (around line 567):

```python
    except asyncio.CancelledError:
        logger.info("llm_turn cancelled (barge-in) call_sid=%s", state.call_sid)
        _bg_call_event(state.call_sid, _state_rid(state), kind="barge_in")
        raise
```

Replace with:

```python
    except asyncio.CancelledError:
        trigger = state.barge_in_trigger or "unknown"
        state.barge_in_trigger = None
        logger.info(
            "llm_turn cancelled (barge-in trigger=%s) call_sid=%s",
            trigger,
            state.call_sid,
        )
        _bg_call_event(
            state.call_sid,
            _state_rid(state),
            kind="barge_in",
            detail={"trigger": trigger},
        )
        raise
```

- [ ] **Step 4: Update `_handle_final_transcript` in `app/telephony/router.py`**

Find the function (around line 585). Replace its body:

```python
async def _handle_final_transcript(text: str, state: _CallState, websocket: WebSocket) -> None:
    interrupted = bool(state.llm_task and not state.llm_task.done())
    # Carry forward — if any prior turn (cancelled or errored) left a
    # transcript on state without persisting it to history, prepend it
    # so Haiku sees the full caller intent in this turn (#170). The
    # field is cleared by ``_run_llm_tts_turn`` only on ``event.final``,
    # so a non-empty value here always means "user words from a prior
    # turn that never made it into history."
    if state.in_flight_transcript.strip():
        text = f"{state.in_flight_transcript} {text}".strip()
    silence_was_active = bool(state.silence_task and not state.silence_task.done())
    # Caller spoke — abort any pending auto-hangup (#78). Even if they
    # spoke during the grace window after a confirmation, we want to
    # keep the call alive and process this transcript.
    _abort_pending_hangup(state)

    if interrupted:
        # True barge-in: a turn is running and we're interrupting it.
        # The barge_in Firestore event fires from _run_llm_tts_turn's
        # CancelledError handler.
        await _barge_in_now(state, websocket, trigger="final_transcript")
    elif silence_was_active:
        # Caller resumed after a silence prompt — flush any leftover
        # prompt audio still buffered, but this isn't a barge-in (no
        # task to cancel, no event to emit).
        _cancel_silence_task(state)
        await clear_twilio_audio(websocket, state.stream_sid)

    state.in_flight_transcript = text
    state.llm_task = asyncio.create_task(_run_llm_tts_turn(text, state, websocket))
    state.llm_task.add_done_callback(lambda _t: _arm_silence_watchdog(state, websocket))
```

- [ ] **Step 5: Write `tests/test_barge_in_helper.py`**

```python
"""Tests for _barge_in_now() — the helper that stops the bot mid-utterance.

The helper itself does not emit a Firestore event; the event is emitted
by _run_llm_tts_turn's CancelledError handler when the cancellation we
trigger here actually propagates. These tests verify the mechanical
steps (task cancel, watchdog cancel, Twilio clear, trigger field set).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.telephony.router import _CallState, _barge_in_now


@pytest.mark.asyncio
async def test_cancels_running_llm_task():
    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZ1"
    async def long_task():
        await asyncio.sleep(60)
    state.llm_task = asyncio.create_task(long_task())

    ws = AsyncMock()
    await _barge_in_now(state, ws, trigger="vad")
    await asyncio.sleep(0)  # let cancellation propagate

    assert state.llm_task.cancelled()


@pytest.mark.asyncio
async def test_no_op_when_no_llm_task():
    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZ1"
    state.llm_task = None
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    # Should not raise.
    await _barge_in_now(state, ws, trigger="vad")
    ws.send_json.assert_awaited_once_with({"event": "clear", "streamSid": "MZ1"})


@pytest.mark.asyncio
async def test_cancels_silence_task():
    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZ1"
    async def long_silence():
        await asyncio.sleep(60)
    state.silence_task = asyncio.create_task(long_silence())

    ws = AsyncMock()
    ws.send_json = AsyncMock()
    await _barge_in_now(state, ws, trigger="vad")
    await asyncio.sleep(0)
    assert state.silence_task is None


@pytest.mark.asyncio
async def test_sends_twilio_clear_event():
    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZabc"
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    await _barge_in_now(state, ws, trigger="vad")
    ws.send_json.assert_awaited_once_with(
        {"event": "clear", "streamSid": "MZabc"}
    )


@pytest.mark.asyncio
async def test_sets_barge_in_trigger_on_state():
    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZ1"
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    await _barge_in_now(state, ws, trigger="final_transcript")
    assert state.barge_in_trigger == "final_transcript"


@pytest.mark.asyncio
async def test_swallows_websocket_disconnect_during_clear():
    """If the caller already hung up, sending clear raises but we must
    not let that exception escape into the call loop."""
    from starlette.websockets import WebSocketDisconnect

    state = _CallState(websocket=AsyncMock())
    state.stream_sid = "MZ1"
    ws = AsyncMock()
    ws.send_json = AsyncMock(side_effect=WebSocketDisconnect())
    # No exception escapes is the assertion.
    await _barge_in_now(state, ws, trigger="vad")
```

- [ ] **Step 6: Run the new tests + the existing barge-in tests**

Run: `python -m pytest tests/test_barge_in_helper.py tests/test_telephony.py -v --tb=short -q`
Expected: 6 new tests pass; existing telephony tests still pass (the helper change is behaviour-preserving for the final-transcript path).

If `test_telephony.py::test_*` fails because barge_in event detail now includes `{"trigger": "..."}`: update the assertion to either ignore detail or assert the trigger value matches.

- [ ] **Step 7: Commit**

```bash
git add app/telephony/router.py tests/test_barge_in_helper.py
git commit -m "refactor(telephony): extract _barge_in_now helper

Pull the cancel-task / cancel-watchdog / Twilio-clear pipeline out of
_handle_final_transcript into a reusable helper. Trigger flows through
state.barge_in_trigger to _run_llm_tts_turn's existing CancelledError
handler, which emits the barge_in Firestore event with the trigger in
detail. Behaviour preserved: events fire only on actual task
cancellations.

Sets up Task 7 (VAD speech-started -> instant barge-in) to use the
same helper.

Refs #250."
```

---

## Task 6: Wire DeepgramSTT into router (α-6)

**Goal:** Replace the inline Deepgram code in the `media_stream` WS handler with `get_stt()` + a `_consume_transcripts` background task. State mutation, Firestore emission, and dispatch into `_handle_final_transcript` move from the SDK callback into the consumer. Migrate the test fixture.

**Files:**
- Modify: `app/stt/__init__.py`
- Modify: `app/telephony/router.py`
- Modify: `tests/test_telephony.py`
- Modify: `tests/test_provider_selector.py`
- Create: `tests/test_transcript_consumer.py`

- [ ] **Step 1: Add `get_stt()` to `app/stt/__init__.py`**

Append to `app/stt/__init__.py`:

```python
def get_stt(*, call_sid: str | None = None) -> tuple["STTProvider", str]:
    """Return the configured STT provider plus its name.

    The name is returned alongside the provider so the caller (the router
    consumer) can include ``provider`` metadata in events when desired,
    without the plugin needing to know its own name.
    """
    from app.config import settings

    name = settings.stt_provider
    if name == "deepgram":
        from app.deepgram.stt import DeepgramSTT

        return DeepgramSTT(call_sid=call_sid), name
    raise ValueError(f"Unknown STT provider: {name}")


__all__ = [
    "STTEvent",
    "STTProvider",
    "SpeechStartedEvent",
    "TranscriptEvent",
    "get_stt",
]
```

- [ ] **Step 2: Add new fields to `_CallState` in `app/telephony/router.py`**

After the `barge_in_trigger` field added in Task 5, add:

```python
    # STT plugin lifecycle. Set on "start"; consumer task drains
    # stt.events() and is cancelled in the WS handler's finally block.
    stt: "STTProvider | None" = None
    stt_provider: str | None = None
    transcript_task: asyncio.Task | None = None
```

You'll also need to import `STTProvider` at the top of `router.py`. Add to existing imports:

```python
from app.stt import STTProvider, SpeechStartedEvent, TranscriptEvent, get_stt
```

- [ ] **Step 3: Add `_consume_transcripts` to `app/telephony/router.py`**

Insert immediately after `_arm_silence_watchdog` (around line 397):

```python
async def _consume_transcripts(
    stt: STTProvider,
    state: _CallState,
    websocket: WebSocket,
) -> None:
    """Background task consuming events from the STT plugin.

    All state mutation, Firestore emission, and dispatch into
    _handle_final_transcript happens here — the plugin is pure and
    knows nothing about call state.
    """
    try:
        async for event in stt.events():
            if isinstance(event, SpeechStartedEvent):
                # VAD branch handled in Task 7. Today: ignore.
                continue

            # event is a TranscriptEvent
            if not event.is_final:
                continue   # interim: captured in plugin logs only

            state.last_caller_transcript = event.text
            if event.confidence < 0.5:
                state.consecutive_low_confidence_turns += 1
            else:
                state.consecutive_low_confidence_turns = 0

            _bg_call_event(
                state.call_sid,
                _state_rid(state),
                kind="transcript_final",
                text=event.text,
                detail={"text": event.text, "confidence": event.confidence},
            )
            await _handle_final_transcript(event.text, state, websocket)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "transcript consumer crashed call_sid=%s", state.call_sid
        )
```

- [ ] **Step 4: Replace inline Deepgram code in `media_stream` WS handler**

In `media_stream` (around line 943), find the `dg_conn = None` line near the top of the handler. Remove it.

Find the `start` event branch (around line 1023) where `_open_deepgram_connection(...)` is called. Replace:

```python
                dg_conn = await _open_deepgram_connection(
                    state.call_sid, state.restaurant.id, on_final, state=state
                )
```

with:

```python
                state.stt, state.stt_provider = get_stt(call_sid=state.call_sid)
                try:
                    await state.stt.open()
                except Exception:
                    logger.exception(
                        "stt: failed to open call_sid=%s", state.call_sid
                    )
                    _bg_call_event(
                        state.call_sid,
                        state.restaurant.id,
                        kind="error",
                        text="STT failed to open",
                        detail={"provider": state.stt_provider},
                    )
                    return
                state.transcript_task = asyncio.create_task(
                    _consume_transcripts(state.stt, state, websocket)
                )
```

Also remove the now-unused `on_final` inner function (around line 957) and any reference to `dg_conn`.

In the `media` event branch (around line 1044), find:

```python
                    if dg_conn is not None:
                        await dg_conn.send(payload)
```

Replace with:

```python
                    if state.stt is not None:
                        await state.stt.send(payload)
```

In the WS handler's `finally` block (around line 1164), find:

```python
        if dg_conn is not None:
            await dg_conn.finish()
```

Replace with:

```python
        if state.transcript_task and not state.transcript_task.done():
            state.transcript_task.cancel()
        if state.stt is not None:
            await state.stt.close()
```

- [ ] **Step 5: Remove `_open_deepgram_connection` and Deepgram SDK imports from `router.py`**

Delete the entire `_open_deepgram_connection` function (lines 294–362 in the pre-refactor file).

Delete the line at the top of the file:

```python
from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
```

Run `python -m pyflakes app/telephony/router.py` to confirm no remaining references. If pyflakes isn't installed: `python -c "import ast; ast.parse(open('app/telephony/router.py').read())"` at minimum confirms the file still parses.

- [ ] **Step 6: Migrate `mock_pipeline` fixture in `tests/test_telephony.py`**

Find the `mock_pipeline` fixture (around line 77). Replace its body:

```python
@pytest.fixture()
def mock_pipeline(monkeypatch):
    """Patch all four network-bound callables for offline testing."""
    from tests.fakes.stt import FakeSTT

    fake_stt = FakeSTT()

    def fake_get_stt(**kwargs):
        return fake_stt, "deepgram"

    async def fake_speak(text, websocket, stream_sid, **kw):
        pass

    from app.storage import call_sessions

    monkeypatch.setattr("app.telephony.router.get_stt", fake_get_stt)
    monkeypatch.setattr("app.telephony.router.speak", fake_speak)
    monkeypatch.setattr("app.telephony.router.stream_reply", _make_fake_stream_reply())
    monkeypatch.setattr(call_sessions, "init_call_session", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "record_event", lambda *a, **kw: None)
    monkeypatch.setattr(call_sessions, "mark_call_ended", lambda *a, **kw: None)
    return fake_stt
```

- [ ] **Step 7: Collapse the five ad-hoc `fake_open_dg` patch blocks in `tests/test_telephony.py`**

Search for `monkeypatch.setattr("app.telephony.router._open_deepgram_connection"` in the test file. Each match is inside a test function that builds its own AsyncMock and patches piece-by-piece. Convert each test to use the `mock_pipeline` fixture:

```python
# Before
def test_some_flow(monkeypatch):
    fake_dg = AsyncMock()
    fake_dg.send = AsyncMock()
    fake_dg.finish = AsyncMock()
    async def fake_open_dg(call_sid, restaurant_id, on_final, **kwargs):
        return fake_dg
    async def fake_speak(text, websocket, stream_sid, **kw):
        pass
    monkeypatch.setattr("app.telephony.router._open_deepgram_connection", fake_open_dg)
    monkeypatch.setattr("app.telephony.router.speak", fake_speak)
    ...
    # uses fake_dg.send

# After
def test_some_flow(mock_pipeline):
    # mock_pipeline is the FakeSTT — use mock_pipeline.sent for assertions
    ...
```

For tests that previously asserted on `fake_dg.send.call_args_list`, switch to `mock_pipeline.sent` (which is a list of bytes payloads in the order they arrived). For tests that previously asserted `fake_dg.finish.assert_awaited_once()`, switch to `mock_pipeline.closed is True`.

- [ ] **Step 8: Add STT-side tests to `tests/test_provider_selector.py`**

Append to the file:

```python
def test_get_stt_returns_deepgram_by_default(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "deepgram")
    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")

    from app.deepgram.stt import DeepgramSTT
    from app.stt import get_stt

    provider, name = get_stt(call_sid="CAtest")
    assert isinstance(provider, DeepgramSTT)
    assert name == "deepgram"


def test_get_stt_raises_for_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "whisper-not-implemented")
    from app.stt import get_stt

    with pytest.raises(ValueError, match="Unknown STT provider"):
        get_stt(call_sid="CAtest")
```

- [ ] **Step 9: Write `tests/test_transcript_consumer.py`**

```python
"""Tests for _consume_transcripts in app/telephony/router.py.

The consumer is the router's bridge between the STT plugin and call
state. We feed scripted events into a FakeSTT and assert state changes,
Firestore emissions, and dispatch into _handle_final_transcript.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.stt.base import SpeechStartedEvent, TranscriptEvent
from app.telephony.router import _CallState, _consume_transcripts
from tests.fakes.stt import FakeSTT


def _make_state() -> _CallState:
    state = _CallState(websocket=AsyncMock())
    state.call_sid = "CAtest"
    state.stream_sid = "MZ1"
    return state


@pytest.mark.asyncio
async def test_interim_transcripts_ignored(monkeypatch):
    """Interims arrive on the queue but cause no state mutation, no
    Firestore call, no _handle_final_transcript dispatch."""
    state = _make_state()
    handler = AsyncMock()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", handler
    )
    bg = MagicMock()
    monkeypatch.setattr("app.telephony.router._bg_call_event", bg)

    fake = FakeSTT(events=[TranscriptEvent("partial", False, 0.7)])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    handler.assert_not_called()
    bg.assert_not_called()
    assert state.last_caller_transcript == ""


@pytest.mark.asyncio
async def test_final_transcript_mutates_state_and_dispatches(monkeypatch):
    state = _make_state()
    handler = AsyncMock()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", handler
    )
    bg = MagicMock()
    monkeypatch.setattr("app.telephony.router._bg_call_event", bg)

    ws = AsyncMock()
    fake = FakeSTT(events=[TranscriptEvent("two pizzas", True, 0.9)])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, ws))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert state.last_caller_transcript == "two pizzas"
    handler.assert_awaited_once_with("two pizzas", state, ws)
    bg.assert_called_once()
    args, kwargs = bg.call_args
    assert kwargs["kind"] == "transcript_final"


@pytest.mark.asyncio
async def test_low_confidence_increments_counter(monkeypatch):
    state = _make_state()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", AsyncMock()
    )
    monkeypatch.setattr("app.telephony.router._bg_call_event", MagicMock())

    fake = FakeSTT(events=[
        TranscriptEvent("muffled", True, 0.3),
        TranscriptEvent("still muffled", True, 0.4),
    ])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert state.consecutive_low_confidence_turns == 2


@pytest.mark.asyncio
async def test_high_confidence_resets_counter(monkeypatch):
    state = _make_state()
    state.consecutive_low_confidence_turns = 3
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", AsyncMock()
    )
    monkeypatch.setattr("app.telephony.router._bg_call_event", MagicMock())

    fake = FakeSTT(events=[TranscriptEvent("clear", True, 0.95)])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert state.consecutive_low_confidence_turns == 0


@pytest.mark.asyncio
async def test_speech_started_currently_ignored(monkeypatch):
    """Until Task 7 wires VAD-triggered barge-in, SpeechStartedEvents
    are silently dropped by the consumer."""
    state = _make_state()
    handler = AsyncMock()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", handler
    )

    fake = FakeSTT(events=[SpeechStartedEvent()])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    handler.assert_not_called()


@pytest.mark.asyncio
async def test_consumer_logs_and_exits_on_stt_error(monkeypatch, caplog):
    state = _make_state()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", AsyncMock()
    )

    fake = FakeSTT()
    await fake.open()
    fake.feed_error(RuntimeError("dropped"))

    # Consumer catches the exception and exits cleanly.
    await _consume_transcripts(fake, state, AsyncMock())


@pytest.mark.asyncio
async def test_consumer_propagates_cancellation(monkeypatch):
    state = _make_state()
    monkeypatch.setattr(
        "app.telephony.router._handle_final_transcript", AsyncMock()
    )

    fake = FakeSTT()
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
```

- [ ] **Step 10: Run the full suite**

Run: `python -m pytest tests/ -x --tb=short -q`
Expected: every test passes — the new consumer tests, the migrated telephony tests, the deepgram tests, the selector tests, the fake-stt tests, and every pre-existing test.

If `tests/test_telephony.py` fails on a previously-passing test: the most likely cause is an ad-hoc patch block that wasn't migrated. Search for `_open_deepgram_connection` in the test file — it should appear zero times after this task.

- [ ] **Step 11: Commit**

```bash
git add app/stt/__init__.py app/telephony/router.py tests/test_telephony.py tests/test_transcript_consumer.py tests/test_provider_selector.py
git commit -m "feat(telephony): replace inline Deepgram with STTProvider

Wire get_stt() and _consume_transcripts into the media-stream WS
handler. State mutation, Firestore emission, and dispatch into
_handle_final_transcript move from the SDK callback closure into the
consumer task. _open_deepgram_connection and the 'from deepgram import'
line are removed from router.py.

Migrates tests/test_telephony.py mock_pipeline fixture to inject
FakeSTT; collapses five ad-hoc patch blocks into the fixture.

Behaviour preserved. Instant barge-in via VAD speech-started lands in
the next commit.

Refs #250."
```

---

## Task 7: Instant barge-in via VAD speech-started (α-7)

**Goal:** Subscribe to Deepgram's `SpeechStarted` event in the plugin; consumer fires `_barge_in_now(trigger="vad")` when one arrives during an in-flight turn. Add `STT_INSTANT_BARGE_IN` kill-switch.

**Files:**
- Modify: `app/config.py`
- Modify: `app/deepgram/stt.py`
- Modify: `app/telephony/router.py`
- Modify: `tests/test_stt_deepgram.py`
- Modify: `tests/test_transcript_consumer.py`

- [ ] **Step 1: Add `stt_instant_barge_in` setting to `app/config.py`**

After `stt_keyterms`, add:

```python
    # Instant barge-in via Deepgram VAD speech-started events. When True
    # (default), a barge-in fires ~50ms after the caller begins speaking
    # instead of waiting for the final transcript (~800-1800ms). Flip to
    # False if VAD turns out to misfire on coughs or background noise on
    # a real call — the call falls back to the existing final-transcript
    # barge-in path with no other changes.
    stt_instant_barge_in: bool = True
```

- [ ] **Step 2: Subscribe to SpeechStarted in `app/deepgram/stt.py`**

Inside `DeepgramSTT.open()`, after the existing `self._conn.on(LiveTranscriptionEvents.Error, ...)` line, add:

```python
        self._conn.on(
            LiveTranscriptionEvents.SpeechStarted, self._on_speech_started
        )
```

Add the new callback method on the class:

```python
    async def _on_speech_started(
        self, _self, _event: Any = None, **_kwargs: Any
    ) -> None:
        logger.info("speech_started call_sid=%s", self._call_sid)
        self._queue.put_nowait(SpeechStartedEvent())
```

Update the import at the top of `app/deepgram/stt.py` so `SpeechStartedEvent` is available:

```python
from app.stt.base import STTEvent, SpeechStartedEvent, TranscriptEvent
```

- [ ] **Step 3: Update `_consume_transcripts` in `app/telephony/router.py`**

Find the existing speech-started branch (currently `# VAD branch handled in Task 7. Today: ignore.`):

```python
            if isinstance(event, SpeechStartedEvent):
                # VAD branch handled in Task 7. Today: ignore.
                continue
```

Replace with:

```python
            if isinstance(event, SpeechStartedEvent):
                if not settings.stt_instant_barge_in:
                    continue
                if state.llm_task and not state.llm_task.done():
                    await _barge_in_now(state, websocket, trigger="vad")
                continue
```

`settings` is already imported at the top of `router.py`.

- [ ] **Step 4: Add VAD-event test to `tests/test_stt_deepgram.py`**

Append:

```python
@pytest.mark.asyncio
async def test_speech_started_callback_emits_event(fake_deepgram_client):
    """Deepgram's SpeechStarted event becomes a SpeechStartedEvent on
    the queue."""
    from deepgram import LiveTranscriptionEvents
    from app.deepgram.stt import DeepgramSTT
    from app.stt.base import SpeechStartedEvent

    stt = DeepgramSTT(call_sid="CAtest")
    await stt.open()
    handler = fake_deepgram_client._handlers[LiveTranscriptionEvents.SpeechStarted]
    await handler(stt, None)

    received = []
    async def consume():
        async for event in stt.events():
            received.append(event)
    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await stt.close()
    await task

    assert len(received) == 1
    assert isinstance(received[0], SpeechStartedEvent)
```

- [ ] **Step 5: Add VAD-trigger tests to `tests/test_transcript_consumer.py`**

Append:

```python
@pytest.mark.asyncio
async def test_speech_started_triggers_barge_in_when_llm_task_running(monkeypatch):
    state = _make_state()

    async def long_turn():
        await asyncio.sleep(60)
    state.llm_task = asyncio.create_task(long_turn())

    barge_in_calls = []
    async def fake_barge(state_, ws_, *, trigger):
        barge_in_calls.append(trigger)
    monkeypatch.setattr("app.telephony.router._barge_in_now", fake_barge)

    fake = FakeSTT(events=[SpeechStartedEvent()])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert barge_in_calls == ["vad"]


@pytest.mark.asyncio
async def test_speech_started_no_op_when_no_llm_task(monkeypatch):
    state = _make_state()
    state.llm_task = None

    barge_in_calls = []
    async def fake_barge(state_, ws_, *, trigger):
        barge_in_calls.append(trigger)
    monkeypatch.setattr("app.telephony.router._barge_in_now", fake_barge)

    fake = FakeSTT(events=[SpeechStartedEvent()])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert barge_in_calls == []


@pytest.mark.asyncio
async def test_speech_started_disabled_by_setting(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "stt_instant_barge_in", False)
    state = _make_state()

    async def long_turn():
        await asyncio.sleep(60)
    state.llm_task = asyncio.create_task(long_turn())

    barge_in_calls = []
    async def fake_barge(state_, ws_, *, trigger):
        barge_in_calls.append(trigger)
    monkeypatch.setattr("app.telephony.router._barge_in_now", fake_barge)

    fake = FakeSTT(events=[SpeechStartedEvent()])
    await fake.open()
    task = asyncio.create_task(_consume_transcripts(fake, state, AsyncMock()))
    await asyncio.sleep(0)
    await fake.close()
    await task

    assert barge_in_calls == []
```

- [ ] **Step 6: Update the placeholder consumer test from Task 6**

In `tests/test_transcript_consumer.py`, replace `test_speech_started_currently_ignored` (the placeholder from Task 6) with the actual VAD branch tests above. Delete the placeholder test.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest tests/ -x --tb=short -q`
Expected: every test passes.

- [ ] **Step 8: Commit**

```bash
git commit -am "feat(telephony): instant barge-in via VAD speech-started

Subscribe to Deepgram's SpeechStarted event in DeepgramSTT; consumer
fires _barge_in_now(trigger='vad') when one arrives during an
in-flight LLM/TTS turn. Cuts barge-in latency from ~800-1800ms (waiting
for a final transcript) to ~50ms (VAD signal).

Adds STT_INSTANT_BARGE_IN env-var kill-switch (default True). Set to
False if VAD turns out to misfire on coughs or background noise during
a real call — the existing final-transcript barge-in path is unchanged
and absorbs the fallback case.

Refs #250."
```

---

## Phase α complete

After Task 7, the structural extraction is finished. Bot behavior matches today **except** instant barge-in is on by default. The first real test call should sound like today's bot but pause faster when interrupted.

### Verification before declaring α done

- [ ] **Run the full test suite once more.**

Run: `python -m pytest tests/ --tb=short -q`
Expected: 100% pass.

- [ ] **Run pre-commit hooks (ruff format, ruff check).**

Run: `pre-commit run --all-files`
Expected: pass with no auto-formatting changes left in the working tree (commit any auto-formatting that does happen).

- [ ] **Confirm `_open_deepgram_connection` and `from deepgram import` no longer appear in `router.py`.**

Run: `grep -n "_open_deepgram_connection\|from deepgram" app/telephony/router.py`
Expected: no matches.

- [ ] **Confirm `app/tts/client.py` is gone.**

Run: `ls app/tts/`
Expected: `__init__.py base.py` and nothing else.

- [ ] **First test call.** Place a real test call to the niko-pizza-kitchen Twilio number. Verify:
  - Bot greets normally.
  - Caller is transcribed correctly (check Cloud Logging for `transcript [final]` lines).
  - Order can be placed end-to-end.
  - Barge-in by speaking over the bot mid-sentence — bot should stop within ~500ms (instant barge-in is on).
  - Recording stays disabled (no GCS uploads, no errors).

If the first test call sounds wrong: revert via `STT_INSTANT_BARGE_IN=False` env var (no code change) and verify the call now matches today's behavior.

---

## Phase β — tuning iterations

β commits are open-ended and judged by test calls. Each is one or two of:

- env var flip → test call → keep / revert / retune
- prompt edit in `app/llm/prompts.py` → test call → keep / revert
- small router tweak (silence prompt copy, hangup grace seconds, etc.) → test call → keep / revert

What this push enables:

| Knob | Try | Expected effect |
|---|---|---|
| `STT_MODEL=nova-3` | Retry the reverted #199 model bump | Better recognition on menu-item names |
| `STT_KEYTERMS=tikka,naan,paneer,...` | Send menu vocabulary | Fewer mishears (Nova-3 only) |
| `STT_ENDPOINTING_MS=600` | Tighten | Bot interrupts caller mid-thought (likely too low) |
| `STT_ENDPOINTING_MS=1000` | Loosen | Long pauses before bot replies (likely too high) |
| `STT_INSTANT_BARGE_IN=False` | Disable VAD | If barge-in misfires on coughs |
| `DEEPGRAM_TTS_MODEL=...` | Try a different Aura voice | TTS naturalness |

β commits use the same atomic-commit discipline. Anything bigger than a config flip lands as its own α-style commit with tests.

---

## Final merge to master

When call quality is where you want it:

- [ ] **Tests green:** `python -m pytest tests/`
- [ ] **Hooks green:** `pre-commit run --all-files`
- [ ] **Three consecutive clean test calls** demonstrating the conversational quality goal of #83.
- [ ] **Master rebase clean:** `git fetch origin master && git rebase origin/master` with no conflicts deferred.
- [ ] **Open PR** referencing both #83 and #250. Structure the description with α (extraction list) separately from β (behavior changes).

---

## Self-review checklist (run before handing off to executor)

This was checked while writing the plan; documenting for transparency:

- **Spec coverage:** Module layout (Tasks 1, 3, 4), STT contract (Task 1), TTS contract (Task 1, Task 3 implementation), consumer + barge-in (Task 5, Task 6, Task 7), config (Tasks 3, 4, 7), error handling (covered in DeepgramSTT, consumer, and WS handler updates), observability (no new event kinds; `barge_in` detail extension in Task 5), testing strategy (FakeSTT in Task 2, dedicated test files per task), migration sequence (Tasks 1–7).
- **Type consistency:** `STTProvider`, `TranscriptEvent`, `SpeechStartedEvent`, `STTEvent`, `SpeakFunc`, `_CallState` field names verified consistent across tasks. `get_stt(call_sid=...)` returns `(STTProvider, str)` everywhere it's called. `_barge_in_now(state, websocket, *, trigger)` signature matches in helper, in `_handle_final_transcript`, and in the consumer.
- **Placeholders:** None. Every step has actual code, exact commands, expected output, or named files.
