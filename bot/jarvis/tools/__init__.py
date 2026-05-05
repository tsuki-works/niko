"""Tool registry + execution context for Jarvis's agent loop.

A ToolRegistry holds named ToolDescriptors. The agent loop calls
`as_anthropic_tools()` to get the SDK-formatted tool list and
`dispatch(name, input, context)` to run a tool by name.

Tools that need state (Discord guild, GitHub client, docs path) opt into
a ToolContext via the `wants_context=True` flag on their descriptor.
The registry passes `context=ctx` as a kwarg only when that flag is set
— this keeps tool functions readable when they don't need state.

Tool output is always a string (JSON-serialized) because that's what
Anthropic's tool_result.content expects. Errors are caught at dispatch
time and serialized as `{"error": "<message>"}` so the model can surface
the failure rather than the loop blowing up.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Per-turn execution context handed to tools that need state."""

    guild: Any  # discord.Guild — `Any` to keep this module discord-import-free
    github_client: Any  # AsyncGitHubClient — likewise
    github_repo: str
    github_project_id: str
    docs_root: Optional[Path]


@dataclass
class ToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., Awaitable[Any]]
    wants_context: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDescriptor] = {}

    def register(self, descriptor: ToolDescriptor) -> None:
        if descriptor.name in self._tools:
            raise ValueError(f"tool {descriptor.name!r} already registered")
        self._tools[descriptor.name] = descriptor

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def as_anthropic_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": d.name,
                "description": d.description,
                "input_schema": d.input_schema,
            }
            for d in self._tools.values()
        ]

    async def dispatch(
        self,
        *,
        name: str,
        tool_input: dict[str, Any],
        context: ToolContext,
    ) -> str:
        """Run tool `name` with `tool_input` and return its result as a
        JSON string suitable for Anthropic's tool_result.content."""
        desc = self._tools.get(name)
        if desc is None:
            payload = {"error": f"unknown tool: {name}"}
            return json.dumps(payload)
        kwargs = dict(tool_input)
        if desc.wants_context:
            kwargs["context"] = context
        try:
            result = await desc.fn(**kwargs)
        except Exception as exc:
            logger.warning("tool %s raised: %s", name, exc)
            return json.dumps({"error": str(exc)})
        return json.dumps(result, default=str)
