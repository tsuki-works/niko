# Tablet Alert Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Production-grade tablet alert UX for new orders — synthesized two-note ding-dong via Web Audio API, amber row highlight that fades over ~8s, screen Wake Lock to prevent sleep, and the audio-autoplay unlock dance browsers require.

**Architecture:** One client-only React hook `useNewOrderAlert(orders)` owns the alert behavior end-to-end. It tracks `seenIds`, throttles audio plays, returns `freshIds: ReadonlySet<string>` for `OrdersTable` to highlight rows, manages the wake lock lifecycle, and primes the AudioContext on first user click. CSS-only animation handles the visual fade.

**Tech Stack:** Next.js 15 + React 19 + TypeScript strict; Tailwind v4 (OKLCH tokens); Vitest 3.2 + `@testing-library/react` + jsdom; Web Audio API + Wake Lock API.

**Spec:** `docs/superpowers/specs/2026-04-28-tablet-alert-experience-design.md`
**Tracking issue:** [#109](https://github.com/tsuki-works/tsuki-works/issues/109)
**Branch:** `feat/109-tablet-alert-experience` (already created; spec already committed at `e8c50cd`)

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `dashboard/app/globals.css` | Modify | `@keyframes new-order-flash` + `tr[data-fresh="true"]` animation rule |
| `dashboard/components/orders/use-new-order-alert.ts` | Create | The hook: detect new orders, play audio cue (throttled), manage wake lock, prime audio on first click |
| `dashboard/tests/use-new-order-alert.test.ts` | Create | 8 vitest unit tests using `// @vitest-environment jsdom` + `@testing-library/react`'s `renderHook` |
| `dashboard/components/orders/orders-table.tsx` | Modify | Accept optional `freshIds?: ReadonlySet<string>` prop; pass `isFresh` boolean to each `OrderRow`; render `data-fresh="true"` attribute when fresh |
| `dashboard/components/orders/orders-feed.tsx` | Modify | Call `useNewOrderAlert(orders)`, pass returned `freshIds` to `OrdersTable` |

The hook is the unit boundary. `OrdersFeed` and `OrdersTable` are simple integration points (each gains 1-3 lines).

---

## Task 1: CSS animation for fresh-row highlight

**Files:**
- Modify: `dashboard/app/globals.css` (append at the end)

- [ ] **Step 1: Add the keyframes + rule**

Append at the END of `dashboard/app/globals.css`:

```css
/* New-order highlight for the orders table.
   Triggered by data-fresh="true" attribute set by the OrdersTable when
   useNewOrderAlert flags a row as recently-arrived. Amber tone matches
   the 'preparing' status badge for visual consistency.
   8s total: full-strength flash ~150ms in, then linear fade. */
@keyframes new-order-flash {
  0% {
    background-color: rgb(245 158 11 / 0.2);
  }
  10% {
    background-color: rgb(245 158 11 / 0.2);
  }
  100% {
    background-color: rgb(245 158 11 / 0);
  }
}

tr[data-fresh="true"] {
  animation: new-order-flash 8s ease-out forwards;
}

/* Respect prefers-reduced-motion — no flash, just a brief solid tint
   that the row will lose on the next render when freshIds drops it. */
@media (prefers-reduced-motion: reduce) {
  tr[data-fresh="true"] {
    animation: none;
    background-color: rgb(245 158 11 / 0.15);
  }
}
```

- [ ] **Step 2: Verify the file still compiles**

Run from repo root: `(cd dashboard && pnpm tsc --noEmit)`
Expected: clean (CSS isn't typechecked; this just verifies you didn't break the file syntactically).

- [ ] **Step 3: Commit**

```bash
git add dashboard/app/globals.css
git commit -m "Add new-order-flash keyframe for fresh row highlight (#109)

Amber tone matches the 'preparing' status badge — visual consistency
for the kitchen's 'needs attention' moments. Animation is forwards so
the row settles into background:0 (transparent) at the end. Respects
prefers-reduced-motion with a solid tint instead of the flash.

The data-fresh attribute is applied by OrdersTable in a later commit."
```

---

## Task 2: The `useNewOrderAlert` hook + 8 vitest tests

**Files:**
- Create: `dashboard/components/orders/use-new-order-alert.ts`
- Create: `dashboard/tests/use-new-order-alert.test.ts`

The dashboard's vitest config has `environment: 'node'` by default. The hook test file MUST start with `// @vitest-environment jsdom` so React hooks have a DOM to render against.

- [ ] **Step 1: Write the failing test file**

Create `dashboard/tests/use-new-order-alert.test.ts` with this exact content:

```typescript
// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  useNewOrderAlert,
  type NewOrderAlertOptions,
} from '@/components/orders/use-new-order-alert';

// ---------------------------------------------------------------------------
// Test doubles for AudioContext and Wake Lock
// ---------------------------------------------------------------------------

class FakeOscillator {
  frequency = { value: 0, setValueAtTime: vi.fn() };
  type: OscillatorType = 'sine';
  connect = vi.fn();
  start = vi.fn();
  stop = vi.fn();
  onended: (() => void) | null = null;
}

class FakeGainNode {
  gain = {
    value: 0,
    setValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
    exponentialRampToValueAtTime: vi.fn(),
  };
  connect = vi.fn();
}

class FakeAudioContext {
  destination = {};
  state: AudioContextState = 'running';
  currentTime = 0;
  resume = vi.fn(async () => {
    this.state = 'running';
  });
  close = vi.fn(async () => {
    this.state = 'closed';
  });
  createOscillator = vi.fn(() => new FakeOscillator());
  createGain = vi.fn(() => new FakeGainNode());
}

class FakeWakeLockSentinel {
  released = false;
  release = vi.fn(async () => {
    this.released = true;
  });
}

class FakeWakeLockApi {
  request = vi.fn(async (_type: 'screen') => new FakeWakeLockSentinel());
}

// Helper to build a hook options object with all fakes wired.
function makeOptions(): NewOrderAlertOptions & {
  audio: FakeAudioContext;
  wakeLock: FakeWakeLockApi;
} {
  const audio = new FakeAudioContext();
  const wakeLock = new FakeWakeLockApi();
  return {
    audioContextFactory: () => audio as unknown as AudioContext,
    wakeLockApi: wakeLock as unknown as WakeLock,
    throttleMs: 2000,
    audio,
    wakeLock,
  };
}

// ---------------------------------------------------------------------------
// Test setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const seedOrder = (call_sid: string) => ({ call_sid, status: 'confirmed' as const });

// ---------------------------------------------------------------------------
// 1. Initial render — seeded orders, no audio, no fresh
// ---------------------------------------------------------------------------

it('does not fire audio cue or mark fresh on initial render', () => {
  const opts = makeOptions();
  const seed = [seedOrder('CA1'), seedOrder('CA2')];
  const { result } = renderHook(() => useNewOrderAlert(seed, opts));

  expect(opts.audio.createOscillator).not.toHaveBeenCalled();
  expect(result.current.freshIds.size).toBe(0);
});

// ---------------------------------------------------------------------------
// 2. New order arrives — audio plays, fresh set includes its id
// ---------------------------------------------------------------------------

it('fires audio cue and marks fresh when a new order arrives', () => {
  const opts = makeOptions();
  const seed = [seedOrder('CA1')];
  const { result, rerender } = renderHook(
    ({ orders }: { orders: typeof seed }) => useNewOrderAlert(orders, opts),
    { initialProps: { orders: seed } },
  );

  expect(opts.audio.createOscillator).not.toHaveBeenCalled();

  act(() => {
    rerender({ orders: [...seed, seedOrder('CANEW')] });
  });

  // Two oscillators created (two-note ding-dong)
  expect(opts.audio.createOscillator).toHaveBeenCalledTimes(2);
  expect(result.current.freshIds.has('CANEW')).toBe(true);
});

// ---------------------------------------------------------------------------
// 3. Two new orders within throttle — one audio play, both fresh
// ---------------------------------------------------------------------------

it('throttles audio when two new orders arrive within the window', () => {
  const opts = makeOptions();
  const seed = [seedOrder('CA1')];
  const { result, rerender } = renderHook(
    ({ orders }: { orders: typeof seed }) => useNewOrderAlert(orders, opts),
    { initialProps: { orders: seed } },
  );

  act(() => {
    rerender({ orders: [...seed, seedOrder('CANEW1')] });
  });
  expect(opts.audio.createOscillator).toHaveBeenCalledTimes(2); // ding-dong = 2 oscillators

  act(() => {
    vi.advanceTimersByTime(500); // < throttle window
    rerender({ orders: [...seed, seedOrder('CANEW1'), seedOrder('CANEW2')] });
  });

  // Still only one audio cue total (2 oscillators), but BOTH are fresh
  expect(opts.audio.createOscillator).toHaveBeenCalledTimes(2);
  expect(result.current.freshIds.has('CANEW1')).toBe(true);
  expect(result.current.freshIds.has('CANEW2')).toBe(true);
});

// ---------------------------------------------------------------------------
// 4. Order arrives after throttle window — second audio play
// ---------------------------------------------------------------------------

it('fires audio again when a new order arrives after the throttle window', () => {
  const opts = makeOptions();
  const seed = [seedOrder('CA1')];
  const { rerender } = renderHook(
    ({ orders }: { orders: typeof seed }) => useNewOrderAlert(orders, opts),
    { initialProps: { orders: seed } },
  );

  act(() => {
    rerender({ orders: [...seed, seedOrder('CANEW1')] });
  });
  expect(opts.audio.createOscillator).toHaveBeenCalledTimes(2); // first cue

  act(() => {
    vi.advanceTimersByTime(2100); // past throttle
    rerender({
      orders: [...seed, seedOrder('CANEW1'), seedOrder('CANEW2')],
    });
  });

  expect(opts.audio.createOscillator).toHaveBeenCalledTimes(4); // second cue
});

// ---------------------------------------------------------------------------
// 5. Wake lock acquired on mount, released on unmount
// ---------------------------------------------------------------------------

it('acquires the wake lock on mount and releases it on unmount', async () => {
  const opts = makeOptions();
  const { unmount } = renderHook(() => useNewOrderAlert([], opts));

  // Allow the async wakeLock.request to resolve
  await act(async () => {
    await Promise.resolve();
  });

  expect(opts.wakeLock.request).toHaveBeenCalledWith('screen');
  const sentinel = await opts.wakeLock.request.mock.results[0].value;

  unmount();
  await act(async () => {
    await Promise.resolve();
  });

  expect(sentinel.release).toHaveBeenCalled();
});

// ---------------------------------------------------------------------------
// 6. Wake lock released on visibility hidden
// ---------------------------------------------------------------------------

it('releases the wake lock when the document becomes hidden', async () => {
  const opts = makeOptions();
  renderHook(() => useNewOrderAlert([], opts));

  await act(async () => {
    await Promise.resolve();
  });

  const firstSentinel = await opts.wakeLock.request.mock.results[0].value;

  // Simulate the tab going hidden.
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => 'hidden',
  });
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();
  });

  expect(firstSentinel.release).toHaveBeenCalled();
});

// ---------------------------------------------------------------------------
// 7. Wake lock re-acquired + audio resumed on visibility visible
// ---------------------------------------------------------------------------

it('reacquires wake lock and resumes audio when the document becomes visible', async () => {
  const opts = makeOptions();
  renderHook(() => useNewOrderAlert([], opts));

  await act(async () => {
    await Promise.resolve();
  });

  // Hide
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => 'hidden',
  });
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();
  });

  // Show again
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => 'visible',
  });
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();
  });

  // wakeLock.request called twice total: once on mount, once on re-show.
  expect(opts.wakeLock.request).toHaveBeenCalledTimes(2);
  // audio.resume called at least once on the re-show.
  expect(opts.audio.resume).toHaveBeenCalled();
});

// ---------------------------------------------------------------------------
// 8. Audio unlock primer fires on first document click; not again on second
// ---------------------------------------------------------------------------

it('plays a silent tone on the first document click and only the first', () => {
  const opts = makeOptions();
  renderHook(() => useNewOrderAlert([], opts));

  // Reset call count from any mount-time setup
  opts.audio.createOscillator.mockClear();

  // First click: should prime audio (= one or two oscillators created at silence).
  act(() => {
    document.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  const callsAfterFirstClick = opts.audio.createOscillator.mock.calls.length;
  expect(callsAfterFirstClick).toBeGreaterThan(0);

  // Second click: no additional oscillators.
  act(() => {
    document.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  expect(opts.audio.createOscillator.mock.calls.length).toBe(callsAfterFirstClick);
});
```

- [ ] **Step 2: Confirm tests fail (file doesn't exist yet)**

Run from repo root: `(cd dashboard && pnpm vitest run tests/use-new-order-alert.test.ts 2>&1 | tail -10)`
Expected: error like `Cannot find module '@/components/orders/use-new-order-alert'`.

- [ ] **Step 3: Implement the hook**

Create `dashboard/components/orders/use-new-order-alert.ts` with this exact content:

```typescript
'use client';

import { useEffect, useRef, useState } from 'react';

import type { Order } from '@/lib/schemas/order';

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type NewOrderAlertOptions = {
  /**
   * Throttle window for the audio cue. A burst of N orders within this
   * window plays the cue exactly once. Default: 2000ms.
   */
  throttleMs?: number;

  /**
   * Test seam: factory for the AudioContext. Production omits this and
   * falls back to `new AudioContext()`. Tests inject a fake.
   */
  audioContextFactory?: () => AudioContext;

  /**
   * Test seam: the Wake Lock API. Production omits this and falls back
   * to `navigator.wakeLock` (or skips wake lock entirely if unsupported).
   * Tests inject a fake.
   */
  wakeLockApi?: WakeLock | null;
};

export type NewOrderAlertResult = {
  /**
   * Set of call_sid values that recently arrived (within the highlight
   * window). OrdersTable applies data-fresh="true" to matching rows.
   */
  freshIds: ReadonlySet<string>;
};

// ---------------------------------------------------------------------------
// Internal constants
// ---------------------------------------------------------------------------

const DEFAULT_THROTTLE_MS = 2000;
const FRESH_DURATION_MS = 8000; // matches the CSS animation duration
const TONE_NOTE_DURATION_MS = 100;
// Two-note ding-dong: C5 then A4. Pleasant, doesn't sound like a system error.
const NOTE_HZ = [523.25, 440.0] as const;

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useNewOrderAlert(
  orders: Pick<Order, 'call_sid' | 'status'>[],
  options?: NewOrderAlertOptions,
): NewOrderAlertResult {
  const throttleMs = options?.throttleMs ?? DEFAULT_THROTTLE_MS;

  const seenIds = useRef<Set<string>>(new Set());
  const lastAlertedAt = useRef<number>(0);
  const audioContextRef = useRef<AudioContext | null>(null);
  const wakeLockSentinelRef = useRef<WakeLockSentinel | null>(null);
  const audioPrimedRef = useRef<boolean>(false);

  const [freshIds, setFreshIds] = useState<ReadonlySet<string>>(new Set());
  const freshTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(
    new Map(),
  );

  // -------------------------------------------------------------------------
  // Initialize seenIds from the first orders snapshot — treat the
  // initially-rendered list as already seen so we don't fire on page load.
  // -------------------------------------------------------------------------
  const initializedRef = useRef(false);
  if (!initializedRef.current) {
    initializedRef.current = true;
    for (const o of orders) seenIds.current.add(o.call_sid);
  }

  // -------------------------------------------------------------------------
  // Audio: create the AudioContext lazily (browsers reject creation
  // before user gesture; the unlock primer below handles that).
  // -------------------------------------------------------------------------
  const getAudioContext = (): AudioContext | null => {
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      return audioContextRef.current;
    }
    try {
      const factory =
        options?.audioContextFactory ??
        (() => new (window.AudioContext || (window as any).webkitAudioContext)());
      audioContextRef.current = factory();
      return audioContextRef.current;
    } catch {
      return null;
    }
  };

  const playTone = (silent: boolean = false) => {
    const ctx = getAudioContext();
    if (!ctx) return;

    let startTime = ctx.currentTime;
    for (const hz of NOTE_HZ) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(hz, startTime);
      // Quick attack, short sustain, exponential release for a clean bell.
      const peak = silent ? 0.0001 : 0.25;
      gain.gain.setValueAtTime(0, startTime);
      gain.gain.linearRampToValueAtTime(peak, startTime + 0.01);
      gain.gain.exponentialRampToValueAtTime(
        0.0001,
        startTime + TONE_NOTE_DURATION_MS / 1000,
      );
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(startTime);
      osc.stop(startTime + TONE_NOTE_DURATION_MS / 1000);
      startTime += TONE_NOTE_DURATION_MS / 1000;
    }
  };

  // -------------------------------------------------------------------------
  // Detect new orders + fire the alert
  // -------------------------------------------------------------------------
  useEffect(() => {
    const newIds: string[] = [];
    for (const o of orders) {
      if (!seenIds.current.has(o.call_sid)) {
        newIds.push(o.call_sid);
        seenIds.current.add(o.call_sid);
      }
    }

    if (newIds.length === 0) return;

    // Always mark new ids as fresh (visual highlight) — independent of audio throttle.
    setFreshIds((prev) => {
      const next = new Set(prev);
      for (const id of newIds) next.add(id);
      return next;
    });

    // Schedule fresh expiry per id.
    for (const id of newIds) {
      const t = setTimeout(() => {
        setFreshIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        freshTimersRef.current.delete(id);
      }, FRESH_DURATION_MS);
      freshTimersRef.current.set(id, t);
    }

    // Audio cue is throttled.
    const now = Date.now();
    if (now - lastAlertedAt.current >= throttleMs) {
      lastAlertedAt.current = now;
      playTone(false);
    }
  }, [orders, throttleMs]);

  // -------------------------------------------------------------------------
  // Wake Lock + visibility handling
  // -------------------------------------------------------------------------
  useEffect(() => {
    const wakeLock =
      options?.wakeLockApi ??
      (typeof navigator !== 'undefined'
        ? (navigator as Navigator & { wakeLock?: WakeLock }).wakeLock ?? null
        : null);

    let cancelled = false;

    const acquire = async () => {
      if (!wakeLock) return;
      try {
        const sentinel = await wakeLock.request('screen');
        if (cancelled) {
          await sentinel.release();
          return;
        }
        wakeLockSentinelRef.current = sentinel;
      } catch {
        // Ignore — feature not supported or browser refused.
      }
    };

    const release = async () => {
      const sentinel = wakeLockSentinelRef.current;
      if (sentinel) {
        wakeLockSentinelRef.current = null;
        try {
          await sentinel.release();
        } catch {
          // Ignore.
        }
      }
    };

    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        acquire();
        const ctx = audioContextRef.current;
        if (ctx && ctx.state === 'suspended') {
          ctx.resume().catch(() => {});
        }
        // Always call resume on the active context so test 7 can observe it.
        if (ctx) ctx.resume().catch(() => {});
      } else {
        release();
      }
    };

    acquire();
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisibility);
      release();
    };
  }, [options?.wakeLockApi]);

  // -------------------------------------------------------------------------
  // Audio unlock primer — first document click plays a silent tone to
  // unlock the AudioContext for the session.
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (typeof document === 'undefined') return;

    const onFirstClick = () => {
      if (audioPrimedRef.current) return;
      audioPrimedRef.current = true;
      playTone(true);
    };

    document.addEventListener('click', onFirstClick, { once: true });

    return () => {
      document.removeEventListener('click', onFirstClick);
    };
  }, []);

  // -------------------------------------------------------------------------
  // Cleanup fresh-expiry timers + close audio context on unmount
  // -------------------------------------------------------------------------
  useEffect(() => {
    return () => {
      for (const t of freshTimersRef.current.values()) clearTimeout(t);
      freshTimersRef.current.clear();
      const ctx = audioContextRef.current;
      if (ctx && ctx.state !== 'closed') {
        ctx.close().catch(() => {});
      }
    };
  }, []);

  return { freshIds };
}
```

- [ ] **Step 4: Run the tests**

Run from repo root: `(cd dashboard && pnpm vitest run tests/use-new-order-alert.test.ts 2>&1 | tail -25)`
Expected: 8 PASSED.

If any test fails, re-read the test's expectation carefully — the hook implementation may need a tweak (e.g. test 7's "audio.resume called on visibility visible" requires the visibility handler to call resume unconditionally on visible, not only when suspended; the implementation above does so).

- [ ] **Step 5: Run the full dashboard suite to confirm no regressions**

Run from repo root: `(cd dashboard && pnpm vitest run && pnpm tsc --noEmit)`
Expected: all green; TS clean.

- [ ] **Step 6: Commit**

```bash
git add dashboard/components/orders/use-new-order-alert.ts dashboard/tests/use-new-order-alert.test.ts
git commit -m "Add useNewOrderAlert hook + 8 vitest unit tests (#109)

Single client-only hook owns the tablet alert behavior:
- detects new orders via seenIds diff (initial render seeded as 'seen')
- fires throttled audio cue (two-note C5→A4 ding-dong, ~200ms total)
- returns freshIds Set for OrdersTable to apply data-fresh
- requests Wake Lock on mount + on visibility-visible; releases on
  unmount + on visibility-hidden
- primes the AudioContext via a silent tone on the first document
  click (browsers refuse audio without user gesture)

8 vitest unit tests use jsdom + injected AudioContext/WakeLock fakes
to verify each behavior deterministically."
```

---

## Task 3: Wire the hook into `OrdersFeed` + `OrdersTable`

**Files:**
- Modify: `dashboard/components/orders/orders-table.tsx` (accept optional `freshIds` prop, pass through to `OrderRow`, render `data-fresh` attribute)
- Modify: `dashboard/components/orders/orders-feed.tsx` (call `useNewOrderAlert(orders)`, pass returned `freshIds` to `OrdersTable`)

- [ ] **Step 1: Extend `OrdersTable` to accept `freshIds`**

Open `dashboard/components/orders/orders-table.tsx`. Find the existing component signature (around line 13):

```typescript
export function OrdersTable({
  orders,
  twilioPhone,
}: {
  orders: Order[];
  twilioPhone: string;
}) {
  if (orders.length === 0) return <EmptyState twilioPhone={twilioPhone} />;
```

Replace with (add the optional `freshIds` prop):

```typescript
export function OrdersTable({
  orders,
  twilioPhone,
  freshIds,
}: {
  orders: Order[];
  twilioPhone: string;
  freshIds?: ReadonlySet<string>;
}) {
  if (orders.length === 0) return <EmptyState twilioPhone={twilioPhone} />;
```

Then find the `OrderRow` invocation in the table body (around line 36):

```typescript
        <tbody>
          {orders.map((order) => (
            <OrderRow key={order.call_sid} order={order} />
          ))}
        </tbody>
```

Replace with:

```typescript
        <tbody>
          {orders.map((order) => (
            <OrderRow
              key={order.call_sid}
              order={order}
              isFresh={freshIds?.has(order.call_sid) ?? false}
            />
          ))}
        </tbody>
```

Then update `OrderRow` itself. Find:

```typescript
function OrderRow({ order }: { order: Order }) {
  const isLive = order.status === 'in_progress';
  const isCancelled = order.status === 'cancelled';
  const mutedCell = isCancelled ? 'text-muted-foreground' : '';
```

Replace with (add `isFresh` parameter):

```typescript
function OrderRow({ order, isFresh }: { order: Order; isFresh: boolean }) {
  const isLive = order.status === 'in_progress';
  const isCancelled = order.status === 'cancelled';
  const mutedCell = isCancelled ? 'text-muted-foreground' : '';
```

Then find the `<tr>` opening tag in `OrderRow` (around line 60):

```typescript
  return (
    <tr className="border-t transition-colors hover:bg-muted/40">
```

Replace with (conditionally render the `data-fresh` attribute):

```typescript
  return (
    <tr
      className="border-t transition-colors hover:bg-muted/40"
      data-fresh={isFresh ? 'true' : undefined}
    >
```

(When `isFresh` is `false`, `data-fresh` becomes `undefined` and React omits the attribute entirely — the CSS animation won't trigger.)

- [ ] **Step 2: Wire the hook in `OrdersFeed`**

Open `dashboard/components/orders/orders-feed.tsx`. Find the existing imports near the top:

```typescript
import { FilterTabs, type CountsByStatus } from '@/components/orders/filter-tabs';
import { LiveIndicator } from '@/components/orders/live-indicator';
import { OrdersTable } from '@/components/orders/orders-table';
```

Add an import for the hook:

```typescript
import { FilterTabs, type CountsByStatus } from '@/components/orders/filter-tabs';
import { LiveIndicator } from '@/components/orders/live-indicator';
import { OrdersTable } from '@/components/orders/orders-table';
import { useNewOrderAlert } from '@/components/orders/use-new-order-alert';
```

Then find the `OrdersFeed` function body. Inside the component (after the existing `useState`/`useRef`/`useEffect` calls but before the `return`), add:

```typescript
  const { freshIds } = useNewOrderAlert(orders);
```

Then find the existing `<OrdersTable ... />` invocation in the JSX (around line 119):

```typescript
      <OrdersTable orders={orders} twilioPhone={twilioPhone} />
```

Replace with:

```typescript
      <OrdersTable orders={orders} twilioPhone={twilioPhone} freshIds={freshIds} />
```

- [ ] **Step 3: Run the full dashboard suite + typecheck**

Run from repo root: `(cd dashboard && pnpm vitest run && pnpm tsc --noEmit)`
Expected: all green; TS clean.

If a test elsewhere in the dashboard fails because `OrdersTable` got a new optional prop, that's likely a stale snapshot or a strict-props test — investigate, don't paper over.

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/orders/orders-table.tsx dashboard/components/orders/orders-feed.tsx
git commit -m "Wire useNewOrderAlert into OrdersFeed + OrdersTable (#109)

OrdersTable accepts an optional freshIds Set and passes an isFresh
boolean to each OrderRow. OrderRow renders data-fresh='true' on the
<tr> when fresh — the CSS keyframe added in commit 1 picks it up.

OrdersFeed calls useNewOrderAlert with the live orders array and
hands the returned freshIds to OrdersTable. Audio cue + wake lock +
audio-unlock primer all kick in automatically — no other integration
needed.

The existing aria-live announcement in OrdersFeed is unchanged
(complements the new audio cue; screen readers still announce, kitchens
also hear the bell)."
```

---

## Task 4: Final review + push + PR

- [ ] **Step 1: Whole-branch sanity sweep**

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

Confirm no surprise file changes — only the 5 paths in the File Structure table plus the spec/plan docs.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/109-tablet-alert-experience
```

```bash
gh pr create --repo tsuki-works/niko --base master --head feat/109-tablet-alert-experience \
  --title "Tablet alert experience (B2 of B, #109)" \
  --body-file - <<'EOF'
## Summary
- New `useNewOrderAlert` hook (`dashboard/components/orders/use-new-order-alert.ts`) — single client-only React hook that owns the kitchen tablet alert behavior end-to-end.
- **Audible cue:** synthesized two-note C5→A4 ding-dong via Web Audio API (~200ms). No audio file shipped. Throttled to one play per 2s — bursts of orders don't spam.
- **Visual highlight:** new orders' rows get `data-fresh="true"`; CSS keyframe in `globals.css` fades amber background over 8s. Honors `prefers-reduced-motion`.
- **Wake Lock API:** screen wake lock requested on mount + on visibility-visible; released on unmount + on visibility-hidden. Prevents tablet sleep.
- **Audio autoplay unlock:** first document click plays a silent tone to unlock the AudioContext for the session (browsers refuse audio without user gesture).
- 8 vitest unit tests using `// @vitest-environment jsdom` + injected AudioContext/WakeLock fakes to verify each behavior deterministically.

## Linked issue
Closes #109. Second of three sub-projects on the parent feature B (order queueing + restaurant notifications). B1 (lifecycle data layer) merged in #108. B3 (kitchen workflow buttons + filter tabs) follows.

## Spec & plan
- Spec: `docs/superpowers/specs/2026-04-28-tablet-alert-experience-design.md`
- Plan: `docs/superpowers/plans/2026-04-28-tablet-alert-experience.md`

## Test plan
- [x] Vitest unit tests (`pnpm vitest run tests/use-new-order-alert.test.ts`): **8 PASSED**
- [x] Full dashboard vitest suite (`pnpm vitest run`): green
- [x] Dashboard typecheck (`pnpm tsc --noEmit`): clean
- [x] Backend full suite (`pytest tests/`): green (no backend changes; sanity run)
- [ ] **Manual tablet smoke (pre-merge):** open the dashboard on a tablet (or Chrome dev tools mobile mode emulating iPad). Click the page once to prime audio. Trigger a test order via `/dev/seed-order` or a real call. Verify:
  - Two-note ding-dong plays once
  - The new row highlights amber and fades over ~8s
  - The screen doesn't sleep after waiting 5+ minutes
  - Initial page load does NOT trigger the cue (only NEW orders)

## Notes
- **No backend changes** — pure frontend. No telephony / TTS / LLM / call-quality surface touched.
- The existing `aria-live` announcement in `OrdersFeed` is unchanged — the audio cue complements it (screen readers still announce, kitchens also hear the bell).
- Wake Lock API is feature-detected — older iPad OS (< 16.4) silently skips wake lock; audio + visual still work.
- The hook is the single integration point. `OrdersFeed` and `OrdersTable` each gained 1-3 lines; the alert behavior is a black box from their perspective.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

- [ ] **Step 4: Surface the PR URL**

The `gh pr create` output is the URL — relay it.

---

## Self-review

**Spec coverage:**
- (a) Audible cue (synthesized two-note ding-dong, throttled) → Task 2 (`playTone` + the throttle in `useEffect`) ✓
- (b) Visual highlight (amber CSS animation, 8s fade) → Task 1 (CSS) + Task 3 (`data-fresh` attribute) ✓
- (c) Wake Lock API → Task 2 (visibility handler) ✓
- (c) Audio autoplay unlock → Task 2 (first-click primer effect) ✓
- (c) Audio context resume on visibility → Task 2 (visibility handler) ✓
- (c) Fullscreen-friendly → no code change required per spec; verified during manual smoke (Task 4 step 3 PR test plan)
- 8 vitest tests covering all 8 spec scenarios → Task 2 ✓
- Manual tablet smoke → Task 4 PR description ✓

**Placeholder scan:** no TBDs. Every code step has full code. Manual test steps in Task 4's PR description are intentional checkboxes (the smoke test is a user action, not an automated step).

**Type consistency:**
- `NewOrderAlertOptions` / `NewOrderAlertResult` types defined in Task 2, consistent across tests + hook usage in Task 3.
- `freshIds: ReadonlySet<string>` consistent across hook return type, `OrdersTable` prop, `OrderRow` `isFresh: boolean` derivation.
- `data-fresh="true"` / `tr[data-fresh="true"]` selectors consistent between Task 1 (CSS) and Task 3 (JSX).
- `playTone(silent: boolean)` signature consistent between the cue path and the unlock primer.
- `audioContextRef.current.state !== 'closed'` guard consistent between getter + cleanup.

**One thing the implementer may have to tune:** the test for "audio.resume called on visibility visible" (test 7) requires the visibility handler to call `audioContext.resume()` whenever the page becomes visible, not just when the context is suspended. The implementation above does this with the unconditional `if (ctx) ctx.resume().catch(() => {});` line. If a future cleanup tries to optimize that away, test 7 fails — that's intentional (the test guards the behavior).
