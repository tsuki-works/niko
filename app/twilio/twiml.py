"""TwiML response builders for the Twilio voice webhook surface.

Pure functions returning Twilio VoiceResponse objects. The FastAPI
handlers in app/telephony/router.py call these and wrap the result
in a fastapi.Response with media_type='application/xml'.

Kept separate so that:
- TwiML XML construction lives in one place (mirrors app/deepgram/);
- builders are easy to snapshot-test without spinning up FastAPI;
- the orchestration layer in app/telephony/ never imports from
  twilio.twiml directly.
"""

from __future__ import annotations

from twilio.twiml.voice_response import Connect, Dial, VoiceResponse

from app.restaurants.models import Restaurant


_UNCONFIGURED_TWIML_MESSAGE = (
    "Sorry, this number is not currently configured. Goodbye."
)
_CLOSED_TWIML_MESSAGE = (
    "Sorry, we're closed. Please call back during business hours."
)


def empty_twiml() -> VoiceResponse:
    """Empty <Response/>. Used for hangup-on-success paths and as a
    safe default when a Twilio callback can't be acted on."""
    return VoiceResponse()


def unconfigured_hangup_twiml() -> VoiceResponse:
    """Inbound call to a number that isn't mapped to any tenant."""
    twiml = VoiceResponse()
    twiml.say(_UNCONFIGURED_TWIML_MESSAGE)
    twiml.hangup()
    return twiml


def closed_hangup_twiml() -> VoiceResponse:
    """Defensive after-hours hangup for the rare case the voicemail
    flow can't run (e.g. CallSid missing on the inbound webhook)."""
    twiml = VoiceResponse()
    twiml.say(_CLOSED_TWIML_MESSAGE)
    twiml.hangup()
    return twiml


def voice_twiml(restaurant: Restaurant, ws_host: str) -> VoiceResponse:
    """Open a bidirectional Media Stream back to /media-stream and
    forward the resolved restaurant id via <Parameter> so the WS
    handler doesn't need to re-query Firestore."""
    twiml = VoiceResponse()
    connect = Connect(action="/voice/stream-ended", method="POST")
    # NOTE: <Connect><Stream> only supports the default ``inbound_track``;
    # passing ``track="both_tracks"`` makes Twilio reject the TwiML and
    # the call drops the moment the caller dismisses the trial-account
    # interstitial. To capture the agent's voice in the recording, the
    # /media-stream WS handler intercepts the TTS bytes we send out via
    # ``speak()`` and feeds them directly into the recording session.
    stream = connect.stream(url=f"wss://{ws_host}/media-stream")
    stream.parameter(name="restaurant_id", value=restaurant.id)
    twiml.append(connect)
    return twiml


def transfer_twiml(
    fallback_phone: str,
    call_sid: str,
    rid: str,
    *,
    timeout: int = 20,
) -> VoiceResponse:
    """Dial the tenant's fallback number, with action callback to
    /voice/transfer-result so we can record the outcome and cascade
    to voicemail on no-answer/busy/failed."""
    twiml = VoiceResponse()
    dial = Dial(
        action=f"/voice/transfer-result?call_sid={call_sid}&rid={rid}",
        method="POST",
        timeout=timeout,
    )
    dial.number(fallback_phone)
    twiml.append(dial)
    return twiml
