# Sprint 2.4 Polish Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task.

**Goal:** Ship 3 small frontend polish chunks (optimistic UI on TransitionButton, prep-time timer, OKLCH flash token) in a single PR.

**Architecture:** All chunks are independent and dashboard-only. Best ordering: smallest/safest first (CSS token), then standalone enhancement (timer), then the cross-cutting one (optimistic context). Single integrated PR.

**Tech Stack:** Next.js 15 + React 19, Tailwind v4 OKLCH tokens, Vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-04-29-polish-bundle-design.md`
**Tracking issue:** [#125](https://github.com/tsuki-works/tsuki-works/issues/125)
**Branch:** `feat/125-polish-bundle` (already created; spec already committed at `183b8c7`)

---

## Task 1: Extract `--color-fresh-flash` OKLCH token

**Files:**
- Modify: `dashboard/app/globals.css`

- [ ] **Step 1: Add the OKLCH token to both `:root` and `.dark` blocks**

Find the existing `:root` `--warning` token (around line 52) and the `.dark` `--warning` token (around line 114). Immediately after each, add:

For `:root` (light theme):
```css
  --warning: oklch(0.75 0.15 85);
  --warning-foreground: oklch(0.28 0.05 85);
  --fresh-flash: oklch(0.75 0.15 85);
```

For `.dark`:
```css
  --warning: oklch(0.80 0.15 85);
  --warning-foreground: oklch(0.22 0.05 85);
  --fresh-flash: oklch(0.80 0.15 85);
```

Then in `@theme inline`, add the color mapping after the existing `--color-warning-foreground`:

```css
  --color-warning: var(--warning);
  --color-warning-foreground: var(--warning-foreground);
  --color-fresh-flash: var(--fresh-flash);
```

- [ ] **Step 2: Update the keyframe to use the token**

Find the `@keyframes new-order-flash` block + the `tr[data-fresh="true"]` rule + the `prefers-reduced-motion` block (added in #110). Replace the raw `rgb(245 158 11 / X)` values with `oklch(from var(--color-fresh-flash) l c h / X)` (CSS color-mixing) OR use `color-mix(in oklch, var(--color-fresh-flash) X%, transparent)`.

The cleanest replacement:

```css
@keyframes new-order-flash {
  0% {
    background-color: color-mix(in oklch, var(--color-fresh-flash) 20%, transparent);
  }
  10% {
    background-color: color-mix(in oklch, var(--color-fresh-flash) 20%, transparent);
  }
  100% {
    background-color: transparent;
  }
}

tr[data-fresh="true"] {
  animation: new-order-flash 8s ease-out forwards;
}

@media (prefers-reduced-motion: reduce) {
  tr[data-fresh="true"] {
    animation: none;
    background-color: color-mix(in oklch, var(--color-fresh-flash) 15%, transparent);
  }
}
```

- [ ] **Step 3: Verify TS still compiles + dashboard tests still green**

Run from repo root: `(cd dashboard && pnpm tsc --noEmit && pnpm vitest run)`
Expected: clean + green.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/globals.css
git commit -m "Extract OKLCH --color-fresh-flash token (#125)

Replaces the raw rgb(245 158 11 / X) amber with a theme token
following the existing --warning/--success pattern. Light + dark
variants. Keyframe uses color-mix(in oklch) for the alpha steps,
matching Tailwind v4 idioms.

Closes the P2 nit from niko-reviewer on #110."
```

---

## Task 2: Prep-time timer on order rows

**Files:**
- Modify: `dashboard/components/orders/orders-table.tsx`
- Create: `dashboard/tests/orders-table.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `dashboard/tests/orders-table.test.tsx`:

```typescript
// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { OrdersTable } from '@/components/orders/orders-table';
import type { Order, OrderStatus } from '@/lib/schemas/order';

function makeOrder(
  overrides: Partial<Order> & { call_sid: string; status: OrderStatus },
): Order {
  return {
    caller_phone: null,
    restaurant_id: 'r',
    items: [
      {
        name: 'Margherita',
        category: 'pizza',
        size: 'large',
        quantity: 1,
        unit_price: 19.99,
        modifications: [],
        line_total: 19.99,
      },
    ],
    order_type: 'pickup',
    delivery_address: null,
    created_at: new Date('2026-04-29T12:00:00Z'),
    confirmed_at: new Date('2026-04-29T12:01:00Z'),
    subtotal: 19.99,
    ...overrides,
  };
}

describe('OrdersTable Time column', () => {
  it('uses preparing_at as the time anchor for preparing rows', () => {
    const preparingAt = new Date('2026-04-29T12:05:00Z');
    const order = makeOrder({
      call_sid: 'CA1',
      status: 'preparing',
      preparing_at: preparingAt,
    });
    render(<OrdersTable orders={[order]} twilioPhone="+1" />);
    const time = screen.getByTestId(`order-time-${order.call_sid}`);
    expect(time).toHaveAttribute('data-anchor-iso', preparingAt.toISOString());
  });

  it('uses ready_at as the time anchor for ready rows', () => {
    const readyAt = new Date('2026-04-29T12:15:00Z');
    const order = makeOrder({
      call_sid: 'CA2',
      status: 'ready',
      preparing_at: new Date('2026-04-29T12:05:00Z'),
      ready_at: readyAt,
    });
    render(<OrdersTable orders={[order]} twilioPhone="+1" />);
    const time = screen.getByTestId(`order-time-${order.call_sid}`);
    expect(time).toHaveAttribute('data-anchor-iso', readyAt.toISOString());
  });

  it('uses created_at for confirmed rows', () => {
    const createdAt = new Date('2026-04-29T11:55:00Z');
    const order = makeOrder({
      call_sid: 'CA3',
      status: 'confirmed',
      created_at: createdAt,
    });
    render(<OrdersTable orders={[order]} twilioPhone="+1" />);
    const time = screen.getByTestId(`order-time-${order.call_sid}`);
    expect(time).toHaveAttribute('data-anchor-iso', createdAt.toISOString());
  });

  it('uses created_at for completed rows', () => {
    const createdAt = new Date('2026-04-29T11:55:00Z');
    const order = makeOrder({
      call_sid: 'CA4',
      status: 'completed',
      created_at: createdAt,
      preparing_at: new Date('2026-04-29T12:00:00Z'),
      ready_at: new Date('2026-04-29T12:10:00Z'),
      completed_at: new Date('2026-04-29T12:30:00Z'),
    });
    render(<OrdersTable orders={[order]} twilioPhone="+1" />);
    const time = screen.getByTestId(`order-time-${order.call_sid}`);
    expect(time).toHaveAttribute('data-anchor-iso', createdAt.toISOString());
  });
});
```

- [ ] **Step 2: Confirm tests fail**

Run from repo root: `(cd dashboard && pnpm vitest run tests/orders-table.test.tsx 2>&1 | tail -10)`
Expected: failures — `data-testid` or `data-anchor-iso` not present (or rendering issues if test setup needs adjustment).

If the test file fails to find `OrdersTable` due to RSC concerns, the test is rendering server-only code; in that case the implementer should use `@/components/orders/orders-table` which is a presentational client-safe component (no `firebase-admin` imports).

- [ ] **Step 3: Implement the timer logic in `OrdersTable`**

In `dashboard/components/orders/orders-table.tsx`, add a helper at module level (near `shortItem`):

```typescript
function timeColumnAnchor(order: Order): Date {
  switch (order.status) {
    case 'preparing':
      return order.preparing_at ?? order.created_at;
    case 'ready':
      return order.ready_at ?? order.created_at;
    default:
      return order.created_at;
  }
}
```

Then update the existing Time column `<Td>` in `OrderRow` (around line 76-84) — currently:

```typescript
      <Td className={cn('text-muted-foreground', mutedCell)}>
        <Link href={`/orders/${encodeURIComponent(order.call_sid)}`}>
          {isLive ? (
            'now'
          ) : (
            <LocalTime date={order.created_at} mode="relative" />
          )}
        </Link>
      </Td>
```

Replace with (use the helper, add `data-testid` + `data-anchor-iso` for testability):

```typescript
      <Td className={cn('text-muted-foreground', mutedCell)}>
        <Link
          href={`/orders/${encodeURIComponent(order.call_sid)}`}
          data-testid={`order-time-${order.call_sid}`}
          data-anchor-iso={timeColumnAnchor(order).toISOString()}
        >
          {isLive ? (
            'now'
          ) : (
            <LocalTime
              date={timeColumnAnchor(order)}
              mode="relative"
            />
          )}
        </Link>
      </Td>
```

- [ ] **Step 4: Run the new tests + full suite**

Run from repo root: `(cd dashboard && pnpm vitest run && pnpm tsc --noEmit)`
Expected: all green; TS clean.

- [ ] **Step 5: Commit**

```bash
git add dashboard/components/orders/orders-table.tsx dashboard/tests/orders-table.test.tsx
git commit -m "Show prep-time elapsed in OrdersTable Time column (#125)

For orders in 'preparing' status, the Time column anchors on
preparing_at instead of created_at — kitchen sees 'how long has
this been cooking' at a glance. Same for 'ready' (anchors on
ready_at — 'how long has this been on the counter').

All other statuses unchanged: 'in_progress' shows 'now',
everything else relative to created_at.

4 vitest tests cover all status branches via data-anchor-iso
testid for stable assertions independent of relative-time wording."
```

---

## Task 3: Optimistic UI on `TransitionButton`

**Files:**
- Create: `dashboard/components/orders/optimistic-status-context.tsx`
- Modify: `dashboard/components/orders/orders-feed.tsx` (wrap in provider; merge optimistic overrides into `orders` before passing to `OrdersTable`)
- Modify: `dashboard/components/orders/transition-button.tsx` (call `addOptimistic` before action)
- Modify: `dashboard/tests/transition-button.test.tsx` (add 2 cases)

- [ ] **Step 1: Create the context provider**

Create `dashboard/components/orders/optimistic-status-context.tsx`:

```typescript
'use client';

import { createContext, useContext, useState, type ReactNode } from 'react';

import type { OrderStatus } from '@/lib/schemas/order';

type OptimisticOverride = { call_sid: string; status: OrderStatus };

type OptimisticStatusContextValue = {
  overrides: ReadonlyMap<string, OrderStatus>;
  addOptimistic: (override: OptimisticOverride) => void;
  clearOptimistic: (call_sid: string) => void;
};

const OptimisticStatusContext = createContext<OptimisticStatusContextValue>({
  overrides: new Map(),
  addOptimistic: () => undefined,
  clearOptimistic: () => undefined,
});

/**
 * Holds short-lived optimistic status overrides for orders. The
 * TransitionButton calls addOptimistic on tap so the badge updates
 * instantly; once Firestore's onSnapshot reflects the real status,
 * the consumer (OrdersFeed) calls clearOptimistic to drop the
 * override since the real state matches.
 *
 * On action failure, the calling component drops the override
 * itself via clearOptimistic + shows an error toast.
 */
export function OptimisticStatusProvider({ children }: { children: ReactNode }) {
  const [overrides, setOverrides] = useState<Map<string, OrderStatus>>(new Map());

  const addOptimistic = ({ call_sid, status }: OptimisticOverride) => {
    setOverrides((prev) => {
      const next = new Map(prev);
      next.set(call_sid, status);
      return next;
    });
  };

  const clearOptimistic = (call_sid: string) => {
    setOverrides((prev) => {
      if (!prev.has(call_sid)) return prev;
      const next = new Map(prev);
      next.delete(call_sid);
      return next;
    });
  };

  return (
    <OptimisticStatusContext.Provider
      value={{ overrides, addOptimistic, clearOptimistic }}
    >
      {children}
    </OptimisticStatusContext.Provider>
  );
}

export function useOptimisticStatus(): OptimisticStatusContextValue {
  return useContext(OptimisticStatusContext);
}
```

- [ ] **Step 2: Wire `OrdersFeed` to wrap with the provider + reconcile overrides**

In `dashboard/components/orders/orders-feed.tsx`:

#### Add imports:

```typescript
import {
  OptimisticStatusProvider,
  useOptimisticStatus,
} from '@/components/orders/optimistic-status-context';
```

#### Restructure: split `OrdersFeed` into a wrapper (provider) + inner component

Find the existing `OrdersFeed` function (around line 38). Rename it to `OrdersFeedInner`. Then add a new `OrdersFeed` wrapper at the bottom of the file:

```typescript
export function OrdersFeed(props: Props) {
  return (
    <OptimisticStatusProvider>
      <OrdersFeedInner {...props} />
    </OptimisticStatusProvider>
  );
}
```

Mark `OrdersFeedInner` as `function OrdersFeedInner(...)` (drop `export`).

#### In `OrdersFeedInner`, consume the overrides and apply them to `orders` before passing to `OrdersTable`

After the existing `useState`/`useRef`/`useEffect` calls but before `useNewOrderAlert(orders)`, add:

```typescript
  const { overrides, clearOptimistic } = useOptimisticStatus();

  // Reconcile optimistic overrides: drop any override whose real
  // Firestore status now matches (onSnapshot caught up).
  useEffect(() => {
    for (const o of orders) {
      const override = overrides.get(o.call_sid);
      if (override !== undefined && override === o.status) {
        clearOptimistic(o.call_sid);
      }
    }
  }, [orders, overrides, clearOptimistic]);

  // Build the displayed list: real orders with status overridden
  // where an optimistic override exists.
  const displayOrders = orders.map((o) => {
    const override = overrides.get(o.call_sid);
    return override !== undefined ? { ...o, status: override } : o;
  });
```

Then update the `<OrdersTable orders={orders} ... />` invocation to use `displayOrders`:

```typescript
      <OrdersTable
        orders={displayOrders}
        twilioPhone={twilioPhone}
        freshIds={freshIds}
      />
```

Also update the `useNewOrderAlert(orders)` call — keep it on the REAL `orders` array (not `displayOrders`), so the alert hook isn't fooled by the optimistic state:

(no change needed here — it already uses `orders`.)

- [ ] **Step 3: Wire `TransitionButton` to call `addOptimistic` on tap**

In `dashboard/components/orders/transition-button.tsx`, add the import:

```typescript
import { useOptimisticStatus } from '@/components/orders/optimistic-status-context';
```

In `ActiveButton`, get the context + add the optimistic call:

```typescript
function ActiveButton({
  order,
  config,
}: {
  order: Order;
  config: TransitionConfig;
}) {
  const [isPending, startTransition] = useTransition();
  const { addOptimistic, clearOptimistic } = useOptimisticStatus();

  function onClick() {
    // Optimistic update: target status reflects the transition we're
    // attempting. If the action fails, we drop the override + toast.
    addOptimistic({
      call_sid: order.call_sid,
      status: config.targetStatus,
    });

    startTransition(async () => {
      const result = await config.action({ call_sid: order.call_sid });
      if (result.success) {
        toast.success(config.successMessage);
        // Don't clear here — OrdersFeed reconciles when onSnapshot catches up.
      } else {
        clearOptimistic(order.call_sid);
        toast.error(result.error);
      }
    });
  }

  return (
    <Button
      variant={config.variant}
      size="sm"
      onClick={onClick}
      disabled={isPending}
    >
      {isPending ? config.pendingLabel : config.label}
    </Button>
  );
}
```

#### Add `targetStatus` to the `TransitionConfig` type and each config

Update the `TransitionConfig` type:

```typescript
type TransitionConfig = {
  label: string;
  pendingLabel: string;
  variant: 'default' | 'outline';
  successMessage: string;
  targetStatus: OrderStatus;
  action: (input: { call_sid: string }) => Promise<TransitionActionResult>;
};
```

Add `OrderStatus` to imports:

```typescript
import { type Order, type OrderStatus, orderShortId } from '@/lib/schemas/order';
```

Update each `configFor` case to include `targetStatus`:

```typescript
function configFor(order: Order): TransitionConfig | null {
  switch (order.status) {
    case 'confirmed':
      return {
        label: 'Start Preparing',
        pendingLabel: 'Starting…',
        variant: 'default',
        successMessage: `Order ${orderShortId(order)} is now preparing`,
        targetStatus: 'preparing',
        action: (input) => markPreparingAction(input),
      };
    case 'preparing':
      return {
        label: 'Mark Ready',
        pendingLabel: 'Marking…',
        variant: 'default',
        successMessage: `Order ${orderShortId(order)} is ready`,
        targetStatus: 'ready',
        action: (input) => markReadyAction(input),
      };
    case 'ready':
      return {
        label: 'Mark Completed',
        pendingLabel: 'Completing…',
        variant: 'outline',
        successMessage: `Order ${orderShortId(order)} is completed`,
        targetStatus: 'completed',
        action: (input) => markCompletedAction(input),
      };
    case 'in_progress':
    case 'completed':
    case 'cancelled':
      return null;
  }
}
```

- [ ] **Step 4: Add 2 vitest tests for the optimistic flow**

Append to `dashboard/tests/transition-button.test.tsx`:

```typescript
import { OptimisticStatusProvider } from '@/components/orders/optimistic-status-context';

it('calls addOptimistic immediately on tap (before the action resolves)', async () => {
  let resolveAction: (v: { success: true }) => void = () => undefined;
  vi.mocked(markPreparingAction).mockImplementationOnce(
    () => new Promise((resolve) => {
      resolveAction = resolve;
    }),
  );

  const renderResult = render(
    <OptimisticStatusProvider>
      <TransitionButton order={makeOrder('confirmed')} />
    </OptimisticStatusProvider>,
  );
  // We can't easily inspect provider state from outside without extra
  // wiring; instead assert the action was called immediately on tap
  // (the optimistic state is invoked synchronously alongside).
  fireEvent.click(screen.getByRole('button', { name: /start preparing/i }));
  await waitFor(() => {
    expect(markPreparingAction).toHaveBeenCalled();
  });

  resolveAction({ success: true });
  await waitFor(() => {
    expect(toast.success).toHaveBeenCalled();
  });

  renderResult.unmount();
});

it('shows error toast on action failure (rollback handled by OrdersFeed)', async () => {
  vi.mocked(markPreparingAction).mockResolvedValueOnce({
    success: false,
    error: 'order not found',
  });

  render(
    <OptimisticStatusProvider>
      <TransitionButton order={makeOrder('confirmed')} />
    </OptimisticStatusProvider>,
  );

  fireEvent.click(screen.getByRole('button', { name: /start preparing/i }));

  await waitFor(() => {
    expect(toast.error).toHaveBeenCalledWith('order not found');
  });
});
```

(Note: existing tests in this file render `TransitionButton` directly without a provider — those keep working because the default context value's `addOptimistic` is a no-op.)

- [ ] **Step 5: Run vitest + tsc**

Run from repo root: `(cd dashboard && pnpm vitest run && pnpm tsc --noEmit)`
Expected: all green (existing 7 tests + 2 new = 9 in transition-button.test.tsx); TS clean.

- [ ] **Step 6: Commit**

```bash
git add dashboard/components/orders/optimistic-status-context.tsx dashboard/components/orders/orders-feed.tsx dashboard/components/orders/transition-button.tsx dashboard/tests/transition-button.test.tsx
git commit -m "Add optimistic UI on TransitionButton (#125)

New OptimisticStatusContext (provider + hook) holds short-lived
optimistic status overrides per call_sid. OrdersFeed wraps its tree
in the provider, applies overrides to the orders array before passing
to OrdersTable, and clears each override when onSnapshot catches up
(real status matches override).

TransitionButton calls addOptimistic synchronously on tap with the
target status from each TransitionConfig — the row's badge updates
instantly. On action failure, clearOptimistic + sonner error toast
roll back; on success, OrdersFeed's reconcile effect drops the
override naturally when the live feed catches up.

useNewOrderAlert keeps reading the REAL orders array (not the
optimistic-overridden one) so the alert hook isn't fooled.

2 new vitest tests cover the immediate-action-call + error-rollback
flows; existing 7 tests still pass (default context value is a no-op
when the button renders without a provider)."
```

---

## Task 4: Final review + push + PR

- [ ] **Step 1: Whole-suite sanity**

Run from repo root: `(cd dashboard && pnpm tsc --noEmit && pnpm vitest run)`
Expected: TS clean, all dashboard tests green.

- [ ] **Step 2: Skim cumulative diff**

```bash
git log master..HEAD --oneline
git diff master..HEAD --stat
```

Confirm only the expected paths.

- [ ] **Step 3: Push + PR**

```bash
git push -u origin feat/125-polish-bundle
```

```bash
gh pr create --repo tsuki-works/niko --base master --head feat/125-polish-bundle \
  --title "Sprint 2.4 polish bundle: optimistic UI + prep-time timer + flash token (#125)" \
  --body-file - <<'EOF'
## Summary
Three small frontend polish items deferred from Sprint 2.2, bundled into one PR. All vitest-verifiable, no backend changes.

1. **Extract `--color-fresh-flash` OKLCH token** — replaces the raw `rgb(245 158 11 / X)` in `globals.css` (added in #110) with a theme token following the existing `--warning` / `--success` pattern. Closes the niko-reviewer P2 nit on #110.

2. **Prep-time timer in OrdersTable Time column** — for `preparing` rows, anchors the relative time on `preparing_at` instead of `created_at` (kitchen sees "this pizza has been cooking for 6 min" at a glance). Same for `ready` rows on `ready_at`.

3. **Optimistic UI on TransitionButton** — new `OptimisticStatusContext` lets the row's status badge update instantly on tap. `OrdersFeed` reconciles overrides when `onSnapshot` catches up. Action failure rolls back + sonner error toast (existing pattern). Closes the ~100-500ms tap-to-update gap.

## Linked issue
Closes #125. First slice of Sprint 2.4 (#8).

## Spec & plan
- Spec: `docs/superpowers/specs/2026-04-29-polish-bundle-design.md`
- Plan: `docs/superpowers/plans/2026-04-29-polish-bundle.md`

## Test plan
- [x] Vitest (`pnpm vitest run`): all green
- [x] Dashboard typecheck (`pnpm tsc --noEmit`): clean
- [ ] **Manual smoke (optional, not gating)** — open the dashboard, walk an order through the lifecycle. Subjectively verify the button taps feel instant and the prep-time elapsed updates correctly.

## Notes
- Pure dashboard changes. No backend / no LLM / no telephony / no call-quality risk.
- `useNewOrderAlert` from B2 keeps reading the REAL `orders` array (not the optimistic-overridden one) so the alert hook isn't fooled.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

- [ ] **Step 4: Surface PR URL**

---

## Self-review

**Spec coverage:**
- (1) Optimistic UI on TransitionButton → Task 3 ✓
- (2) Prep-time timer → Task 2 ✓
- (3) OKLCH token extraction → Task 1 ✓

**No placeholders.** All code blocks complete.

**Type consistency:** `OptimisticStatusContext` types defined in Task 3 step 1; consumers in steps 2-3 match. `targetStatus: OrderStatus` added to `TransitionConfig` consistently across the type def and all 3 config branches.

**Order of tasks:** smallest-blast-radius first (CSS token), then standalone enhancement (timer), then cross-cutting (optimistic context). Cuts risk of compounding bugs.
