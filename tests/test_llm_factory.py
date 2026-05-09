"""Tests for the ``app.llm.get_llm`` provider factory.

The factory dispatches on ``settings.llm_provider``. Today only
"anthropic" is wired in; an unknown provider must raise so a typo or
half-merged feature branch can't silently fall through to a stale
default. Mirrors the verification step in
``docs/superpowers/plans/2026-05-09-multi-llm-abstraction.md``.
"""

from __future__ import annotations

import pytest

from app.llm import get_llm
from app.llm.anthropic import AnthropicLLM


def test_get_llm_returns_anthropic_provider_by_default(monkeypatch):
    """Default provider name "anthropic" returns an AnthropicLLM instance."""
    from app.config import settings

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    assert isinstance(get_llm(), AnthropicLLM)


def test_get_llm_rejects_unknown_provider(monkeypatch):
    """A typo / unrecognised provider name must raise rather than fall
    through to a stale default — guards the factory wiring against
    silent regressions when adding the next provider."""
    from app.config import settings

    monkeypatch.setattr(settings, "llm_provider", "openai")
    with pytest.raises(ValueError, match="Unknown LLM provider: openai"):
        get_llm()
