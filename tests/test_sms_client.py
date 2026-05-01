"""Unit tests for app.sms.client.send_sms.

Mocks Twilio's REST client and Firestore, mirroring
test_orders_lifecycle.py's MagicMock pattern.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.orders.models import (
    ItemCategory,
    LineItem,
    Order,
    OrderType,
    SmsSentRecord,
)
from app.sms.client import SmsResult, send_sms
from app.sms.exceptions import SmsError
from app.storage import firestore as storage


@pytest.fixture(autouse=True)
def reset_storage_client():
    yield
    storage.set_client(None)


def _fake_storage(order: Order | None) -> MagicMock:
    """Wire the firestore module to return ``order`` for the
    restaurants/{rid}/orders/{call_sid} read."""
    client = MagicMock()
    storage.set_client(client)
    snapshot = MagicMock()
    if order is None:
        snapshot.exists = False
    else:
        snapshot.exists = True
        snapshot.to_dict.return_value = order.model_dump(mode="python")
    (
        client.collection.return_value
        .document.return_value
        .collection.return_value
        .document.return_value
        .get
        .return_value
    ) = snapshot
    return client


def _ready_order() -> Order:
    return Order(
        call_sid="CAabc",
        caller_phone="+15551234567",
        restaurant_id="niko-pizza-kitchen",
        items=[
            LineItem(
                name="Pepperoni",
                category=ItemCategory.PIZZA,
                size="large",
                quantity=1,
                unit_price=18.99,
            ),
        ],
        order_type=OrderType.PICKUP,
    )


def test_send_sms_calls_twilio_with_messaging_service():
    order = _ready_order()
    _fake_storage(order)
    fake_message = MagicMock(sid="SM123", status="queued")

    with (
        patch("app.sms.client._twilio_client") as twilio_factory,
        patch("app.config.settings.twilio_messaging_service_sid", "MGfake"),
    ):
        twilio_factory.return_value.messages.create.return_value = fake_message
        result = send_sms(
            to="+15551234567",
            body="hello",
            idempotency_key="CAabc:order_confirmation",
            tenant_id="niko-pizza-kitchen",
        )

    twilio_factory.return_value.messages.create.assert_called_once()
    kwargs = twilio_factory.return_value.messages.create.call_args.kwargs
    assert kwargs["to"] == "+15551234567"
    assert kwargs["body"] == "hello"
    assert "messaging_service_sid" in kwargs
    assert isinstance(result, SmsResult)
    assert result.sid == "SM123"
    assert result.status == "queued"


def test_send_sms_short_circuits_when_record_already_exists():
    """If sms_sent[template] already has a record, return it without
    calling Twilio."""
    existing = SmsSentRecord(
        sid="SMexisting",
        sent_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    order = _ready_order()
    order.sms_sent["order_confirmation"] = existing
    _fake_storage(order)

    with patch("app.sms.client._twilio_client") as twilio_factory:
        result = send_sms(
            to="+15551234567",
            body="hello",
            idempotency_key="CAabc:order_confirmation",
            tenant_id="niko-pizza-kitchen",
        )

    twilio_factory.return_value.messages.create.assert_not_called()
    assert result.sid == "SMexisting"
    assert result.status == "sent"  # short-circuit returns "sent" since record's presence implies success


def test_send_sms_writes_record_back_to_firestore_on_success():
    order = _ready_order()
    client = _fake_storage(order)

    with (
        patch("app.sms.client._twilio_client") as twilio_factory,
        patch("app.config.settings.twilio_messaging_service_sid", "MGfake"),
    ):
        twilio_factory.return_value.messages.create.return_value = MagicMock(
            sid="SMnew",
            status="queued",
        )
        send_sms(
            to="+15551234567",
            body="hello",
            idempotency_key="CAabc:order_confirmation",
            tenant_id="niko-pizza-kitchen",
        )

    # Confirm the doc was set with the new record under sms_sent
    set_call = (
        client.collection.return_value
        .document.return_value
        .collection.return_value
        .document.return_value
        .set
    )
    set_call.assert_called_once()
    payload = set_call.call_args.args[0]
    assert "order_confirmation" in payload["sms_sent"]
    assert payload["sms_sent"]["order_confirmation"]["sid"] == "SMnew"


def test_send_sms_raises_sms_error_when_twilio_fails():
    order = _ready_order()
    _fake_storage(order)

    with (
        patch("app.sms.client._twilio_client") as twilio_factory,
        patch("app.config.settings.twilio_messaging_service_sid", "MGfake"),
    ):
        twilio_factory.return_value.messages.create.side_effect = Exception(
            "twilio is sad",
        )
        with pytest.raises(SmsError) as exc:
            send_sms(
                to="+15551234567",
                body="hello",
                idempotency_key="CAabc:order_confirmation",
                tenant_id="niko-pizza-kitchen",
            )
        assert "twilio is sad" in str(exc.value)


def test_send_sms_raises_sms_error_when_order_not_found():
    _fake_storage(None)

    with pytest.raises(SmsError) as exc:
        send_sms(
            to="+15551234567",
            body="hello",
            idempotency_key="CAmissing:order_confirmation",
            tenant_id="niko-pizza-kitchen",
        )
    assert "not found" in str(exc.value).lower()


def test_send_sms_rejects_malformed_idempotency_key():
    with pytest.raises(SmsError):
        send_sms(
            to="+15551234567",
            body="hello",
            idempotency_key="no-colon-here",
            tenant_id="niko-pizza-kitchen",
        )


def test_send_sms_raises_when_messaging_service_sid_missing():
    """Production safeguard: env var unset → fail fast with a clear
    error rather than letting Twilio reject opaquely."""
    order = _ready_order()
    _fake_storage(order)

    with (
        patch("app.sms.client._twilio_client") as twilio_factory,
        patch("app.config.settings.twilio_messaging_service_sid", None),
    ):
        with pytest.raises(SmsError) as exc:
            send_sms(
                to="+15551234567",
                body="hello",
                idempotency_key="CAabc:order_confirmation",
                tenant_id="niko-pizza-kitchen",
            )
        assert "MESSAGING_SERVICE_SID" in str(exc.value)
        twilio_factory.return_value.messages.create.assert_not_called()
