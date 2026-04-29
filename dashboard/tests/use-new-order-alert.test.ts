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

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const seedOrder = (call_sid: string) => ({ call_sid, status: 'confirmed' as const });

it('does not fire audio cue or mark fresh on initial render', () => {
  const opts = makeOptions();
  const seed = [seedOrder('CA1'), seedOrder('CA2')];
  const { result } = renderHook(() => useNewOrderAlert(seed, opts));

  expect(opts.audio.createOscillator).not.toHaveBeenCalled();
  expect(result.current.freshIds.size).toBe(0);
});

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
  expect(opts.audio.createOscillator).toHaveBeenCalledTimes(2);

  act(() => {
    vi.advanceTimersByTime(500);
    rerender({ orders: [...seed, seedOrder('CANEW1'), seedOrder('CANEW2')] });
  });

  expect(opts.audio.createOscillator).toHaveBeenCalledTimes(2);
  expect(result.current.freshIds.has('CANEW1')).toBe(true);
  expect(result.current.freshIds.has('CANEW2')).toBe(true);
});

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
  expect(opts.audio.createOscillator).toHaveBeenCalledTimes(2);

  act(() => {
    vi.advanceTimersByTime(2100);
    rerender({
      orders: [...seed, seedOrder('CANEW1'), seedOrder('CANEW2')],
    });
  });

  expect(opts.audio.createOscillator).toHaveBeenCalledTimes(4);
});

it('acquires the wake lock on mount and releases it on unmount', async () => {
  const opts = makeOptions();
  const { unmount } = renderHook(() => useNewOrderAlert([], opts));

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

it('releases the wake lock when the document becomes hidden', async () => {
  const opts = makeOptions();
  renderHook(() => useNewOrderAlert([], opts));

  await act(async () => {
    await Promise.resolve();
  });

  const firstSentinel = await opts.wakeLock.request.mock.results[0].value;

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

it('reacquires wake lock and resumes audio when the document becomes visible', async () => {
  const opts = makeOptions();
  renderHook(() => useNewOrderAlert([], opts));

  await act(async () => {
    await Promise.resolve();
  });

  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => 'hidden',
  });
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();
  });

  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => 'visible',
  });
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();
  });

  expect(opts.wakeLock.request).toHaveBeenCalledTimes(2);
  expect(opts.audio.resume).toHaveBeenCalled();
});

it('plays a silent tone on the first document click and only the first', () => {
  const opts = makeOptions();
  renderHook(() => useNewOrderAlert([], opts));

  opts.audio.createOscillator.mockClear();

  act(() => {
    document.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  const callsAfterFirstClick = opts.audio.createOscillator.mock.calls.length;
  expect(callsAfterFirstClick).toBeGreaterThan(0);

  act(() => {
    document.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  expect(opts.audio.createOscillator.mock.calls.length).toBe(callsAfterFirstClick);
});
