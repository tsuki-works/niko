# Kitchen Workflow UI (Design Spec — B3)

**Date:** 2026-04-29
**Sprint:** 2.2 — Order Taking Excellence (#5)
**Tracking issue:** #111
**Owner:** Meet
**Status:** Approved — ready for implementation plan
**Parent feature:** B (Order queueing + restaurant notifications). B1 (#108) and B2 (#110) are merged. B3 closes out parent feature B and Sprint 2.2.

## Goal

Wire the kitchen-facing UI to the transition endpoints from B1. Each order shows a single status-aware action button (Start Preparing → Mark Ready → Mark Completed) on both the row and the detail page. Filter tabs grow to surface each lifecycle stage. Server Actions wrap the FastAPI calls; toast feedback surfaces success/error.

## In scope

### (1) `TransitionButton` component — single button, status-aware

A new shared component renders ONE button based on the order's current status:

| Status | Button label | Visual | Server Action |
|---|---|---|---|
| `confirmed` | "Start Preparing" | Primary, emerald | `markPreparingAction` |
| `preparing` | "Mark Ready" | Primary, emerald | `markReadyAction` |
| `ready` | "Mark Completed" | Outline, neutral | `markCompletedAction` |
| `completed` / `cancelled` / `in_progress` | — | — | None (renders nothing) |

- **No confirmation dialog** for forward transitions — kitchen wants single-tap speed. The cancel button keeps its existing dialog (destructive + irreversible).
- Disabled while `useTransition` is pending.
- Uses sonner for success/error toasts: `"Order #ABCD is now preparing"` / `"Order #ABCD is ready"` / `"Order #ABCD is completed"`. Error toast surfaces FastAPI's `{ detail: string }` field.

### (2) Filter tabs grow from 4 to 7 (additive, no renames)

`dashboard/components/orders/filter-tabs.tsx`'s `TABS` array gains 3 entries:

```
All | Live | Confirmed | Preparing | Ready | Completed | Cancelled
```

URL pattern unchanged (`?status=preparing`, etc.). The page route's status query parsing is already enum-driven via the Zod schema (extended in B1) — no parsing changes needed.

### (3) Server Actions

A new file `dashboard/app/actions/transition-order.ts` exports three Server Actions, each parallel to `cancelOrder`:

- `markPreparingAction({ call_sid }) → { success: true } | { success: false, error: string }`
- `markReadyAction({ call_sid }) → { success: true } | { success: false, error: string }`
- `markCompletedAction({ call_sid }) → { success: true } | { success: false, error: string }`

Each:
- Validates input via Zod (`{ call_sid: z.string().min(1) }`)
- Calls the corresponding API client function (below)
- `revalidatePath('/')` and `revalidatePath('/orders/${call_sid}')` on success
- Returns the discriminated-union shape

### (4) API client functions

`dashboard/lib/api/orders.ts` gains three functions parallel to `cancelOrderApi`:

- `markPreparingApi(call_sid: string): Promise<{ success: true } | { success: false; error: string }>` — calls `POST /orders/{call_sid}/preparing` via `apiFetch`
- `markReadyApi(call_sid: string)` — calls `POST /orders/{call_sid}/ready`
- `markCompletedApi(call_sid: string)` — calls `POST /orders/{call_sid}/completed`

All three surface FastAPI's `{ detail: string }` field as the error message on 4xx, falling back to `${res.status} ${res.statusText}` if the body can't be parsed (mirrors `cancelOrderApi`).

### (5) `OrdersTable` integration — new "Action" column

The table grows from 5 columns to 6 by adding a right-most "Action" column rendering `<TransitionButton order={order} />`. Existing column widths/styles preserved. When the button is `null` (terminal/inapplicable status), the cell renders empty — no layout jump.

Existing `freshIds` highlight from B2 still applies (the row, not the button).

### (6) `OrderDetail` integration

Two changes to `dashboard/components/orders/order-detail.tsx`:

1. **Action button** — render `<TransitionButton order={order} />` in the existing actions area at the bottom of the detail page, alongside the existing `<CancelOrderButton>`. The cancel button's render condition broadens from just `confirmed` to `confirmed | preparing | ready` (you can cancel any pre-completed order — B1 endpoint allows it).

2. **`headerTimestamp` fix** (B1 follow-up): the existing switch only covers `confirmed`/`cancelled`/`in_progress`. Add cases for the 3 new statuses, each showing the relevant transition timestamp:
   - `preparing` → `"Started prep <preparing_at>"`
   - `ready` → `"Ready <ready_at>"`
   - `completed` → `"Completed <completed_at>"`
   - Fallback (defensive): if the timestamp field is `null`, render the bare label without a date.

## Out of scope

- **Kitchen card-grid layout** (big tiles instead of dense table rows). Sprint 2.4 polish.
- **Optimistic UI** via `useOptimistic`. The existing `onSnapshot` live feed reflects transitions within 100-500ms; if a transition fails, the toast surfaces it. `useOptimistic` is a Sprint 2.4 concern.
- **Undo** for accidental forward transitions. No backward transition endpoint exists; users can `cancel_order` from any pre-completed state if they need to off-ramp.
- **Per-status sound variations** (different bell for "ready" vs "preparing"). The single ding-dong from B2 covers all transitions — kitchen uses the visual cue (status badge color + table position) to disambiguate.
- **Undoing the rename of "Confirmed" to "Incoming"** — keeping "Confirmed" as the tab label since the term is well-established in the codebase + dashboard CLAUDE.md.

## Approach

**Mirror the cancel pattern.** `CancelOrderButton`/`cancelOrder`/`cancelOrderApi` are the existing template for "kitchen-facing UI button → Server Action → FastAPI". The three new transitions follow the exact same shape. This keeps the review surface small + the failure modes uniform.

**One status-aware button instead of three buttons + one cancel.** A single `<TransitionButton>` per row branches on status to render the right label/action. This:
- Shows only the *next* action — no decision fatigue ("should I tap Ready or Completed?")
- Avoids cluttering rows with 3 disabled-most-of-the-time buttons
- Naturally enforces the lifecycle (you can't tap "Mark Ready" on a `confirmed` order — the button doesn't exist)

**Cancel stays separate** — it's the destructive off-ramp, semantically different from forward transitions, and benefits from its own dialog.

**No Optimistic UI.** The live `onSnapshot` feed reconciles within ~500ms. Adding `useOptimistic` introduces complexity (revert on failure, key-stable updates) without much UX gain when the live feed is already fast.

### Why no confirmation dialog for forward transitions

The kitchen workflow is a tight loop: order arrives → tap Start Preparing → cook → tap Mark Ready → tap Mark Completed when handed off. Asking "Are you sure you want to start preparing?" on every tap is friction the kitchen will hate. The cost of a mis-tap is small (kitchen marked something ready early; their workflow self-corrects). The cost of friction is high (every order takes longer).

## Test plan

### Vitest unit tests

**`dashboard/tests/transition-button.test.tsx`** (NEW, uses `// @vitest-environment jsdom` + `@testing-library/react`):

Mock the three Server Actions. Test cases:

1. Renders nothing for `in_progress` / `completed` / `cancelled` orders.
2. Renders "Start Preparing" for `confirmed` orders; click triggers `markPreparingAction({call_sid})` once.
3. Renders "Mark Ready" for `preparing` orders; click triggers `markReadyAction`.
4. Renders "Mark Completed" for `ready` orders; click triggers `markCompletedAction`.
5. On success, fires success toast.
6. On failure, fires error toast with the action's error string.
7. Button disabled while pending.

**`dashboard/tests/transition-actions.test.ts`** (NEW):

Mock `apiFetch`. Test cases per action (3 actions × 3 patterns = ~9 tests):

1. Returns `{success: true}` when the API responds 200.
2. Returns `{success: false, error: detail}` when the API responds 4xx with a `{detail}` body.
3. Returns `{success: false, error: ${status} ${statusText}}` when the body isn't parseable.
4. Validates input (rejects empty `call_sid` with `{success: false, error: 'Invalid input'}`).
5. Calls `revalidatePath('/')` and `revalidatePath('/orders/{call_sid}')` on success.

### Manual smoke (pre-merge)

On a real tablet (or Chrome dev tools mobile mode):

1. Place a test order via `/dev/seed-order` or a real call. Verify it shows up in the live feed with status `confirmed` and a "Start Preparing" button.
2. Tap "Start Preparing". Verify the row's status badge updates to "Preparing" within ~500ms; toast says "Order #ABCD is now preparing"; the button now reads "Mark Ready".
3. Tap "Mark Ready". Same flow → status "Ready" → button reads "Mark Completed".
4. Tap "Mark Completed". Status badge → "Completed", muted color; button disappears (terminal state).
5. Place another order. Walk it to `preparing`, then tap the existing "Cancel order" button on the detail page. Verify the order moves to `cancelled` (B1's cancel endpoint accepts pre-completed states).
6. Visit `?status=preparing`, `?status=ready`, `?status=completed`. Verify each filter shows the right orders.
7. Verify the detail-page header timestamp shows the right transition timestamp for each new status.

## Done criteria

- All vitest unit tests green
- Dashboard typecheck (`pnpm tsc --noEmit`) clean
- Full vitest suite green
- Manual smoke test verified (results captured in PR description)
- `niko-reviewer` sign-off
- Sprint 2.2 (#5) checklist marks "Order queueing and notification to restaurant" done

## Risks and mitigations

- **Risk:** Kitchen taps "Mark Ready" too early (food still cooking), then realizes mid-flow. **Mitigation:** no undo for MVP — kitchen can `cancel_order` if needed. Sprint 2.4 can add backward transitions if real call data shows this is common.
- **Risk:** A row's button is for a state the user hasn't seen yet because their `?status=` filter is set narrowly (e.g. they're on the "Confirmed" tab and the order moves to `preparing`). **Mitigation:** the live `onSnapshot` query reflects status changes, so the order naturally drops out of the filtered view as it transitions. Toast still confirms the change occurred. The user can navigate to the "Preparing" tab to find it.
- **Risk:** Optimistic-update absence makes the dashboard feel sluggish on slow networks. **Mitigation:** `useTransition` provides a "pending" indicator on the button; the button text becomes "Working…" while waiting. Live feed reconciles when the round-trip completes. If real-call data shows this is meaningfully slow, add `useOptimistic` in Sprint 2.4.
- **Risk:** `OrdersTable` gaining a 6th column overflows on iPad portrait mode (768px wide). **Mitigation:** test in Chrome dev tools at 768×1024; if overflow, the existing `overflow-hidden` on the wrapper means horizontal scroll is the fallback (acceptable for MVP). Card-grid layout in Sprint 2.4 supersedes the table for kitchen view anyway.
- **Risk:** `headerTimestamp`'s switch could go stale if a *future* status is added without updating it (the existing one was stale from B1 and we're fixing it now). **Mitigation:** add a `default` branch with a `never` assertion so a future enum addition forces a TypeScript error at compile time.

## Files touched (anticipated)

- `dashboard/components/orders/transition-button.tsx` — NEW (the status-aware action button)
- `dashboard/components/orders/orders-table.tsx` — add "Action" column rendering `<TransitionButton>`
- `dashboard/components/orders/order-detail.tsx` — render `<TransitionButton>`; broaden cancel render condition to all pre-completed states; fix `headerTimestamp` for new statuses with exhaustive `never` default
- `dashboard/components/orders/filter-tabs.tsx` — extend `TABS` array with 3 entries
- `dashboard/lib/api/orders.ts` — `markPreparingApi`, `markReadyApi`, `markCompletedApi`
- `dashboard/app/actions/transition-order.ts` — NEW (3 Server Actions)
- `dashboard/tests/transition-button.test.tsx` — NEW (7 vitest tests, jsdom env, RTL)
- `dashboard/tests/transition-actions.test.ts` — NEW (~9 vitest tests, mocked `apiFetch`)
