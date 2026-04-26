"""Firestore persistence for orders (PR C of #79).

Path: ``restaurants/{restaurant_id}/orders/{call_sid}``. Nested under
the restaurant doc so security rules can grant ``request.auth.token
.restaurant_id == rid`` access in one place (PR E owns those rules).

Documents are keyed by ``call_sid`` so writes during a single call are
idempotent — the same Twilio call always maps to the same document.

Auth resolution:

- In Cloud Run, the service account attached to the service auto-auths
  via the GCE metadata server — no setup needed.
- Locally: ``gcloud auth application-default login`` or point
  ``GOOGLE_APPLICATION_CREDENTIALS`` at a service-account JSON.

Project is auto-detected in Cloud Run. Locally set
``GOOGLE_CLOUD_PROJECT=niko-tsuki``.

Computed fields on ``Order`` / ``LineItem`` (``subtotal``,
``line_total``) are written to Firestore as plain numbers for easy
reads by the dashboard. On the way back through ``model_validate``
they are dropped and recomputed from the source fields, so stored
values can't drift.

Migration note: pre-#79, orders lived in a flat ``orders`` collection.
``scripts/migrate_to_nested_subcollections.py`` copies historical docs
into the new path. The flat collection becomes read-only legacy data
until PR F deletes it.
"""

from __future__ import annotations

from typing import Optional

from google.cloud import firestore

from app.orders.models import Order

_RESTAURANTS_COLLECTION = "restaurants"
_ORDERS_SUBCOLLECTION = "orders"

_client: Optional[firestore.Client] = None


def _get_client() -> firestore.Client:
    global _client
    if _client is None:
        _client = firestore.Client()
    return _client


def set_client(client: Optional[firestore.Client]) -> None:
    """Override the module-level Firestore client.

    Used by tests (with a ``MagicMock``) and by the Firestore emulator
    wiring. Pass ``None`` to reset to the default client on next call.
    """

    global _client
    _client = client


def _orders_collection(client: firestore.Client, restaurant_id: str):
    return (
        client.collection(_RESTAURANTS_COLLECTION)
        .document(restaurant_id)
        .collection(_ORDERS_SUBCOLLECTION)
    )


def save_order(order: Order) -> str:
    """Upsert an Order under its restaurant, keyed by ``call_sid``.

    Path: ``restaurants/{order.restaurant_id}/orders/{order.call_sid}``.
    Idempotent across retries within the same call.
    """

    client = _get_client()
    payload = order.model_dump(mode="python")
    _orders_collection(client, order.restaurant_id).document(order.call_sid).set(
        payload
    )
    return order.call_sid


def get_order(call_sid: str, restaurant_id: str) -> Optional[Order]:
    """Fetch a single Order by ``call_sid`` under a restaurant.

    Returns ``None`` if the document doesn't exist. ``restaurant_id``
    is required — multi-tenant reads must always be scoped.
    """

    client = _get_client()
    snapshot = (
        _orders_collection(client, restaurant_id).document(call_sid).get()
    )
    if not snapshot.exists:
        return None
    return Order.model_validate(snapshot.to_dict())


def list_recent_orders(
    restaurant_id: str, limit: int = 50
) -> list[Order]:
    """Return one restaurant's recent orders, newest-first, up to ``limit``."""

    client = _get_client()
    query = (
        _orders_collection(client, restaurant_id)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [Order.model_validate(snap.to_dict()) for snap in query.stream()]
