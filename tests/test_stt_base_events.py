"""Tests for the vendor-neutral event dataclasses in app.stt.base.

These events are the contract between STT providers and consumers.
Pinning their shape protects both Flux's translation and any future
provider (Whisper) that needs to emit them.
"""

from __future__ import annotations

import dataclasses
from typing import get_args

import pytest

from app.stt.base import (
    EarlyTurnEndEvent,
    SpeechStartedEvent,
    STTEvent,
    TranscriptEvent,
    TurnResumedEvent,
)


def test_early_turn_end_event_is_frozen() -> None:
    e = EarlyTurnEndEvent()
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.some_attr = "x"  # type: ignore[attr-defined]


def test_turn_resumed_event_is_frozen() -> None:
    e = TurnResumedEvent()
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.some_attr = "x"  # type: ignore[attr-defined]


def test_stt_event_union_includes_all_four_types() -> None:
    members = set(get_args(STTEvent))
    assert members == {
        TranscriptEvent,
        SpeechStartedEvent,
        EarlyTurnEndEvent,
        TurnResumedEvent,
    }


def test_early_and_resumed_events_have_no_payload_fields() -> None:
    """These events are pure signals — they carry no payload. Pinning
    that here so a future-PR field addition is a deliberate, reviewed
    change rather than an accidental drift."""
    assert dataclasses.fields(EarlyTurnEndEvent) == ()
    assert dataclasses.fields(TurnResumedEvent) == ()


def test_existing_event_shapes_unchanged() -> None:
    """Regression guard. The migration must not silently change the
    field set on the two pre-existing event types."""
    assert {f.name for f in dataclasses.fields(SpeechStartedEvent)} == {"at"}
    assert {f.name for f in dataclasses.fields(TranscriptEvent)} == {
        "text",
        "is_final",
        "confidence",
    }
