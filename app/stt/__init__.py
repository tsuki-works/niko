"""Public entry point for the STT abstraction layer.

Re-exports the contract so callers do ``from app.stt import
TranscriptEvent`` instead of reaching into ``app.stt.base``. The
``get_stt()`` selector is added in a later task once a concrete
implementation exists.
"""

from app.stt.base import (
    STTEvent,
    STTProvider,
    SpeechStartedEvent,
    TranscriptEvent,
)

__all__ = [
    "STTEvent",
    "STTProvider",
    "SpeechStartedEvent",
    "TranscriptEvent",
]
