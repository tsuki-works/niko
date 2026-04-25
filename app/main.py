import logging
import time

from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)

from app.config import settings
from app.dev import calls as dev_calls
from app.orders.models import ItemCategory, LineItem, Order, OrderType
from app.storage import firestore as order_storage
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
def list_orders(limit: int = 50):
    """Return recent orders for the dashboard, most-recent-first.

    Read-only view over the Firestore ``orders`` collection (#41). Hard
    cap on ``limit`` so a misconfigured client can't exhaust the Cloud
    Run instance.
    """

    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be 1..200")
    orders = order_storage.list_recent_orders(limit=limit)
    return {"orders": [o.model_dump(mode="json") for o in orders]}


def _require_dev_endpoints() -> None:
    if not settings.niko_dev_endpoints:
        raise HTTPException(status_code=404, detail="Not Found")


@app.get("/dev/calls")
def dev_list_calls(hours: int = 24):
    """List recent call sessions extracted from Cloud Logging.

    Gated on ``NIKO_DEV_ENDPOINTS=true``. Returns one entry per call_sid
    seen in the last ``hours`` window, newest-first. Used by the
    dashboard's dev-only Calls page (#68).
    """
    _require_dev_endpoints()
    if hours < 1 or hours > 24 * 7:
        raise HTTPException(status_code=400, detail="hours must be 1..168")
    summaries = dev_calls.list_recent_calls(hours=hours)
    return {
        "calls": [
            {
                "call_sid": s.call_sid,
                "started_at": s.started_at.isoformat(),
                "ended_at": s.ended_at.isoformat(),
                "transcript_count": s.transcript_count,
                "has_error": s.has_error,
                "status": s.status,
            }
            for s in summaries
        ]
    }


@app.get("/dev/calls/{call_sid}")
def dev_call_timeline(call_sid: str, hours: int = 168):
    """Full event timeline for one call_sid (transcripts, LLM turns,
    barge-ins, silence timeouts, errors). Gated on dev endpoints (#68)."""
    _require_dev_endpoints()
    if hours < 1 or hours > 24 * 7:
        raise HTTPException(status_code=400, detail="hours must be 1..168")
    events = dev_calls.get_call_timeline(call_sid, hours=hours)
    if events is None:
        raise HTTPException(status_code=404, detail="call_sid not found in logs")
    return {
        "call_sid": call_sid,
        "events": [
            {
                "timestamp": e.timestamp.isoformat(),
                "kind": e.kind,
                "text": e.text,
                "detail": e.detail,
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
