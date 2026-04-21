import { OrdersFeed } from '@/components/orders/orders-feed';
import type { CountsByStatus } from '@/components/orders/filter-tabs';
import { listOrders, parseStatusParam } from '@/lib/api/orders';
import type { Order, OrderStatus } from '@/lib/schemas/order';

export const dynamic = 'force-dynamic';

const RESTAURANT_PHONE = '+1 647-905-8093';

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status } = await searchParams;
  const filter = parseStatusParam(status);

  // Fetch ALL recent for the counts badge, then apply the status filter
  // for the rendered list. For POC scale (≤200 orders) this is fine.
  const all = await listOrders({ limit: 200 });
  const counts = computeCounts(all);
  const initial = filter ? all.filter((o) => o.status === filter) : all.slice(0, 50);

  return (
    <OrdersFeed
      initial={initial}
      initialCounts={counts}
      statusFilter={filter}
      restaurantPhone={RESTAURANT_PHONE}
    />
  );
}

function computeCounts(orders: Order[]): CountsByStatus {
  const base: CountsByStatus = {
    all: orders.length,
    in_progress: 0,
    confirmed: 0,
    cancelled: 0,
  };
  for (const o of orders) {
    base[o.status as OrderStatus] += 1;
  }
  return base;
}
