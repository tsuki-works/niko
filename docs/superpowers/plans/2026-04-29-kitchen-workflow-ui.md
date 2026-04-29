# Kitchen Workflow UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the kitchen-facing UI to the transition endpoints from B1. Each order shows a single status-aware action button (Start Preparing → Mark Ready → Mark Completed) on both the row and the detail page. Filter tabs grow to surface each lifecycle stage.

**Architecture:** Mirror the existing `cancelOrder` / `cancelOrderApi` / `CancelOrderButton` pattern. Three new API client functions + three new Server Actions + one shared status-aware `TransitionButton` component. Each transition is a thin wrapper around `POST /orders/{call_sid}/{transition}`. UI is integrated by adding an "Action" column to `OrdersTable`, a button on the order-detail page, and three new entries in `FilterTabs`. The B1 follow-up `headerTimestamp` gap is fixed in this PR.

**Tech Stack:** Next.js 15 + React 19 + TypeScript strict; Tailwind v4 (OKLCH tokens); Vitest 3.2 + `@testing-library/react` + jsdom; sonner for toasts; Zod for input validation.

**Spec:** `docs/superpowers/specs/2026-04-29-kitchen-workflow-ui-design.md`
**Tracking issue:** [#111](https://github.com/tsuki-works/niko/issues/111)
**Branch:** `feat/111-kitchen-workflow-ui` (already created; spec already committed at `bca80c1`)

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `dashboard/lib/api/orders.ts` | Modify | 3 new functions (`markPreparingApi`, `markReadyApi`, `markCompletedApi`) — thin wrappers around `apiFetch` returning a discriminated-union result, mirroring `cancelOrderApi` |
| `dashboard/app/actions/transition-order.ts` | Create | 3 Server Actions (`markPreparingAction`, `markReadyAction`, `markCompletedAction`) — Zod input validation, call API client, `revalidatePath`, return discriminated union |
| `dashboard/components/orders/transition-button.tsx` | Create | Status-aware button: renders nothing for terminal states; renders the next-action button for `confirmed`/`preparing`/`ready`. Uses `useTransition` + sonner toast |
| `dashboard/components/orders/orders-table.tsx` | Modify | Add a 6th right-most "Action" column rendering `<TransitionButton order={order} />` |
| `dashboard/components/orders/order-detail.tsx` | Modify | Render `<TransitionButton order={order} />` next to the existing `<CancelOrderButton>`; broaden cancel render condition to `confirmed | preparing | ready`; add `headerTimestamp` cases for the 3 new statuses with `never` default |
| `dashboard/components/orders/filter-tabs.tsx` | Modify | Extend `TABS` array with 3 entries (preparing / ready / completed) |
| `dashboard/tests/transition-actions.test.ts` | Create | Vitest: 9 tests (3 actions × 3 patterns: 200 success, 4xx with detail, input validation) — mocks `apiFetch` |
| `dashboard/tests/transition-button.test.tsx` | Create | Vitest with `// @vitest-environment jsdom` + RTL: 7 tests covering each status branch + toast feedback + pending state |

The work decomposes naturally into 5 layers: API client → Server Actions → Button component → 3 small UI integrations → final review/PR. Each lower layer is a dependency for the next.

---

## Task 1: API client functions in `dashboard/lib/api/orders.ts`

**Files:**
- Modify: `dashboard/lib/api/orders.ts` (append 3 new exported functions; reuse the existing `CancelResult` type by renaming it, OR add a sibling `TransitionResult` type — implementer's call, both are acceptable)

- [ ] **Step 1: Add the 3 new functions to `dashboard/lib/api/orders.ts`**

Open `dashboard/lib/api/orders.ts`. Find the existing `CancelResult` type definition (around line 73) and the `cancelOrderApi` function. Immediately AFTER `cancelOrderApi` ends (before `parseStatusParam`), insert this block:

```typescript

// ---------------------------------------------------------------------------
// B3 transition API functions (Sprint 2.2 #111)
// ---------------------------------------------------------------------------
// Each is a thin wrapper around POST /orders/{call_sid}/{transition}.
// Same shape as cancelOrderApi: returns { success: true, order } on 200,
// { success: false, error } on 4xx/5xx (FastAPI's { detail } surfaced).

export type TransitionResult =
  | { success: true; order: Order }
  | { success: false; error: string };

async function postTransition(
  callSid: string,
  transition: 'preparing' | 'ready' | 'completed',
): Promise<TransitionResult> {
  const path = `/orders/${encodeURIComponent(callSid)}/${transition}`;
  const res = await apiFetch(path, { method: 'POST' });

  if (!res.ok) {
    // FastAPI returns { detail: string } on 4xx — surface that to the user.
    let detail: string;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail =
        typeof body.detail === 'string'
          ? body.detail
          : `${res.status} ${res.statusText}`;
    } catch {
      detail = `${res.status} ${res.statusText}`;
    }
    return { success: false, error: detail };
  }

  const body = await res.json();
  const parsed = OrderSchema.safeParse(
    body && typeof body === 'object' && 'order' in body ? body.order : body,
  );
  if (!parsed.success) {
    return { success: false, error: `${transition} response failed validation` };
  }
  return { success: true, order: parsed.data };
}

export function markPreparingApi(callSid: string): Promise<TransitionResult> {
  return postTransition(callSid, 'preparing');
}

export function markReadyApi(callSid: string): Promise<TransitionResult> {
  return postTransition(callSid, 'ready');
}

export function markCompletedApi(callSid: string): Promise<TransitionResult> {
  return postTransition(callSid, 'completed');
}
```

- [ ] **Step 2: Verify TS compiles**

Run from repo root: `(cd dashboard && pnpm tsc --noEmit)`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboard/lib/api/orders.ts
git commit -m "Add transition API client functions (#111)

Three new exports — markPreparingApi, markReadyApi, markCompletedApi —
each a thin wrapper around POST /orders/{call_sid}/{transition} via
the existing apiFetch helper. Return TransitionResult discriminated
union mirroring cancelOrderApi's shape. Internal postTransition helper
de-dupes the response-handling logic across the three transitions.

Server Actions wrapping these land in the next commit."
```

Stage ONLY `dashboard/lib/api/orders.ts`.

---

## Task 2: Server Actions in `dashboard/app/actions/transition-order.ts`

**Files:**
- Create: `dashboard/app/actions/transition-order.ts`
- Create: `dashboard/tests/transition-actions.test.ts`

- [ ] **Step 1: Write the failing test file**

Create `dashboard/tests/transition-actions.test.ts` with this exact content:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the API client and Next.js cache before importing the actions.
vi.mock('@/lib/api/orders', () => ({
  markPreparingApi: vi.fn(),
  markReadyApi: vi.fn(),
  markCompletedApi: vi.fn(),
}));

vi.mock('next/cache', () => ({
  revalidatePath: vi.fn(),
}));

import {
  markPreparingApi,
  markReadyApi,
  markCompletedApi,
} from '@/lib/api/orders';
import { revalidatePath } from 'next/cache';

import {
  markPreparingAction,
  markReadyAction,
  markCompletedAction,
} from '@/app/actions/transition-order';

const okOrder = (call_sid: string, status: string) => ({
  success: true as const,
  order: {
    call_sid,
    caller_phone: null,
    restaurant_id: 'r',
    items: [],
    order_type: 'pickup' as const,
    delivery_address: null,
    status,
    created_at: new Date(),
    confirmed_at: new Date(),
    subtotal: 0,
  },
});

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---- markPreparingAction --------------------------------------------------

describe('markPreparingAction', () => {
  it('returns success and revalidates paths on 200', async () => {
    vi.mocked(markPreparingApi).mockResolvedValueOnce(
      okOrder('CAtest', 'preparing'),
    );
    const result = await markPreparingAction({ call_sid: 'CAtest' });
    expect(result).toEqual({ success: true });
    expect(markPreparingApi).toHaveBeenCalledWith('CAtest');
    expect(revalidatePath).toHaveBeenCalledWith('/');
    expect(revalidatePath).toHaveBeenCalledWith('/orders/CAtest');
  });

  it('returns failure when the API client returns failure', async () => {
    vi.mocked(markPreparingApi).mockResolvedValueOnce({
      success: false,
      error: 'Cannot transition order CAtest to preparing: ...',
    });
    const result = await markPreparingAction({ call_sid: 'CAtest' });
    expect(result).toEqual({
      success: false,
      error: 'Cannot transition order CAtest to preparing: ...',
    });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it('rejects empty call_sid input', async () => {
    const result = await markPreparingAction({ call_sid: '' });
    expect(result).toEqual({ success: false, error: 'Invalid input' });
    expect(markPreparingApi).not.toHaveBeenCalled();
  });
});

// ---- markReadyAction ------------------------------------------------------

describe('markReadyAction', () => {
  it('returns success and revalidates paths on 200', async () => {
    vi.mocked(markReadyApi).mockResolvedValueOnce(okOrder('CAtest', 'ready'));
    const result = await markReadyAction({ call_sid: 'CAtest' });
    expect(result).toEqual({ success: true });
    expect(markReadyApi).toHaveBeenCalledWith('CAtest');
    expect(revalidatePath).toHaveBeenCalledWith('/');
    expect(revalidatePath).toHaveBeenCalledWith('/orders/CAtest');
  });

  it('returns failure when the API client returns failure', async () => {
    vi.mocked(markReadyApi).mockResolvedValueOnce({
      success: false,
      error: 'Cannot transition',
    });
    const result = await markReadyAction({ call_sid: 'CAtest' });
    expect(result).toEqual({ success: false, error: 'Cannot transition' });
  });

  it('rejects empty call_sid input', async () => {
    const result = await markReadyAction({ call_sid: '' });
    expect(result).toEqual({ success: false, error: 'Invalid input' });
  });
});

// ---- markCompletedAction --------------------------------------------------

describe('markCompletedAction', () => {
  it('returns success and revalidates paths on 200', async () => {
    vi.mocked(markCompletedApi).mockResolvedValueOnce(
      okOrder('CAtest', 'completed'),
    );
    const result = await markCompletedAction({ call_sid: 'CAtest' });
    expect(result).toEqual({ success: true });
    expect(markCompletedApi).toHaveBeenCalledWith('CAtest');
    expect(revalidatePath).toHaveBeenCalledWith('/');
    expect(revalidatePath).toHaveBeenCalledWith('/orders/CAtest');
  });

  it('returns failure when the API client returns failure', async () => {
    vi.mocked(markCompletedApi).mockResolvedValueOnce({
      success: false,
      error: 'Cannot transition',
    });
    const result = await markCompletedAction({ call_sid: 'CAtest' });
    expect(result).toEqual({ success: false, error: 'Cannot transition' });
  });

  it('rejects empty call_sid input', async () => {
    const result = await markCompletedAction({ call_sid: '' });
    expect(result).toEqual({ success: false, error: 'Invalid input' });
  });
});
```

- [ ] **Step 2: Confirm tests fail**

Run from repo root: `(cd dashboard && pnpm vitest run tests/transition-actions.test.ts 2>&1 | tail -10)`
Expected: error like `Cannot find module '@/app/actions/transition-order'`.

- [ ] **Step 3: Implement the Server Actions**

Create `dashboard/app/actions/transition-order.ts` with this exact content:

```typescript
'use server';

import { revalidatePath } from 'next/cache';
import { z } from 'zod';

import {
  markPreparingApi,
  markReadyApi,
  markCompletedApi,
} from '@/lib/api/orders';

const InputSchema = z.object({
  call_sid: z.string().min(1),
});

export type TransitionActionResult =
  | { success: true }
  | { success: false; error: string };

/**
 * Server Actions for the kitchen workflow transitions, mirroring the
 * existing cancelOrder action shape.
 *
 * Each action validates input, calls the corresponding FastAPI endpoint
 * via the API client, revalidates the orders feed + the order's detail
 * page on success, and returns a typed discriminated union.
 *
 * Race note: the backend is the single writer for these transitions
 * (no AI-side races post-call). The dashboard relies on Firestore
 * onSnapshot to reflect the new state in addition to revalidation.
 */

async function runTransition(
  input: unknown,
  apiCall: (callSid: string) => Promise<{ success: boolean; error?: string }>,
): Promise<TransitionActionResult> {
  const parsed = InputSchema.safeParse(input);
  if (!parsed.success) {
    return { success: false, error: 'Invalid input' };
  }

  const result = await apiCall(parsed.data.call_sid);
  if (!result.success) {
    return { success: false, error: result.error ?? 'Unknown error' };
  }

  revalidatePath('/');
  revalidatePath(`/orders/${parsed.data.call_sid}`);
  return { success: true };
}

export async function markPreparingAction(
  input: unknown,
): Promise<TransitionActionResult> {
  return runTransition(input, markPreparingApi);
}

export async function markReadyAction(
  input: unknown,
): Promise<TransitionActionResult> {
  return runTransition(input, markReadyApi);
}

export async function markCompletedAction(
  input: unknown,
): Promise<TransitionActionResult> {
  return runTransition(input, markCompletedApi);
}
```

- [ ] **Step 4: Run the new tests**

Run from repo root: `(cd dashboard && pnpm vitest run tests/transition-actions.test.ts 2>&1 | tail -15)`
Expected: 9 PASSED.

- [ ] **Step 5: Run the full dashboard suite + typecheck**

Run from repo root: `(cd dashboard && pnpm vitest run && pnpm tsc --noEmit)`
Expected: all green; TS clean.

- [ ] **Step 6: Commit**

```bash
git add dashboard/app/actions/transition-order.ts dashboard/tests/transition-actions.test.ts
git commit -m "Add transition Server Actions + 9 vitest unit tests (#111)

Three new Server Actions — markPreparingAction, markReadyAction,
markCompletedAction — mirror the existing cancelOrder action pattern.
Each validates input via Zod, calls the corresponding API client
function, revalidates the orders feed + the order's detail page on
success, and returns a typed discriminated union.

A small runTransition helper de-dupes the validate/call/revalidate
boilerplate across the three actions.

9 vitest tests cover success/failure/invalid-input per action with
mocked API client + mocked next/cache."
```

---

## Task 3: `TransitionButton` component + tests

**Files:**
- Create: `dashboard/components/orders/transition-button.tsx`
- Create: `dashboard/tests/transition-button.test.tsx`

- [ ] **Step 1: Write the failing test file**

Create `dashboard/tests/transition-button.test.tsx` with this exact content:

```typescript
// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the Server Actions.
vi.mock('@/app/actions/transition-order', () => ({
  markPreparingAction: vi.fn(),
  markReadyAction: vi.fn(),
  markCompletedAction: vi.fn(),
}));

// Mock sonner toast.
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import {
  markPreparingAction,
  markReadyAction,
  markCompletedAction,
} from '@/app/actions/transition-order';
import { toast } from 'sonner';

import { TransitionButton } from '@/components/orders/transition-button';
import type { Order, OrderStatus } from '@/lib/schemas/order';

function makeOrder(status: OrderStatus): Order {
  return {
    call_sid: 'CA1234ABCD',
    caller_phone: null,
    restaurant_id: 'r',
    items: [],
    order_type: 'pickup',
    delivery_address: null,
    status,
    created_at: new Date(),
    confirmed_at: new Date(),
    subtotal: 0,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

it('renders nothing for in_progress orders', () => {
  const { container } = render(<TransitionButton order={makeOrder('in_progress')} />);
  expect(container).toBeEmptyDOMElement();
});

it('renders nothing for completed orders', () => {
  const { container } = render(<TransitionButton order={makeOrder('completed')} />);
  expect(container).toBeEmptyDOMElement();
});

it('renders nothing for cancelled orders', () => {
  const { container } = render(<TransitionButton order={makeOrder('cancelled')} />);
  expect(container).toBeEmptyDOMElement();
});

it('renders Start Preparing for confirmed orders and calls markPreparingAction on click', async () => {
  vi.mocked(markPreparingAction).mockResolvedValueOnce({ success: true });
  render(<TransitionButton order={makeOrder('confirmed')} />);

  const button = screen.getByRole('button', { name: /start preparing/i });
  fireEvent.click(button);

  await waitFor(() => {
    expect(markPreparingAction).toHaveBeenCalledWith({ call_sid: 'CA1234ABCD' });
  });
  await waitFor(() => {
    expect(toast.success).toHaveBeenCalled();
  });
});

it('renders Mark Ready for preparing orders and calls markReadyAction on click', async () => {
  vi.mocked(markReadyAction).mockResolvedValueOnce({ success: true });
  render(<TransitionButton order={makeOrder('preparing')} />);

  const button = screen.getByRole('button', { name: /mark ready/i });
  fireEvent.click(button);

  await waitFor(() => {
    expect(markReadyAction).toHaveBeenCalledWith({ call_sid: 'CA1234ABCD' });
  });
});

it('renders Mark Completed for ready orders and calls markCompletedAction on click', async () => {
  vi.mocked(markCompletedAction).mockResolvedValueOnce({ success: true });
  render(<TransitionButton order={makeOrder('ready')} />);

  const button = screen.getByRole('button', { name: /mark completed/i });
  fireEvent.click(button);

  await waitFor(() => {
    expect(markCompletedAction).toHaveBeenCalledWith({ call_sid: 'CA1234ABCD' });
  });
});

it('shows error toast when the action returns failure', async () => {
  vi.mocked(markPreparingAction).mockResolvedValueOnce({
    success: false,
    error: 'order not found',
  });
  render(<TransitionButton order={makeOrder('confirmed')} />);

  fireEvent.click(screen.getByRole('button', { name: /start preparing/i }));

  await waitFor(() => {
    expect(toast.error).toHaveBeenCalledWith('order not found');
  });
  expect(toast.success).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Confirm tests fail**

Run from repo root: `(cd dashboard && pnpm vitest run tests/transition-button.test.tsx 2>&1 | tail -10)`
Expected: error like `Cannot find module '@/components/orders/transition-button'`.

- [ ] **Step 3: Implement the component**

Create `dashboard/components/orders/transition-button.tsx` with this exact content:

```typescript
'use client';

import { useTransition } from 'react';
import { toast } from 'sonner';

import {
  markPreparingAction,
  markReadyAction,
  markCompletedAction,
  type TransitionActionResult,
} from '@/app/actions/transition-order';
import { Button } from '@/components/ui/button';
import { type Order, orderShortId } from '@/lib/schemas/order';

type TransitionConfig = {
  label: string;
  pendingLabel: string;
  variant: 'default' | 'outline';
  successMessage: string;
  action: (input: { call_sid: string }) => Promise<TransitionActionResult>;
};

/**
 * Status-aware action button. Renders the next-action button for orders
 * in confirmed/preparing/ready; renders nothing for terminal or
 * not-yet-confirmed orders.
 *
 * No confirmation dialog — kitchen wants single-tap speed. Cancel
 * (which IS destructive) keeps its own dialog in CancelOrderButton.
 */
export function TransitionButton({ order }: { order: Order }) {
  const config = configFor(order);
  if (!config) return null;

  return <ActiveButton order={order} config={config} />;
}

function configFor(order: Order): TransitionConfig | null {
  switch (order.status) {
    case 'confirmed':
      return {
        label: 'Start Preparing',
        pendingLabel: 'Starting…',
        variant: 'default',
        successMessage: `Order ${orderShortId(order)} is now preparing`,
        action: (input) => markPreparingAction(input),
      };
    case 'preparing':
      return {
        label: 'Mark Ready',
        pendingLabel: 'Marking…',
        variant: 'default',
        successMessage: `Order ${orderShortId(order)} is ready`,
        action: (input) => markReadyAction(input),
      };
    case 'ready':
      return {
        label: 'Mark Completed',
        pendingLabel: 'Completing…',
        variant: 'outline',
        successMessage: `Order ${orderShortId(order)} is completed`,
        action: (input) => markCompletedAction(input),
      };
    case 'in_progress':
    case 'completed':
    case 'cancelled':
      return null;
  }
}

function ActiveButton({
  order,
  config,
}: {
  order: Order;
  config: TransitionConfig;
}) {
  const [isPending, startTransition] = useTransition();

  function onClick() {
    startTransition(async () => {
      const result = await config.action({ call_sid: order.call_sid });
      if (result.success) {
        toast.success(config.successMessage);
      } else {
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

- [ ] **Step 4: Run the new tests**

Run from repo root: `(cd dashboard && pnpm vitest run tests/transition-button.test.tsx 2>&1 | tail -15)`
Expected: 7 PASSED.

- [ ] **Step 5: Run the full dashboard suite + typecheck**

Run from repo root: `(cd dashboard && pnpm vitest run && pnpm tsc --noEmit)`
Expected: all green; TS clean.

- [ ] **Step 6: Commit**

```bash
git add dashboard/components/orders/transition-button.tsx dashboard/tests/transition-button.test.tsx
git commit -m "Add TransitionButton component + 7 vitest tests (#111)

Single status-aware button: renders the next-action button for orders
in confirmed/preparing/ready; renders nothing for terminal or
not-yet-confirmed orders. Wraps the corresponding Server Action with
useTransition + sonner toast feedback. No confirmation dialog for
forward transitions — kitchen wants single-tap speed.

7 vitest tests cover all 6 status branches + error toast flow."
```

---

## Task 4: Wire `TransitionButton` into `OrdersTable` + `OrderDetail` + `FilterTabs`

This task is one logical chunk: three small UI integrations. Single commit at the end.

**Files:**
- Modify: `dashboard/components/orders/orders-table.tsx` (add Action column)
- Modify: `dashboard/components/orders/order-detail.tsx` (render button + fix headerTimestamp + broaden cancel render condition)
- Modify: `dashboard/components/orders/filter-tabs.tsx` (extend TABS array)

- [ ] **Step 1: `OrdersTable` — add Action column**

In `dashboard/components/orders/orders-table.tsx`:

#### Step 1a — Add the import

Find the existing imports near the top:

```typescript
import { LocalTime } from '@/components/shared/local-time';
import { StatusBadge } from '@/components/orders/status-badge';
```

Add `TransitionButton`:

```typescript
import { LocalTime } from '@/components/shared/local-time';
import { StatusBadge } from '@/components/orders/status-badge';
import { TransitionButton } from '@/components/orders/transition-button';
```

#### Step 1b — Add the Action column header

Find the existing `<thead>` block (around line 25):

```typescript
        <thead className="bg-muted/40 text-muted-foreground">
          <tr>
            <Th className="w-28">Order</Th>
            <Th className="w-24">Time</Th>
            <Th>Items</Th>
            <Th className="w-32 text-right">Subtotal</Th>
            <Th className="w-32">Status</Th>
          </tr>
        </thead>
```

Replace with (add a 6th column header):

```typescript
        <thead className="bg-muted/40 text-muted-foreground">
          <tr>
            <Th className="w-28">Order</Th>
            <Th className="w-24">Time</Th>
            <Th>Items</Th>
            <Th className="w-32 text-right">Subtotal</Th>
            <Th className="w-32">Status</Th>
            <Th className="w-36">Action</Th>
          </tr>
        </thead>
```

#### Step 1c — Render the button in each row

Find the `<Td>` block at the end of `OrderRow` (the Status column, around line 108-112):

```typescript
      <Td>
        <Link href={`/orders/${encodeURIComponent(order.call_sid)}`}>
          <StatusBadge status={order.status} />
        </Link>
      </Td>
    </tr>
  );
}
```

Replace with (add a 6th `<Td>` for the action button — note the cell is OUTSIDE the `<Link>`, since clicking the button should NOT navigate to the detail page):

```typescript
      <Td>
        <Link href={`/orders/${encodeURIComponent(order.call_sid)}`}>
          <StatusBadge status={order.status} />
        </Link>
      </Td>
      <Td>
        <TransitionButton order={order} />
      </Td>
    </tr>
  );
}
```

- [ ] **Step 2: `OrderDetail` — render button + fix headerTimestamp + broaden cancel condition**

In `dashboard/components/orders/order-detail.tsx`:

#### Step 2a — Add the import

Find the existing imports:

```typescript
import { CancelOrderButton } from '@/components/orders/cancel-order-button';
import { StatusBadge } from '@/components/orders/status-badge';
```

Add `TransitionButton`:

```typescript
import { CancelOrderButton } from '@/components/orders/cancel-order-button';
import { StatusBadge } from '@/components/orders/status-badge';
import { TransitionButton } from '@/components/orders/transition-button';
```

#### Step 2b — Render the TransitionButton + broaden cancel render condition

Find the existing render block at the bottom of `OrderDetail` (around line 30-34):

```typescript
      {order.status === 'confirmed' && (
        <div className="pt-2">
          <CancelOrderButton callSid={order.call_sid} />
        </div>
      )}
```

Replace with (broaden cancel condition + add TransitionButton to the same actions row):

```typescript
      {(order.status === 'confirmed' ||
        order.status === 'preparing' ||
        order.status === 'ready') && (
        <div className="flex flex-wrap items-center gap-2 pt-2">
          <TransitionButton order={order} />
          <CancelOrderButton callSid={order.call_sid} />
        </div>
      )}
```

#### Step 2c — Fix `headerTimestamp` for the new statuses with exhaustive `never` default

Find the existing `headerTimestamp` function (around line 57-80):

```typescript
function headerTimestamp(order: Order): React.ReactNode {
  switch (order.status) {
    case 'confirmed':
      return order.confirmed_at ? (
        <>
          Confirmed <LocalTime date={order.confirmed_at} mode="absolute" />
        </>
      ) : (
        <>Confirmed</>
      );
    case 'cancelled':
      return (
        <>
          Cancelled <LocalTime date={order.created_at} mode="absolute" />
        </>
      );
    case 'in_progress':
      return (
        <>
          Started <LocalTime date={order.created_at} mode="absolute" />
        </>
      );
  }
}
```

Replace with (add the 3 new cases + exhaustive `never` default that forces a TS error if a future status is added):

```typescript
function headerTimestamp(order: Order): React.ReactNode {
  switch (order.status) {
    case 'in_progress':
      return (
        <>
          Started <LocalTime date={order.created_at} mode="absolute" />
        </>
      );
    case 'confirmed':
      return order.confirmed_at ? (
        <>
          Confirmed <LocalTime date={order.confirmed_at} mode="absolute" />
        </>
      ) : (
        <>Confirmed</>
      );
    case 'preparing':
      return order.preparing_at ? (
        <>
          Started prep <LocalTime date={order.preparing_at} mode="absolute" />
        </>
      ) : (
        <>Preparing</>
      );
    case 'ready':
      return order.ready_at ? (
        <>
          Ready <LocalTime date={order.ready_at} mode="absolute" />
        </>
      ) : (
        <>Ready</>
      );
    case 'completed':
      return order.completed_at ? (
        <>
          Completed <LocalTime date={order.completed_at} mode="absolute" />
        </>
      ) : (
        <>Completed</>
      );
    case 'cancelled':
      return order.cancelled_at ? (
        <>
          Cancelled <LocalTime date={order.cancelled_at} mode="absolute" />
        </>
      ) : (
        <>
          Cancelled <LocalTime date={order.created_at} mode="absolute" />
        </>
      );
    default: {
      // Exhaustiveness check: if a new OrderStatus is added without a
      // case here, TypeScript will error on this line.
      const _exhaustive: never = order.status;
      return _exhaustive;
    }
  }
}
```

- [ ] **Step 3: `FilterTabs` — extend the TABS array**

In `dashboard/components/orders/filter-tabs.tsx`, find the existing `TABS` array (around line 14-19):

```typescript
const TABS: Tab[] = [
  { key: 'all', label: 'All', href: '/' },
  { key: 'in_progress', label: 'Live', href: '/?status=in_progress' },
  { key: 'confirmed', label: 'Confirmed', href: '/?status=confirmed' },
  { key: 'cancelled', label: 'Cancelled', href: '/?status=cancelled' },
];
```

Replace with (insert the 3 new entries between `confirmed` and `cancelled` to match the lifecycle order):

```typescript
const TABS: Tab[] = [
  { key: 'all', label: 'All', href: '/' },
  { key: 'in_progress', label: 'Live', href: '/?status=in_progress' },
  { key: 'confirmed', label: 'Confirmed', href: '/?status=confirmed' },
  { key: 'preparing', label: 'Preparing', href: '/?status=preparing' },
  { key: 'ready', label: 'Ready', href: '/?status=ready' },
  { key: 'completed', label: 'Completed', href: '/?status=completed' },
  { key: 'cancelled', label: 'Cancelled', href: '/?status=cancelled' },
];
```

- [ ] **Step 4: Run the full dashboard suite + typecheck**

Run from repo root: `(cd dashboard && pnpm vitest run && pnpm tsc --noEmit)`
Expected: all green; TS clean.

If TS errors anywhere because the `headerTimestamp`'s `never` assertion catches a previously-untested branch, that's the exhaustiveness mechanism working — investigate. Likely the existing tests still pass because they use the old surface; the new surface is just additive.

- [ ] **Step 5: Commit**

```bash
git add dashboard/components/orders/orders-table.tsx dashboard/components/orders/order-detail.tsx dashboard/components/orders/filter-tabs.tsx
git commit -m "Wire TransitionButton + grow filter tabs + fix headerTimestamp (#111)

Three coordinated UI integrations:

1. OrdersTable gains a 6th right-most 'Action' column rendering
   <TransitionButton/> per row. The cell sits OUTSIDE the row's
   <Link> wrapper so clicking the button doesn't navigate.

2. OrderDetail renders <TransitionButton/> next to <CancelOrderButton/>
   in the bottom actions area. Cancel render condition broadens from
   'confirmed' alone to 'confirmed|preparing|ready' (B1's cancel
   endpoint accepts any pre-completed source state).

3. OrderDetail's headerTimestamp switch gains cases for the 3 new
   statuses, each showing the relevant per-transition timestamp.
   Adds an exhaustive 'never' default so future OrderStatus additions
   force a TypeScript error here.

4. FilterTabs grows from 4 to 7 entries (additive; no renames):
   All | Live | Confirmed | Preparing | Ready | Completed | Cancelled.
   URL pattern unchanged."
```

---

## Task 5: Sprint 2.2 (#5) checklist update + final review + push + PR

- [ ] **Step 1: Sanity sweep across both stacks**

Run from repo root:

```bash
(cd dashboard && pnpm tsc --noEmit && pnpm vitest run)
python -m pytest tests/ 2>&1 | tail -5
```

Expected: dashboard TS clean + dashboard vitest green; backend full suite green (no backend changes in this branch but worth a sanity run).

- [ ] **Step 2: Skim the cumulative diff**

```bash
git log master..HEAD --oneline
git diff master..HEAD --stat
```

Confirm no surprise file changes — only the 8 paths in the File Structure table plus the spec/plan docs.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/111-kitchen-workflow-ui
```

```bash
gh pr create --repo tsuki-works/niko --base master --head feat/111-kitchen-workflow-ui \
  --title "Kitchen workflow UI (B3 of B, #111)" \
  --body-file - <<'EOF'
## Summary
- New `TransitionButton` component (`dashboard/components/orders/transition-button.tsx`) — single status-aware button per row + per detail page. Renders "Start Preparing" / "Mark Ready" / "Mark Completed" based on the order's current status; renders nothing for terminal/in-progress states. Single-tap speed (no confirmation dialog) — cancel keeps its destructive dialog.
- Three new Server Actions (`dashboard/app/actions/transition-order.ts`) and three new API client functions (`dashboard/lib/api/orders.ts`) — thin wrappers around `POST /orders/{call_sid}/{transition}`, mirroring the existing `cancelOrder` / `cancelOrderApi` pattern.
- `OrdersTable` grows from 5 to 6 columns with a right-most "Action" column.
- `OrderDetail` renders the button alongside `<CancelOrderButton>`; cancel render condition broadens from `confirmed` alone to `confirmed | preparing | ready` (matches B1's cancel endpoint contract).
- `OrderDetail`'s `headerTimestamp` switch gains cases for the 3 new statuses + an exhaustive `never` default — future enum additions force a TypeScript error at compile time. (Closes the B1 follow-up flagged in #108's review.)
- `FilterTabs` grows from 4 to 7 entries (additive; no renames).
- 9 vitest tests for the Server Actions; 7 vitest tests for `TransitionButton`.

## Linked issue
Closes #111. Final sub-project on parent feature B (order queueing + restaurant notifications). B1 (#108) shipped the lifecycle data layer; B2 (#110) shipped the tablet alert experience. With B3 merged, the entire parent feature B is done — and Sprint 2.2 (#5) reaches all 6 deliverables.

## Spec & plan
- Spec: `docs/superpowers/specs/2026-04-29-kitchen-workflow-ui-design.md`
- Plan: `docs/superpowers/plans/2026-04-29-kitchen-workflow-ui.md`

## Test plan
- [x] Vitest unit tests for Server Actions (`pnpm vitest run tests/transition-actions.test.ts`): **9/9 PASSED**
- [x] Vitest unit tests for `TransitionButton` (`pnpm vitest run tests/transition-button.test.tsx`): **7/7 PASSED**
- [x] Full dashboard vitest suite (`pnpm vitest run`): green
- [x] Dashboard typecheck (`pnpm tsc --noEmit`): clean
- [x] Backend full suite (`pytest tests/`): green (no backend changes; sanity run)
- [ ] **Manual smoke (pre-merge)** — on a real tablet (or Chrome dev tools mobile mode):
  - Place a test order. Verify the row shows status "Confirmed" + a "Start Preparing" button.
  - Tap "Start Preparing" → row updates to "Preparing" within ~500ms; toast confirms; button now reads "Mark Ready".
  - Tap "Mark Ready" → status "Ready"; button reads "Mark Completed".
  - Tap "Mark Completed" → status "Completed", button disappears.
  - Place another order, walk to "Preparing", then tap "Cancel order" on the detail page — verify it transitions to "Cancelled".
  - Visit `?status=preparing`, `?status=ready`, `?status=completed` — verify each filter shows the right orders.
  - Verify the detail-page header timestamp shows the right transition timestamp for each status.

## Notes
- **No backend changes.** The endpoints + lifecycle were shipped in B1 (#108). This PR is purely the dashboard wiring.
- **No optimistic updates.** The `onSnapshot` live feed reflects transitions within ~100-500ms; sonner toast surfaces success/error. `useOptimistic` polish is a Sprint 2.4 concern.
- **No undo for accidental forward transitions.** Kitchen can `cancel_order` from any pre-completed state if they need to off-ramp.
- The B2 audible/visual alert from #110 still fires on new orders entering the live feed — `useNewOrderAlert` is keyed off the `orders` array, not on the status transitions.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

- [ ] **Step 4: Surface the PR URL**

The `gh pr create` output is the URL — relay it.

---

## Self-review

**Spec coverage:**
- (1) `TransitionButton` component (status-aware) → Task 3 ✓
- (2) Filter tabs grow from 4 to 7 → Task 4 step 3 ✓
- (3) Server Actions (3 new) → Task 2 ✓
- (4) API client functions (3 new) → Task 1 ✓
- (5) `OrdersTable` integration (Action column) → Task 4 step 1 ✓
- (6) `OrderDetail` integration (button + broaden cancel + headerTimestamp fix) → Task 4 step 2 ✓
- 7 vitest tests for `TransitionButton` → Task 3 ✓
- 9 vitest tests for Server Actions → Task 2 ✓
- Manual smoke test → Task 5 PR description ✓

**Placeholder scan:** no TBDs. Manual smoke checklist in PR description is intentional (user action, not automated step).

**Type consistency:**
- `TransitionResult` (API client) and `TransitionActionResult` (Server Action) types are distinct but consistent shape — discriminated union with `success: true` / `success: false; error: string`. Server Action returns `{success: true}` (no order, only success flag) per the cancel pattern.
- `TransitionConfig` type local to `TransitionButton`, consistent with how it's consumed.
- Action function signatures `(input: { call_sid: string }) => Promise<TransitionActionResult>` consistent in component (`config.action`) and tests (`expect(markPreparingAction).toHaveBeenCalledWith({call_sid: 'CA1234ABCD'})`).
- `OrderStatus` enum values consistent across switch cases in `headerTimestamp`, `configFor`, and tests.

**One ambiguity left for the implementer:** the `Th className="w-36"` width for the Action column in Task 4 Step 1b is a guess based on existing column widths. If the button overflows or the column looks too narrow at iPad portrait, adjust. Not worth pinning in advance.
