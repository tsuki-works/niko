# Order Lifecycle Statuses + Transition Endpoints (Design Spec — B1)

**Date:** 2026-04-28
**Sprint:** 2.2 — Order Taking Excellence (#5)
**Tracking issue:** #107
**Owner:** Meet
**Status:** Approved — ready for implementation plan
**Parent feature:** B (Order queueing + restaurant notifications). B1 is the data-layer foundation; B2 (tablet alert experience) and B3 (kitchen workflow UI) follow.

## Goal

Expand the order lifecycle from `confirmed → cancelled` (terminal) to a real kitchen workflow: `confirmed → preparing → ready → completed`, with `cancelled` as an off-ramp from any pre-`completed` state. Ship the data-layer foundation (enum, transition functions, FastAPI endpoints, dashboard schema mirror) so B2 and B3 can build the UI on top.

## In scope

### Backend (`app/`)

1. **Enum expansion.** `OrderStatus` in `app/orders/models.py` gains `PREPARING`, `READY`, `COMPLETED` values.
2. **Per-transition timestamps.** `Order` gets four new optional `datetime` fields: `preparing_at`, `ready_at`, `completed_at`, `cancelled_at`. Symmetric with the existing `confirmed_at`. None of them are required (a freshly-confirmed order has only `created_at` + `confirmed_at`).
3. **Transition functions** in `app/orders/lifecycle.py`:

   | Function | Source state required | Target state | Stamps |
   |---|---|---|---|
   | `mark_preparing(order)` | `CONFIRMED` | `PREPARING` | `preparing_at` |
   | `mark_ready(order)` | `PREPARING` | `READY` | `ready_at` |
   | `mark_completed(order)` | `READY` | `COMPLETED` | `completed_at` |
   | `cancel_order(order)` | any of `IN_PROGRESS`, `CONFIRMED`, `PREPARING`, `READY` | `CANCELLED` | `cancelled_at` |

   All transitions:
   - **Validate the source state** — raise `OrderTransitionError` (new) if called from the wrong state.
   - **Idempotent** — calling `mark_preparing` on an already-`PREPARING` order is a no-op write that preserves the original `preparing_at` timestamp. Same as `persist_on_confirm`.
   - **Stamp the timestamp at write time** if not already set.
   - **Persist via `app.storage.firestore.save_order`** (existing).
   - **Return the updated `Order`** in the new state.

4. **FastAPI endpoints** in `app/main.py`, all tenant-scoped via `current_tenant`:

   | Method + path | Source state | Target state |
   |---|---|---|
   | `POST /orders/{call_sid}/preparing` | `CONFIRMED` | `PREPARING` |
   | `POST /orders/{call_sid}/ready` | `PREPARING` | `READY` |
   | `POST /orders/{call_sid}/completed` | `READY` | `COMPLETED` |
   | `POST /orders/{call_sid}/cancel` | any pre-`completed` | `CANCELLED` |

   Behavior:
   - Look up the order in `restaurants/{tenant.restaurant_id}/orders/{call_sid}`.
   - **404** if no doc, OR the doc exists but belongs to a different tenant (indistinguishable, matches the pattern from `/dev/calls/{call_sid}`).
   - **409** if the order is in the wrong source state (`OrderTransitionError` → 409 with the error message).
   - **200** with the updated Order JSON on success (`order.model_dump(mode="json")`).
   - The `cancel` endpoint completes the existing stub the dashboard already calls (`STUB_CANCEL_ORDER` in `dashboard/lib/api/orders.ts`).

### Dashboard (`dashboard/`)

5. **`lib/schemas/order.ts`:** extend `OrderStatusSchema` Zod enum with `'preparing'`, `'ready'`, `'completed'`. Add four new optional date fields to `OrderSchema`: `preparing_at`, `ready_at`, `completed_at`, `cancelled_at` — all `z.date().nullish()` so reads of pre-existing orders without these fields don't fail.
6. **`lib/status-styles.ts`:** badge styles for the 3 new statuses. Color choices:
   - `preparing` → amber/orange (active, requires attention)
   - `ready` → emerald (positive, the "this can leave the kitchen" moment — matches the existing brand emerald per dashboard CLAUDE.md)
   - `completed` → muted/neutral (terminal, no action required)
   The exact OKLCH values match existing token conventions (`bg-{color}/15 text-{color} border-{color}/30`).
7. **`lib/api/orders.ts`:** flip `STUB_CANCEL_ORDER = false`. Implement `cancelOrderApi` to actually call `POST /orders/{call_sid}/cancel` via `apiFetch`. Other transition endpoints are not added in B1 — those are B3's job.
8. **`lib/firebase/converters.ts`:** no changes expected. The Zod converter already handles new optional fields gracefully when the doc lacks them.

## Out of scope

- **Action buttons in the UI** ("Start preparing" / "Mark ready" / etc.) — B3.
- **Filter tabs growing** to include the new statuses — B3.
- **Server actions** wrapping the new transition endpoints — B3.
- **Tablet alert experience** (audible cue + visual highlight + kiosk niceties) — B2.
- **Backfill** of `preparing_at`/etc. on existing orders. Pydantic `Optional` defaults to `None`; existing Firestore docs read cleanly via the new optional Zod fields.
- **Migration script** to flip historical `confirmed` orders to `completed`. Phase 2 history is too small to matter; the lifecycle starts working forward from this PR.
- **`Order.is_ready_to_confirm()` change.** Stays as today (only relates to `in_progress → confirmed`, no impact on the new transitions).

## Approach

**Mirror the existing `persist_on_confirm` pattern.** Each new lifecycle function does the same shape: validate source state, stamp the right timestamp, write to Firestore, return the updated Order. The `OrderTransitionError` type is the analog of the existing `OrderNotReadyError` and maps naturally to a 409 in the endpoint layer.

**Keep B1 pure data-layer.** Adding the buttons and filter tabs in B1 would balloon the PR and complicate the dashboard review. Splitting at the data/UI boundary keeps each PR's review focused.

**Implement cancel as part of B1, even though the dashboard already wired its UI side.** The cancel endpoint has been a stub for two sprints — picking it up here closes a gap and exercises the same transition machinery, so the per-transition test pattern gets reused naturally.

### Why per-transition timestamps (not just one `last_transition_at`)

Each timestamp is independently useful:
- `preparing_at` → "how long has this been cooking?" — answers prep-time UX (B2/B3)
- `ready_at` → "how long has this been waiting on the counter?" — handoff timeliness
- `completed_at` → "average time-to-fulfillment" — analytics

A single `last_transition_at` would lose all that history.

### Why FastAPI endpoints (not Server Actions writing directly to Firestore)

Two reasons:
1. **Single writer.** FastAPI is the source of truth for order state mutations. Server Actions calling Firestore directly would race with FastAPI on edge cases and bypass any future server-side hooks (e.g., notifying analytics on each transition).
2. **Pattern consistency.** The existing cancel stub already uses the FastAPI-via-`apiFetch` pattern. New transitions should match.

## Test plan

### Backend

**Unit tests** in `tests/test_orders_lifecycle.py` (existing file). Per transition function (4 functions × 4 test patterns = ~16 tests):
- Positive case: source state matches, transition succeeds, target state set, target timestamp stamped.
- Wrong-source rejection: each invalid source state raises `OrderTransitionError` with a descriptive message.
- Idempotency: calling the transition again on an already-target-state order is a no-op write that preserves the original timestamp.
- Persistence: `save_order` is called with the updated state (mocked).

**Integration tests** in `tests/test_orders_route.py` (existing file). Per endpoint (4 endpoints × 4 test patterns):
- 200 + correct payload on valid transition.
- 401 / 403 when called without a valid tenant session.
- 404 when the order doesn't belong to the calling tenant (cross-tenant isolation).
- 409 when the order is in the wrong source state.

### Dashboard

**Vitest** tests in `dashboard/tests/order-schema.test.ts` (existing file):
- `OrderSchema.parse(...)` accepts the 3 new statuses.
- `OrderSchema.parse(...)` accepts orders with the new optional timestamps populated AND with them missing.
- `status-styles.ts` `STYLES` map covers all 6 OrderStatus values (compile-time exhaustiveness via `Record<OrderStatus, ...>` already enforces this; the test asserts the expected labels and class strings).

**No live-LLM tests** — B1 doesn't touch the conversation engine.

## Done criteria

- All backend unit tests green
- All backend integration tests green
- Dashboard vitest green
- `niko-reviewer` sign-off (multi-tenant safety on the new endpoints, schema mirroring correct, no call-quality regression)
- Manual smoke check: with `ANTHROPIC_API_KEY` and a Twilio test number, place an order, then `curl -X POST` each transition endpoint in turn (with a valid session cookie). Verify the Firestore doc walks through `confirmed → preparing → ready → completed` with timestamps stamping correctly. Cancel from `preparing` works too.

## Risks and mitigations

- **Risk:** Adding new statuses breaks existing dashboard rendering paths that haven't been audited (e.g., `OrdersTable`, `OrderDetail`, `FilterTabs`). **Mitigation:** the Zod enum expansion is additive; the `Record<OrderStatus, StatusStyle>` map in `status-styles.ts` is exhaustive at compile time and will fail TypeScript compilation if any new status is missing. Filter tabs currently filter on `status === 'in_progress' | 'confirmed' | 'cancelled'` — orders with a new status will show in the "all" view (no filter tab) until B3 adds them. That's acceptable for B1; no orders will be in those states yet anyway.
- **Risk:** The cancel endpoint behaves differently from the dashboard's expectation (today the dashboard calls a stubbed endpoint that returns success). **Mitigation:** keep the response shape simple (200 + Order JSON, 4xx with error string in detail). The dashboard's `cancelOrder` Server Action already handles the `{ success, error }` discriminated union — wire `cancelOrderApi` to map FastAPI's response into that shape.
- **Risk:** Race between the AI's confirmation write and a staff cancel. **Mitigation:** the existing dashboard CLAUDE.md note acknowledges this — "we only cancel `confirmed` orders, FastAPI is done by then." Same applies to the new transitions: `preparing` / `ready` / `completed` are kitchen-side, post-call. The AI writes once on confirmation; everything after is single-writer kitchen.

## Files touched (anticipated)

**Backend:**
- `app/orders/models.py` — enum expansion + 4 new optional timestamp fields + new `OrderTransitionError` (could go in `lifecycle.py` instead — implementer's call)
- `app/orders/lifecycle.py` — 4 new transition functions
- `app/main.py` — 4 new endpoint handlers
- `tests/test_orders_lifecycle.py` — unit tests
- `tests/test_orders_route.py` — endpoint tests

**Dashboard:**
- `dashboard/lib/schemas/order.ts` — Zod enum + new optional date fields
- `dashboard/lib/status-styles.ts` — 3 new entries in the styles map
- `dashboard/lib/api/orders.ts` — flip `STUB_CANCEL_ORDER`, implement `cancelOrderApi` for real
- `dashboard/tests/order-schema.test.ts` — schema tests + status-styles coverage
