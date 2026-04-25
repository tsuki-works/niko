"""Unit tests for app.tts.client.speak().

All tests mock httpx and WebSocket — no real API calls made.
"""
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.websockets import WebSocketDisconnect

from app.tts.client import speak


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _AsyncStreamCtx:
    """Async context manager that returns a pre-built mock response."""
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        pass


async def _chunk_gen(chunks: list[bytes]):
    """Async generator that yields each chunk in order."""
    for chunk in chunks:
        yield chunk


def make_mock_client(chunks: list[bytes], status_code: int = 200) -> MagicMock:
    """Return an httpx.AsyncClient mock that streams the given chunks."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.aiter_bytes = lambda: _chunk_gen(chunks)
    mock_response.aread = AsyncMock(return_value=b"bad request from deepgram")

    mock_client = MagicMock()
    mock_client.stream.return_value = _AsyncStreamCtx(mock_response)
    return mock_client


def make_mock_websocket() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.fixture(autouse=True)
def _patch_settings():
    """Default settings for every test — keeps the suite independent of local .env."""
    with patch("app.tts.client.settings") as mock_settings:
        mock_settings.deepgram_api_key = "test-key"
        mock_settings.deepgram_tts_model = "aura-2-thalia-en"
        yield mock_settings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_speak_sends_media_events():
    """Each audio chunk becomes a Twilio media event with the right streamSid."""
    chunks = [b"\x00\x01\x02", b"\x03\x04\x05"]
    client = make_mock_client(chunks)
    ws = make_mock_websocket()

    await speak("Hello there", ws, stream_sid="MZ123", client=client)

    assert ws.send_json.call_count == 2
    call_args = [call.args[0] for call in ws.send_json.call_args_list]

    for chunk, call in zip(chunks, call_args):
        assert call["event"] == "media"
        assert call["streamSid"] == "MZ123"
        assert call["media"]["payload"] == base64.b64encode(chunk).decode()


@pytest.mark.asyncio
async def test_speak_empty_text_sends_nothing():
    """Empty text returns immediately without hitting Deepgram."""
    client = make_mock_client([b"\x00"])
    ws = make_mock_websocket()

    await speak("", ws, stream_sid="MZ123", client=client)

    client.stream.assert_not_called()
    ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_speak_whitespace_only_sends_nothing():
    """Whitespace-only text is treated as empty — Deepgram not called."""
    client = make_mock_client([b"\x00"])
    ws = make_mock_websocket()

    await speak("   ", ws, stream_sid="MZ123", client=client)

    client.stream.assert_not_called()
    ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_speak_missing_api_key_raises(_patch_settings):
    """RuntimeError raised when DEEPGRAM_API_KEY is not set."""
    ws = make_mock_websocket()
    _patch_settings.deepgram_api_key = None

    with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY"):
        await speak("Hello", ws, stream_sid="MZ123")


@pytest.mark.asyncio
async def test_speak_non_200_raises():
    """RuntimeError raised when Deepgram returns a non-200 status."""
    client = make_mock_client([], status_code=401)
    ws = make_mock_websocket()

    with pytest.raises(RuntimeError, match="401"):
        await speak("Hello", ws, stream_sid="MZ123", client=client)


@pytest.mark.asyncio
async def test_speak_websocket_disconnect_is_handled():
    """WebSocketDisconnect mid-stream is caught and does not propagate."""
    chunks = [b"\x00\x01", b"\x02\x03"]
    client = make_mock_client(chunks)
    ws = make_mock_websocket()
    ws.send_json.side_effect = [None, WebSocketDisconnect()]

    # Should not raise
    await speak("Hello", ws, stream_sid="MZ123", client=client)

    assert ws.send_json.call_count == 2


@pytest.mark.asyncio
async def test_speak_uses_configured_model_and_mulaw_format():
    """Deepgram is called with the configured model, mulaw 8 kHz, no container."""
    client = make_mock_client([b"\x00"])
    ws = make_mock_websocket()

    await speak("Hello", ws, stream_sid="MZ123", client=client)

    assert client.stream.call_args.args[0] == "POST"
    assert client.stream.call_args.args[1].endswith("/speak")

    kwargs = client.stream.call_args.kwargs
    assert kwargs["params"]["model"] == "aura-2-thalia-en"
    assert kwargs["params"]["encoding"] == "mulaw"
    assert kwargs["params"]["sample_rate"] == "8000"
    assert kwargs["params"]["container"] == "none"
    assert kwargs["headers"]["Authorization"] == "Token test-key"
    assert kwargs["json"] == {"text": "Hello"}
