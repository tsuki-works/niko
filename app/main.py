import logging
import time

from fastapi import Depends, FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)

from datetime import datetime
from typing import Any

from app.auth import Tenant, current_tenant
from app.config import settings
from app.orders.models import ItemCategory, LineItem, Order, OrderType
from app.storage import (
    call_sessions,
    firestore as order_storage,
    restaurants as restaurants_storage,
)
from app.storage.restaurants import DEMO_RID
from app.telephony.router import router as telephony_router

app = FastAPI(title="niko")
app.include_router(telephony_router)


@app.get("/")
def root():
    return {"service": "niko", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/me")
def whoami(tenant: Tenant = Depends(current_tenant)):
    """Return the verified tenant context for the dashboard.

    Used right after login to populate the auth-aware UI shell with
    the user's email + restaurant id without re-decoding the cookie
    on the client. Adds a round-trip but keeps the dashboard's
    server-derived auth source-of-truth single.
    """
    return {
        "uid": tenant.uid,
        "email": tenant.email,
        "restaurant_id": tenant.restaurant_id,
        "role": tenant.role,
    }


@app.get("/restaurants/me")
def restaurants_me(tenant: Tenant = Depends(current_tenant)):
    """Return the calling tenant's full Restaurant doc.

    Used by the dashboard header / empty states to surface the live
    ``twilio_phone`` (or its absence). An empty ``twilio_phone`` is the
    explicit "awaiting Twilio number" state — the dashboard renders a
    badge in that case rather than a dead phone number.

    Returns 404 only if the tenant id resolved from the session has no
    matching Firestore doc, which is a genuine misconfiguration —
    don't fall back to ``demo_restaurant_from_menu`` here, that would
    paper over the missing tenant.
    """
    restaurant = restaurants_storage.get_restaurant(tenant.restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="restaurant not found")
    return restaurant.model_dump(mode="json")


@app.get("/orders")
def list_orders(
    limit: int = 50,
    tenant: Tenant = Depends(current_tenant),
):
    """Return the calling tenant's recent orders, most-recent-first.

    Reads from ``restaurants/{tenant.restaurant_id}/orders``. The
    tenant comes from the verified Firebase session cookie or Bearer
    ID token — there is no query-param override (#81 closes the
    cross-tenant-read hole that was open through PR C).
    """
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be 1..200")
    orders = order_storage.list_recent_orders(
        restaurant_id=tenant.restaurant_id, limit=limit
    )
    return {"orders": [o.model_dump(mode="json") for o in orders]}


def _require_dev_endpoints() -> None:
    if not settings.niko_dev_endpoints:
        raise HTTPException(status_code=404, detail="Not Found")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@app.get("/dev/calls")
def dev_list_calls(
    limit: int = 50,
    tenant: Tenant = Depends(current_tenant),
):
    """List the calling tenant's recent call sessions, newest-first.

    Gated on ``NIKO_DEV_ENDPOINTS=true``. Reads from the nested
    ``restaurants/{tenant.restaurant_id}/call_sessions`` subcollection.
    The dashboard's live ``onSnapshot`` now also points at the nested
    path (PR D); the legacy flat collection writes are still mirrored
    in ``app/storage/call_sessions.py`` until PR F removes them.
    """
    _require_dev_endpoints()
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be 1..200")
    sessions = call_sessions.list_recent_sessions(
        restaurant_id=tenant.restaurant_id, limit=limit
    )
    return {
        "calls": [
            {
                "call_sid": s.get("call_sid"),
                "started_at": _iso(s.get("started_at")),
                "ended_at": _iso(s.get("ended_at"))
                or _iso(s.get("last_event_at")),
                "transcript_count": s.get("transcript_count", 0),
                "has_error": s.get("has_error", False),
                "status": s.get("status", "in_progress"),
            }
            for s in sessions
        ]
    }


@app.get("/dev/calls/{call_sid}")
def dev_call_timeline(
    call_sid: str,
    tenant: Tenant = Depends(current_tenant),
):
    """Full event timeline for one of the calling tenant's calls.

    Reads from
    ``restaurants/{tenant.restaurant_id}/call_sessions/{call_sid}/events``.
    A 404 here means *either* the call_sid doesn't exist *or* it
    belongs to a different tenant — both are indistinguishable to
    the caller, which is the desired tenant-isolation property.
    """
    _require_dev_endpoints()
    events = call_sessions.get_session_events(call_sid, tenant.restaurant_id)
    if events is None:
        raise HTTPException(status_code=404, detail="call_sid not found")
    return {
        "call_sid": call_sid,
        "events": [
            {
                "timestamp": _iso(e.get("timestamp")),
                "kind": e.get("kind", "log"),
                "text": e.get("text", ""),
                "detail": e.get("detail", {}),
            }
            for e in events
        ],
    }


@app.post("/dev/seed-order")
def seed_order():
    """Insert a canned order so Daniel can build the dashboard against a
    real Firestore read path before the voice loop is wired up.

    Gated on ``NIKO_DEV_ENDPOINTS=true`` — returns 404 in production so
    the route effectively doesn't exist there. Seeds always land
    under the demo tenant ``niko-pizza-kitchen`` (no auth required;
    this is a Tsuki-internal dev escape hatch).
    """

    if not settings.niko_dev_endpoints:
        raise HTTPException(status_code=404, detail="Not Found")

    seed = Order(
        call_sid=f"CAseed-{int(time.time())}",
        caller_phone="+15551234567",
        restaurant_id=DEMO_RID,
        order_type=OrderType.PICKUP,
        items=[
            LineItem(
                name="Pepperoni",
                category=ItemCategory.PIZZA,
                size="medium",
                quantity=1,
                unit_price=17.99,
            ),
            LineItem(
                name="Coke",
                category=ItemCategory.DRINK,
                quantity=2,
                unit_price=2.99,
            ),
        ],
    )
    doc_id = order_storage.save_order(seed)
    return {"doc_id": doc_id, "order": seed.model_dump(mode="json")}
