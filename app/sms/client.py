"""Outbound SMS client — Twilio REST wrapper with idempotency.

The function flow:

1. Parse the idempotency key into (call_sid, template_name).
2. Read the order doc from Firestore.
3. If sms_sent[template_name] already exists, short-circuit — the
   original record is the source of truth.
4. Otherwise, send via Twilio's Messaging Service.
5. Write sms_sent[template_name] back to the order doc.

Sync — Twilio's SDK is sync, the storage layer is sync, async callers
wrap with asyncio.to_thread.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from twilio.rest import Client as TwilioClient

from app.config import settings
from app.orders.models import SmsSentRecord
from app.sms.exceptions import SmsError
from app.storage import firestore as order_storage


class SmsResult(BaseModel):
    sid: str
    status: str  # Twilio message status (queued | sending | sent | delivered | failed)
    sent_at: datetime


def _twilio_client() -> TwilioClient:
    """Construct a Twilio client at call time so tests can patch this."""
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise SmsError("Twilio credentials missing — set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.")
    return TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)


def send_sms(
    to: str,
    body: str,
    *,
    idempotency_key: str,
    tenant_id: str,
) -> SmsResult:
    """Send a single SMS, idempotent on (call_sid, template_name).

    ``idempotency_key`` is ``f"{call_sid}:{template_name}"``. The split
    is the contract — callers form keys this way and ``send_sms`` parses
    back. Returns the existing record if one is already present for the
    key. Raises ``SmsError`` on Twilio failure or missing order.
    """
    if ":" not in idempotency_key:
        raise SmsError(f"idempotency_key must be 'call_sid:template_name', got {idempotency_key!r}")
    call_sid, template_name = idempotency_key.split(":", 1)

    order = order_storage.get_order(call_sid, tenant_id)
    if order is None:
        raise SmsError(
            f"order {call_sid!r} not found under tenant {tenant_id!r} — "
            "cannot record SMS idempotency without the order doc"
        )

    existing = order.sms_sent.get(template_name)
    if existing is not None:
        return SmsResult(
            sid=existing.sid,
            status="sent",  # Re-sends would have updated the record; presence implies a successful prior dispatch
            sent_at=existing.sent_at,
        )

    if not settings.twilio_messaging_service_sid:
        raise SmsError(
            "TWILIO_MESSAGING_SERVICE_SID not configured — outbound SMS "
            "requires a Messaging Service for 10DLC compliance."
        )

    try:
        message = _twilio_client().messages.create(
            to=to,
            body=body,
            messaging_service_sid=settings.twilio_messaging_service_sid,
        )
    except SmsError:
        raise
    except Exception as exc:  # twilio raises various subclasses
        raise SmsError(f"Twilio send failed: {exc}") from exc

    sent_at = datetime.now(timezone.utc)
    record = SmsSentRecord(sid=message.sid, sent_at=sent_at)
    updated = order.model_copy(
        update={"sms_sent": {**order.sms_sent, template_name: record}},
    )
    order_storage.save_order(updated)
    return SmsResult(
        sid=message.sid,
        status=message.status,
        sent_at=sent_at,
    )
