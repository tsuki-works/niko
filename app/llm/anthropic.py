"""Anthropic Claude provider for the voice ordering agent.

Implements the ``LLMProvider`` Protocol declared in ``app/llm/base.py``
against Anthropic's Messages API. Wraps the synchronous and async SDK
clients, threads the conversation history forward, applies the
``update_order`` tool feedback loop, and emits provider-neutral
``StreamEvent``s on the streaming path.

Two entry points on the ``AnthropicLLM`` class:

- ``generate_reply`` — synchronous round-trip used by tests and the
  offline replay harness.
- ``stream_reply`` — async generator that yields text deltas as Haiku
  produces them, then a terminal event with the final order and
  threaded history. Used by the call-flow orchestrator to start TTS
  before the full reply is ready and hit the <1s first-audio budget.

Model + max_tokens come from ``app.config.settings``
(``anthropic_model``, ``anthropic_max_tokens``) with constructor
overrides for tests.
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Optional

from anthropic import Anthropic, AsyncAnthropic

from app.config import settings
from app.llm.base import (
    ATOMIC_TOOL_SPECS,
    LLMResponse,
    StreamEvent,
)
from app.llm.orchestration import (
    apply_tool_call,
    should_skip_followup,
    summarize_order_for_tool_result,
)
from app.orders.models import Order

_MAX_HISTORY_MESSAGES = 40

# Anthropic accepts the JSON Schema directly under ``input_schema``.
# Build the wire-shape list once at import so the cached ``tools=[...]``
# stays a constant across calls (matters for prompt caching: tools sit
# before system in Anthropic's cached prefix order).
ATOMIC_TOOLS: list[dict[str, Any]] = [
    {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.parameters,
    }
    for spec in ATOMIC_TOOL_SPECS
]


def _missing_key_error() -> RuntimeError:
    return RuntimeError(
        "ANTHROPIC_API_KEY not set — cannot call the LLM. "
        "Populate it in your .env (fetch via /shared-creds)."
    )


def _client() -> Anthropic:
    key = settings.anthropic_api_key
    if not key:
        raise _missing_key_error()
    # Sync path is only used by tests; intentionally not a singleton so tests
    # can patch/inject freely without worrying about module-level state. If this
    # ever needs to be a singleton too, follow the same lazy pattern as
    # _get_async_client below — but don't change it speculatively.
    return Anthropic(api_key=key)


# Process-wide reusable AsyncAnthropic instance (#175). Constructing a new
# AsyncAnthropic() on every stream_reply call creates a fresh httpx.AsyncClient
# per turn; when the local reference goes out of scope the pool closes and the
# TLS connection is torn down, costing a full TCP+TLS handshake on the next
# turn (~100-250ms). Reusing one instance keeps the connection pool warm.
# Lazy-initialised so importing this module never spins up sockets at startup.
# Reset to None in tests that need a clean slate (see _reset_async_client).
_default_async_client: Optional[AsyncAnthropic] = None


def _get_async_client() -> AsyncAnthropic:
    global _default_async_client
    if _default_async_client is None:
        key = settings.anthropic_api_key
        if not key:
            raise _missing_key_error()
        _default_async_client = AsyncAnthropic(api_key=key)
    return _default_async_client


def _reset_async_client() -> None:
    """Reset the module-level singleton. Called by tests that inject their own
    fake client so they don't accidentally touch the real singleton."""
    global _default_async_client
    _default_async_client = None


def _serialize_block(block: Any) -> dict[str, Any]:
    """Convert an SDK content block to the dict shape the Messages API accepts.

    The Anthropic SDK's streaming blocks carry extra attributes like
    ``parsed_output`` that ``model_dump()`` faithfully serializes — but the
    Messages API rejects unknown fields, so any subsequent turn that threads
    that history 400s. We rebuild the API-valid shape by hand instead.
    """
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    raise ValueError(f"Unsupported content block type: {block.type!r}")


def _tool_result_block(tool_use_id: str, content: str = "Order updated.") -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }


def _system_cache_block(system_prompt: str) -> list[dict[str, Any]]:
    """Wrap the system prompt for Anthropic prompt caching.

    Passing system as a list with cache_control=ephemeral tells Anthropic
    to cache the block server-side for up to 5 minutes. Cache hits reduce
    system-prompt token cost by ~90% and shave first-token latency on
    turns 2+ of the same call — near-certain for any call lasting > 20s.
    """
    return [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _with_rolling_cache_breakpoint(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Mark the last block of ``messages[-1]`` with ``cache_control: ephemeral``.

    Together with the system-prompt breakpoint, this gives a 2-breakpoint
    rolling cache (#176): each turn's request is cached up through the
    new last message, and the next turn reads that as its cached prefix
    so only the new content (previous assistant reply + new user turn)
    is uncached prefill.

    Caveat: Haiku 4.5 has a 4096-token minimum cacheable prefix. Short
    calls won't engage the rolling breakpoint; longer calls (turn 3+ of
    a typical order) will.

    Returns a NEW messages list with a NEW last message — the input is
    not mutated. This matters because callers thread the original
    history forward into ``LLMResponse.history``; a stale cache_control
    marker in threaded history would accumulate every turn and quickly
    blow past Anthropic's 4-breakpoint cap.
    """
    if not messages:
        return messages
    last = messages[-1]
    content = last["content"]
    if isinstance(content, str):
        # Plain-string user transcript. Convert to a one-block list so we
        # can attach cache_control — strings have nowhere to attach it.
        new_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": content,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    else:
        if not content:
            return messages  # defensive: nothing to mark
        new_content = [dict(block) for block in content]
        new_content[-1] = {
            **new_content[-1],
            "cache_control": {"type": "ephemeral"},
        }
    return [*messages[:-1], {**last, "content": new_content}]


def _trim_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop oldest turns when history exceeds _MAX_HISTORY_MESSAGES.

    The cut point must always be a user message that starts with text
    content (not a pure tool_result), because a tool_result requires
    the preceding tool_use to stay in context. Scanning forward from
    the oldest end, we find the first user message whose content is
    either a plain string or starts with a text block, and drop
    everything before it.

    If no safe cut point exists (entire history is tool pairs), return
    as-is — better to let the call exceed the limit than corrupt context.
    """
    if len(history) <= _MAX_HISTORY_MESSAGES:
        return history

    # Find the oldest safe cut index: scan forward until the tail fits within
    # the limit, then pick the first user message with text (not pure tool_result)
    # at or after that point so the cut lands on a safe boundary.
    min_drop = len(history) - _MAX_HISTORY_MESSAGES
    for i, msg in enumerate(history):
        if i < min_drop:
            continue
        if msg["role"] != "user":
            continue
        content = msg["content"]
        # Plain string transcript — always safe to cut here
        if isinstance(content, str):
            return history[i:]
        # List content: safe only if the first block is NOT a tool_result
        if isinstance(content, list) and content and content[0].get("type") != "tool_result":
            return history[i:]

    # No safe cut found — return unchanged
    return history


def _append_user_transcript(history: list[dict[str, Any]], transcript: str) -> list[dict[str, Any]]:
    """Append the caller's transcript to history with valid alternation.

    Anthropic requires strict user/assistant alternation. After a turn
    that produced both text and a ``tool_use``, history ends in a synthetic
    ``user: [tool_result]`` message. Appending another ``user`` message
    would error, so we merge the new transcript into that pending
    ``tool_result`` message instead.
    """
    if (
        history
        and history[-1]["role"] == "user"
        and isinstance(history[-1]["content"], list)
        and history[-1]["content"]
        and history[-1]["content"][0].get("type") == "tool_result"
    ):
        merged = [
            *history[-1]["content"],
            {"type": "text", "text": transcript},
        ]
        return [*history[:-1], {"role": "user", "content": merged}]
    return [*history, {"role": "user", "content": transcript}]


def _make_timing_event(
    _t_req: float,
    _t_first_ev: Optional[float],
    _t_msg_start: Optional[float],
    _t_first_text: Optional[float],
    _cache_read: int,
    _cache_creation: int,
) -> StreamEvent:
    return StreamEvent(
        timing={
            "ttft_seconds": round((_t_first_ev or _t_req) - _t_req, 3),
            "tool_prefix_seconds": round(
                (_t_first_text - _t_first_ev) if (_t_first_text and _t_first_ev) else 0.0,
                3,
            ),
            "network_prefill_seconds": round(
                (_t_msg_start - _t_req) if _t_msg_start is not None else 0.0,
                3,
            ),
            "decode_seconds": round(
                (_t_first_text - _t_msg_start)
                if (_t_first_text is not None and _t_msg_start is not None)
                else 0.0,
                3,
            ),
            "cache_read_tokens": _cache_read,
            "cache_creation_tokens": _cache_creation,
        }
    )


class AnthropicLLM:
    """Anthropic provider implementing the ``LLMProvider`` Protocol.

    Constructor args are all optional — production callers instantiate
    with no args and let the provider read from ``settings`` and reuse
    the process-wide ``AsyncAnthropic`` singleton. Tests inject fake
    clients and/or override the model.
    """

    def __init__(
        self,
        *,
        async_client: Optional[AsyncAnthropic] = None,
        sync_client: Optional[Anthropic] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        self._async_client = async_client
        self._sync_client = sync_client
        self._model = model or settings.anthropic_model
        self._max_tokens = max_tokens or settings.anthropic_max_tokens

    def generate_reply(
        self,
        *,
        transcript: str,
        history: list[dict[str, Any]],
        order: Order,
        system_prompt: str,
    ) -> LLMResponse:
        """Send the caller's latest transcript to Claude and return a reply.

        ``system_prompt`` is rendered per call from the inbound restaurant's
        config (#79); the previously-cached module-level prompt is gone.

        ``history`` is Anthropic's Messages format: a list of
        ``{"role": "user"|"assistant", "content": ...}`` dicts. The updated
        history (with the new user turn and the assistant turn appended) is
        returned in ``LLMResponse.history`` so the caller can thread it
        into the next turn verbatim — including any tool_use blocks, which
        Anthropic requires to stay in context.
        """
        api = self._sync_client or _client()

        new_history = _append_user_transcript(history, transcript)
        new_history = _trim_history(new_history)

        response = api.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_system_cache_block(system_prompt),
            tools=ATOMIC_TOOLS,
            messages=_with_rolling_cache_breakpoint(new_history),
        )

        reply_text_parts: list[str] = []
        tool_uses: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                reply_text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append({"id": block.id, "name": block.name, "input": block.input})

        updated_order = order
        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            updated_order, rejection_notes = apply_tool_call(updated_order, tu["name"], tu["input"])
            summary = summarize_order_for_tool_result(updated_order)
            if rejection_notes:
                summary = summary + " " + " ".join(rejection_notes)
            tool_results.append(_tool_result_block(tu["id"], summary))

        assistant_content = [_serialize_block(block) for block in response.content]
        new_history = [
            *new_history,
            {"role": "assistant", "content": assistant_content},
        ]

        if tool_uses:
            new_history = [
                *new_history,
                {"role": "user", "content": tool_results},
            ]

        if tool_uses and not should_skip_followup(tool_uses, bool(reply_text_parts)):
            # Verbal continuation only — no further tool calls (#173). We keep the
            # tool schema in ``tools`` and use ``tool_choice="none"`` to suppress
            # tool use, rather than passing ``tools=[]``: tools sit before system
            # in Anthropic's cached prefix order, so changing them across the two
            # calls of one turn invalidates the entire cached prefix on the
            # follow-up (system + menu + history). See #176.
            followup = api.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=_system_cache_block(system_prompt),
                tools=ATOMIC_TOOLS,
                tool_choice={"type": "none"},
                messages=_with_rolling_cache_breakpoint(new_history),
            )
            for block in followup.content:
                if block.type == "text":
                    reply_text_parts.append(block.text)
            followup_content = [_serialize_block(block) for block in followup.content]
            new_history = [
                *new_history,
                {"role": "assistant", "content": followup_content},
            ]

        return LLMResponse(
            reply_text="".join(reply_text_parts).strip(),
            order=updated_order,
            history=new_history,
        )

    async def stream_reply(
        self,
        *,
        transcript: str,
        history: list[dict[str, Any]],
        order: Order,
        system_prompt: str,
    ) -> AsyncIterator[StreamEvent]:
        """Stream Claude's reply token-by-token for low-latency TTS handoff.

        Yields ``StreamEvent(text_delta=str)`` for each incremental chunk
        of the assistant's spoken reply, then a single terminal
        ``StreamEvent(final=LLMResponse)`` with the full reply text,
        updated order, and threaded history.

        The contract matches ``generate_reply`` for tool-use semantics:
        if the first turn emits only ``update_order`` blocks (no text),
        we send a ``tool_result`` and stream a follow-up call so the
        caller still gets a spoken reply. In practice this is the
        "I cancelled the order" path — the model often wants to confirm
        the side effect before talking back.
        """
        api = self._async_client or _get_async_client()

        new_history = _append_user_transcript(history, transcript)
        new_history = _trim_history(new_history)

        text_parts: list[str] = []
        tool_uses: list[dict[str, Any]] = []

        # Latency instrumentation (#146, extended in #175). t_request_start anchors
        # the whole turn — TTFT is time to first SDK event; tool_prefix is the gap
        # between first event and first text block. #175 adds two finer fields:
        # - network_prefill_seconds: request → message_start (TCP+TLS+queue+prefill)
        # - decode_seconds: message_start → first text block (token-1 decode)
        t_request_start = time.monotonic()
        t_first_event: Optional[float] = None
        t_message_start: Optional[float] = None
        t_first_text_block: Optional[float] = None
        cache_read_tokens = 0
        cache_creation_tokens = 0
        timing_emitted = False
        # Tracks the block type observed at the most recent
        # ``content_block_start`` so the matching ``content_block_stop``
        # can decide whether to emit ``flush_now`` (#305). Only text
        # blocks trigger a flush — tool_use blocks carry no spoken text.
        current_block_type: Optional[str] = None

        async with api.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_system_cache_block(system_prompt),
            tools=ATOMIC_TOOLS,
            messages=_with_rolling_cache_breakpoint(new_history),
        ) as stream:
            async for event in stream:
                if t_first_event is None:
                    t_first_event = time.monotonic()
                etype = getattr(event, "type", None)
                if etype == "message_start":
                    t_message_start = time.monotonic()
                    msg = getattr(event, "message", None)
                    usage = getattr(msg, "usage", None) if msg is not None else None
                    if usage is not None:
                        cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
                        cache_creation_tokens = (
                            getattr(usage, "cache_creation_input_tokens", 0) or 0
                        )
                elif etype == "content_block_start":
                    block = getattr(event, "content_block", None)
                    current_block_type = getattr(block, "type", None)
                    if current_block_type == "text" and t_first_text_block is None:
                        t_first_text_block = time.monotonic()
                        yield _make_timing_event(
                            t_request_start,
                            t_first_event,
                            t_message_start,
                            t_first_text_block,
                            cache_read_tokens,
                            cache_creation_tokens,
                        )
                        timing_emitted = True
                elif etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if getattr(delta, "type", None) == "text_delta":
                        text_parts.append(delta.text)
                        yield StreamEvent(text_delta=delta.text)
                elif etype == "content_block_stop":
                    if current_block_type == "text":
                        yield StreamEvent(flush_now=True)
                    current_block_type = None
            first_message = await stream.get_final_message()

        for block in first_message.content:
            if block.type == "tool_use":
                tool_uses.append({"id": block.id, "name": block.name, "input": block.input})

        updated_order = order
        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            updated_order, rejection_notes = apply_tool_call(updated_order, tu["name"], tu["input"])
            summary = summarize_order_for_tool_result(updated_order)
            if rejection_notes:
                summary = summary + " " + " ".join(rejection_notes)
            tool_results.append(_tool_result_block(tu["id"], summary))

        assistant_content = [_serialize_block(block) for block in first_message.content]
        new_history = [
            *new_history,
            {"role": "assistant", "content": assistant_content},
        ]

        if tool_uses:
            new_history = [
                *new_history,
                {"role": "user", "content": tool_results},
            ]

        if tool_uses and not timing_emitted:
            # First stream produced only tool_use blocks (no text). Emit the
            # first-call timing snapshot before starting the follow-up so the
            # router always receives a timing event per network round-trip (#175).
            yield _make_timing_event(
                t_request_start,
                t_first_event,
                t_message_start,
                t_first_text_block,
                cache_read_tokens,
                cache_creation_tokens,
            )

        if tool_uses and not should_skip_followup(tool_uses, bool(text_parts)):
            # Verbal continuation only — no further tool calls (#173). We keep the
            # tool schema in ``tools`` and use ``tool_choice="none"`` to suppress
            # tool use, rather than passing ``tools=[]``: tools sit before system
            # in Anthropic's cached prefix order, so changing them across the two
            # calls of one turn invalidates the entire cached prefix on the
            # follow-up (system + menu + history). See #176.
            # Each follow-up call gets its own scoped timing variables so the second
            # timing event reports that call's numbers, not the first call's (#175).
            fu_t_request_start = time.monotonic()
            fu_t_first_event: Optional[float] = None
            fu_t_message_start: Optional[float] = None
            fu_t_first_text_block: Optional[float] = None
            fu_cache_read_tokens = 0
            fu_cache_creation_tokens = 0
            fu_timing_emitted = False
            fu_current_block_type: Optional[str] = None

            async with api.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=_system_cache_block(system_prompt),
                tools=ATOMIC_TOOLS,
                tool_choice={"type": "none"},
                messages=_with_rolling_cache_breakpoint(new_history),
            ) as followup_stream:
                async for event in followup_stream:
                    if fu_t_first_event is None:
                        fu_t_first_event = time.monotonic()
                    etype = getattr(event, "type", None)
                    if etype == "message_start":
                        fu_t_message_start = time.monotonic()
                        msg = getattr(event, "message", None)
                        usage = getattr(msg, "usage", None) if msg is not None else None
                        if usage is not None:
                            fu_cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
                            fu_cache_creation_tokens = (
                                getattr(usage, "cache_creation_input_tokens", 0) or 0
                            )
                    elif etype == "content_block_start":
                        block = getattr(event, "content_block", None)
                        fu_current_block_type = getattr(block, "type", None)
                        if fu_current_block_type == "text" and fu_t_first_text_block is None:
                            fu_t_first_text_block = time.monotonic()
                            yield _make_timing_event(
                                fu_t_request_start,
                                fu_t_first_event,
                                fu_t_message_start,
                                fu_t_first_text_block,
                                fu_cache_read_tokens,
                                fu_cache_creation_tokens,
                            )
                            fu_timing_emitted = True
                    elif etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if getattr(delta, "type", None) == "text_delta":
                            text_parts.append(delta.text)
                            yield StreamEvent(text_delta=delta.text)
                    elif etype == "content_block_stop":
                        if fu_current_block_type == "text":
                            yield StreamEvent(flush_now=True)
                        fu_current_block_type = None
                followup_message = await followup_stream.get_final_message()

            if not fu_timing_emitted:
                # Follow-up emitted no text blocks; emit a timing snapshot anyway.
                yield _make_timing_event(
                    fu_t_request_start,
                    fu_t_first_event,
                    fu_t_message_start,
                    fu_t_first_text_block,
                    fu_cache_read_tokens,
                    fu_cache_creation_tokens,
                )

            followup_content = [_serialize_block(b) for b in followup_message.content]
            new_history = [
                *new_history,
                {"role": "assistant", "content": followup_content},
            ]

        if not timing_emitted and not tool_uses:
            # Tool-only path with no follow-up text (rare); still emit a
            # timing snapshot so consumers always see the breakdown.
            yield _make_timing_event(
                t_request_start,
                t_first_event,
                t_message_start,
                t_first_text_block,
                cache_read_tokens,
                cache_creation_tokens,
            )

        yield StreamEvent(
            final=LLMResponse(
                reply_text="".join(text_parts).strip(),
                order=updated_order,
                history=new_history,
            )
        )


__all__ = [
    "ATOMIC_TOOLS",
    "AnthropicLLM",
]
