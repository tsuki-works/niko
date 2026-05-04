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

const QUEUE_STATUSES: ReadonlySet<Order['status']> = new Set([
  'confirmed',
  'preparing',
]);

const QUEUE_DISPLAY_LIMIT = 8;

const ITEMS_TRUNCATE = 40;

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
    // window and filter on the client (consistent with OrdersFeed for
    // the unfiltered case).
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

  const queue = orders
    .filter((o) => QUEUE_STATUSES.has(o.status))
    // Oldest first — the kitchen works the queue head-down.
    .sort((a, b) => a.created_at.getTime() - b.created_at.getTime())
    .slice(0, QUEUE_DISPLAY_LIMIT);

  return (
    <article className="flex flex-col gap-3 rounded-md border border-border-subtle bg-surface-1 p-4">
      <header className="flex items-center justify-between gap-2">
        <h3 className="text-md font-medium">Kitchen queue</h3>
        <Link
          href="/orders?status=confirmed"
          className="text-sm text-foreground-muted hover:text-foreground"
        >
          See all →
        </Link>
      </header>

      {queue.length === 0 ? (
        <EmptyState />
      ) : (
        <table className="w-full text-left text-sm">
          <tbody>
            {queue.map((order) => (
              <QueueRow key={order.call_sid} order={order} />
            ))}
          </tbody>
        </table>
      )}
    </article>
  );
}

function QueueRow({ order }: { order: Order }) {
  const itemsLine =
    order.items.length === 0
      ? '—'
      : truncate(
          order.items
            .map((i) => `${i.quantity}× ${i.name.toLowerCase()}`)
            .join(', '),
          ITEMS_TRUNCATE,
        );

  const detailHref = `/orders/${encodeURIComponent(order.call_sid)}`;

  return (
    <tr className="border-b border-border-subtle last:border-b-0 hover:bg-surface-2/40">
      <td className="px-1 py-2 align-middle font-mono text-xs">
        <Link href={detailHref}>{orderShortId(order)}</Link>
      </td>
      <td className="px-1 py-2 align-middle">
        <Link href={detailHref} className="block truncate">
          {itemsLine}
        </Link>
      </td>
      <td className="px-1 py-2 align-middle text-foreground-muted">
        <Link href={detailHref}>
          <LocalTime date={order.created_at} mode="relative" />
        </Link>
      </td>
      <td className="px-1 py-2 align-middle">
        <Link href={detailHref}>
          <StatusBadge status={order.status} />
        </Link>
      </td>
      <td className="px-1 py-2 align-middle text-right">
        <TransitionButton order={order} />
      </td>
    </tr>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <ChefHat className="size-8 text-foreground-faint" aria-hidden />
      <p className="text-md font-medium">Queue is clear</p>
      <p className="text-sm text-foreground-muted">
        New confirmed orders will land here.
      </p>
    </div>
  );
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1).trimEnd() + '…';
}
