"""Unit tests for the Deepgram TTS connection warmup (#192).

``warm_aura`` is called from FastAPI's lifespan startup. Its purpose is
to establish the HTTPS/2 connection to api.deepgram.com so T1's first
TTS chunk doesn't pay TCP+TLS setup on a freshly opened socket.

Tests stub the Deepgram HTTP layer; no network is touched.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.tts import warmup as tts_warmup


class _FakeResponse:
    def __init__(self, status_code: int = 200, chunks: list[bytes] | None = None):
        self.status_code = status_code
        self._chunks = chunks or [b"\x00"]

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aread(self) -> bytes:
        return b""


@pytest.mark.asyncio
async def test_warm_aura_issues_synth_request_to_deepgram():
    """A single throwaway synth establishes the HTTPS connection. The
    response body is drained and discarded — we only care about the
    socket being alive."""
    fake_resp = _FakeResponse(status_code=200, chunks=[b"\x00\x01"])
    fake_client = AsyncMock()
    fake_client.stream = lambda *a, **kw: fake_resp
    with patch.object(tts_warmup, "_get_client", return_value=fake_client):
        await tts_warmup.warm_aura()


@pytest.mark.asyncio
async def test_warm_aura_swallows_http_error(caplog):
    """A Deepgram 5xx on warmup must not prevent the FastAPI app from
    booting — T1's real synth might still succeed (Deepgram blips are
    transient)."""

    class _BoomClient:
        def stream(self, *a, **kw):
            raise RuntimeError("connection refused")

    with patch.object(tts_warmup, "_get_client", return_value=_BoomClient()):
        with caplog.at_level("WARNING", logger="app.tts.warmup"):
            await tts_warmup.warm_aura()
    assert any("aura warmup failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_warm_aura_swallows_non_200_status(caplog):
    fake_resp = _FakeResponse(status_code=503, chunks=[])
    fake_client = AsyncMock()
    fake_client.stream = lambda *a, **kw: fake_resp
    with patch.object(tts_warmup, "_get_client", return_value=fake_client):
        with caplog.at_level("WARNING", logger="app.tts.warmup"):
            await tts_warmup.warm_aura()
    # Non-200 is logged but does not raise.
    assert any("aura warmup failed" in r.message for r in caplog.records)
