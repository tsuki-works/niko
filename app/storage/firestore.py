"""Firestore persistence for orders.

One collection: ``orders``. Documents are keyed by ``call_sid`` so
writes during a single call are idempotent — the same Twilio call
always maps to the same document.

Auth resolution:

- In Cloud Run, the service account attached to the service auto-auths
  via the GCE metadata server — no setup needed.
- Locally: ``gcloud auth application-default login`` or point
  ``GOOGLE_APPLICATION_CREDENTIALS`` at a service-account JSON.

Project is auto-detected in Cloud Run. Locally set
``GOOGLE_CLOUD_PROJECT=niko-tsuki``.

Computed fields on ``Order`` / ``LineItem`` (``subtotal``, ``line_total``)
are written to Firestore as plain numbers for easy reads by the
dashboard. On the way back through ``model_validate`` they are dropped
and recomputed from the source fields, so stored values can't drift.
"""

from __future__ import annotations

from typing import Optional

from google.cloud import firestore

from app.orders.models import Order

_COLLECTION = "orders"

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


def save_order(order: Order) -> str:
    """Upsert an Order into Firestore, keyed by ``call_sid``.

    Returns the document ID (== ``call_sid``). Idempotent across
    retries within the same call.
    """

    client = _get_client()
    payload = order.model_dump(mode="python")
    client.collection(_COLLECTION).document(order.call_sid).set(payload)
    return order.call_sid


def get_order(call_sid: str) -> Optional[Order]:
    """Fetch a single Order by its ``call_sid``. Returns ``None`` if
    the document doesn't exist."""

    client = _get_client()
    snapshot = client.collection(_COLLECTION).document(call_sid).get()
    if not snapshot.exists:
        return None
    return Order.model_validate(snapshot.to_dict())


def list_recent_orders(limit: int = 50) -> list[Order]:
    """Return orders most-recent-first, up to ``limit``. Used by the
    dashboard read route (#41)."""

    client = _get_client()
    query = (
        client.collection(_COLLECTION)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [Order.model_validate(snap.to_dict()) for snap in query.stream()]
