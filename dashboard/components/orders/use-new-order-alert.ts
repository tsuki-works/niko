'use client';

import { useEffect, useRef, useState } from 'react';

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

  // Initialize seenIds from the first orders snapshot — treat the
  // initially-rendered list as already seen so we don't fire on page load.
  const initializedRef = useRef(false);
  if (!initializedRef.current) {
    initializedRef.current = true;
    for (const o of orders) seenIds.current.add(o.call_sid);
  }

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
    const newIds: string[] = [];
    for (const o of orders) {
      if (!seenIds.current.has(o.call_sid)) {
        newIds.push(o.call_sid);
        seenIds.current.add(o.call_sid);
      }
    }

    if (newIds.length === 0) return;

    setFreshIds((prev) => {
      const next = new Set(prev);
      for (const id of newIds) next.add(id);
      return next;
    });

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
