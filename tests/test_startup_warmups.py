"""Unit tests for the FastAPI startup warmup hook (#192).

The lifespan hook fires:
- ``prime_tenant_cache`` for every tenant with a Twilio number.
- ``warm_aura`` once.

This module tests the orchestration, not the underlying primers (covered
in ``test_llm_warmup.py`` and ``test_tts_warmup.py``).
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.restaurants.models import Restaurant


def _restaurant(rid: str, phone: str) -> Restaurant:
    return Restaurant(
        id=rid,
        name=rid.title(),
        display_phone="+1",
        twilio_phone=phone,
        address="-",
        hours="-",
    )


@pytest.mark.asyncio
async def test_startup_primes_each_active_tenant():
    from app import startup as startup_module

    tenants = [
        _restaurant("twilight", "+15551111111"),
        _restaurant("niko", "+15552222222"),
    ]
    primer = AsyncMock()
    aura = AsyncMock()
    with (
        patch.object(startup_module, "list_active_restaurants", return_value=tenants),
        patch.object(startup_module, "prime_tenant_cache", primer),
        patch.object(startup_module, "warm_aura", aura),
    ):
        await startup_module.run_startup_warmups()
    assert primer.await_count == 2
    rids = {call.args[0].id for call in primer.await_args_list}
    assert rids == {"twilight", "niko"}
    assert aura.await_count == 1


@pytest.mark.asyncio
async def test_startup_skips_tenants_without_twilio_phone():
    """``twilio_phone == ""`` is the explicit 'awaiting Twilio number'
    state. Priming such a tenant is wasted spend — and the dashboard
    pill already flags the state for the operator."""
    from app import startup as startup_module

    tenants = [
        _restaurant("twilight", "+15551111111"),
        _restaurant("pending-onboarding", ""),
    ]
    primer = AsyncMock()
    with (
        patch.object(startup_module, "list_active_restaurants", return_value=tenants),
        patch.object(startup_module, "prime_tenant_cache", primer),
        patch.object(startup_module, "warm_aura", AsyncMock()),
    ):
        await startup_module.run_startup_warmups()
    assert primer.await_count == 1
    assert primer.await_args.args[0].id == "twilight"


@pytest.mark.asyncio
async def test_startup_survives_individual_primer_failure(caplog):
    """If one tenant's primer raises, the others must still complete and
    the app must still boot. Anthropic outages on startup are not
    deployment blockers."""
    from app import startup as startup_module

    tenants = [
        _restaurant("twilight", "+15551111111"),
        _restaurant("niko", "+15552222222"),
    ]
    async def _flaky(restaurant):
        if restaurant.id == "twilight":
            raise RuntimeError("anthropic down")

    with (
        patch.object(startup_module, "list_active_restaurants", return_value=tenants),
        patch.object(startup_module, "prime_tenant_cache", _flaky),
        patch.object(startup_module, "warm_aura", AsyncMock()),
    ):
        with caplog.at_level("WARNING", logger="app.startup"):
            await startup_module.run_startup_warmups()
    # The function returns normally despite one failure — the test
    # reaching this line is the assertion.


@pytest.mark.asyncio
async def test_startup_survives_list_active_failure(caplog):
    """Firestore being unreachable at boot must not crash the app. We
    log and proceed with an empty tenant list — /voice's per-call primer
    still primes once real traffic arrives."""
    from app import startup as startup_module

    def _boom():
        raise RuntimeError("firestore unreachable")

    primer = AsyncMock()
    aura = AsyncMock()
    with (
        patch.object(startup_module, "list_active_restaurants", _boom),
        patch.object(startup_module, "prime_tenant_cache", primer),
        patch.object(startup_module, "warm_aura", aura),
    ):
        with caplog.at_level("WARNING", logger="app.startup"):
            await startup_module.run_startup_warmups()
    assert primer.await_count == 0
    assert aura.await_count == 1  # Aura warmup still runs


@pytest.mark.asyncio
async def test_startup_logs_summary(caplog):
    from app import startup as startup_module

    tenants = [_restaurant("twilight", "+15551111111")]
    with (
        patch.object(startup_module, "list_active_restaurants", return_value=tenants),
        patch.object(startup_module, "prime_tenant_cache", AsyncMock()),
        patch.object(startup_module, "warm_aura", AsyncMock()),
    ):
        with caplog.at_level("INFO", logger="app.startup"):
            await startup_module.run_startup_warmups()
    msgs = " ".join(r.message for r in caplog.records)
    assert "startup_primers" in msgs
