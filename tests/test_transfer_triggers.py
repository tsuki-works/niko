"""Unit tests for app.telephony.transfer_triggers.

Each function is a pure check that returns True if its trigger condition
is met for a given snapshot of call state."""

from app.telephony.transfer_triggers import (
    detect_human_intent_in_text,
    should_trigger_transfer,
    TransferReason,
)


def test_detect_human_intent_matches_common_phrases():
    cases = [
        "let me talk to a human please",
        "can I speak to a person",
        "I want to talk to someone",
        "give me a real person",
    ]
    for text in cases:
        assert detect_human_intent_in_text(text), text


def test_detect_human_intent_does_not_match_unrelated():
    cases = [
        "I want a pepperoni pizza",
        "talk dirty to me",
        "person of interest is a great show",
    ]
    for text in cases:
        assert not detect_human_intent_in_text(text), text


def test_detect_human_intent_handles_punctuation_and_case():
    assert detect_human_intent_in_text("Let me SPEAK to a Person!")


def test_should_trigger_transfer_after_three_misheard_turns():
    reason = should_trigger_transfer(
        consecutive_low_confidence_turns=3,
        last_transcript="any",
        llm_error_occurred=False,
    )
    assert reason is TransferReason.MISHEARD_TURNS


def test_should_trigger_transfer_on_llm_error():
    reason = should_trigger_transfer(
        consecutive_low_confidence_turns=0,
        last_transcript="any",
        llm_error_occurred=True,
    )
    assert reason is TransferReason.LLM_ERROR


def test_should_trigger_transfer_on_human_intent():
    reason = should_trigger_transfer(
        consecutive_low_confidence_turns=0,
        last_transcript="please let me talk to a human",
        llm_error_occurred=False,
    )
    assert reason is TransferReason.HUMAN_INTENT


def test_should_trigger_transfer_returns_none_below_threshold():
    reason = should_trigger_transfer(
        consecutive_low_confidence_turns=2,
        last_transcript="my pizza order",
        llm_error_occurred=False,
    )
    assert reason is None
