"""Twilio vendor module.

Holds Twilio-specific I/O — TwiML response builders, Media Stream
WebSocket protocol primitives, and REST helpers — kept separate from
the vendor-neutral call orchestration in app/telephony/. Mirrors the
app/deepgram/ pattern.

Consumers that need vendor-agnostic call logic should import from
app/telephony/, not from here. Anything that touches a Twilio JSON
envelope, TwiML XML, or Twilio's REST API lives under this package.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.storage import recordings as _recordings

logger = logging.getLogger(__name__)


def twilio_basic_auth() -> tuple[str, str] | None:
    """Return Twilio REST basic-auth tuple, or None when unconfigured.

    Centralised so the voicemail-recorded callback doesn't have to
    reach into ``settings.twilio_account_sid`` /
    ``settings.twilio_auth_token`` directly. Returns None (rather than
    raising) so the caller can log + degrade gracefully — voicemail
    upload is best-effort, missing creds shouldn't crash the request.
    """
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    if not sid or not token:
        return None
    return (sid, token)


def upload_voicemail(
    *,
    call_sid: str,
    restaurant_id: str,
    twilio_recording_url: str,
) -> str:
    """Download the voicemail recording from Twilio's REST API and
    upload to GCS. Wraps app.storage.recordings.upload_voicemail_from_twilio
    with the Twilio creds resolved from settings.

    Raises RuntimeError if Twilio creds are missing — the caller is
    expected to check ``twilio_basic_auth()`` first if it wants to
    short-circuit gracefully (the voicemail-recorded handler does).
    """
    auth = twilio_basic_auth()
    if auth is None:
        raise RuntimeError("Twilio credentials missing")
    return _recordings.upload_voicemail_from_twilio(
        call_sid=call_sid,
        restaurant_id=restaurant_id,
        twilio_recording_url=twilio_recording_url,
        auth=auth,
    )
