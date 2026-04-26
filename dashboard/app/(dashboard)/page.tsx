import { redirect } from 'next/navigation';

import { OrdersFeed } from '@/components/orders/orders-feed';
import type { CountsByStatus } from '@/components/orders/filter-tabs';
import { listOrders, parseStatusParam } from '@/lib/api/orders';
import { getMyRestaurant } from '@/lib/api/restaurant';
import { getServerSession } from '@/lib/auth/session';
import { humanizeRestaurantId } from '@/lib/formatters/restaurant';
import type { Order, OrderStatus } from '@/lib/schemas/order';

export const dynamic = 'force-dynamic';

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  // Belt-and-suspenders: layout already verified the session, but
  // running it here lets us narrow the type without `!` and gives us
  // restaurantId for the data subscription.
  const session = await getServerSession();
  if (!session) redirect('/login');

  const { status } = await searchParams;
  const filter = parseStatusParam(status);

  // Fetch ALL recent for the counts badge, then apply the status filter
  // for the rendered list. For POC scale (≤200 orders) this is fine.
  const all = await listOrders({ limit: 200 });
  const counts = computeCounts(all);
  const initial = filter ? all.filter((o) => o.status === filter) : all.slice(0, 50);

  // Pull restaurant for the empty-state phone copy. Don't let a backend
  // hiccup take down the whole page — degrade to humanized rid +
  // unknown phone (empty-state will fall back to "no number assigned").
  let restaurantName = humanizeRestaurantId(session.restaurantId);
  let twilioPhone = '';
  try {
    const restaurant = await getMyRestaurant();
    restaurantName = restaurant.name || restaurantName;
    twilioPhone = restaurant.twilio_phone;
  } catch (err) {
    console.error('[orders page] /restaurants/me fetch failed', err);
  }

  return (
    <OrdersFeed
      initial={initial}
      initialCounts={counts}
      statusFilter={filter}
      restaurantId={session.restaurantId}
      restaurantName={restaurantName}
      twilioPhone={twilioPhone}
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
