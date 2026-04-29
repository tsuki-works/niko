# Tablet Alert Experience (Design Spec — B2)

**Date:** 2026-04-28
**Sprint:** 2.2 — Order Taking Excellence (#5)
**Tracking issue:** #109
**Owner:** Meet
**Status:** Approved — ready for implementation plan
**Parent feature:** B (Order queueing + restaurant notifications). B1 (lifecycle data layer) is merged in #108. B2 ships the tablet alert UX. B3 (kitchen workflow buttons) follows.

## Goal

Each restaurant runs the niko dashboard on a dedicated kitchen tablet — the tablet IS the primary new-order notification surface. Make that experience production-grade: an audible cue, a visual highlight on fresh rows, a wake lock to keep the tablet awake, and the audio-autoplay unlock dance browsers require.

## In scope

### (a) Audible cue
- Web Audio API synthesizes a short two-note "ding-dong" — e.g. C5 (~523Hz) → A4 (~440Hz), each ~100ms with a short gain envelope to avoid pop. Total tone duration ~200ms.
- No audio file shipped — keeps the dashboard bundle small and avoids cache/PWA complexity.
- Throttled to one play per 2000ms, matching the existing `aria-live` announcement throttle in `OrdersFeed`. A burst of N orders within 2s plays once.
- Fires only when a *new* order's `call_sid` enters the live `orders` array (not on initial RSC-rendered seed).

### (b) Visual highlight
- New orders in `OrdersTable` get a subtle amber background that fades over ~8s.
- CSS-only via a `data-fresh="true"` attribute on the row + a one-shot CSS keyframe animation in `globals.css`. No JS animation library.
- The amber tone matches the `preparing` status badge color (B1) — visual consistency for "active / needs attention".
- After the animation completes, the attribute can be removed by the hook (or simply never re-applied — the animation is one-shot).

### (c) Tablet kiosk niceties
- **Wake Lock API.** Request `screen` wake lock on mount + on `visibilitychange` to visible. Release on unmount + on visibility hidden. Prevents the tablet from sleeping while the dashboard is open.
- **Audio autoplay unlock.** On the first `click` event anywhere on `document`, play a silent tone to "unlock" the AudioContext for the session. After this, subsequent alerts play without prompts. Use `addEventListener('click', ..., { once: true })` so it self-removes.
- **Audio context resume on visibility.** When the tab becomes visible again, the hook calls `audioContext.resume()` (browsers suspend it when hidden). Quiet no-op if already running.
- **Fullscreen-friendly.** No explicit fullscreen mode (browsers require user gesture per request). Verify the existing layout doesn't overflow at iPad viewport sizes (1024×768, 820×1180). Manual smoke check; no code change unless a regression is found.

## Out of scope

- **No "settings" UI** for the kitchen to toggle sound on/off, volume, or tone style. Single hardcoded behavior. Add controls later if a real restaurant asks.
- **No multi-tone "escalating" cue** if the kitchen doesn't acknowledge. Single play per new order, throttled. (Acknowledge mechanic itself is in B3 via the "Start preparing" tap.)
- **No persistent unread count** in the page title or favicon.
- **No PWA install / service worker.** Restaurants just open the URL in their tablet's browser.
- **No multi-restaurant alert routing** — each tablet is logged in as a single tenant; the existing per-tenant `OrdersFeed` subscription already scopes correctly.
- **No kitchen workflow buttons** — that's B3.

## Approach

**One client-only React hook owns the alert behavior.** A new `useNewOrderAlert(orders: Order[])` hook in `dashboard/components/orders/use-new-order-alert.ts` is the single integration point. It:
- Tracks `seenIds` internally.
- Detects new orders by diffing `orders` against the seen set.
- On a new-order detection: plays the audio cue (throttled), updates the returned `freshIds` Set so `OrdersTable` can highlight the row.
- Manages the wake lock lifecycle.
- Attaches the one-shot click listener that primes the AudioContext.

`OrdersFeed` calls the hook with the current `orders` array and passes the returned `freshIds` down to `OrdersTable`. `OrdersFeed` keeps its existing `aria-live` announcement logic (the hook adds audio + visual on top, doesn't replace).

### Why one hook instead of three separate concerns

Audio, visual highlighting, and kiosk niceties all key off the SAME signal — "a new order arrived in the live feed" or "the page became visible." Splitting them into 3 hooks would mean 3 places computing the same thing. One hook with a clear input (`orders: Order[]`) and a clear output (`freshIds: Set<string>` + side effects) keeps the integration simple.

### Why synthesized audio over a file

- One fewer asset to ship, cache, or worry about CDN-loading
- No format-compatibility concerns (Safari vs Chrome)
- Easy to tune the tone in code if the first version sounds wrong (rather than asking Daniel to produce a new MP3)
- Total Web Audio code is ~30 lines

### Why the AudioContext-unlock dance

Modern browsers (especially Safari) refuse to play audio without an initial user interaction. The dashboard's first user click — even just clicking on the page anywhere — counts as the gesture. Playing a silent tone in response to that gesture "unlocks" the AudioContext for the rest of the session. After that, automated alerts work without prompts.

## Architecture

```
dashboard/components/orders/
├── use-new-order-alert.ts   ← NEW: the hook
├── orders-feed.tsx          ← integration point: call the hook, pass freshIds down
└── orders-table.tsx         ← accept freshIds prop, apply data-fresh attribute

dashboard/app/globals.css    ← add @keyframes + [data-fresh="true"] animation rule

dashboard/tests/
└── use-new-order-alert.test.ts  ← NEW: vitest unit tests
```

### Hook signature

```ts
export type NewOrderAlertOptions = {
  // Throttle for audio cue (also applies to "fresh" detection burst). Default 2000ms.
  throttleMs?: number;
  // Test seam: inject an AudioContext factory + WakeLock API.
  audioContextFactory?: () => AudioContext;
  wakeLockApi?: WakeLockSentinel | null;
};

export type NewOrderAlertResult = {
  // Set of call_sid values that recently arrived (within the throttle window).
  // OrdersTable uses this to apply data-fresh="true".
  freshIds: ReadonlySet<string>;
};

export function useNewOrderAlert(
  orders: Pick<Order, 'call_sid' | 'status'>[],
  options?: NewOrderAlertOptions,
): NewOrderAlertResult;
```

The factory injection is purely a test seam — production usage is just `useNewOrderAlert(orders)`.

### Hook responsibilities (concretely)

On mount:
- Initialize `seenIds` from the first `orders` snapshot (treat the initial RSC-rendered list as already seen — don't fire alerts on page load).
- Request the wake lock if `navigator.wakeLock` exists. Save the sentinel for release later.
- Attach a `visibilitychange` listener that:
  - On visible: re-acquires wake lock, calls `audioContext.resume()`.
  - On hidden: releases wake lock.
- Attach a `document.addEventListener('click', primeAudio, { once: true })` listener. `primeAudio` plays a silent tone via the AudioContext to unlock it.

On every render where `orders` changes:
- Compute `newIds = orders.filter(o => !seenIds.has(o.call_sid)).map(o => o.call_sid)`.
- If `newIds.length > 0` AND `(now - lastAlertedAt) >= throttleMs`:
  - Play the audio cue.
  - Update `lastAlertedAt`.
  - Mark these IDs as `fresh` for `~8s` (visual highlight duration), then drop them from `freshIds`.
- Add the new IDs to `seenIds` regardless of throttle.

On unmount:
- Release wake lock.
- Remove visibilitychange listener.
- Close the AudioContext.

## Test plan

### Vitest unit tests (`dashboard/tests/use-new-order-alert.test.ts`)

Use injected factories for `AudioContext` and `wakeLock` so tests are deterministic and offline.

| # | Behavior | Setup |
|---|---|---|
| 1 | Initial render with N seeded orders → no audio cue, no fresh ids | Render hook with `orders=[seed1, seed2]`. Assert audio mock not called, freshIds empty. |
| 2 | New order arrives → audio cue plays + freshIds includes its id | Re-render with `orders=[seed1, seed2, NEW]`. Assert audio mock called once, freshIds.has(NEW.call_sid). |
| 3 | Two orders within throttle window → audio plays once, both fresh | Re-render twice within < throttle. Assert audio called once, freshIds has both. |
| 4 | Order arrives after throttle window → audio plays again | Re-render after `vi.advanceTimersByTime(throttleMs + 100)`. Assert second audio call. |
| 5 | Wake lock requested on mount, released on unmount | Assert wakeLockApi.request called on mount, sentinel.release called on unmount. |
| 6 | Wake lock released on visibilitychange to hidden | Trigger visibilitychange event with `document.hidden=true`. Assert sentinel.release called. |
| 7 | Wake lock re-acquired + audio resumed on visibilitychange to visible | Toggle visibility hidden → visible. Assert request + audioContext.resume called. |
| 8 | Audio unlock primer fires on first document click | Trigger document click. Assert silent tone plays via the audio context. Trigger another click. Assert primer NOT called again (one-shot). |

### Manual smoke test (pre-merge)

On a real iPad in Safari (or Chrome dev tools mobile mode emulating iPad):
- Open the dashboard, sign in, land on the orders feed.
- Trigger a test call (`/dev/seed-order` or place an actual call). Verify:
  - Audio cue plays (after first click on the page anywhere)
  - The new order's row highlights amber + fades over ~8s
  - The screen doesn't sleep after waiting 5+ minutes
  - The cue does NOT play on initial page load (existing orders aren't fresh)

## Done criteria

- All 8 vitest unit tests green
- Dashboard typecheck (`pnpm tsc --noEmit`) clean
- Full vitest suite green
- Manual tablet smoke test verified (results captured in PR description)
- `niko-reviewer` sign-off

## Risks and mitigations

- **Risk:** Wake Lock API not supported (older iPad OS). **Mitigation:** feature-detect `navigator.wakeLock`; if missing, log a one-time warning and skip the wake lock entirely. Audio + visual still work.
- **Risk:** Audio context creation fails before user interaction. **Mitigation:** lazily create the AudioContext inside the audio-unlock primer (the first click handler), not at module load. If the first-click primer never runs (page never clicked), audio simply doesn't play — no crash.
- **Risk:** The `seenIds` tracking duplicates `OrdersFeed`'s existing `seenIds` ref. **Mitigation:** the implementer chooses one of two paths during plan execution: (1) delete `OrdersFeed`'s ref since it's only used to gate the aria-live announcement, and have the hook own seenIds + return both `freshIds` and `announcement`; (2) keep `OrdersFeed`'s ref for the announcement and have the hook maintain its own seenIds independently. Either is fine; (1) is slightly cleaner. Plan will pick one.
- **Risk:** Visual highlight is jarring or invisible depending on light/dark theme. **Mitigation:** use the same `bg-amber-500/15` token as the `preparing` status badge — proven readable in both themes.
- **Risk:** Hook re-runs on every render and races with the throttle. **Mitigation:** use `useRef` for `lastAlertedAt` and `seenIds` so they don't trigger re-renders themselves. Effect runs in `useEffect([orders])`.

## Files touched (anticipated)

- `dashboard/components/orders/use-new-order-alert.ts` — NEW
- `dashboard/components/orders/orders-feed.tsx` — call the hook, pass `freshIds` down
- `dashboard/components/orders/orders-table.tsx` — accept `freshIds`, apply `data-fresh` attribute on rows
- `dashboard/app/globals.css` — `@keyframes new-order-flash` + `[data-fresh="true"]` rule
- `dashboard/tests/use-new-order-alert.test.ts` — NEW (vitest unit tests, 8 cases)
