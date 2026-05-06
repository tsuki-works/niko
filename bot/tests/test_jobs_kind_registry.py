from __future__ import annotations

import pytest
from jarvis.jobs.kinds import KIND_REGISTRY, register_kind


@pytest.mark.asyncio
async def test_register_and_lookup_roundtrip():
    async def fake_handler(ctx):
        return None
    register_kind("__test_only_kind", fake_handler)
    assert KIND_REGISTRY["__test_only_kind"] is fake_handler


def test_duplicate_registration_raises():
    async def h(ctx):
        return None
    register_kind("__dup_kind", h)
    with pytest.raises(ValueError):
        register_kind("__dup_kind", h)
