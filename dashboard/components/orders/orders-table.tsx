'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { PhoneIncoming } from 'lucide-react';

import { LocalTime } from '@/components/shared/local-time';
import { StatusBadge } from '@/components/orders/status-badge';
import { TransitionButton } from '@/components/orders/transition-button';
import { type Order, orderShortId } from '@/lib/schemas/order';
import { formatCAD } from '@/lib/formatters/money';
import { formatPhone } from '@/lib/formatters/phone';
import { cn } from '@/lib/utils';

const MAX_ITEMS_LINE = 48;

export function OrdersTable({
  orders,
  twilioPhone,
  freshIds,
}: {
  orders: Order[];
  twilioPhone: string;
  freshIds?: ReadonlySet<string>;
}) {
  if (orders.length === 0) return <EmptyState twilioPhone={twilioPhone} />;

  return (
    <div className="overflow-hidden">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border-subtle text-foreground-muted">
            <Th className="w-28">Order</Th>
            <Th className="w-24">Time</Th>
            <Th>Items</Th>
            <Th className="w-28 text-right">Subtotal</Th>
            <Th className="w-24">Status</Th>
            <Th className="w-24">Action</Th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <OrderRow
              key={order.call_sid}
              order={order}
              isFresh={freshIds?.has(order.call_sid) ?? false}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OrderRow({ order, isFresh }: { order: Order; isFresh: boolean }) {
  const router = useRouter();

  const isLive = order.status === 'in_progress';

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

  const detailHref = `/orders/${encodeURIComponent(order.call_sid)}`;

  return (
    <tr
      onClick={() => {
        // Don't navigate when the user is selecting text — kitchen
        // staff routinely copy order IDs / phone numbers to other
        // windows. Released drag-selection would otherwise eat them.
        if (window.getSelection()?.toString()) return;
        router.push(detailHref);
      }}
      className={cn(
        'cursor-pointer border-b border-border-subtle transition-colors hover:bg-surface-2/40',
        isFresh && 'animate-row-enter',
      )}
      data-fresh={isFresh ? 'true' : undefined}
    >
      {/* Cell 1 — the only <Link> in the row. The cell-1 link is the
          single keyboard target per row; cells 2-5 are plain content
          and the <tr> onClick handles mouse navigation. <TransitionButton>
          in cell 6 stays independently focusable and stops propagation
          on its own click. */}
      <Td className="font-mono text-xs text-foreground-muted">
        <Link
          href={detailHref}
          aria-label={`View order ${orderShortId(order)}`}
          className="block"
        >
          {orderShortId(order)}
        </Link>
      </Td>
      <Td className="text-foreground-muted">
        <span
          data-testid={`order-time-${order.call_sid}`}
          data-anchor-iso={timeColumnAnchor(order).toISOString()}
        >
          {isLive ? (
            'now'
          ) : (
            <LocalTime
              date={timeColumnAnchor(order)}
              mode="relative"
            />
          )}
        </span>
      </Td>
      <Td>
        <div className={cn('truncate', isLive && 'italic')}>
          {isLive ? `Building… ${itemsSummary}` : itemsSummary}
        </div>
        {secondary && (
          <div className="text-xs text-foreground-faint">{secondary}</div>
        )}
      </Td>
      <Td className="text-right font-mono font-medium tabular-nums">
        {formatCAD(order.subtotal)}
      </Td>
      <Td>
        <StatusBadge status={order.status} />
      </Td>
      <Td>
        <TransitionButton order={order} />
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
        'px-2.5 py-2.5 text-xs font-medium uppercase tracking-wide',
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
  return (
    <td className={cn('px-2.5 py-2.5 align-middle', className)}>{children}</td>
  );
}

function EmptyState({ twilioPhone }: { twilioPhone: string }) {
  const display = formatPhone(twilioPhone);
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
      <PhoneIncoming
        className="size-8 text-foreground-faint"
        aria-hidden
      />
      <p className="text-md font-medium">No orders yet</p>
      <p className="max-w-sm text-sm text-foreground-muted">
        {display
          ? `Calls to ${display} will appear here in real time.`
          : 'No Twilio number is assigned to this restaurant yet — assign one to start receiving calls.'}
      </p>
    </div>
  );
}

function timeColumnAnchor(order: Order): Date {
  switch (order.status) {
    case 'preparing':
      return order.preparing_at ?? order.created_at;
    case 'ready':
      return order.ready_at ?? order.created_at;
    default:
      return order.created_at;
  }
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
