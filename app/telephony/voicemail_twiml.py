"""Voicemail TwiML rendering. Stub for Phase C; Phase D fills out the
recording + transcription wiring with real <Record> attributes."""

from __future__ import annotations

from twilio.twiml.voice_response import VoiceResponse


def voicemail_response(call_sid: str, restaurant_id: str) -> VoiceResponse:
    """Return TwiML that plays a brief greeting and records the caller's
    voicemail. Phase D will wire `transcribe=True`, `transcribeCallback`,
    and `action` for the recording-ready callback. For Phase C, this
    stub gives downstream tests a `<Record>` element to assert on."""
    twiml = VoiceResponse()
    twiml.say(
        "We weren't able to take your call. Please leave a message after "
        "the tone, and we'll get back to you.",
        voice="alice",
    )
    twiml.record(
        max_length=90,
        action=f"/voice/voicemail-recorded?call_sid={call_sid}&rid={restaurant_id}",
        transcribe=True,
        transcribe_callback=(
            f"/voice/voicemail-transcription?call_sid={call_sid}&rid={restaurant_id}"
        ),
        method="POST",
    )
    twiml.hangup()
    return twiml
