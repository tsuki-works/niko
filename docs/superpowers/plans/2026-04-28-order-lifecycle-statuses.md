# Order Lifecycle Statuses + Transition Endpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the order lifecycle from `confirmed`/`cancelled` (terminal) to a real kitchen workflow: `confirmed → preparing → ready → completed`, with `cancelled` as an off-ramp from any pre-`completed` state. Ship the data layer (enum, transition functions, FastAPI endpoints, dashboard schema mirror) so B2 (alert UX) and B3 (workflow buttons) can build on top.

**Architecture:** Mirror the existing `persist_on_confirm` pattern. Each transition function validates source state, stamps a per-transition timestamp, and persists via `app.storage.firestore.save_order`. A small `_transition` helper de-duplicates the four nearly-identical implementations. FastAPI endpoints translate `OrderTransitionError` → 409 and missing/cross-tenant orders → 404. Dashboard mirrors the schema additively (existing reads stay green; new statuses become parsable but no UI consumes them yet — that's B3).

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 (backend); Next.js 15 + Zod + Firebase web SDK (dashboard); pytest (backend tests); vitest (dashboard tests).

**Spec:** `docs/superpowers/specs/2026-04-28-order-lifecycle-statuses-design.md`
**Tracking issue:** [#107](https://github.com/tsuki-works/niko/issues/107)
**Branch:** `feat/107-order-lifecycle-statuses` (already created; spec already committed at `adc4f16`)

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `app/orders/models.py` | Modify | Expand `OrderStatus` enum with `PREPARING`/`READY`/`COMPLETED`; add 4 new optional `datetime` fields to `Order` |
| `app/orders/lifecycle.py` | Modify | New `OrderTransitionError` exception; new `_transition` helper; 4 new transition functions (`mark_preparing`, `mark_ready`, `mark_completed`, `cancel_order`) |
| `app/main.py` | Modify | 4 new FastAPI endpoint handlers — all tenant-scoped, all returning the updated Order JSON |
| `tests/test_orders_lifecycle.py` | Modify | Append unit tests per new transition function (positive + wrong-source rejection + idempotency) |
| `tests/test_orders_route.py` | Modify | Append integration tests per new endpoint (200 / 404 / 409) |
| `dashboard/lib/schemas/order.ts` | Modify | Extend `OrderStatusSchema` enum with 3 new values; add 4 new optional date fields to `OrderSchema` |
| `dashboard/lib/status-styles.ts` | Modify | Add 3 new entries to the `STYLES` map |
| `dashboard/lib/api/orders.ts` | Modify | Flip `STUB_CANCEL_ORDER = false`; implement `cancelOrderApi` to call the new endpoint via `apiFetch` |
| `dashboard/tests/order-schema.test.ts` | Modify | Update the existing "unknown status" test (currently uses `'completed'`, which is now valid); add tests for the 3 new statuses parsing |

The single biggest decomposition decision: **the four transition functions share a `_transition` helper.** Without it, four near-duplicates of the same 8-line function. With it, four 2-line wrappers + one focused helper.

---

## Task 1: Schema expansion — `OrderStatus` enum + new timestamp fields

**Files:**
- Modify: `app/orders/models.py:33-37` (`OrderStatus` enum) and `:79-89` (`Order` model)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orders_lifecycle.py` (at the very end of the file):

```python
def test_order_supports_new_lifecycle_statuses_and_timestamps():
    """Sprint 2.2 #107 — OrderStatus must include preparing/ready/completed,
    and Order must accept the per-transition timestamps without complaint."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    order = Order(
        call_sid="CAlife",
        items=[_pepperoni()],
        order_type=OrderType.PICKUP,
        status=OrderStatus.READY,
        confirmed_at=now,
        preparing_at=now,
        ready_at=now,
    )

    assert order.status is OrderStatus.READY
    assert order.preparing_at == now
    assert order.ready_at == now
    assert order.completed_at is None  # not yet completed
    assert order.cancelled_at is None

    # All four enum values exist
    assert OrderStatus.PREPARING.value == "preparing"
    assert OrderStatus.READY.value == "ready"
    assert OrderStatus.COMPLETED.value == "completed"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_orders_lifecycle.py::test_order_supports_new_lifecycle_statuses_and_timestamps -v`
Expected: FAIL with `AttributeError: PREPARING` on the enum, OR a Pydantic validation error rejecting the new kwargs.

- [ ] **Step 3: Expand the `OrderStatus` enum**

In `app/orders/models.py`, find the existing `OrderStatus` class (around line 33):

```python
class OrderStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
```

Replace with:

```python
class OrderStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
```

(Order matters for documentation only — Pydantic's enum validation is value-based, not position-based.)

- [ ] **Step 4: Add the four new optional timestamp fields to `Order`**

In the same file, find the `Order` class (around line 79). The current shape ends with:

```python
    status: OrderStatus = OrderStatus.IN_PROGRESS
    created_at: datetime = Field(default_factory=_now_utc)
    confirmed_at: Optional[datetime] = None
```

Replace with:

```python
    status: OrderStatus = OrderStatus.IN_PROGRESS
    created_at: datetime = Field(default_factory=_now_utc)
    confirmed_at: Optional[datetime] = None
    # Per-transition timestamps stamped by app.orders.lifecycle on each
    # successful state change. None for any transition that hasn't
    # happened yet — independently useful for kitchen UX
    # ("how long has this been cooking?") and analytics
    # ("average time-to-fulfillment").
    preparing_at: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
```

- [ ] **Step 5: Run the new test**

Run: `python -m pytest tests/test_orders_lifecycle.py::test_order_supports_new_lifecycle_statuses_and_timestamps -v`
Expected: PASS.

- [ ] **Step 6: Run the full models-related suite — no regressions**

Run: `python -m pytest tests/test_order_models.py tests/test_orders_lifecycle.py -v 2>&1 | tail -10`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add app/orders/models.py tests/test_orders_lifecycle.py
git commit -m "Expand OrderStatus enum + add per-transition timestamps (#107)

OrderStatus gains PREPARING / READY / COMPLETED so the lifecycle can
walk past 'confirmed' through the kitchen workflow.

Order gains four new optional timestamp fields (preparing_at, ready_at,
completed_at, cancelled_at) symmetric with the existing confirmed_at.
Each is independently useful for kitchen UX and analytics; a single
last_transition_at would lose that history.

Pure data-shape change — transition functions land in the next commit."
```

---

## Task 2: `OrderTransitionError` + four transition functions in `lifecycle.py`

**Files:**
- Modify: `app/orders/lifecycle.py` (add new exception + helper + 4 transition functions)
- Modify: `tests/test_orders_lifecycle.py` (append unit tests for each transition)

- [ ] **Step 1: Write the failing tests**

Append these 12 tests to the END of `tests/test_orders_lifecycle.py`. They cover all 4 transitions with the same 3-pattern shape (positive + wrong-source rejection + idempotency).

```python
# ---------------------------------------------------------------------------
# B1 transition functions (Sprint 2.2 #107)
# ---------------------------------------------------------------------------


def _confirmed_pickup_order(**overrides) -> Order:
    """A pickup order in CONFIRMED state — the starting point for the
    kitchen workflow transitions."""
    base = dict(
        call_sid="CAconfirmed",
        items=[_pepperoni()],
        order_type=OrderType.PICKUP,
        status=OrderStatus.CONFIRMED,
        confirmed_at=datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return Order(**base)


# ----- mark_preparing -----


def test_mark_preparing_transitions_confirmed_to_preparing():
    from app.orders.lifecycle import mark_preparing
    client = _fake_client()
    order = _confirmed_pickup_order()

    updated = mark_preparing(order)

    assert updated.status is OrderStatus.PREPARING
    assert updated.preparing_at is not None
    age = datetime.now(timezone.utc) - updated.preparing_at
    assert timedelta(seconds=0) <= age < timedelta(seconds=5)
    _order_doc(client).set.assert_called_once()


def test_mark_preparing_rejects_wrong_source_state():
    from app.orders.lifecycle import OrderTransitionError, mark_preparing
    _fake_client()
    order = _ready_pickup_order()  # status=IN_PROGRESS

    with pytest.raises(OrderTransitionError, match="preparing"):
        mark_preparing(order)


def test_mark_preparing_is_idempotent():
    from app.orders.lifecycle import mark_preparing
    client = _fake_client()
    original_ts = datetime(2026, 4, 28, 13, 0, 0, tzinfo=timezone.utc)
    order = _confirmed_pickup_order(
        status=OrderStatus.PREPARING, preparing_at=original_ts
    )

    updated = mark_preparing(order)

    assert updated.preparing_at == original_ts
    _order_doc(client).set.assert_called_once()


# ----- mark_ready -----


def test_mark_ready_transitions_preparing_to_ready():
    from app.orders.lifecycle import mark_ready
    client = _fake_client()
    order = _confirmed_pickup_order(
        status=OrderStatus.PREPARING,
        preparing_at=datetime(2026, 4, 28, 13, 0, 0, tzinfo=timezone.utc),
    )

    updated = mark_ready(order)

    assert updated.status is OrderStatus.READY
    assert updated.ready_at is not None
    _order_doc(client).set.assert_called_once()


def test_mark_ready_rejects_wrong_source_state():
    from app.orders.lifecycle import OrderTransitionError, mark_ready
    _fake_client()
    order = _confirmed_pickup_order()  # status=CONFIRMED, not PREPARING

    with pytest.raises(OrderTransitionError, match="ready"):
        mark_ready(order)


def test_mark_ready_is_idempotent():
    from app.orders.lifecycle import mark_ready
    client = _fake_client()
    original_ts = datetime(2026, 4, 28, 13, 30, 0, tzinfo=timezone.utc)
    order = _confirmed_pickup_order(
        status=OrderStatus.READY, ready_at=original_ts
    )

    updated = mark_ready(order)

    assert updated.ready_at == original_ts
    _order_doc(client).set.assert_called_once()


# ----- mark_completed -----


def test_mark_completed_transitions_ready_to_completed():
    from app.orders.lifecycle import mark_completed
    client = _fake_client()
    order = _confirmed_pickup_order(
        status=OrderStatus.READY,
        ready_at=datetime(2026, 4, 28, 13, 30, 0, tzinfo=timezone.utc),
    )

    updated = mark_completed(order)

    assert updated.status is OrderStatus.COMPLETED
    assert updated.completed_at is not None
    _order_doc(client).set.assert_called_once()


def test_mark_completed_rejects_wrong_source_state():
    from app.orders.lifecycle import OrderTransitionError, mark_completed
    _fake_client()
    order = _confirmed_pickup_order()  # status=CONFIRMED, not READY

    with pytest.raises(OrderTransitionError, match="completed"):
        mark_completed(order)


def test_mark_completed_is_idempotent():
    from app.orders.lifecycle import mark_completed
    client = _fake_client()
    original_ts = datetime(2026, 4, 28, 14, 0, 0, tzinfo=timezone.utc)
    order = _confirmed_pickup_order(
        status=OrderStatus.COMPLETED, completed_at=original_ts
    )

    updated = mark_completed(order)

    assert updated.completed_at == original_ts
    _order_doc(client).set.assert_called_once()


# ----- cancel_order -----


def test_cancel_order_transitions_from_in_progress():
    from app.orders.lifecycle import cancel_order
    client = _fake_client()
    order = _ready_pickup_order()  # status=IN_PROGRESS

    updated = cancel_order(order)

    assert updated.status is OrderStatus.CANCELLED
    assert updated.cancelled_at is not None
    _order_doc(client).set.assert_called_once()


def test_cancel_order_transitions_from_preparing():
    from app.orders.lifecycle import cancel_order
    _fake_client()
    order = _confirmed_pickup_order(
        status=OrderStatus.PREPARING,
        preparing_at=datetime(2026, 4, 28, 13, 0, 0, tzinfo=timezone.utc),
    )

    updated = cancel_order(order)

    assert updated.status is OrderStatus.CANCELLED
    # preparing_at preserved — we don't erase history on cancel
    assert updated.preparing_at is not None


def test_cancel_order_rejects_already_completed_order():
    from app.orders.lifecycle import OrderTransitionError, cancel_order
    _fake_client()
    order = _confirmed_pickup_order(
        status=OrderStatus.COMPLETED,
        completed_at=datetime(2026, 4, 28, 14, 0, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(OrderTransitionError, match="completed"):
        cancel_order(order)


def test_cancel_order_is_idempotent():
    from app.orders.lifecycle import cancel_order
    client = _fake_client()
    original_ts = datetime(2026, 4, 28, 13, 0, 0, tzinfo=timezone.utc)
    order = _confirmed_pickup_order(
        status=OrderStatus.CANCELLED, cancelled_at=original_ts
    )

    updated = cancel_order(order)

    assert updated.cancelled_at == original_ts
    _order_doc(client).set.assert_called_once()
```

- [ ] **Step 2: Confirm tests fail**

Run: `python -m pytest tests/test_orders_lifecycle.py -v -k "preparing or ready or completed or cancel" 2>&1 | tail -20`
Expected: most fail with `ImportError` for `mark_preparing` / `mark_ready` / `mark_completed` / `cancel_order` / `OrderTransitionError`.

- [ ] **Step 3: Implement the new exception, helper, and 4 transition functions**

Open `app/orders/lifecycle.py`. The existing file ends with `persist_on_confirm` (around line 67). Append AT THE END of the file:

```python


class OrderTransitionError(ValueError):
    """A transition function was called from an invalid source state.
    Mirrors ``OrderNotReadyError``'s shape but specific to the
    confirmed → preparing → ready → completed kitchen workflow."""


def _transition(
    order: Order,
    *,
    allowed_sources: list[OrderStatus],
    target: OrderStatus,
    timestamp_field: str,
) -> Order:
    """Generic state-machine transition helper.

    Idempotent: if the order is already in the target state, save
    again (recovery from partial failure where the in-memory transition
    landed but the Firestore write didn't) and preserve the original
    timestamp.

    Validates source state: raises ``OrderTransitionError`` if the
    order's current status isn't in ``allowed_sources`` and isn't
    already the target.
    """
    if order.status is target:
        order_storage.save_order(order)
        return order

    if order.status not in allowed_sources:
        raise OrderTransitionError(
            f"Cannot transition order {order.call_sid!r} to "
            f"{target.value!r}: current status is {order.status.value!r}, "
            f"expected one of {[s.value for s in allowed_sources]}"
        )

    now = datetime.now(timezone.utc)
    updated = order.model_copy(
        update={"status": target, timestamp_field: now}
    )
    order_storage.save_order(updated)
    return updated


def mark_preparing(order: Order) -> Order:
    """Confirmed → Preparing. Kitchen has accepted the order and started
    cooking. Stamps ``preparing_at``."""
    return _transition(
        order,
        allowed_sources=[OrderStatus.CONFIRMED],
        target=OrderStatus.PREPARING,
        timestamp_field="preparing_at",
    )


def mark_ready(order: Order) -> Order:
    """Preparing → Ready. Food is done and waiting for handoff (counter
    pickup or restaurant's own driver). Stamps ``ready_at``."""
    return _transition(
        order,
        allowed_sources=[OrderStatus.PREPARING],
        target=OrderStatus.READY,
        timestamp_field="ready_at",
    )


def mark_completed(order: Order) -> Order:
    """Ready → Completed. Food has left the kitchen. Terminal state for
    successful orders. Stamps ``completed_at``."""
    return _transition(
        order,
        allowed_sources=[OrderStatus.READY],
        target=OrderStatus.COMPLETED,
        timestamp_field="completed_at",
    )


def cancel_order(order: Order) -> Order:
    """Any pre-completed state → Cancelled. Off-ramp from the workflow
    (caller-cancel, kitchen-reject, staff-cancel via dashboard).
    Stamps ``cancelled_at``."""
    return _transition(
        order,
        allowed_sources=[
            OrderStatus.IN_PROGRESS,
            OrderStatus.CONFIRMED,
            OrderStatus.PREPARING,
            OrderStatus.READY,
        ],
        target=OrderStatus.CANCELLED,
        timestamp_field="cancelled_at",
    )
```

- [ ] **Step 4: Run the new tests**

Run: `python -m pytest tests/test_orders_lifecycle.py -v 2>&1 | tail -25`
Expected: all green (existing `persist_on_confirm` tests + new transition tests).

- [ ] **Step 5: Commit**

```bash
git add app/orders/lifecycle.py tests/test_orders_lifecycle.py
git commit -m "Add transition functions for kitchen workflow (#107)

Four new transition functions in app/orders/lifecycle.py:
- mark_preparing: confirmed → preparing
- mark_ready: preparing → ready
- mark_completed: ready → completed
- cancel_order: any pre-completed → cancelled

All four delegate to a new _transition helper that validates source
state, stamps the right timestamp, persists via save_order, and is
idempotent on re-application (preserves the original timestamp).

OrderTransitionError mirrors the existing OrderNotReadyError shape;
endpoint layer in the next commit will map it to HTTP 409.

12 unit tests cover positive transitions, wrong-source rejection,
and idempotency for each of the four functions."
```

---

## Task 3: FastAPI transition endpoints

**Files:**
- Modify: `app/main.py` (add 4 new endpoint handlers + helper for shared logic)
- Modify: `tests/test_orders_route.py` (append integration tests for each endpoint)

- [ ] **Step 1: Write the failing integration tests**

First, read the existing `tests/test_orders_route.py` to confirm the test client setup pattern. Then append at the end:

```python
# ---------------------------------------------------------------------------
# B1 transition endpoints (Sprint 2.2 #107)
# ---------------------------------------------------------------------------
# These follow the same FastAPI TestClient + tenant-mock pattern used by
# the existing GET /orders tests. Each endpoint gets four checks:
# 1. 200 + correct payload on valid transition
# 2. 401/403 when no valid tenant session (rely on existing auth dependency)
# 3. 404 when the order doesn't belong to the calling tenant
# 4. 409 when the order is in the wrong source state


def _seed_confirmed_order(rid: str = "niko-pizza-kitchen", call_sid: str = "CAtest"):
    """Create a CONFIRMED order in the mock Firestore for the given tenant.

    Returns the seeded Order. Caller is responsible for setting up the
    Firestore client mock first via the existing storage._fake_client()
    pattern (see tests/test_firestore_storage.py)."""
    from app.orders.models import LineItem, Order, OrderStatus, OrderType
    from app.storage import firestore as storage

    order = Order(
        call_sid=call_sid,
        items=[LineItem(name="Pepperoni", category="pizza", size="medium",
                        quantity=1, unit_price=17.99)],
        order_type=OrderType.PICKUP,
        restaurant_id=rid,
        status=OrderStatus.CONFIRMED,
        confirmed_at=datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc),
    )
    return order


# Note: the existing tests/test_orders_route.py uses a tenant-mock and a
# storage-mock pattern — REPLICATE THAT PATTERN here for the new tests.
# Each test below is a sketch of WHAT to assert; the implementer fills in
# the exact mocking shape by following the existing test setup.

def test_post_preparing_transitions_confirmed_order(client_with_tenant):
    """POST /orders/{call_sid}/preparing returns 200 + the updated order."""
    # Setup: seed a confirmed order for the calling tenant in the mock
    # storage. Call the endpoint. Assert 200, assert response JSON has
    # status='preparing' and preparing_at populated.
    pass  # implementer: fill in following the existing test pattern


def test_post_preparing_rejects_in_progress_order(client_with_tenant):
    """POST /orders/{call_sid}/preparing returns 409 when the order is
    still in_progress (not yet confirmed)."""
    pass


def test_post_preparing_returns_404_for_other_tenant(client_with_tenant):
    """An order belonging to a different tenant is indistinguishable
    from a missing order — both return 404."""
    pass


def test_post_ready_transitions_preparing_order(client_with_tenant):
    pass


def test_post_ready_rejects_confirmed_order(client_with_tenant):
    pass


def test_post_completed_transitions_ready_order(client_with_tenant):
    pass


def test_post_completed_rejects_preparing_order(client_with_tenant):
    pass


def test_post_cancel_transitions_from_any_pre_completed_state(client_with_tenant):
    """cancel accepts any source state from in_progress through ready."""
    pass


def test_post_cancel_returns_409_for_already_completed_order(client_with_tenant):
    pass
```

**IMPORTANT NOTE TO IMPLEMENTER:** The 9 test stubs above are written in placeholder form because the exact mocking pattern in `tests/test_orders_route.py` depends on the existing test client + tenant-injection + firestore-mock setup, which you should READ before filling in. Your task: read `tests/test_orders_route.py` end-to-end first, identify the existing test pattern (likely a fixture that yields a TestClient with a mocked tenant + a mocked firestore client), and write each new test FOLLOWING that pattern. The assertions to make are clear from the comments; the wiring is what you mirror from existing tests.

- [ ] **Step 2: Confirm tests fail (or skeleton-only at this stage)**

Run: `python -m pytest tests/test_orders_route.py -v 2>&1 | tail -10`
Expected: the 9 new tests should fail or show as `PASSED` if you stubbed them with `pass`. Either way: implementing the endpoints comes next.

- [ ] **Step 3: Add the endpoint helpers + 4 endpoints to `app/main.py`**

In `app/main.py`, add the following imports near the existing `from app.orders.lifecycle import persist_on_confirm` (or wherever lifecycle is imported — add it if it's not):

```python
from app.orders.lifecycle import (
    OrderTransitionError,
    cancel_order,
    mark_completed,
    mark_preparing,
    mark_ready,
)
from app.orders.models import Order
```

Find the existing `@app.get("/orders")` handler (around line 73). Immediately AFTER that handler ends, add this helper + four endpoints:

```python
def _load_tenant_order(call_sid: str, tenant: Tenant) -> Order:
    """Look up an order by call_sid scoped to the calling tenant.

    Returns the Order. Raises HTTP 404 if the order doesn't exist OR
    belongs to a different tenant — both are indistinguishable to the
    caller, which is the desired tenant-isolation property (matches
    the pattern in /dev/calls/{call_sid})."""
    order = order_storage.get_order(
        call_sid=call_sid, restaurant_id=tenant.restaurant_id
    )
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


def _transition_response(order: Order) -> dict[str, Any]:
    return order.model_dump(mode="json")


@app.post("/orders/{call_sid}/preparing")
def post_order_preparing(
    call_sid: str,
    tenant: Tenant = Depends(current_tenant),
):
    """Transition an order from CONFIRMED to PREPARING. Idempotent.

    Returns the updated Order JSON. 404 if the order doesn't belong to
    the calling tenant. 409 if the order is in a state that can't
    transition to preparing (e.g. still in_progress, or already past
    preparing into ready/completed/cancelled)."""
    order = _load_tenant_order(call_sid, tenant)
    try:
        updated = mark_preparing(order)
    except OrderTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _transition_response(updated)


@app.post("/orders/{call_sid}/ready")
def post_order_ready(
    call_sid: str,
    tenant: Tenant = Depends(current_tenant),
):
    """Transition an order from PREPARING to READY. Idempotent."""
    order = _load_tenant_order(call_sid, tenant)
    try:
        updated = mark_ready(order)
    except OrderTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _transition_response(updated)


@app.post("/orders/{call_sid}/completed")
def post_order_completed(
    call_sid: str,
    tenant: Tenant = Depends(current_tenant),
):
    """Transition an order from READY to COMPLETED. Idempotent.
    Terminal state for successful orders."""
    order = _load_tenant_order(call_sid, tenant)
    try:
        updated = mark_completed(order)
    except OrderTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _transition_response(updated)


@app.post("/orders/{call_sid}/cancel")
def post_order_cancel(
    call_sid: str,
    tenant: Tenant = Depends(current_tenant),
):
    """Cancel an order from any pre-completed state. Idempotent.

    Implements the endpoint the dashboard's cancelOrder Server Action
    has been calling against a stub since Phase 1."""
    order = _load_tenant_order(call_sid, tenant)
    try:
        updated = cancel_order(order)
    except OrderTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _transition_response(updated)
```

**IMPLEMENTATION NOTE:** the `_load_tenant_order` helper assumes `order_storage.get_order(call_sid=..., restaurant_id=...)` exists. Verify by inspecting `app/storage/firestore.py`. If the function doesn't exist or has a different signature, EITHER add a thin `get_order` helper to `app/storage/firestore.py` (matching `list_recent_orders`'s pattern) OR adapt `_load_tenant_order` to use whatever read API is already there. Don't invent a new public API surface beyond what's needed.

- [ ] **Step 4: Verify the imports + helper resolve**

Run: `python -c "from app.main import app; print([r.path for r in app.routes if 'orders' in r.path])"`
Expected: prints a list including `/orders/{call_sid}/preparing`, `/orders/{call_sid}/ready`, `/orders/{call_sid}/completed`, `/orders/{call_sid}/cancel` plus the existing `/orders`.

- [ ] **Step 5: Fill in the test stubs and run them**

Now go back to the 9 test stubs in Step 1. Replace each `pass` with concrete assertions following the existing pattern in `tests/test_orders_route.py`. Run after each test or batch:

Run: `python -m pytest tests/test_orders_route.py -v 2>&1 | tail -25`
Expected: all 9 new tests pass + all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_orders_route.py
git commit -m "Add FastAPI transition endpoints for kitchen workflow (#107)

Four new POST endpoints, all tenant-scoped via current_tenant:
- POST /orders/{call_sid}/preparing  (confirmed → preparing)
- POST /orders/{call_sid}/ready      (preparing → ready)
- POST /orders/{call_sid}/completed  (ready → completed)
- POST /orders/{call_sid}/cancel     (any pre-completed → cancelled)

The cancel endpoint completes the stub the dashboard's cancelOrder
Server Action has been calling since Phase 1.

OrderTransitionError → HTTP 409 with the error message in detail.
Cross-tenant order lookup returns 404 (indistinguishable from missing,
preserves tenant-isolation guarantee).

9 integration tests cover positive transitions, 409 wrong-source
rejection, and 404 cross-tenant isolation per endpoint."
```

---

## Task 4: Dashboard schema mirror — Zod enum + new optional date fields

**Files:**
- Modify: `dashboard/lib/schemas/order.ts`
- Modify: `dashboard/tests/order-schema.test.ts`

- [ ] **Step 1: Update the existing "rejects unknown statuses" test**

The existing test at `dashboard/tests/order-schema.test.ts:48-52` asserts that `'completed'` is rejected:

```typescript
it('rejects unknown statuses via OrderSchema directly', () => {
  expect(() =>
    OrderSchema.parse({ ...VALID, status: 'completed' }),
  ).toThrow();
});
```

Once we add `'completed'` to the enum, this test will fail. Update it to use a clearly-fictional status:

```typescript
it('rejects unknown statuses via OrderSchema directly', () => {
  expect(() =>
    OrderSchema.parse({ ...VALID, status: 'flux-capacitor-engaged' }),
  ).toThrow();
});
```

- [ ] **Step 2: Add new tests for the 3 new statuses + new optional timestamps**

Append these tests to `dashboard/tests/order-schema.test.ts` (in the `describe('OrderSchema / parseOrderFromJson', ...)` block, before the closing `});`):

```typescript
  it('parses orders with the new lifecycle statuses', () => {
    for (const status of ['preparing', 'ready', 'completed'] as const) {
      const order = OrderSchema.parse({ ...VALID, status });
      expect(order.status).toBe(status);
    }
  });

  it('parses orders with new per-transition timestamps populated', () => {
    const order = OrderSchema.parse({
      ...VALID,
      status: 'completed',
      preparing_at: '2026-04-20T19:35:00.000Z',
      ready_at: '2026-04-20T19:42:00.000Z',
      completed_at: '2026-04-20T19:48:00.000Z',
    });
    expect(order.preparing_at).toBeInstanceOf(Date);
    expect(order.ready_at).toBeInstanceOf(Date);
    expect(order.completed_at).toBeInstanceOf(Date);
  });

  it('parses orders without the new optional timestamps (existing docs)', () => {
    // Existing Firestore docs have only confirmed_at — make sure those
    // still parse cleanly without the new fields present.
    const order = OrderSchema.parse(VALID);
    expect(order.preparing_at).toBeFalsy();
    expect(order.ready_at).toBeFalsy();
    expect(order.completed_at).toBeFalsy();
    expect(order.cancelled_at).toBeFalsy();
  });
```

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `cd dashboard && pnpm vitest run tests/order-schema.test.ts 2>&1 | tail -15` (from the niko repo root: `(cd dashboard && pnpm vitest run tests/order-schema.test.ts)`)
Expected: at minimum the 3 new "parses ... new statuses" tests fail because the enum doesn't include them yet.

- [ ] **Step 4: Update `OrderStatusSchema` and add new optional date fields**

In `dashboard/lib/schemas/order.ts`, find:

```typescript
export const OrderStatusSchema = z.enum([
  'in_progress',
  'confirmed',
  'cancelled',
]);
```

Replace with:

```typescript
export const OrderStatusSchema = z.enum([
  'in_progress',
  'confirmed',
  'preparing',
  'ready',
  'completed',
  'cancelled',
]);
```

Then find the `OrderSchema` definition. Currently:

```typescript
export const OrderSchema = z.object({
  call_sid: z.string(),
  caller_phone: z.string().nullish(),
  restaurant_id: z.string(),
  items: z.array(LineItemSchema).default([]),
  order_type: OrderTypeSchema.nullish(),
  delivery_address: z.string().nullish(),
  status: OrderStatusSchema,
  created_at: z.date(),
  confirmed_at: z.date().nullish(),
  subtotal: z.number(),
});
```

Replace with (insert the four new optional date fields after `confirmed_at`):

```typescript
export const OrderSchema = z.object({
  call_sid: z.string(),
  caller_phone: z.string().nullish(),
  restaurant_id: z.string(),
  items: z.array(LineItemSchema).default([]),
  order_type: OrderTypeSchema.nullish(),
  delivery_address: z.string().nullish(),
  status: OrderStatusSchema,
  created_at: z.date(),
  confirmed_at: z.date().nullish(),
  // Per-transition timestamps stamped by the backend on each
  // successful state change. None for any transition that hasn't
  // happened yet. See app/orders/lifecycle.py for the source.
  preparing_at: z.date().nullish(),
  ready_at: z.date().nullish(),
  completed_at: z.date().nullish(),
  cancelled_at: z.date().nullish(),
  subtotal: z.number(),
});
```

- [ ] **Step 5: Run the tests**

Run from repo root: `(cd dashboard && pnpm vitest run tests/order-schema.test.ts)`
Expected: all tests in this file PASS (existing 5 + 3 new).

- [ ] **Step 6: Run the dashboard's full vitest suite to catch any other regressions**

Run from repo root: `(cd dashboard && pnpm vitest run)`
Expected: all dashboard tests PASS.

If any test elsewhere in the dashboard fails because it `switch`-es on `OrderStatus` and now has unhandled cases, that's a real signal — exhaustiveness was the whole point. Investigate and report rather than papering over.

- [ ] **Step 7: Commit**

```bash
git add dashboard/lib/schemas/order.ts dashboard/tests/order-schema.test.ts
git commit -m "Mirror new OrderStatus values + timestamps in dashboard schema (#107)

OrderStatusSchema gains preparing/ready/completed; OrderSchema gains
four new optional date fields (preparing_at, ready_at, completed_at,
cancelled_at) so reads of orders that have walked through the new
lifecycle parse cleanly.

The existing 'rejects unknown statuses' test was using 'completed' as
its fictional status — flipped it to 'flux-capacitor-engaged' since
'completed' is now a real value.

No UI changes — buttons + filter tabs come in B3."
```

---

## Task 5: Dashboard `status-styles.ts` — 3 new badge entries

**Files:**
- Modify: `dashboard/lib/status-styles.ts`

- [ ] **Step 1: Verify TypeScript will fail without the new entries**

Run from repo root: `(cd dashboard && pnpm tsc --noEmit 2>&1 | head -20)`
Expected: at least one error like `Property 'preparing' is missing in type ...` because `STYLES` is typed as `Record<OrderStatus, StatusStyle>` and the enum just gained 3 values.

- [ ] **Step 2: Add the three new entries**

In `dashboard/lib/status-styles.ts`, find the existing `STYLES` map:

```typescript
const STYLES: Record<OrderStatus, StatusStyle> = {
  in_progress: {
    label: 'Live call',
    className: 'bg-warning/15 text-warning border-warning/30',
  },
  confirmed: {
    label: 'Confirmed',
    className: 'bg-success/15 text-success border-success/40',
  },
  cancelled: {
    label: 'Cancelled',
    className: 'bg-destructive/15 text-destructive border-destructive/30',
  },
};
```

Replace with (the new entries follow the same pattern: low-opacity bg, saturated text, slightly heavier border):

```typescript
const STYLES: Record<OrderStatus, StatusStyle> = {
  in_progress: {
    label: 'Live call',
    className: 'bg-warning/15 text-warning border-warning/30',
  },
  confirmed: {
    label: 'Confirmed',
    className: 'bg-success/15 text-success border-success/40',
  },
  // Active in the kitchen — amber tone signals "this needs attention".
  // Reuses the warning token; intentionally adjacent to in_progress
  // visually because both are "active" states from the kitchen's POV.
  preparing: {
    label: 'Preparing',
    className: 'bg-amber-500/15 text-amber-600 border-amber-500/30 dark:text-amber-400',
  },
  // Done cooking, awaiting handoff. Uses success tones (different shade
  // than confirmed) — emerald is the brand "things are going well" color.
  ready: {
    label: 'Ready',
    className: 'bg-emerald-500/15 text-emerald-600 border-emerald-500/40 dark:text-emerald-400',
  },
  // Terminal, no action required. Muted neutral so the eye skips past
  // them in a busy queue.
  completed: {
    label: 'Completed',
    className: 'bg-muted text-muted-foreground border-border',
  },
  cancelled: {
    label: 'Cancelled',
    className: 'bg-destructive/15 text-destructive border-destructive/30',
  },
};
```

- [ ] **Step 3: Verify TypeScript compiles + dashboard tests still pass**

Run from repo root: `(cd dashboard && pnpm tsc --noEmit && pnpm vitest run)`
Expected: zero TS errors; vitest green.

- [ ] **Step 4: Commit**

```bash
git add dashboard/lib/status-styles.ts
git commit -m "Add badge styles for preparing/ready/completed (#107)

- preparing: amber (active, needs kitchen attention)
- ready: emerald (the 'this can leave' moment, matches brand color)
- completed: muted neutral (terminal, no action; doesn't compete for
  attention in a busy queue)

Color tokens reused from existing Tailwind palette + theme tokens.
No new tokens introduced. The Record<OrderStatus, StatusStyle>
type ensures exhaustiveness — TS would have failed without these."
```

---

## Task 6: Implement `cancelOrderApi` for real

**Files:**
- Modify: `dashboard/lib/api/orders.ts`

- [ ] **Step 1: Read the existing stub + the apiFetch helper**

In `dashboard/lib/api/orders.ts`, find the `STUB_CANCEL_ORDER` constant + the `cancelOrderApi` function. Also read `dashboard/lib/api/http.ts` to understand the `apiFetch` signature (it's used by `listOrders` already in the same file).

- [ ] **Step 2: Flip the stub off and wire up the real call**

Find:

```typescript
const STUB_CANCEL_ORDER = true;
```

Replace with:

```typescript
const STUB_CANCEL_ORDER = false;
```

Then find the existing `cancelOrderApi` function (which probably returns the stub). Replace it with a real implementation that calls `POST /orders/{call_sid}/cancel`:

```typescript
export async function cancelOrderApi(
  call_sid: string,
): Promise<{ success: true } | { success: false; error: string }> {
  if (STUB_CANCEL_ORDER) {
    return {
      success: false,
      error: 'cancel endpoint not yet implemented',
    };
  }

  const path = `/orders/${encodeURIComponent(call_sid)}/cancel`;
  const res = await apiFetch(path, { method: 'POST' });

  if (res.ok) {
    return { success: true };
  }

  // FastAPI returns { detail: string } on 4xx — surface that detail
  // to the user as the error message.
  let detail: string;
  try {
    const body = (await res.json()) as { detail?: unknown };
    detail = typeof body.detail === 'string'
      ? body.detail
      : `${res.status} ${res.statusText}`;
  } catch {
    detail = `${res.status} ${res.statusText}`;
  }
  return { success: false, error: detail };
}
```

(If the existing `cancelOrderApi` shape is different from what's described above — e.g. different return type — adapt to match the existing contract, but flip the stub off and wire up the real call.)

- [ ] **Step 3: Run dashboard typecheck + tests**

Run from repo root: `(cd dashboard && pnpm tsc --noEmit && pnpm vitest run)`
Expected: zero TS errors; vitest green.

- [ ] **Step 4: Commit**

```bash
git add dashboard/lib/api/orders.ts
git commit -m "Wire dashboard cancelOrderApi to the real backend endpoint (#107)

The cancel stub has been in place since Phase 1 (the dashboard UI
calls the Server Action which calls cancelOrderApi which returned
a typed error). Now that the FastAPI endpoint exists, flip the stub
off and call POST /orders/{call_sid}/cancel via apiFetch.

Surfaces FastAPI's { detail: string } as the error message on 4xx
so the user sees actionable feedback (e.g. '409: Cannot cancel order
already in completed state') rather than a generic failure."
```

---

## Task 7: Whole-branch sanity + push + PR

- [ ] **Step 1: Sanity sweep across both stacks**

Run from repo root:

```bash
python -m pytest tests/ -v 2>&1 | tail -15
(cd dashboard && pnpm tsc --noEmit && pnpm vitest run)
```

Expected: backend full suite green (or with pre-existing firebase_admin import-skip); dashboard TS clean + vitest green.

- [ ] **Step 2: Skim the cumulative diff**

```bash
git log master..HEAD --oneline
git diff master..HEAD --stat
```

Confirm there are no surprise file changes — only the 8 paths listed in File Structure plus the spec/plan docs.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/107-order-lifecycle-statuses
```

```bash
gh pr create --repo tsuki-works/niko --base master --head feat/107-order-lifecycle-statuses \
  --title "Order lifecycle statuses + transition endpoints (B1 of B, #107)" \
  --body-file - <<'EOF'
## Summary
- Expands `OrderStatus` enum with `preparing` / `ready` / `completed` so the lifecycle can walk past `confirmed` through the kitchen workflow.
- Adds 4 new optional per-transition timestamps to `Order` (`preparing_at`, `ready_at`, `completed_at`, `cancelled_at`).
- New `_transition` helper in `app/orders/lifecycle.py` + 4 new transition functions (`mark_preparing`, `mark_ready`, `mark_completed`, `cancel_order`) — all idempotent, all stamping the right timestamp.
- 4 new tenant-scoped FastAPI endpoints (`POST /orders/{call_sid}/{transition}`) — including the cancel endpoint that has been stubbed since Phase 1.
- Dashboard mirror: `OrderStatusSchema` extended; new optional date fields on `OrderSchema`; `status-styles` map gains 3 new entries; `cancelOrderApi` wired to call the real backend endpoint.

## Linked issue
Closes #107. First of three sub-projects on the parent feature B (order queueing + restaurant notifications). B2 (tablet alert experience) and B3 (kitchen workflow buttons + filter tabs) follow.

## Spec & plan
- Spec: `docs/superpowers/specs/2026-04-28-order-lifecycle-statuses-design.md`
- Plan: `docs/superpowers/plans/2026-04-28-order-lifecycle-statuses.md`

## Test plan
- [x] Backend unit: `pytest tests/test_orders_lifecycle.py` — green (existing + 12 new transition tests)
- [x] Backend integration: `pytest tests/test_orders_route.py` — green (existing + 9 new endpoint tests)
- [x] Dashboard schema: `(cd dashboard && pnpm vitest run tests/order-schema.test.ts)` — green
- [x] Dashboard typecheck: `(cd dashboard && pnpm tsc --noEmit)` — clean (the exhaustive `Record<OrderStatus, StatusStyle>` would have failed without the new badge entries)
- [x] Dashboard full suite: `(cd dashboard && pnpm vitest run)` — green
- [ ] **Manual smoke** (optional pre-merge): with `ANTHROPIC_API_KEY` and a Twilio test number, place an order, then `curl -X POST` each transition endpoint with a valid session cookie. Verify Firestore doc walks through `confirmed → preparing → ready → completed`.

## Notes
- **No UI changes in this PR.** Buttons + filter tabs land in B3. Without the buttons, no orders will land in the new statuses in production yet — the dashboard just becomes ready to display them when they do.
- The existing `dashboard/tests/order-schema.test.ts` had a "rejects unknown statuses" test that used `'completed'` as its fictional unknown — updated to `'flux-capacitor-engaged'` since `'completed'` is now valid.
- Pure data-layer foundation. No telephony / TTS / LLM / call-quality surface touched.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

- [ ] **Step 4: Surface the PR URL**

The `gh pr create` output is the URL — relay it to the user.

---

## Self-review

**Spec coverage:**
- Enum expansion → Task 1 ✓
- Per-transition timestamps → Task 1 ✓
- Transition functions (4) → Task 2 ✓
- `OrderTransitionError` → Task 2 ✓
- FastAPI endpoints (4) → Task 3 ✓
- Cancel endpoint completing the dashboard stub → Tasks 3 + 6 ✓
- Dashboard `OrderStatusSchema` extension → Task 4 ✓
- Dashboard new optional date fields → Task 4 ✓
- `status-styles` map extension → Task 5 ✓
- `cancelOrderApi` real implementation → Task 6 ✓
- Backend unit + integration tests → Tasks 2 + 3 ✓
- Dashboard schema + status-styles tests → Tasks 4 + 5 ✓
- Push + PR → Task 7 ✓

**Placeholder scan:**
- Task 3 Step 1 has 9 stubbed test bodies (`pass`). Documented as intentional — implementer reads existing test pattern first, then fills in. Acceptable hedging because the EXACT mocking shape requires reading existing context I don't have in scope. Step 5 is the "fill in and run" gate.
- Task 3 Step 3 has the `_load_tenant_order` helper note: "if `order_storage.get_order` doesn't exist, add a thin helper or adapt." This is a small implementation choice rather than a placeholder — the spec doesn't dictate the storage API surface.

**Type consistency:**
- `OrderStatus.PREPARING` / `.READY` / `.COMPLETED` consistent across all 7 tasks.
- Field names (`preparing_at`, `ready_at`, `completed_at`, `cancelled_at`) consistent across schema (Task 1), transitions (Task 2), tests (all), dashboard schema (Task 4).
- Transition function names (`mark_preparing`, `mark_ready`, `mark_completed`, `cancel_order`) consistent across lifecycle (Task 2), endpoints (Task 3), tests.
- `OrderTransitionError` consistent across lifecycle (Task 2), endpoints (Task 3), tests.
- `_transition` helper signature matches the four call sites in `mark_*` / `cancel_order`.

**One ambiguity left for the implementer:** the storage `get_order` API. If it doesn't exist, the implementer adds a small helper to `app/storage/firestore.py` matching `list_recent_orders`'s pattern. Documented inline.
