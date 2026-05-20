"""Pure-function checks that decide whether the AI loop should transfer
the caller to a human. Kept free of WebSocket / Twilio dependencies so
they can be unit-tested independently of the call harness.

Track 2's WebSocket integration in ``app/telephony/router.py`` calls
``should_trigger_transfer`` at end-of-stream with accumulated state and
persists the result to the call session. The ``/voice/stream-ended``
action callback (Phase C) reads it and returns either ``<Dial>`` TwiML
(transfer) or empty TwiML (normal end) accordingly.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

# Threshold above which we assume the ASR is fundamentally not
# picking the caller up. Tunable post-pilot.
MISHEARD_THRESHOLD = 3

_HUMAN_INTENT = re.compile(
    r"\b("
    r"(let\s+me|i\s+(want\s+to|need\s+to|wanna))\s+"
    r"(speak|talk)\s+to\s+(a\s+)?(human|person|someone|real\s+person)"
    r"|"
    r"can\s+i\s+(speak|talk)\s+to\s+(a\s+)?(human|person|someone)"
    r"|"
    r"give\s+me\s+a\s+(real\s+)?(human|person)"
    r")\b",
    re.IGNORECASE,
)


class TransferReason(str, Enum):
    MISHEARD_TURNS = "misheard_turns"
    LLM_ERROR = "llm_error"
    TTS_ERROR = "tts_error"
    HUMAN_INTENT = "human_intent"


def detect_human_intent_in_text(text: str) -> bool:
    """True if the caller's transcript reads as a request for a human.
    Conservative regex; tune at sprint-end if false positives are noisy.
    Future: replace with LLM-based intent classification."""
    if not text:
        return False
    return _HUMAN_INTENT.search(text) is not None


def should_trigger_transfer(
    *,
    consecutive_low_confidence_turns: int,
    last_transcript: str,
    llm_error_occurred: bool,
    tts_error_occurred: bool = False,
) -> Optional[TransferReason]:
    """Return the first matching transfer reason, or None.

    The order matters — LLM error takes highest priority (Anthropic
    failure is a harder signal than Deepgram TTS), then human intent,
    then TTS error, then the misheard threshold.
    """
    if llm_error_occurred:
        return TransferReason.LLM_ERROR
    if detect_human_intent_in_text(last_transcript):
        return TransferReason.HUMAN_INTENT
    if tts_error_occurred:
        return TransferReason.TTS_ERROR
    if consecutive_low_confidence_turns >= MISHEARD_THRESHOLD:
        return TransferReason.MISHEARD_TURNS
    return None
