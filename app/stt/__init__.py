"""Public entry point for the STT abstraction layer.

Re-exports the contract so callers do ``from app.stt import
TranscriptEvent`` instead of reaching into ``app.stt.base``.
"""

from app.stt.base import (
    EarlyTurnEndEvent,
    SpeechStartedEvent,
    STTEvent,
    STTProvider,
    TranscriptEvent,
    TurnResumedEvent,
)

__all__ = [
    "EarlyTurnEndEvent",
    "STTEvent",
    "STTProvider",
    "SpeechStartedEvent",
    "TranscriptEvent",
    "TurnResumedEvent",
    "get_stt",
]


def get_stt(
    *,
    call_sid: str | None = None,
    keyterms: "list[str] | None" = None,
) -> tuple["STTProvider", str]:
    """Return the configured STT provider plus its name.

    ``keyterms`` (when provided) is forwarded to providers that support
    biased recognition; the Deepgram Flux provider uses it to pre-bias
    against the active tenant's menu vocabulary. Providers that don't
    support keyterms ignore the argument — callers can always pass it
    safely.

    The provider name is returned alongside the provider so the caller
    (the router consumer) can include ``provider`` metadata in events
    when desired, without the plugin needing to know its own name.
    """
    from app.config import settings

    name = settings.stt_provider
    if name == "deepgram":
        from app.deepgram.stt import DeepgramSTT

        return DeepgramSTT(call_sid=call_sid, keyterms=keyterms), name
    raise ValueError(f"Unknown STT provider: {name}")
