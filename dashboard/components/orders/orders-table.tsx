import Link from 'next/link';
import { PhoneIncoming } from 'lucide-react';

import { LocalTime } from '@/components/shared/local-time';
import { StatusBadge } from '@/components/orders/status-badge';
import { type Order, orderShortId } from '@/lib/schemas/order';
import { formatCAD } from '@/lib/formatters/money';
import { formatPhone } from '@/lib/formatters/phone';
import { cn } from '@/lib/utils';

const MAX_ITEMS_LINE = 48;

export function OrdersTable({
  orders,
  twilioPhone,
}: {
  orders: Order[];
  twilioPhone: string;
}) {
  if (orders.length === 0) return <EmptyState twilioPhone={twilioPhone} />;

  return (
    <div className="overflow-hidden rounded-xl border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted/40 text-muted-foreground">
          <tr>
            <Th className="w-28">Order</Th>
            <Th className="w-24">Time</Th>
            <Th>Items</Th>
            <Th className="w-32 text-right">Subtotal</Th>
            <Th className="w-32">Status</Th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <OrderRow key={order.call_sid} order={order} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OrderRow({ order }: { order: Order }) {
  const isLive = order.status === 'in_progress';
  const isCancelled = order.status === 'cancelled';
  const mutedCell = isCancelled ? 'text-muted-foreground' : '';

  const itemsSummary =
    order.items.length === 0
      ? '—'
      : truncate(order.items.map(shortItem).join(', '), MAX_ITEMS_LINE);
  const secondary = [
    order.order_type ? capitalize(order.order_type) : null,
    formatPhone(order.caller_phone),
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <tr className="border-t transition-colors hover:bg-muted/40">
      <Td className={cn('py-3', mutedCell)}>
        <Link
          href={`/orders/${encodeURIComponent(order.call_sid)}`}
          className="flex items-center gap-2 font-medium"
        >
          {isLive && (
            <span
              aria-hidden
              className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500"
            />
          )}
          {orderShortId(order)}
        </Link>
      </Td>
      <Td className={cn('text-muted-foreground', mutedCell)}>
        <Link href={`/orders/${encodeURIComponent(order.call_sid)}`}>
          {isLive ? (
            'now'
          ) : (
            <LocalTime date={order.created_at} mode="relative" />
          )}
        </Link>
      </Td>
      <Td className={mutedCell}>
        <Link
          href={`/orders/${encodeURIComponent(order.call_sid)}`}
          className="block"
        >
          <div className={isLive ? 'italic' : ''}>
            {isLive ? `Building… ${itemsSummary}` : itemsSummary}
          </div>
          {secondary && (
            <div className="text-xs text-muted-foreground">{secondary}</div>
          )}
        </Link>
      </Td>
      <Td
        className={cn(
          'text-right font-medium tabular-nums',
          mutedCell,
        )}
      >
        <Link href={`/orders/${encodeURIComponent(order.call_sid)}`}>
          {formatCAD(order.subtotal)}
        </Link>
      </Td>
      <Td>
        <Link href={`/orders/${encodeURIComponent(order.call_sid)}`}>
          <StatusBadge status={order.status} />
        </Link>
      </Td>
    </tr>
  );
}

function Th({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <th
      className={cn(
        'px-4 py-2 text-xs font-medium uppercase tracking-wide',
        className,
      )}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <td className={cn('px-4 py-3 align-top', className)}>{children}</td>;
}

function EmptyState({ twilioPhone }: { twilioPhone: string }) {
  const display = formatPhone(twilioPhone);
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-16 text-center">
      <PhoneIncoming className="mb-4 h-8 w-8 text-muted-foreground" />
      <p className="text-base font-medium">Waiting for first order</p>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">
        {display
          ? `Calls to ${display} will appear here in real time.`
          : 'No Twilio number is assigned to this restaurant yet — assign one to start receiving calls.'}
      </p>
    </div>
  );
}

function shortItem(item: {
  quantity: number;
  size?: string | null | undefined;
  name: string;
}): string {
  const size = item.size ? abbrevSize(item.size) + ' ' : '';
  return `${item.quantity}× ${size}${item.name.toLowerCase()}`;
}

function abbrevSize(size: string): string {
  const lower = size.toLowerCase();
  if (lower.startsWith('l')) return 'Lg';
  if (lower.startsWith('m')) return 'Md';
  if (lower.startsWith('s')) return 'Sm';
  return capitalize(size);
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1).trimEnd() + '…';
}
