"""Public entry point for the LLM abstraction layer.

Re-exports the contract from ``app.llm.base`` so callers do
``from app.llm import StreamEvent`` instead of reaching into
``app.llm.base``. Dispatches to the configured provider via
``get_llm()``; today only Anthropic is wired in. Adding OpenAI/Gemini
is a one-clause add to ``get_llm()`` plus a new ``app/llm/<vendor>.py``
matching the ``LLMProvider`` Protocol from ``app/llm/base.py``.
"""

from __future__ import annotations

from app.llm.base import (
    UPDATE_ORDER_TOOL_SPEC,
    LLMProvider,
    LLMResponse,
    StreamEvent,
    ToolSpec,
)

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "StreamEvent",
    "ToolSpec",
    "UPDATE_ORDER_TOOL_SPEC",
    "get_llm",
]


def get_llm() -> LLMProvider:
    """Return the configured LLM provider.

    Lazy-imports the provider module so importing ``app.llm`` doesn't
    pull the Anthropic SDK on cold start (matches the STT/TTS pattern
    in ``app.stt.__init__``).
    """
    from app.config import settings

    name = settings.llm_provider
    if name == "anthropic":
        from app.llm.anthropic import AnthropicLLM

        return AnthropicLLM()
    raise ValueError(f"Unknown LLM provider: {name}")
