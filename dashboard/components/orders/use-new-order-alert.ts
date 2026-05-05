'use client';

import { useEffect, useReducer, useRef } from 'react';

import type { Order } from '@/lib/schemas/order';

export type NewOrderAlertOptions = {
  /**
   * Throttle window for the audio cue. A burst of N orders within this
   * window plays the cue exactly once. Default: 2000ms.
   */
  throttleMs?: number;

  /** Test seam: factory for the AudioContext. */
  audioContextFactory?: () => AudioContext;

  /** Test seam: the Wake Lock API. */
  wakeLockApi?: WakeLock | null;
};

export type NewOrderAlertResult = {
  /** Set of call_sid values that recently arrived (within the highlight window). */
  freshIds: ReadonlySet<string>;
};

const DEFAULT_THROTTLE_MS = 2000;
const FRESH_DURATION_MS = 8000;
const TONE_NOTE_DURATION_MS = 100;
// Two-note ding-dong: C5 then A4. Pleasant, doesn't sound like a system error.
const NOTE_HZ = [523.25, 440.0] as const;

type FreshIdsAction =
  | { type: 'add'; ids: string[] }
  | { type: 'remove'; id: string };

function freshIdsReducer(
  state: ReadonlySet<string>,
  action: FreshIdsAction,
): ReadonlySet<string> {
  if (action.type === 'add') {
    const next = new Set(state);
    for (const id of action.ids) next.add(id);
    return next;
  }
  if (action.type === 'remove') {
    const next = new Set(state);
    next.delete(action.id);
    return next;
  }
  return state;
}

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
  // Tracks whether the detection effect has run for the first time. Accessed
  // only inside effects, never during render, so this is safe.
  const initializedRef = useRef(false);

  const [freshIds, dispatch] = useReducer(
    freshIdsReducer,
    new Set<string>() as ReadonlySet<string>,
  );
  const freshTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(
    new Map(),
  );

  const getAudioContext = (): AudioContext | null => {
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      return audioContextRef.current;
    }
    try {
      const factory =
        options?.audioContextFactory ??
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
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

  // Detect new orders + fire the alert
  useEffect(() => {
    // On the first run, seed seenIds from the current snapshot so the
    // initially-rendered list is treated as already seen (no alert on load).
    if (!initializedRef.current) {
      initializedRef.current = true;
      for (const o of orders) seenIds.current.add(o.call_sid);
      return;
    }

    const newIds: string[] = [];
    for (const o of orders) {
      if (!seenIds.current.has(o.call_sid)) {
        newIds.push(o.call_sid);
        seenIds.current.add(o.call_sid);
      }
    }

    if (newIds.length === 0) return;

    dispatch({ type: 'add', ids: newIds });

    for (const id of newIds) {
      const t = setTimeout(() => {
        dispatch({ type: 'remove', id });
        freshTimersRef.current.delete(id);
      }, FRESH_DURATION_MS);
      freshTimersRef.current.set(id, t);
    }

    const now = Date.now();
    if (now - lastAlertedAt.current >= throttleMs) {
      lastAlertedAt.current = now;
      playTone(false);
    }
  }, [orders, throttleMs]);

  // Wake Lock + visibility handling
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
        // Ensure the context exists (creates it if needed) then resume.
        // Browsers may suspend the context while the tab is hidden; always
        // calling resume here covers both the suspended and running states.
        // Test 7 observes this unconditional call.
        const ctx = getAudioContext();
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

  // Audio unlock primer — first document click plays a silent tone.
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

  // Cleanup on unmount
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
