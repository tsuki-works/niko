"""Exception types raised by app.sms."""

from __future__ import annotations


class SmsError(Exception):
    """Outbound SMS failed. Caller decides whether to retry or surface
    the failure. The lifecycle hook treats this as best-effort and
    does not roll back the order on failure."""
