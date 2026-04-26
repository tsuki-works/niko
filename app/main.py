import logging
import time

from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)

from datetime import datetime
from typing import Any

from app.config import settings
from app.orders.models import ItemCategory, LineItem, Order, OrderType
from app.storage import call_sessions, firestore as order_storage
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


@app.get("/orders")
def list_orders(limit: int = 50, restaurant_id: str = DEMO_RID):
    """Return recent orders for the dashboard, most-recent-first.

    Read-only view over the Firestore
    ``restaurants/{restaurant_id}/orders`` subcollection (#79).

    The ``restaurant_id`` query param defaults to the demo tenant for
    now; PR D adds Firebase Auth and derives the tenant from the
    requester's custom claims so the param can drop to the
    authenticated user's restaurant only.

    Hard cap on ``limit`` so a misconfigured client can't exhaust the
    Cloud Run instance.
    """

    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be 1..200")
    orders = order_storage.list_recent_orders(
        restaurant_id=restaurant_id, limit=limit
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
def dev_list_calls(limit: int = 50, restaurant_id: str = DEMO_RID):
    """List recent call sessions from Firestore, newest-first.

    Gated on ``NIKO_DEV_ENDPOINTS=true``. Reads from the nested
    ``restaurants/{restaurant_id}/call_sessions`` subcollection (#79
    PR C). The dashboard's live ``onSnapshot`` subscription still
    points at the legacy flat ``call_sessions`` collection until PR D
    moves it; both paths receive every write via the dual-write
    pattern in ``app/storage/call_sessions.py``.
    """
    _require_dev_endpoints()
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be 1..200")
    sessions = call_sessions.list_recent_sessions(
        restaurant_id=restaurant_id, limit=limit
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
def dev_call_timeline(call_sid: str, restaurant_id: str = DEMO_RID):
    """Full event timeline for one call_sid (#70 + #79 PR C).

    Reads from the
    ``restaurants/{restaurant_id}/call_sessions/{call_sid}/events``
    subcollection. The dashboard uses this for the initial server
    render; live updates still arrive via direct Firestore
    ``onSnapshot`` against the legacy flat path until PR D switches
    the subscription.
    """
    _require_dev_endpoints()
    events = call_sessions.get_session_events(call_sid, restaurant_id)
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
    the route effectively doesn't exist there.
    """

    if not settings.niko_dev_endpoints:
        raise HTTPException(status_code=404, detail="Not Found")

    seed = Order(
        call_sid=f"CAseed-{int(time.time())}",
        caller_phone="+15551234567",
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
