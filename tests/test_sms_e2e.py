"""End-to-end test: Order confirmation triggers SMS through the full
lifecycle path with only Twilio mocked at the boundary."""

from unittest.mock import MagicMock, patch

import pytest

from app.orders.lifecycle import persist_on_confirm
from app.orders.models import (
    ItemCategory,
    LineItem,
    Order,
    OrderType,
)
from app.storage import firestore as storage


@pytest.fixture(autouse=True)
def reset_storage_client():
    yield
    storage.set_client(None)


def test_confirm_to_sms_full_path():
    fs_client = MagicMock()
    storage.set_client(fs_client)

    # Wire get_order to return an order without sms_sent populated, so
    # the idempotency check passes through to Twilio.
    order = Order(
        call_sid="CAfull",
        caller_phone="+15551234567",
        restaurant_id="niko-pizza-kitchen",
        items=[
            LineItem(
                name="Pepperoni",
                category=ItemCategory.PIZZA,
                size="medium",
                quantity=1,
                unit_price=17.99,
            ),
        ],
        order_type=OrderType.PICKUP,
    )

    snapshot = MagicMock()
    snapshot.exists = True
    # First save_order writes the confirmed order; later get_order reads
    # it back. Stub get to return the confirmed order.
    confirmed_dump = order.model_copy(
        update={"status": "confirmed"},
    ).model_dump(mode="python")
    snapshot.to_dict.return_value = confirmed_dump
    (
        fs_client.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value
    ) = snapshot

    with (
        patch("app.sms.client._twilio_client") as twilio_factory,
        patch(
            "app.config.settings.twilio_messaging_service_sid",
            "MGfake",
        ),
        patch("app.config.settings.twilio_account_sid", "ACfake"),
        patch("app.config.settings.twilio_auth_token", "tokenfake"),
    ):
        twilio_factory.return_value.messages.create.return_value = MagicMock(
            sid="SMend2end",
            status="queued",
        )
        confirmed = persist_on_confirm(order)

    twilio_factory.return_value.messages.create.assert_called_once()
    body = twilio_factory.return_value.messages.create.call_args.kwargs["body"]
    assert "Pepperoni" in body
    assert "$17.99" in body
    assert confirmed.status.value == "confirmed"
