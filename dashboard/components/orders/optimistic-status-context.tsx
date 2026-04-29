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
