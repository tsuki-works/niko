import Link from 'next/link';
import { ChevronLeft, Play, Radio } from 'lucide-react';

import { CallDuration } from '@/components/orders/call-duration';
import { CancelOrderButton } from '@/components/orders/cancel-order-button';
import { StatusBadge } from '@/components/orders/status-badge';
import { TransitionButton } from '@/components/orders/transition-button';
import { LocalTime } from '@/components/shared/local-time';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { formatCAD } from '@/lib/formatters/money';
import { formatPhone } from '@/lib/formatters/phone';
import {
  type Order,
  formatLineItemTitle,
  orderShortId,
} from '@/lib/schemas/order';

const ACTION_STATUSES: ReadonlySet<Order['status']> = new Set([
  'confirmed',
  'preparing',
  'ready',
]);

export function OrderDetail({ order }: { order: Order }) {
  const showActionRow = ACTION_STATUSES.has(order.status);

  return (
    <div className="mx-auto max-w-6xl p-6">
      <Header order={order} />
      <div className="mt-6 flex flex-col gap-6 min-[960px]:grid min-[960px]:grid-cols-[3fr_2fr]">
        <div className="flex flex-col gap-6">
          <CallerCard order={order} />
          <ItemsList order={order} />
          <Totals order={order} />
          {showActionRow && (
            <div className="flex flex-wrap items-center gap-3 pt-2">
              <TransitionButton order={order} mode="detail" />
              <CancelOrderButton callSid={order.call_sid} />
            </div>
          )}
        </div>
        <div className="flex flex-col gap-6">
          <CallSidebarCard order={order} />
        </div>
      </div>
    </div>
  );
}

function Header({ order }: { order: Order }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="ghost" size="sm" asChild>
        <Link href="/orders" aria-label="Back to orders">
          <ChevronLeft className="size-4" />
          Back
        </Link>
      </Button>
      <h2 className="font-mono text-lg font-semibold">
        Order {orderShortId(order)}
      </h2>
      <StatusBadge status={order.status} />
      <div className="ml-auto text-sm text-foreground-muted">
        {headerTimestamp(order)}
      </div>
    </div>
  );
}

function headerTimestamp(order: Order): React.ReactNode {
  switch (order.status) {
    case 'in_progress':
      return (
        <>
          Started <LocalTime date={order.created_at} mode="absolute" />
        </>
      );
    case 'confirmed':
      return order.confirmed_at ? (
        <>
          Confirmed <LocalTime date={order.confirmed_at} mode="absolute" />
        </>
      ) : (
        <>Confirmed</>
      );
    case 'preparing':
      return order.preparing_at ? (
        <>
          Started prep <LocalTime date={order.preparing_at} mode="absolute" />
        </>
      ) : (
        <>Preparing</>
      );
    case 'ready':
      return order.ready_at ? (
        <>
          Ready <LocalTime date={order.ready_at} mode="absolute" />
        </>
      ) : (
        <>Ready</>
      );
    case 'completed':
      return order.completed_at ? (
        <>
          Completed <LocalTime date={order.completed_at} mode="absolute" />
        </>
      ) : (
        <>Completed</>
      );
    case 'cancelled':
      return order.cancelled_at ? (
        <>
          Cancelled <LocalTime date={order.cancelled_at} mode="absolute" />
        </>
      ) : (
        <>
          Cancelled <LocalTime date={order.created_at} mode="absolute" />
        </>
      );
    default: {
      // Exhaustiveness check: if a new OrderStatus is added without a
      // case here, TypeScript will error on this line.
      const _exhaustive: never = order.status;
      return _exhaustive;
    }
  }
}

function CallerCard({ order }: { order: Order }) {
  return (
    <div className="rounded-md border border-border-subtle bg-surface-1 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="font-medium">{formatPhone(order.caller_phone)}</div>
          <div className="text-sm text-foreground-muted">
            {order.order_type ? capitalize(order.order_type) : 'Type unknown'}
          </div>
          {order.order_type === 'delivery' && order.delivery_address && (
            <div className="mt-1 text-sm text-foreground-muted">
              {order.delivery_address}
            </div>
          )}
        </div>
        <div className="text-right text-sm text-foreground-muted">
          <CallDuration order={order} />
        </div>
      </div>
    </div>
  );
}

function ItemsList({ order }: { order: Order }) {
  if (order.items.length === 0) {
    return (
      <p className="text-sm text-foreground-muted">No items.</p>
    );
  }

  return (
    <ul className="flex flex-col">
      {order.items.map((item, idx) => (
        <li
          key={idx}
          className="border-b border-border-subtle py-3 last:border-b-0"
        >
          <div className="flex items-baseline justify-between gap-4">
            <div className="font-medium">{formatLineItemTitle(item)}</div>
            <div className="font-mono font-medium tabular-nums">
              {formatCAD(item.line_total)}
            </div>
          </div>
          {item.modifications.length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-4 text-sm text-foreground-muted">
              {item.modifications.map((mod, i) => (
                <li key={i}>{mod}</li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}

function Totals({ order }: { order: Order }) {
  return (
    <div className="rounded-md bg-surface-2 p-4">
      <div className="flex items-baseline justify-between">
        <div className="font-medium">Subtotal</div>
        <div className="font-mono font-medium tabular-nums">
          {formatCAD(order.subtotal)}
        </div>
      </div>
      <p className="mt-1 text-xs italic text-foreground-subtle">
        Tax and total aren&rsquo;t computed in this build.
      </p>
    </div>
  );
}

function CallSidebarCard({ order }: { order: Order }) {
  return (
    <div className="rounded-md border border-border-subtle bg-surface-1 p-4">
      <div className="flex items-center gap-2">
        <Radio
          className="size-3 text-foreground-faint"
          aria-hidden
        />
        <span className="text-eyebrow">Call recording</span>
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        <div className="text-sm text-foreground-muted">
          <CallDuration order={order} />
        </div>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                disabled
                aria-label="Recording playback (coming in Phase 2)"
              >
                <Play className="mr-1 size-4" />
                Play
              </Button>
            </TooltipTrigger>
            <TooltipContent>Recording UI ships in PR 4 (calls)</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    </div>
  );
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
