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


# ---------------------------------------------------------------------------
# B1 transition endpoints (Sprint 2.2 #107)
# ---------------------------------------------------------------------------

# Tests below cover four endpoints × three concerns:
# - 200 + correct payload on valid transition
# - 404 when the order doesn't exist or belongs to a different tenant
# - 409 when the order is in the wrong source state
#
# Mocking: same TestClient + tenant-injection + firestore-mock pattern as
# above. get_order reads via .collection().document().collection().document()
# .get(); save_order writes via the same path's .set(). We only need the
# read side to return data — writes can silently succeed via MagicMock.


def _fake_firestore_with_single_order(doc: dict | None) -> MagicMock:
    """Seed a fake Firestore client that returns ``doc`` for any single-doc
    .get() call, and ``None`` (snapshot.exists == False) when ``doc is
    None``. Also wires the list path so any list_recent_orders calls
    that happen to fire don't blow up."""
    fake_client = MagicMock()

    snapshot = MagicMock()
    if doc is not None:
        snapshot.exists = True
        snapshot.to_dict.return_value = doc
    else:
        snapshot.exists = False

    (
        fake_client.collection.return_value
        .document.return_value
        .collection.return_value
        .document.return_value
        .get.return_value
    ) = snapshot

    # Wire the list path too so the stream doesn't raise on accidental calls.
    (
        fake_client.collection.return_value
        .document.return_value
        .collection.return_value
        .order_by.return_value
        .limit.return_value
        .stream.return_value
    ) = iter([])

    storage.set_client(fake_client)
    return fake_client


def _confirmed_order_doc(call_sid: str = "CA-test-1") -> dict:
    return {
        "call_sid": call_sid,
        "restaurant_id": _DEMO_RID,
        "status": "confirmed",
        "order_type": "pickup",
        "items": [
            {
                "name": "Pepperoni",
                "category": "pizza",
                "quantity": 1,
                "unit_price": 17.99,
                "modifications": [],
            }
        ],
    }


# Endpoint: POST /orders/{call_sid}/preparing -----------------------------


def test_post_preparing_transitions_confirmed_order():
    _fake_firestore_with_single_order(_confirmed_order_doc())
    response = client.post("/orders/CA-test-1/preparing")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "preparing"
    assert body["preparing_at"] is not None


def test_post_preparing_returns_404_for_other_tenant():
    # Order belongs to a different restaurant; get_order returns None
    # because the tenant-scoped path finds no doc.
    _fake_firestore_with_single_order(None)
    response = client.post("/orders/CA-other-tenant/preparing")
    assert response.status_code == 404


def test_post_preparing_returns_409_for_in_progress_order():
    doc = _confirmed_order_doc("CA-bad")
    doc["status"] = "in_progress"
    _fake_firestore_with_single_order(doc)
    response = client.post("/orders/CA-bad/preparing")
    assert response.status_code == 409
    assert "Cannot transition" in response.json()["detail"]


# Endpoint: POST /orders/{call_sid}/ready --------------------------------


def test_post_ready_transitions_preparing_order():
    doc = _confirmed_order_doc("CA-prep")
    doc["status"] = "preparing"
    _fake_firestore_with_single_order(doc)
    response = client.post("/orders/CA-prep/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["ready_at"] is not None


def test_post_ready_returns_409_for_confirmed_order():
    _fake_firestore_with_single_order(_confirmed_order_doc("CA-bad-ready"))
    response = client.post("/orders/CA-bad-ready/ready")
    assert response.status_code == 409
    assert "Cannot transition" in response.json()["detail"]


# Endpoint: POST /orders/{call_sid}/completed ----------------------------


def test_post_completed_transitions_ready_order():
    doc = _confirmed_order_doc("CA-rdy")
    doc["status"] = "ready"
    _fake_firestore_with_single_order(doc)
    response = client.post("/orders/CA-rdy/completed")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None


def test_post_completed_returns_409_for_preparing_order():
    doc = _confirmed_order_doc("CA-bad-comp")
    doc["status"] = "preparing"
    _fake_firestore_with_single_order(doc)
    response = client.post("/orders/CA-bad-comp/completed")
    assert response.status_code == 409
    assert "Cannot transition" in response.json()["detail"]


# Endpoint: POST /orders/{call_sid}/cancel -------------------------------


def test_post_cancel_transitions_from_preparing():
    doc = _confirmed_order_doc("CA-cancel-prep")
    doc["status"] = "preparing"
    _fake_firestore_with_single_order(doc)
    response = client.post("/orders/CA-cancel-prep/cancel")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancelled_at"] is not None


def test_post_cancel_returns_409_for_completed_order():
    doc = _confirmed_order_doc("CA-bad-cancel")
    doc["status"] = "completed"
    _fake_firestore_with_single_order(doc)
    response = client.post("/orders/CA-bad-cancel/cancel")
    assert response.status_code == 409
    assert "Cannot transition" in response.json()["detail"]
