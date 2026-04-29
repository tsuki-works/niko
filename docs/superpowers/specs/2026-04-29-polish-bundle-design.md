# Sprint 2.4 Polish Bundle (Design Spec)

**Date:** 2026-04-29
**Sprint:** 2.4 — Dashboard & Polish (#8)
**Tracking issue:** #125
**Owner:** Meet
**Status:** Approved — ready for implementation plan

## Goal

Three small, complementary frontend polish improvements deferred from Sprint 2.2. All vitest-verifiable, all dashboard-only, no backend changes.

## In scope

### 1. Optimistic UI on `TransitionButton`

Wrap each transition (`mark_preparing` / `mark_ready` / `mark_completed`) with `useOptimistic` so the row's status badge updates instantly on tap. Today there's a 100-500ms gap between tap and the `onSnapshot` reflection.

**Implementation:**
- `OrdersFeed` owns the `orders` state already (from `onSnapshot`). It needs to expose an "optimistically override status for this call_sid" mechanism.
- Cleanest path: `OrdersFeed` provides an `OptimisticStatusContext` (React context) that `TransitionButton` reads via `useOptimistic` against. On click, button calls the action AND simultaneously calls `addOptimistic({call_sid, target_status})`; `OrdersTable` reads the optimistic overrides and displays them when present.
- On failure, the optimistic state reverts (sonner error toast still fires per existing behavior).
- On success, `onSnapshot` reconciles the real Firestore update; the optimistic override naturally falls away.

### 2. Prep-time timer on order rows

In `OrdersTable`'s "Time" column, when `order.status` is `preparing` or `ready`, show elapsed time since the relevant transition timestamp (`preparing_at` for preparing rows, `ready_at` for ready rows) instead of `created_at`. Use the existing `<LocalTime mode="relative">` pattern that already exists in the table.

| Status | Time column shows |
|---|---|
| `in_progress` | "now" (existing) |
| `confirmed` | created_at relative (existing) |
| `preparing` | preparing_at relative |
| `ready` | ready_at relative |
| `completed` / `cancelled` | created_at relative (existing default) |

Useful kitchen signal: "this pizza has been preparing for 6 min."

### 3. B2 follow-up: extract OKLCH token for new-order flash

Replace the raw `rgb(245 158 11 / X)` in `globals.css` (added in #110) with a `--color-fresh-flash` OKLCH token defined in `@theme inline`. Light + dark variants. Follow the existing pattern of `--warning` / `--success` tokens.

## Out of scope

- Kitchen card-grid layout (separate Sprint 2.4 sub-project)
- Backward transitions / undo (needs new backend endpoint)
- Connection-state live indicator (separate Sprint 2.4 sub-project)
- Optimistic UI on `CancelOrderButton` (separate small follow-up; same pattern but covers a different action)

## Approach

**One context provider, one hook, one prop pass-through.** `OrdersFeed` wraps its render tree in `OptimisticStatusProvider` exposing `addOptimistic(call_sid, target_status)` + `optimisticOverrides: Map<call_sid, status>`. `TransitionButton` calls `addOptimistic` + the action together via `useOptimistic`. `OrdersTable` (or the `StatusBadge` it renders) consumes the override map and displays the optimistic status when present. Once `onSnapshot` reconciles, the override naturally stops applying.

Why a context (vs lifting state into `OrdersFeed` and prop-drilling): the override is needed deep in the tree (button → row → badge) AND needs to survive across re-renders without being recomputed. Context fits the React idiom.

For prep-time timer: a tiny helper `timeColumnTimestamp(order)` returns the right timestamp based on status. `OrdersTable` calls it.

For OKLCH token: standard Tailwind v4 `@theme` extension.

## Test plan

### Vitest

- `tests/transition-button.test.tsx` (existing): add 1-2 cases for the optimistic flow — verify `addOptimistic` is called immediately on tap, not waiting for the action; verify rollback on action failure.
- `tests/order-row.test.tsx` (NEW or extend existing table test): table-driven test asserting the right timestamp is displayed per status.
- No new test file for the OKLCH token (CSS-only, no logic to verify).

### Manual smoke (optional, not required for merge)

Open the dashboard, walk an order through the lifecycle. Subjectively verify the button taps feel instant (no perceptible gap before the badge updates).

## Done criteria

- All vitest tests green
- Dashboard typecheck clean
- niko-reviewer sign-off
- No backend changes (purely frontend)
- No manual e2e gate (changes are visible-but-not-load-bearing; safe to merge from automated tests alone)

## Files touched (anticipated)

- `dashboard/components/orders/optimistic-status-context.tsx` — NEW (context provider + hook)
- `dashboard/components/orders/orders-feed.tsx` — wrap in provider
- `dashboard/components/orders/transition-button.tsx` — call `addOptimistic` + action together
- `dashboard/components/orders/orders-table.tsx` — read optimistic overrides; use `timeColumnTimestamp` helper for the Time column
- `dashboard/components/orders/status-badge.tsx` (maybe) — accept optional override prop OR `OrdersTable` resolves the status before passing to badge
- `dashboard/app/globals.css` — add `--color-fresh-flash` OKLCH token (light + dark); update keyframe to use it
- `dashboard/tests/transition-button.test.tsx` — extend for optimistic flow
- `dashboard/tests/order-row.test.tsx` — NEW (or extend existing table test) for timestamp logic
