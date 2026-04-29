'use client';

import {
  collection,
  limit as fsLimit,
  onSnapshot,
  orderBy,
  query,
  where,
} from 'firebase/firestore';
import { useEffect, useRef, useState } from 'react';

import { FilterTabs, type CountsByStatus } from '@/components/orders/filter-tabs';
import { LiveIndicator } from '@/components/orders/live-indicator';
import {
  OptimisticStatusProvider,
  useOptimisticStatus,
} from '@/components/orders/optimistic-status-context';
import { OrdersTable } from '@/components/orders/orders-table';
import { useNewOrderAlert } from '@/components/orders/use-new-order-alert';
import { db } from '@/lib/firebase/client';
import { orderConverter } from '@/lib/firebase/converters';
import { formatPhone } from '@/lib/formatters/phone';
import {
  type Order,
  type OrderStatus,
  orderShortId,
} from '@/lib/schemas/order';

type Props = {
  initial: Order[];
  initialCounts: CountsByStatus;
  statusFilter?: OrderStatus;
  restaurantId: string;
  restaurantName: string;
  // Empty string means the tenant doesn't yet have a Twilio number
  // assigned — empty state renders awaiting-number copy instead.
  twilioPhone: string;
};

const ANNOUNCE_THROTTLE_MS = 2000;

function OrdersFeedInner({
  initial,
  initialCounts,
  statusFilter,
  restaurantId,
  restaurantName,
  twilioPhone,
}: Props) {
  const [orders, setOrders] = useState<Order[]>(initial);
  const [announcement, setAnnouncement] = useState('');

  const seenIds = useRef(new Set(initial.map((o) => o.call_sid)));
  const lastAnnouncedAt = useRef(0);

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

  const { freshIds } = useNewOrderAlert(orders);

  useEffect(() => {
    if (!db) {
      // Firebase web config isn't wired up yet. Feed already rendered
      // from RSC props; live updates just won't come in until the config
      // lands. See lib/firebase/client.ts for the guard.
      return;
    }

    // Multi-tenant path: every order doc lives under the calling
    // tenant's restaurant. Server Component resolves restaurantId
    // from the session cookie and passes it down.
    const base = collection(
      db,
      'restaurants',
      restaurantId,
      'orders',
    ).withConverter(orderConverter);
    const q = statusFilter
      ? query(
          base,
          where('status', '==', statusFilter),
          orderBy('created_at', 'desc'),
          fsLimit(50),
        )
      : query(base, orderBy('created_at', 'desc'), fsLimit(50));

    const unsub = onSnapshot(
      q,
      (snap) => {
        const next = snap.docs.map((d) => d.data());
        setOrders(next);

        const fresh = next.filter((o) => !seenIds.current.has(o.call_sid));
        fresh.forEach((o) => seenIds.current.add(o.call_sid));

        if (fresh.length > 0) {
          const now = Date.now();
          if (now - lastAnnouncedAt.current >= ANNOUNCE_THROTTLE_MS) {
            lastAnnouncedAt.current = now;
            const newest = fresh[0];
            const phone = formatPhone(newest.caller_phone) || 'unknown';
            setAnnouncement(
              `New order ${orderShortId(newest)} from ${phone}`,
            );
          }
        }
      },
      (err) => {
        console.error('Orders subscription error', err);
      },
    );

    return unsub;
  }, [statusFilter, restaurantId]);

  return (
    <section className="flex flex-col gap-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-2xl font-medium">Orders</h2>
          <p className="text-sm text-muted-foreground">{restaurantName}</p>
        </div>
        <LiveIndicator />
      </header>

      <FilterTabs active={statusFilter} counts={initialCounts} />

      <OrdersTable orders={displayOrders} twilioPhone={twilioPhone} freshIds={freshIds} />

      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
    </section>
  );
}

export function OrdersFeed(props: Props) {
  return (
    <OptimisticStatusProvider>
      <OrdersFeedInner {...props} />
    </OptimisticStatusProvider>
  );
}
