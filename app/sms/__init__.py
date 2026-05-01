"""Outbound SMS — Twilio Messaging Service wrapper, idempotency-keyed.

Shared with Sprint 2.3 payments work (which adds payment_link and
payment_expired templates without touching the client).
"""

from app.sms.client import SmsResult, send_sms
from app.sms.exceptions import SmsError

__all__ = ["SmsError", "SmsResult", "send_sms"]
