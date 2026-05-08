"""Tests for app/dev/audio_dump.py.

This module owns local-dev caller-audio capture. The contract that
matters for production safety: when ``niko_local_audio_dump_dir`` is
unset (production default), ``open_caller_dump`` returns ``None`` and
no filesystem I/O happens. Every other test verifies the local-dev
behavior we depend on for offline STT replay.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.dev import audio_dump


@pytest.fixture(autouse=True)
def _reset_settings_dump_dir():
    """Snapshot/restore the dump-dir setting around each test."""
    original = audio_dump.settings.niko_local_audio_dump_dir
    yield
    audio_dump.settings.niko_local_audio_dump_dir = original


def test_returns_none_when_setting_unset() -> None:
    audio_dump.settings.niko_local_audio_dump_dir = None
    assert audio_dump.open_caller_dump("CA123") is None


def test_returns_none_when_setting_blank() -> None:
    audio_dump.settings.niko_local_audio_dump_dir = "   "
    assert audio_dump.open_caller_dump("CA123") is None


def test_returns_none_when_call_sid_blank(tmp_path: Path) -> None:
    audio_dump.settings.niko_local_audio_dump_dir = str(tmp_path)
    assert audio_dump.open_caller_dump("") is None


def test_writes_bytes_to_disk(tmp_path: Path) -> None:
    audio_dump.settings.niko_local_audio_dump_dir = str(tmp_path)
    dump = audio_dump.open_caller_dump("CA123")
    assert dump is not None
    dump.append(b"\xff\x80\x7f")
    dump.append(b"\x00\x01\x02")
    dump.close()

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].name.startswith("CA123_")
    assert files[0].name.endswith(".ulaw")
    assert files[0].read_bytes() == b"\xff\x80\x7f\x00\x01\x02"


def test_creates_missing_directory(tmp_path: Path) -> None:
    nested = tmp_path / "does" / "not" / "exist"
    audio_dump.settings.niko_local_audio_dump_dir = str(nested)
    dump = audio_dump.open_caller_dump("CA123")
    assert dump is not None
    dump.append(b"hello")
    dump.close()
    assert nested.is_dir()
    assert any(nested.iterdir())


def test_returns_none_when_dir_path_is_a_file(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")
    audio_dump.settings.niko_local_audio_dump_dir = str(blocker)
    assert audio_dump.open_caller_dump("CA123") is None


def test_returns_none_when_makedirs_fails(tmp_path: Path) -> None:
    audio_dump.settings.niko_local_audio_dump_dir = str(tmp_path / "x")
    with patch("app.dev.audio_dump.os.makedirs", side_effect=PermissionError("denied")):
        assert audio_dump.open_caller_dump("CA123") is None


def test_returns_none_when_open_fails(tmp_path: Path) -> None:
    audio_dump.settings.niko_local_audio_dump_dir = str(tmp_path)
    with patch(
        "app.dev.audio_dump.open",
        side_effect=PermissionError("denied"),
        create=True,
    ):
        assert audio_dump.open_caller_dump("CA123") is None


def test_append_after_ioerror_becomes_noop(tmp_path: Path) -> None:
    audio_dump.settings.niko_local_audio_dump_dir = str(tmp_path)
    dump = audio_dump.open_caller_dump("CA123")
    assert dump is not None
    dump.append(b"first")

    # Force an error on the next write by closing the underlying fh.
    dump._fh.close()  # type: ignore[attr-defined]

    # This should be caught, log, and flip _broken — not raise.
    dump.append(b"second")

    # Subsequent writes are no-ops; close is also safe.
    dump.append(b"third")
    dump.close()


def test_call_sid_with_special_chars_is_sanitized(tmp_path: Path) -> None:
    audio_dump.settings.niko_local_audio_dump_dir = str(tmp_path)
    dump = audio_dump.open_caller_dump("CA/123\\..\\..\\evil")
    assert dump is not None
    dump.close()
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    # No path separators should survive sanitization.
    assert "/" not in files[0].name
    assert "\\" not in files[0].name


def test_empty_append_is_noop(tmp_path: Path) -> None:
    audio_dump.settings.niko_local_audio_dump_dir = str(tmp_path)
    dump = audio_dump.open_caller_dump("CA123")
    assert dump is not None
    dump.append(b"")  # should not crash, should not write
    dump.close()
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == b""


def test_dump_path_is_recorded(tmp_path: Path) -> None:
    audio_dump.settings.niko_local_audio_dump_dir = str(tmp_path)
    dump = audio_dump.open_caller_dump("CA123")
    assert dump is not None
    assert os.path.dirname(dump.path) == str(tmp_path)
    assert dump.path.endswith(".ulaw")
    dump.close()
