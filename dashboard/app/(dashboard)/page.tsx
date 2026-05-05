import { redirect } from 'next/navigation';

import { ActiveOrdersWidget } from '@/components/overview/active-orders-widget';
import { KpiStrip, type KpiItem } from '@/components/overview/kpi-strip';
import { LiveCallsWidget } from '@/components/overview/live-calls-widget';
import { PageHeader } from '@/components/shared/page-header';
import { getOrderSummary } from '@/lib/api/analytics';
import { listRecentCalls } from '@/lib/api/calls';
import { listOrders } from '@/lib/api/orders';
import { getMyRestaurant } from '@/lib/api/restaurant';
import { getServerSession } from '@/lib/auth/session';
import { parseCallSessionFromJson } from '@/lib/firebase/call-converters';
import { humanizeRestaurantId } from '@/lib/formatters/restaurant';
import { formatCAD } from '@/lib/formatters/money';
import type { CallSession } from '@/lib/schemas/call';
import type { Order } from '@/lib/schemas/order';

export const dynamic = 'force-dynamic';

export default async function OverviewPage() {
  const session = await getServerSession();
  if (!session) redirect('/login');

  const [summary, callsSeed, ordersSeed, restaurantName] = await Promise.all([
    safeSummary(),
    safeLiveCallsSeed(),
    safeOrdersSeed(),
    safeRestaurantName(session.restaurantId),
  ]);

  const kpis: KpiItem[] = [
    {
      eyebrow: 'Orders today',
      value: summary ? String(summary.today_count) : '—',
      zeroHint:
        summary?.today_count === 0 ? 'No orders yet today.' : undefined,
    },
    {
      eyebrow: 'Orders this week',
      value: summary ? String(summary.seven_day_count) : '—',
      caption: 'rolling 7 days',
    },
    {
      eyebrow: 'Avg order value',
      value: summary ? formatCAD(summary.average_order_value_7d) : '—',
      caption: 'rolling 7 days',
    },
    {
      eyebrow: 'Completion rate',
      value: summary
        ? `${Math.round(summary.completion_rate_7d * 100)}%`
        : '—',
      caption: 'confirmed → completed',
    },
  ];

  return (
    <section className="flex flex-1 flex-col gap-8 p-6 lg:p-10">
      <PageHeader title="Overview" subtitle={restaurantName} />

      <KpiStrip items={kpis} />

      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <LiveCallsWidget
          initial={callsSeed}
          restaurantId={session.restaurantId}
        />
        <ActiveOrdersWidget
          initial={ordersSeed}
          restaurantId={session.restaurantId}
        />
      </div>
    </section>
  );
}

async function safeSummary() {
  try {
    return await getOrderSummary();
  } catch (err) {
    console.error('[overview] /analytics/summary fetch failed', err);
    return null;
  }
}

async function safeLiveCallsSeed(): Promise<CallSession[]> {
  try {
    const result = await listRecentCalls(2);
    if (!result.available) return [];
    return result.calls
      .filter((c) => c.status === 'in_progress')
      .map((c) =>
        parseCallSessionFromJson({
          call_sid: c.call_sid,
          started_at: c.started_at,
          ended_at: c.ended_at,
          status: c.status,
          transcript_count: c.transcript_count,
          has_error: c.has_error,
        }),
      );
  } catch (err) {
    console.error('[overview] listRecentCalls failed', err);
    return [];
  }
}

async function safeOrdersSeed(): Promise<Order[]> {
  try {
    return await listOrders({ limit: 50 });
  } catch (err) {
    console.error('[overview] /orders fetch failed', err);
    return [];
  }
}

async function safeRestaurantName(restaurantId: string): Promise<string> {
  try {
    const restaurant = await getMyRestaurant();
    return restaurant.name || humanizeRestaurantId(restaurantId);
  } catch (err) {
    console.error('[overview] /restaurants/me fetch failed', err);
    return humanizeRestaurantId(restaurantId);
  }
}
