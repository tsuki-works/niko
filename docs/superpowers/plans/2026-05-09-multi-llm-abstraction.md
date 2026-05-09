# Multi-LLM provider abstraction

## Context

Today the LLM call path is hardcoded to Anthropic Claude Haiku 4.5. The wire-format code, the domain logic (apply/validate/summarize an `update_order` patch), and the public contract (`StreamEvent`, `LLMResponse`) all live in one 742-line file at `app/llm/client.py`. The router/session import `stream_reply` directly:

- `app/telephony/session.py:26` — `from app.llm.client import stream_reply`
- `app/telephony/session.py:487` — `async for event in stream_reply(...)`

There is no provider seam analogous to the one we already have for STT (`app/stt/__init__.py:get_stt()`) and TTS (`app/tts/__init__.py:speak()`). The router doesn't *contain* LLM logic, but it's directly bound to the Anthropic implementation.

**Goal:** introduce a provider seam so a future OpenAI/Gemini/etc. provider becomes a one-clause add to a factory, *without* implementing a second provider yet. The seam should match the STT/TTS pattern (global env var selects provider) and keep the `update_order` tool definition provider-neutral.

User-confirmed scope:
- Just abstract for now — Anthropic stays the only implementation.
- Provider chosen by a global env var (`llm_provider`), matching `stt_provider` / `tts_provider`.
- Tool schema kept provider-neutral, adapted per-provider at the edges.

## Approach

Split `app/llm/client.py` into three concerns and add a factory.

### Final layout

```
app/llm/
  __init__.py        # get_llm() factory + re-exports
  base.py            # public contract (Protocol + dataclasses + neutral tool spec)
  orchestration.py   # provider-neutral domain helpers
  anthropic.py       # Anthropic implementation (renamed from client.py)
  prompts.py         # unchanged
```

### `app/llm/base.py` (new)

Move from `client.py`:

- `StreamEvent` dataclass (currently `client.py:111-141`)
- `LLMResponse` dataclass (currently `client.py:104-108`)

Add new:

- `ToolSpec` dataclass — provider-neutral tool definition: `name`, `description`, `parameters` (JSON Schema dict). This is what `UPDATE_ORDER_TOOL` already is, minus the Anthropic-shaped key name (`input_schema` → `parameters`).
- `UPDATE_ORDER_TOOL_SPEC: ToolSpec` — the canonical tool definition. Each provider adapts it to its native wire shape (`AnthropicLLM` wraps `parameters` as `input_schema`; a future OpenAI provider would wrap as `{"type": "function", "function": {...}}`).
- `LLMProvider(Protocol)` — public interface:
  ```python
  class LLMProvider(Protocol):
      async def stream_reply(
          self, *, transcript: str, history: list[dict[str, Any]],
          order: Order, system_prompt: str,
      ) -> AsyncIterator[StreamEvent]: ...

      def generate_reply(
          self, *, transcript: str, history: list[dict[str, Any]],
          order: Order, system_prompt: str,
      ) -> LLMResponse: ...
  ```
  `history` stays as `list[dict[str, Any]]` and is opaque to the router — each provider owns its own message shape and threads it back. No cross-provider history normalization at this stage (would be a bigger refactor; revisit when a second provider lands).

### Streaming event abstraction

Anthropic, OpenAI, and Gemini all emit *different* native streaming event shapes. The point of `StreamEvent` is that each provider consumes its own native events internally and translates them into the three neutral kinds the router cares about — `text_delta`, `timing`, `final`. The router never sees raw provider events; that's the whole reason `StreamEvent` exists. Today the Anthropic translation happens inline in `client.py:578-606`; after the refactor it lives inside `AnthropicLLM.stream_reply` and is invisible to callers.

### Known leak — Anthropic-flavored timing payload

The current `timing` payload sits in the neutral `StreamEvent` contract but four of its six fields are Anthropic-specific:

- `ttft_seconds` — neutral, every provider can report this.
- `tool_prefix_seconds` — neutral, gap between first event and first text block.
- `network_prefill_seconds` / `decode_seconds` — split using Anthropic's `message_start` event. OpenAI's chat-completion stream has no equivalent dividing line.
- `cache_read_tokens` / `cache_creation_tokens` — Anthropic prompt-caching headers. OpenAI exposes `cached_tokens` (one number, not two); Gemini doesn't expose this in usage today.

Two options for this refactor:

- **(picked) Keep schema as-is, document optionality.** `base.py` declares `ttft_seconds` required and the four Anthropic-flavored fields best-effort (providers without equivalents report `0`). No schema churn now; revisit when a second provider actually lands and we know what it can give us.
- **(deferred) Restructure as `{ttft_seconds: float, extras: dict[str, Any]}`** — cleaner separation, but it's churn for a hypothetical. Skip until the second provider exists.

This is the one acknowledged sharp edge in the abstraction. Flag in `base.py` docstring as "TODO: revisit timing schema when adding a second provider."

### Known leak — history is provider-private

`LLMResponse.history` is typed as `list[dict[str, Any]]` and is opaque to the router. But the shape inside it is **provider-private**: Anthropic uses `{"role": ..., "content": [{"type": "tool_use", ...}, ...]}` with `cache_control` markers; OpenAI would use `{"role": ..., "tool_calls": [...]}`. The router stores `state.history` and threads it back into the next turn — that only works if the *same provider* handles both turns.

Today this is fine: provider is selected once via env var and stays for the process lifetime. Document this constraint in `base.py`:

> History returned by a provider must only be passed back to the *same* provider on subsequent turns. Provider hot-swap within a call is not supported. If providers are switched (config change + restart), in-flight calls finish on the original provider; new calls start fresh.

A future cross-provider history normalization (neutral `Conversation` log that providers translate to/from their wire shape) is a bigger refactor — explicitly out of scope here.

### Per-provider model + token-limit config

Haiku and the 512-token cap are hardcoded as module constants today (`client.py:35-36`). Move them to `app/config.py` so swapping to Sonnet/Opus is an env change, not a code edit. Pattern matches `deepgram_tts_model` / `stt_model`:

```python
# In app/config.py, alongside llm_provider:
anthropic_model: str = "claude-haiku-4-5-20251001"
anthropic_max_tokens: int = 512
```

`AnthropicLLM.__init__` reads them from `settings` and stores on the instance:

```python
def __init__(self, *, async_client=None, sync_client=None,
                   model: Optional[str] = None,
                   max_tokens: Optional[int] = None) -> None:
    self._model = model or settings.anthropic_model
    self._max_tokens = max_tokens or settings.anthropic_max_tokens
    ...
```

The constructor args are for tests / future per-call overrides; production reads from env. All five `api.messages.create(...)` / `api.messages.stream(...)` call sites in `anthropic.py` swap `MODEL` → `self._model` and `MAX_TOKENS` → `self._max_tokens`. Drop the module-level `MODEL` / `MAX_TOKENS` constants.

When a future second Anthropic-family provider variant is needed (e.g. a separate `AnthropicSonnetLLM`), it's just a different default — no new class required. For now: one `AnthropicLLM`, one env var, swap models freely.

### `app/llm/orchestration.py` (new)

Move provider-neutral domain helpers from `client.py`:

- `_apply_update` (`client.py:385-401`) → public `apply_order_patch`
- `_apply_validation` (`client.py:328-359`) → public `validate_order_patch`
- `_summarize_order` (`client.py:208-225`) → public `summarize_order_for_tool_result`
- `_should_skip_followup` (`client.py:365-382`) → public `should_skip_followup`
- `_TERMINAL_STATUSES`, `_INVALID_ADDRESS_NOTE` constants

These are pure domain functions shared across any provider. Renaming drops the leading underscore since they're now part of an inter-module API. Keep signatures identical so the diff in `anthropic.py` is just import-path swaps.

### `app/llm/anthropic.py` (renamed from `client.py`)

Keep all Anthropic wire-format code:

- `MODEL = "claude-haiku-4-5-20251001"`, `MAX_TOKENS`
- `_serialize_block`, `_system_cache_block`, `_with_rolling_cache_breakpoint`, `_append_user_transcript`, `_tool_result_block`
- Latency timing helpers (`_make_timing_event`, etc.)
- `_get_async_client`, `_reset_async_client`, `_client`, `_missing_key_error` (process-wide AsyncAnthropic singleton stays)

Refactor the entry points into a class:

```python
class AnthropicLLM:
    def __init__(self, *, async_client: Optional[AsyncAnthropic] = None,
                       sync_client: Optional[Anthropic] = None) -> None:
        self._async_client = async_client
        self._sync_client = sync_client

    def generate_reply(self, *, transcript, history, order, system_prompt) -> LLMResponse:
        # body of current generate_reply, swapped to self._sync_client or _client()

    async def stream_reply(self, *, transcript, history, order, system_prompt
                          ) -> AsyncIterator[StreamEvent]:
        # body of current stream_reply, swapped to self._async_client or _get_async_client()
```

The optional `async_client` / `sync_client` constructor args replace today's `client=` kwarg on the module-level functions — that's the test-injection seam.

Tool schema rendering: `AnthropicLLM` translates `UPDATE_ORDER_TOOL_SPEC` from `base.py` into Anthropic's `{name, description, input_schema}` shape at module top-level so the cached `tools=[...]` list stays a constant.

Drop the module-level `stream_reply` / `generate_reply` functions — callers now go through `AnthropicLLM(...)` or the factory.

### `app/llm/__init__.py` (replace empty file)

Mirror `app/stt/__init__.py`:

```python
from app.llm.base import (
    LLMProvider,
    LLMResponse,
    StreamEvent,
    ToolSpec,
    UPDATE_ORDER_TOOL_SPEC,
)

__all__ = [
    "LLMProvider", "LLMResponse", "StreamEvent",
    "ToolSpec", "UPDATE_ORDER_TOOL_SPEC", "get_llm",
]


def get_llm() -> LLMProvider:
    from app.config import settings
    name = settings.llm_provider
    if name == "anthropic":
        from app.llm.anthropic import AnthropicLLM
        return AnthropicLLM()
    raise ValueError(f"Unknown LLM provider: {name}")
```

Lazy import inside the factory so importing `app.llm` doesn't pull the Anthropic SDK on cold start (matches `app/stt/__init__.py:44-50`).

### `app/config.py`

Add at line ~36 (next to `stt_provider`):

```python
# LLM provider selector. Today only "anthropic" is implemented.
llm_provider: str = "anthropic"

# Anthropic model + reply cap. Was hardcoded in app/llm/client.py;
# pulled into config so a model swap (Haiku → Sonnet → Opus) is an
# env change, not a code edit.
anthropic_model: str = "claude-haiku-4-5-20251001"
anthropic_max_tokens: int = 512
```

### `app/telephony/session.py`

Two-line change:

- Line 26: `from app.llm.client import stream_reply` → `from app.llm import get_llm`
- Line 487: `async for event in stream_reply(...)` → `async for event in get_llm().stream_reply(...)`

`get_llm()` is called per-turn. The Anthropic provider construction is cheap (the underlying `AsyncAnthropic` client stays a process-wide singleton via `_get_async_client`), so this matches how `get_stt()` is called per-call today.

### Tests

Update import paths in three files:

- `tests/test_llm_client.py:16-17` — `client_module` → `app.llm.anthropic`; pull `UPDATE_ORDER_TOOL` from the Anthropic-shaped constant inside `anthropic.py`, or from the neutral `UPDATE_ORDER_TOOL_SPEC` in `base.py` depending on what the test asserts.
- `tests/test_llm_client.py:1530` — `_INVALID_ADDRESS_NOTE`, `_apply_validation` → `app.llm.orchestration` (renamed without the underscore).
- `tests/test_llm_integration.py:20` — `from app.llm.client import generate_reply, stream_reply` → instantiate `AnthropicLLM()` and call methods on it.

Tests that currently inject `client=fake` into `generate_reply` / `stream_reply` switch to `AnthropicLLM(async_client=fake)` / `AnthropicLLM(sync_client=fake)`.

`_reset_async_client` stays on the `app.llm.anthropic` module — the autouse fixture at `tests/test_llm_client.py:29-35` keeps working with one import-path tweak.

## Critical files

- `app/llm/client.py` — split into three (delete after split, or keep as a thin re-export shim if compatibility shim is preferred; prefer a clean split)
- `app/llm/__init__.py` — currently empty; gains the factory
- `app/llm/base.py` — new
- `app/llm/orchestration.py` — new
- `app/llm/anthropic.py` — new (renamed from `client.py`)
- `app/config.py` — add `llm_provider`
- `app/telephony/session.py:26,487` — swap import + call site
- `tests/test_llm_client.py`, `tests/test_llm_integration.py` — import-path + entry-point updates

## Reuse / patterns to follow

- `app/stt/__init__.py:27-51` — exact factory shape to mirror.
- `app/stt/base.py` — Protocol + dataclass contract pattern for `LLMProvider` and `StreamEvent`.
- `app/tts/__init__.py:22-45` — provider dispatch with lazy import.

## Verification

1. `pytest tests/test_llm_client.py tests/test_llm_integration.py` — all green after import updates. No behavior change expected.
2. `pytest tests/` full suite — no regressions in router/session/order tests.
3. Manual smoke: start the dev server, place a test call, confirm a normal order flow (greet → add item → confirm → hangup) works end-to-end. Latency `first_audio` / `first_tts_byte` events should look identical to baseline (same Anthropic path, just a thin class wrapper).
4. `rg "from app.llm.client" app/ tests/` returns zero hits after the refactor — proves no caller is bypassing the factory.
5. Config sanity: `LLM_PROVIDER=foo python -c "from app.llm import get_llm; get_llm()"` raises `ValueError: Unknown LLM provider: foo` — confirms the selector wiring.
