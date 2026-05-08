"""Unit tests for app.deepgram.tts.speak().

All tests mock httpx and WebSocket — no real API calls made.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.websockets import WebSocketDisconnect

import app.deepgram.tts as tts_module
from app.config import settings
from app.deepgram.tts import speak

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
    """Default settings for every test — keeps the suite independent of local .env.

    Both ``app.deepgram`` (where _api_key reads the key) and
    ``app.deepgram.tts`` (where the model is read) use their own import of
    ``settings``, so we patch both module-level names. We yield the
    ``app.deepgram`` mock because _api_key() reads from there; tests that
    want to test missing-key behaviour set deepgram_api_key = None on the
    yielded object and it propagates correctly.
    """
    with patch("app.deepgram.settings") as mock_dg, patch("app.deepgram.tts.settings") as mock_tts:
        mock_dg.deepgram_api_key = "test-key"
        mock_tts.deepgram_api_key = "test-key"
        mock_tts.deepgram_tts_model = "aura-2-thalia-en"
        # Keep the two mocks in sync when the test sets deepgram_api_key = None
        # on the yielded object. We yield mock_dg so _api_key() sees the change.
        yield mock_dg


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


@pytest.mark.asyncio
async def test_speak_on_chunk_receives_each_audio_chunk():
    """When ``on_chunk`` is passed, each TTS chunk is forwarded to it.
    This is how the router captures outbound audio for the recording
    session — the callback is constructed by _make_recording_chunk_handler."""
    chunks = [b"\xab\xcd", b"\xef\x01\x02", b"\x03"]
    client = make_mock_client(chunks)
    ws = make_mock_websocket()

    captured: list[bytes] = []

    await speak(
        "Hello",
        ws,
        stream_sid="MZ123",
        client=client,
        on_chunk=captured.append,
    )

    assert captured == chunks


@pytest.mark.asyncio
async def test_speak_without_on_chunk_skips_callback():
    """If no on_chunk is passed, the call still completes normally
    and no callback-related error is raised."""
    chunks = [b"\xab", b"\xcd"]
    client = make_mock_client(chunks)
    ws = make_mock_websocket()

    # Should not raise; two media events sent
    await speak("Hello", ws, stream_sid="MZ123", client=client)

    assert ws.send_json.call_count == 2


# ---------------------------------------------------------------------------
# _get_client — module-level persistent httpx.AsyncClient (#151)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_default_client():
    """Reset the module-level singleton between tests so one test's
    instance doesn't leak into another. The real process never needs
    this — the singleton is intentionally long-lived."""
    yield
    tts_module._default_client = None


def test_get_client_returns_same_instance_across_calls():
    c1 = tts_module._get_client()
    c2 = tts_module._get_client()
    assert c1 is c2


def test_get_client_constructs_with_expected_timeouts():
    import httpx

    c = tts_module._get_client()
    assert isinstance(c, httpx.AsyncClient)
    # httpx.Timeout exposes per-stage attributes; the values match what
    # the per-call client used to set.
    assert c.timeout.connect == 5.0
    assert c.timeout.read == 10.0
    assert c.timeout.write == 5.0
    assert c.timeout.pool == 5.0


@pytest.mark.asyncio
async def test_speak_uses_default_client_when_none_passed(monkeypatch):
    """When ``client`` is not passed, speak() must reuse the singleton —
    NOT construct a fresh client per call (the whole point of this
    change is to skip the TLS handshake)."""
    chunks = [b"\xab"]
    fake_default = make_mock_client(chunks)
    ws = make_mock_websocket()

    # Pre-populate the singleton with our mock so speak() picks it up.
    tts_module._default_client = fake_default

    await speak("Hello", ws, stream_sid="MZ123")

    fake_default.stream.assert_called_once()
    # And the singleton was NOT closed at the end of the call —
    # persistent across speak() invocations is the whole point.
    assert tts_module._default_client is fake_default


@pytest.mark.asyncio
async def test_speak_does_not_close_default_client(monkeypatch):
    """The singleton lives for the process lifetime. ``aclose()`` must
    not be called from inside speak(), even on the success path."""
    chunks = [b"\xab"]
    fake_default = make_mock_client(chunks)
    fake_default.aclose = AsyncMock()
    ws = make_mock_websocket()

    tts_module._default_client = fake_default

    await speak("Hello", ws, stream_sid="MZ123")

    fake_default.aclose.assert_not_called()


# ---------------------------------------------------------------------------
# on_first_byte callback (#152)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_speak_invokes_on_first_byte_once(monkeypatch):
    """on_first_byte fires exactly once when the first non-empty chunk
    arrives, regardless of how many chunks follow."""
    chunks = [b"\xab\xcd", b"\xef\x01", b"\x02"]
    mock_client = make_mock_client(chunks)
    ws = make_mock_websocket()

    calls: list[float] = []

    def cb():
        calls.append(1.0)

    await speak("Hello", ws, stream_sid="MZ123", client=mock_client, on_first_byte=cb)

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_speak_skips_on_first_byte_for_empty_chunks():
    """Empty chunks must not trigger the callback — first non-empty
    chunk wins. The existing aiter_bytes loop already skips empty
    chunks before sending; verify the callback respects the same gate."""
    chunks = [b"", b"", b"\xab", b"\xcd"]
    mock_client = make_mock_client(chunks)
    ws = make_mock_websocket()

    calls: list[int] = []
    await speak(
        "Hello",
        ws,
        stream_sid="MZ123",
        client=mock_client,
        on_first_byte=lambda: calls.append(1),
    )
    assert calls == [1]


@pytest.mark.asyncio
async def test_speak_swallows_on_first_byte_exception():
    """A buggy callback must not break the call. The chunk send still
    happens; the exception is logged and discarded."""
    chunks = [b"\xab"]
    mock_client = make_mock_client(chunks)
    ws = make_mock_websocket()

    def bad_cb():
        raise RuntimeError("boom")

    # Should not raise
    await speak(
        "Hello",
        ws,
        stream_sid="MZ123",
        client=mock_client,
        on_first_byte=bad_cb,
    )
    ws.send_json.assert_called_once()


@pytest.mark.asyncio
async def test_speak_without_on_first_byte_works(monkeypatch):
    """Callback is optional — omitting it is the existing behaviour."""
    chunks = [b"\xab"]
    mock_client = make_mock_client(chunks)
    ws = make_mock_websocket()
    # No on_first_byte kwarg
    await speak("Hello", ws, stream_sid="MZ123", client=mock_client)
    ws.send_json.assert_called_once()


# ---------------------------------------------------------------------------
# on_chunk callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_chunk_receives_each_audio_chunk(monkeypatch):
    """Every non-empty body chunk Deepgram returns is forwarded to on_chunk."""
    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")

    chunks_seen: list[bytes] = []
    fake_chunks = [b"\x01\x02", b"\x03\x04", b"\x05"]

    async def fake_aiter_bytes():
        for c in fake_chunks:
            yield c

    response = AsyncMock()
    response.status_code = 200
    response.aiter_bytes = fake_aiter_bytes

    stream_cm = AsyncMock()
    stream_cm.__aenter__ = AsyncMock(return_value=response)
    stream_cm.__aexit__ = AsyncMock(return_value=None)

    fake_client = AsyncMock()
    fake_client.stream = MagicMock(return_value=stream_cm)

    ws = AsyncMock()
    ws.send_json = AsyncMock()

    await speak("hello", ws, "MZ123", client=fake_client, on_chunk=chunks_seen.append)

    assert chunks_seen == fake_chunks


@pytest.mark.asyncio
async def test_on_chunk_exceptions_are_swallowed(monkeypatch, caplog):
    """A buggy on_chunk callback never breaks a call."""
    monkeypatch.setattr(settings, "deepgram_api_key", "test-key")

    async def fake_aiter_bytes():
        yield b"\x01"

    response = AsyncMock()
    response.status_code = 200
    response.aiter_bytes = fake_aiter_bytes

    stream_cm = AsyncMock()
    stream_cm.__aenter__ = AsyncMock(return_value=response)
    stream_cm.__aexit__ = AsyncMock(return_value=None)

    fake_client = AsyncMock()
    fake_client.stream = MagicMock(return_value=stream_cm)

    ws = AsyncMock()
    ws.send_json = AsyncMock()

    def bad(_chunk: bytes) -> None:
        raise RuntimeError("boom")

    # No exception escapes; the assertion is that this returns normally.
    await speak("hi", ws, "MZ123", client=fake_client, on_chunk=bad)
