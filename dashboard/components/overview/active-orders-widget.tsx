'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  collection,
  limit as fsLimit,
  onSnapshot,
  orderBy,
  query,
} from 'firebase/firestore';
import { ChefHat } from 'lucide-react';

import { LocalTime } from '@/components/shared/local-time';
import { StatusBadge } from '@/components/orders/status-badge';
import { TransitionButton } from '@/components/orders/transition-button';
import { OptimisticStatusProvider } from '@/components/orders/optimistic-status-context';
import { db } from '@/lib/firebase/client';
import { orderConverter } from '@/lib/firebase/converters';
import { type Order, orderShortId } from '@/lib/schemas/order';

type Props = {
  initial: Order[];
  restaurantId: string;
};

const ACTIVE_STATUSES: ReadonlySet<Order['status']> = new Set([
  'in_progress',
  'confirmed',
  'preparing',
  'ready',
]);

const QUEUE_DISPLAY_LIMIT = 8;

export function ActiveOrdersWidget(props: Props) {
  return (
    <OptimisticStatusProvider>
      <ActiveOrdersInner {...props} />
    </OptimisticStatusProvider>
  );
}

function ActiveOrdersInner({ initial, restaurantId }: Props) {
  const [orders, setOrders] = useState<Order[]>(initial);

  useEffect(() => {
    if (!db) return;

    // Firestore doesn't take an `in` over arbitrary status values plus
    // an orderBy without a composite index, so subscribe to the recent
    // window and filter active statuses on the client (consistent with
    // OrdersFeed for the unfiltered case).
    const q = query(
      collection(db, 'restaurants', restaurantId, 'orders').withConverter(
        orderConverter,
      ),
      orderBy('created_at', 'desc'),
      fsLimit(50),
    );

    const unsub = onSnapshot(
      q,
      (snap) => setOrders(snap.docs.map((d) => d.data())),
      (err) => console.error('Active orders subscription error', err),
    );
    return unsub;
  }, [restaurantId]);

  const active = orders
    .filter((o) => ACTIVE_STATUSES.has(o.status))
    // Oldest first — the kitchen works the queue head-down.
    .sort((a, b) => a.created_at.getTime() - b.created_at.getTime())
    .slice(0, QUEUE_DISPLAY_LIMIT);

  return (
    <article className="flex flex-col gap-4 rounded-lg border border-border p-6">
      <header className="flex items-baseline justify-between gap-2">
        <div>
          <h3 className="text-base font-medium">Kitchen queue</h3>
          <p className="text-xs text-muted-foreground">
            {active.length === 0
              ? 'No active orders'
              : `${active.length} order${active.length === 1 ? '' : 's'} to make`}
          </p>
        </div>
        <Link
          href="/orders"
          className="text-xs text-muted-foreground hover:text-primary"
        >
          See all →
        </Link>
      </header>

      {active.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {active.map((order) => (
            <QueueRow key={order.call_sid} order={order} />
          ))}
        </ul>
      )}
    </article>
  );
}

function QueueRow({ order }: { order: Order }) {
  const isLive = order.status === 'in_progress';
  const itemsLine =
    order.items.length === 0
      ? 'Building…'
      : order.items
          .map((i) => `${i.quantity}× ${i.name.toLowerCase()}`)
          .join(', ');

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <Link
          href={`/orders/${encodeURIComponent(order.call_sid)}`}
          className="flex items-center gap-2"
        >
          <span className="font-medium">{orderShortId(order)}</span>
          <span className="text-xs text-muted-foreground">
            {isLive ? (
              'now'
            ) : (
              <LocalTime date={order.created_at} mode="relative" />
            )}
          </span>
        </Link>
        <p className="truncate text-sm text-muted-foreground">{itemsLine}</p>
      </div>
      <div className="flex items-center gap-2">
        <StatusBadge status={order.status} />
        <TransitionButton order={order} />
      </div>
    </li>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border py-8 text-center">
      <ChefHat className="h-5 w-5 text-muted-foreground" />
      <p className="text-sm text-muted-foreground">
        Nothing in the queue. New orders will land here as they confirm.
      </p>
    </div>
  );
}
