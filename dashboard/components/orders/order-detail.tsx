import Link from 'next/link';
import { ArrowLeft, Play } from 'lucide-react';

import { CallDuration } from '@/components/orders/call-duration';
import { CancelOrderButton } from '@/components/orders/cancel-order-button';
import { StatusBadge } from '@/components/orders/status-badge';
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

export function OrderDetail({ order }: { order: Order }) {
  return (
    <section className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
      <Header order={order} />
      <CallerCard order={order} />
      <ItemsCard order={order} />
      <SubtotalCard order={order} />
      {order.status === 'confirmed' && (
        <div className="pt-2">
          <CancelOrderButton callSid={order.call_sid} />
        </div>
      )}
    </section>
  );
}

function Header({ order }: { order: Order }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="ghost" size="sm" asChild>
        <Link href="/" aria-label="Back to orders">
          <ArrowLeft className="mr-1 h-4 w-4" />
          Back
        </Link>
      </Button>
      <h2 className="text-xl font-medium">Order {orderShortId(order)}</h2>
      <StatusBadge status={order.status} />
      <div className="ml-auto text-sm text-muted-foreground">
        {headerTimestamp(order)}
      </div>
    </div>
  );
}

function headerTimestamp(order: Order): React.ReactNode {
  switch (order.status) {
    case 'confirmed':
      return order.confirmed_at ? (
        <>
          Confirmed <LocalTime date={order.confirmed_at} mode="absolute" />
        </>
      ) : (
        <>Confirmed</>
      );
    case 'cancelled':
      return (
        <>
          Cancelled <LocalTime date={order.created_at} mode="absolute" />
        </>
      );
    case 'in_progress':
      return (
        <>
          Started <LocalTime date={order.created_at} mode="absolute" />
        </>
      );
  }
}

function CallerCard({ order }: { order: Order }) {
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4 p-4">
        <div>
          <div className="font-medium">{formatPhone(order.caller_phone)}</div>
          <div className="text-sm text-muted-foreground">
            {order.order_type ? capitalize(order.order_type) : 'Type unknown'}
          </div>
          {order.order_type === 'delivery' && order.delivery_address && (
            <div className="mt-1 text-sm text-muted-foreground">
              {order.delivery_address}
            </div>
          )}
        </div>
        <div className="text-right text-sm text-muted-foreground">
          <div>
            <CallDuration order={order} />
          </div>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled
                  className="mt-2"
                  aria-label="Recording playback (coming in Phase 2)"
                >
                  <Play className="mr-1 h-4 w-4" />
                  Recording
                </Button>
              </TooltipTrigger>
              <TooltipContent>Recording UI coming in Phase 2</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>
    </Card>
  );
}

function ItemsCard({ order }: { order: Order }) {
  if (order.items.length === 0) {
    return (
      <Card>
        <div className="p-4 text-sm text-muted-foreground">No items.</div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="divide-y">
        {order.items.map((item, idx) => (
          <div key={idx} className="p-4">
            <div className="flex items-baseline justify-between gap-4">
              <div className="font-medium">{formatLineItemTitle(item)}</div>
              <div className="tabular-nums font-medium">
                {formatCAD(item.line_total)}
              </div>
            </div>
            {item.modifications.length > 0 && (
              <ul className="mt-2 space-y-0.5 pl-4 text-sm text-muted-foreground list-disc">
                {item.modifications.map((mod, i) => (
                  <li key={i}>{mod}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function SubtotalCard({ order }: { order: Order }) {
  return (
    <div className="rounded-xl border bg-muted/40 p-4">
      <div className="flex items-baseline justify-between">
        <div className="font-medium">Subtotal</div>
        <div className="tabular-nums font-medium">
          {formatCAD(order.subtotal)}
        </div>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        Tax and total aren&rsquo;t computed in Phase 1.
      </div>
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border bg-card">{children}</div>;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
