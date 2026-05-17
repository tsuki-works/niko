"""Unit tests for the prompt-cache primer (#192).

The primer is a ``max_tokens=1`` call fired on FastAPI startup and from
the Twilio ``/voice`` webhook. Its purpose is to write the per-tenant
system prompt to Anthropic's prompt cache so the caller's first real
turn (T2) hits ``cache_read`` instead of paying ``cache_creation``.

Tests assert the request shape and the swallow-all-exceptions contract.
There is no in-process surface to verify Anthropic actually stored the
prefix — that is covered end-to-end by the staged-call validation in
the PR description.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.llm import anthropic as anthropic_module
from app.llm import warmup
from app.llm.anthropic import ATOMIC_TOOLS
from app.restaurants.models import Restaurant


@pytest.fixture(autouse=True)
def _reset_async_client_singleton():
    yield
    anthropic_module._reset_async_client()


def _restaurant() -> Restaurant:
    return Restaurant(
        id="t",
        name="Twilight",
        display_phone="+1",
        twilio_phone="+1",
        address="-",
        hours="-",
    )


def _install_fake_async_client(response=None, exc: BaseException | None = None) -> MagicMock:
    """Return a MagicMock acting as AsyncAnthropic. ``messages.create`` is
    an AsyncMock that either returns ``response`` or raises ``exc``."""
    client = MagicMock()
    create = AsyncMock()
    if exc is not None:
        create.side_effect = exc
    else:
        create.return_value = response or SimpleNamespace(
            usage=SimpleNamespace(cache_creation_input_tokens=1500, cache_read_input_tokens=0),
        )
    client.messages = SimpleNamespace(create=create)
    anthropic_module._default_async_client = client
    return client


@pytest.mark.asyncio
async def test_prime_tenant_cache_uses_max_tokens_one():
    client = _install_fake_async_client()
    await warmup.prime_tenant_cache(_restaurant())
    kwargs = client.messages.create.await_args.kwargs
    assert kwargs["max_tokens"] == 1


@pytest.mark.asyncio
async def test_prime_tenant_cache_wraps_system_in_ephemeral_cache_block():
    """Same ``_system_cache_block`` shape the real call uses — otherwise
    the primer writes a different cache key than T2 reads from."""
    client = _install_fake_async_client()
    await warmup.prime_tenant_cache(_restaurant())
    kwargs = client.messages.create.await_args.kwargs
    system = kwargs["system"]
    assert isinstance(system, list) and len(system) == 1
    assert system[0]["type"] == "text"
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "Twilight" in system[0]["text"]


@pytest.mark.asyncio
async def test_prime_tenant_cache_includes_atomic_tools():
    """Tools sit before system in Anthropic's cached prefix order
    (per #176). A primer missing the tools would write a *different*
    cache key than T2's real call."""
    client = _install_fake_async_client()
    await warmup.prime_tenant_cache(_restaurant())
    kwargs = client.messages.create.await_args.kwargs
    assert kwargs["tools"] == ATOMIC_TOOLS


@pytest.mark.asyncio
async def test_prime_tenant_cache_uses_configured_model():
    client = _install_fake_async_client()
    await warmup.prime_tenant_cache(_restaurant())
    kwargs = client.messages.create.await_args.kwargs
    assert kwargs["model"] == settings.anthropic_model


@pytest.mark.asyncio
async def test_prime_tenant_cache_sends_single_user_ping():
    client = _install_fake_async_client()
    await warmup.prime_tenant_cache(_restaurant())
    kwargs = client.messages.create.await_args.kwargs
    assert kwargs["messages"] == [{"role": "user", "content": "ping"}]


@pytest.mark.asyncio
async def test_prime_tenant_cache_reuses_pooled_singleton():
    """No fresh AsyncAnthropic() per primer — that would defeat the
    connection-pooling work in #175."""
    client = _install_fake_async_client()
    await warmup.prime_tenant_cache(_restaurant())
    await warmup.prime_tenant_cache(_restaurant())
    assert client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_prime_tenant_cache_swallows_anthropic_errors(caplog):
    """Anthropic 5xx, network blip, missing key — none of these should
    crash the caller. The cost of a failed primer is the real call paying
    cache_creation, which is today's behavior."""
    _install_fake_async_client(exc=RuntimeError("boom"))
    with caplog.at_level("WARNING", logger="app.llm.warmup"):
        result = await warmup.prime_tenant_cache(_restaurant())
    assert result is None
    assert any("primer failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_prime_tenant_cache_logs_success_metrics(caplog):
    _install_fake_async_client()
    with caplog.at_level("INFO", logger="app.llm.warmup"):
        await warmup.prime_tenant_cache(_restaurant())
    msgs = " ".join(r.message for r in caplog.records)
    assert "primer completed" in msgs
    assert "rid=t" in msgs
