"""Server-side validators for order field shapes (Sprint 2.2 #105).

Pure functions: input → bool. Orchestration (rejecting payloads,
shaping tool_result feedback) lives in the LLM client, not here.
"""

from __future__ import annotations


def validate_delivery_address(addr: str | None) -> bool:
    """A delivery address is acceptable iff it is non-empty after
    stripping whitespace AND contains at least one digit.

    Voice transcription is noisy: callers say partial addresses
    ("14 Main"), Deepgram drops words, garbage like "uhh" gets
    captured. This is the minimum bar to filter clearly-broken
    captures without rejecting realistic short addresses. Geocoder-
    grade validation is out of scope.
    """
    if addr is None:
        return False
    stripped = addr.strip()
    if not stripped:
        return False
    return any(ch.isdigit() for ch in stripped)
