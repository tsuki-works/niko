"""Tests for jarvis.logging_setup."""

from __future__ import annotations

import logging

from jarvis.logging_setup import configure_logging


def test_configure_logging_sets_root_level():
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_idempotent():
    configure_logging("INFO")
    handlers_before = list(logging.getLogger().handlers)
    configure_logging("INFO")
    handlers_after = list(logging.getLogger().handlers)
    # Should not duplicate handlers on repeat invocation.
    assert len(handlers_after) == len(handlers_before)


def test_configure_logging_invalid_level_falls_back_to_info(caplog):
    configure_logging("NOT_A_LEVEL")
    assert logging.getLogger().level == logging.INFO
