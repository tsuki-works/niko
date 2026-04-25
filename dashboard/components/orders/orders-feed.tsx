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
import { OrdersTable } from '@/components/orders/orders-table';
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
  restaurantPhone: string;
};

const ANNOUNCE_THROTTLE_MS = 2000;

export function OrdersFeed({
  initial,
  initialCounts,
  statusFilter,
  restaurantPhone,
}: Props) {
  const [orders, setOrders] = useState<Order[]>(initial);
  const [announcement, setAnnouncement] = useState('');

  const seenIds = useRef(new Set(initial.map((o) => o.call_sid)));
  const lastAnnouncedAt = useRef(0);

  useEffect(() => {
    if (!db) {
      // Firebase web config isn't wired up yet. Feed already rendered
      // from RSC props; live updates just won't come in until the config
      // lands. See lib/firebase/client.ts for the guard.
      return;
    }

    const base = collection(db, 'orders').withConverter(orderConverter);
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
  }, [statusFilter]);

  return (
    <section className="flex flex-col gap-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-2xl font-medium">Orders</h2>
          <p className="text-sm text-muted-foreground">
            Niko Pizza Kitchen · {restaurantPhone}
          </p>
        </div>
        <LiveIndicator />
      </header>

      <FilterTabs active={statusFilter} counts={initialCounts} />

      <OrdersTable orders={orders} />

      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
    </section>
  );
}
