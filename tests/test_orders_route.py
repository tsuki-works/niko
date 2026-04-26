"""Tests for the dashboard /orders read route and /dev/seed-order.

Uses the Firestore storage module's ``set_client`` injection hook with
a ``MagicMock`` so the HTTP layer is exercised end-to-end without any
GCP dependency.

After PR C of #79, orders live under
``restaurants/{restaurant_id}/orders/{call_sid}`` — the MagicMock chain
mirrors that nesting.

After PR D of #81, /orders requires Firebase Auth — the
``current_tenant`` dependency is overridden via ``app.dependency_overrides``
to inject a fake tenant for test runs.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth.dependency import Tenant, current_tenant
from app.config import settings
from app.main import app
from app.storage import firestore as storage

client = TestClient(app)

_DEMO_RID = "niko-pizza-kitchen"
_TEST_TENANT = Tenant(
    uid="uid-test",
    email="owner@niko.com",
    restaurant_id=_DEMO_RID,
    role="owner",
)


@pytest.fixture(autouse=True)
def reset_storage_client():
    yield
    storage.set_client(None)


@pytest.fixture(autouse=True)
def override_tenant():
    """Bypass auth verification for the route tests by overriding
    ``current_tenant`` with a fixed demo tenant. Route logic still
    runs end-to-end through the dep, but we don't need a real
    Firebase token."""
    app.dependency_overrides[current_tenant] = lambda: _TEST_TENANT
    yield
    app.dependency_overrides.pop(current_tenant, None)


@pytest.fixture
def dev_endpoints_enabled(monkeypatch):
    monkeypatch.setattr(settings, "niko_dev_endpoints", True)


def _fake_firestore_with_orders(docs: list[dict]) -> MagicMock:
    fake_client = MagicMock()
    snapshots = []
    for doc in docs:
        snap = MagicMock()
        snap.to_dict.return_value = doc
        snapshots.append(snap)

    # Path: restaurants/{rid}/orders → order_by → limit → stream
    (
        fake_client.collection.return_value
        .document.return_value
        .collection.return_value
        .order_by.return_value
        .limit.return_value
        .stream.return_value
    ) = iter(snapshots)
    storage.set_client(fake_client)
    return fake_client


def test_list_orders_returns_recent_orders():
    _fake_firestore_with_orders([
        {
            "call_sid": "CA1",
            "items": [
                {
                    "name": "Pepperoni",
                    "category": "pizza",
                    "size": "medium",
                    "quantity": 1,
                    "unit_price": 17.99,
                    "modifications": [],
                }
            ],
            "order_type": "pickup",
            "status": "confirmed",
        },
        {"call_sid": "CA2", "items": []},
    ])

    response = client.get("/orders")

    assert response.status_code == 200
    body = response.json()
    assert [o["call_sid"] for o in body["orders"]] == ["CA1", "CA2"]
    # Computed fields make it into the JSON payload for the dashboard.
    assert body["orders"][0]["subtotal"] == 17.99
    assert body["orders"][0]["items"][0]["line_total"] == 17.99


def test_list_orders_addresses_authenticated_tenant():
    """``/orders`` reads under
    ``restaurants/{tenant.restaurant_id}/orders``. The tenant comes
    from the verified session — no query param override is honored."""
    fake = _fake_firestore_with_orders([])

    client.get("/orders")

    fake.collection.assert_called_with("restaurants")
    fake.collection.return_value.document.assert_called_with(_DEMO_RID)
    (
        fake.collection.return_value
        .document.return_value
        .collection.assert_called_with("orders")
    )


def test_list_orders_ignores_query_param_attempts_to_cross_tenant():
    """An explicit ``?restaurant_id=other`` does NOT widen the read
    scope — auth is the source of truth."""
    fake = _fake_firestore_with_orders([])

    client.get("/orders?restaurant_id=pizza-palace")

    fake.collection.return_value.document.assert_called_with(_DEMO_RID)


def test_list_orders_returns_401_without_auth():
    """Without the auth dep override, no credentials → 401."""
    app.dependency_overrides.pop(current_tenant, None)
    try:
        response = client.get("/orders")
        assert response.status_code == 401
    finally:
        app.dependency_overrides[current_tenant] = lambda: _TEST_TENANT


def test_list_orders_respects_limit_query_param():
    fake = _fake_firestore_with_orders([])

    response = client.get("/orders?limit=10")

    assert response.status_code == 200
    (
        fake.collection.return_value
        .document.return_value
        .collection.return_value
        .order_by.return_value
        .limit.assert_called_with(10)
    )


def test_list_orders_rejects_out_of_range_limit():
    _fake_firestore_with_orders([])

    assert client.get("/orders?limit=0").status_code == 400
    assert client.get("/orders?limit=500").status_code == 400


def test_seed_order_returns_404_when_dev_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "niko_dev_endpoints", False)

    response = client.post("/dev/seed-order")

    assert response.status_code == 404


def test_seed_order_persists_when_dev_flag_on(dev_endpoints_enabled):
    fake = MagicMock()
    storage.set_client(fake)

    response = client.post("/dev/seed-order")

    assert response.status_code == 200
    body = response.json()
    assert body["doc_id"].startswith("CAseed-")
    assert body["order"]["order_type"] == "pickup"
    assert len(body["order"]["items"]) == 2

    # Seed orders land under the demo tenant's nested path.
    fake.collection.assert_called_with("restaurants")
    fake.collection.return_value.document.assert_called_with(_DEMO_RID)
    (
        fake.collection.return_value
        .document.return_value
        .collection.assert_called_with("orders")
    )
    set_call = (
        fake.collection.return_value
        .document.return_value
        .collection.return_value
        .document.return_value
        .set
    )
    set_call.assert_called_once()
