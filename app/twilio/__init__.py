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
