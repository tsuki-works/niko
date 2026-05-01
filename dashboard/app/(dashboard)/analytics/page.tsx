import { redirect } from 'next/navigation';

import { Tile } from '@/components/analytics/tile';
import { getOrderSummary } from '@/lib/api/analytics';
import { getServerSession } from '@/lib/auth/session';
import { formatCAD } from '@/lib/formatters/money';

export const dynamic = 'force-dynamic';

export default async function AnalyticsPage() {
  const session = await getServerSession();
  if (!session) redirect('/login');

  let summary;
  try {
    summary = await getOrderSummary();
  } catch (err) {
    console.error('[analytics page] /analytics/summary fetch failed', err);
    return (
      <section className="flex flex-1 flex-col gap-3 p-6 lg:p-10">
        <h2 className="text-3xl font-medium tracking-tight">Analytics</h2>
        <p className="text-sm text-muted-foreground">
          Could not load metrics. Try again in a moment.
        </p>
      </section>
    );
  }

  const empty = summary.seven_day_count === 0;

  return (
    <section className="flex flex-1 flex-col gap-10 p-6 lg:p-10">
      <header className="flex max-w-3xl flex-col gap-3">
        <div className="flex items-baseline gap-3">
          <h2 className="text-3xl font-medium tracking-tight">Analytics</h2>
          <span aria-hidden className="h-px flex-1 translate-y-[-0.5rem] bg-border" />
        </div>
        <p className="text-sm text-muted-foreground">
          Today and the past seven days.
        </p>
      </header>

      {empty ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          No orders in the last seven days yet. Make a test call to your
          Niko number — the metrics will populate automatically.
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Tile
            label="Orders today"
            value={String(summary.today_count)}
            unit={summary.today_count === 1 ? 'order' : 'orders'}
          />
          <Tile
            label="Orders this week"
            value={String(summary.seven_day_count)}
            unit={summary.seven_day_count === 1 ? 'order' : 'orders'}
            hint="rolling 7 days"
          />
          <Tile
            label="Avg order value"
            value={formatCAD(summary.average_order_value_7d)}
            hint="rolling 7 days"
          />
          <Tile
            label="Completion rate"
            value={`${Math.round(summary.completion_rate_7d * 100)}%`}
            hint="of orders confirmed → completed"
          />
        </div>
      )}
    </section>
  );
}
