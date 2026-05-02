"""Discord on_message orchestrator.

OnMessageHandler.handle(message) is the entry point JarvisBot's
on_message hook calls. It:

1. Asks the router whether to act.
2. For MENTION_NEW_THREAD: opens a thread off the triggering message
   and records it in memory.
3. For both response paths: loads thread history, sends a "thinking..."
   placeholder, streams the agent's reply into it, and persists both
   the user and assistant turns.

Dependencies (memory, agent, system prompt builder, stream writer) are
all constructor-injected so the unit tests don't need to monkeypatch
modules and main.py wires production deps once at startup.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable, Protocol

from jarvis.router import RoutingDecision, classify_incoming

logger = logging.getLogger(__name__)

# Type aliases for the injected callables. Spelled as Protocols rather
# than Callable[...] so they can be async generators (Callable doesn't
# express the AsyncIterator return shape cleanly).
class _AgentFn(Protocol):
    def __call__(
        self,
        *,
        system_prompt: str,
        history: list[dict[str, Any]],
        user_message: str,
        tool_registry: Any,
        tool_context: Any,
    ) -> AsyncIterator[str]: ...


class _StreamWriterFn(Protocol):
    async def __call__(
        self, placeholder: Any, chunks: AsyncIterator[str]
    ) -> str: ...


class _MemoryProto(Protocol):
    async def thread_exists(self, thread_id: str) -> bool: ...
    async def record_thread(
        self,
        *,
        thread_id: str,
        parent_channel_id: str,
        guild_id: str,
    ) -> None: ...
    async def get_turns(
        self, thread_id: str
    ) -> list[dict[str, Any]]: ...
    async def append_turn(
        self,
        *,
        thread_id: str,
        role: str,
        content: str,
        user_id: str | None = None,
    ) -> None: ...


_THREAD_NAME_PREFIX = "jarvis: "
_MAX_THREAD_NAME_LEN = 90  # Discord cap is 100; leave headroom for prefix
_PLACEHOLDER_TEXT = "thinking…"
_EMPTY_RESPONSE = "(empty response)"


class OnMessageHandler:
    def __init__(
        self,
        *,
        bot_user_id: int,
        memory: _MemoryProto,
        agent_fn: _AgentFn,
        system_prompt_fn: Callable[[], str],
        stream_writer_fn: _StreamWriterFn,
        rate_limiter: Any,  # Optional[InMemoryRateLimiter] — Any to keep events.py independent of ratelimit
        tool_registry: Any,  # Optional[ToolRegistry]
        tool_context_factory: Callable[[Any], Any],
    ) -> None:
        self._bot_user_id = bot_user_id
        self._memory = memory
        self._agent_fn = agent_fn
        self._system_prompt_fn = system_prompt_fn
        self._stream_writer_fn = stream_writer_fn
        self._rate_limiter = rate_limiter
        self._tool_registry = tool_registry
        self._tool_context_factory = tool_context_factory

    async def handle(self, message: Any) -> None:
        decision = await classify_incoming(
            message,
            bot_user_id=self._bot_user_id,
            memory=self._memory,
        )
        if decision == RoutingDecision.IGNORE:
            return

        # Rate limit BEFORE thread creation — a rate-limited caller
        # shouldn't pollute the channel with empty threads.
        if self._rate_limiter is not None:
            allowed = self._rate_limiter.check_and_record(
                user_id=int(message.author.id)
            )
            if not allowed:
                logger.info(
                    "rate-limited user %s in channel %s",
                    message.author.id,
                    message.channel.id,
                )
                try:
                    await message.reply(
                        "Rate limit reached — try again in a few minutes."
                    )
                except Exception:  # noqa: BLE001 — best-effort notice
                    logger.exception("failed to post rate-limit reply")
                return

        if decision == RoutingDecision.MENTION_NEW_THREAD:
            thread = await self._open_thread(message)
        elif decision == RoutingDecision.IN_THREAD:
            thread = message.channel
        else:
            logger.warning("unknown routing decision: %s", decision)
            return

        thread_id = str(thread.id)

        # Record user's message before calling the LLM so it survives a
        # mid-stream crash.
        await self._memory.append_turn(
            thread_id=thread_id,
            role="user",
            content=message.content,
            user_id=str(message.author.id),
        )

        history = await self._memory.get_turns(thread_id)
        # `history` already includes the user turn we just appended, so
        # drop the last entry; agent.respond appends user_message itself.
        if history and history[-1]["role"] == "user":
            history = history[:-1]

        placeholder = await thread.send(_PLACEHOLDER_TEXT)

        chunks = self._agent_fn(
            system_prompt=self._system_prompt_fn(),
            history=history,
            user_message=message.content,
            tool_registry=self._tool_registry,
            tool_context=self._tool_context_factory(message),
        )
        final_text = await self._stream_writer_fn(placeholder, chunks)

        await self._memory.append_turn(
            thread_id=thread_id,
            role="assistant",
            content=final_text or _EMPTY_RESPONSE,
        )

    def set_bot_user_id(self, bot_user_id: int) -> None:
        """Set the bot's own Discord user id. Called from main once
        on_ready fires and the gateway delivers it."""
        self._bot_user_id = bot_user_id

    async def _open_thread(self, message: Any) -> Any:
        # Discord rejects empty thread names; fall back to "chat" if the
        # @-mention had no other content.
        content = (message.content or "").strip() or "chat"
        name = _THREAD_NAME_PREFIX + content[:_MAX_THREAD_NAME_LEN]
        thread = await message.create_thread(name=name)
        await self._memory.record_thread(
            thread_id=str(thread.id),
            parent_channel_id=str(message.channel.id),
            guild_id=str(getattr(message.guild, "id", "")),
        )
        return thread
