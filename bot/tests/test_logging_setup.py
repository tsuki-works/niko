"""Tests for jarvis.logging_setup."""

from __future__ import annotations

import logging

from jarvis.logging_setup import configure_logging


def test_configure_logging_sets_root_level():
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_idempotent():
    configure_logging("INFO")
    configure_logging("INFO")
    tagged = [
        h for h in logging.getLogger().handlers if getattr(h, "_jarvis_stream_handler", False)
    ]
    assert len(tagged) == 1


def test_configure_logging_invalid_level_falls_back_to_info(caplog):
    configure_logging("NOT_A_LEVEL")
    assert logging.getLogger().level == logging.INFO
    assert caplog.records == []
