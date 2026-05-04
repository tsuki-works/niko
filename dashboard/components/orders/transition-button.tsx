'use client';

import { useTransition } from 'react';
import { toast } from 'sonner';

import {
  markPreparingAction,
  markReadyAction,
  markCompletedAction,
  type TransitionActionResult,
} from '@/app/actions/transition-order';
import { Button } from '@/components/ui/button';
import { useOptimisticStatus } from '@/components/orders/optimistic-status-context';
import { type Order, type OrderStatus, orderShortId } from '@/lib/schemas/order';
import { cn } from '@/lib/utils';

type Mode = 'compact' | 'detail';

type TransitionConfig = {
  label: string;
  pendingLabel: string;
  successMessage: string;
  targetStatus: OrderStatus;
  action: (input: { call_sid: string }) => Promise<TransitionActionResult>;
};

/**
 * Status-aware action button. Renders the next-action button for orders
 * in confirmed/preparing/ready; renders nothing for terminal or
 * not-yet-confirmed orders.
 *
 * `mode="compact"` (default) is for table rows + the overview kitchen
 * queue: short labels, 28px tall, secondary treatment. `mode="detail"`
 * is for the order detail page: full labels, 36px tall, primary
 * treatment.
 *
 * No confirmation dialog — kitchen wants single-tap speed. Cancel
 * (which IS destructive) keeps its own dialog in CancelOrderButton.
 */
export function TransitionButton({
  order,
  mode = 'compact',
}: {
  order: Order;
  mode?: Mode;
}) {
  const config = configFor(order, mode);
  if (!config) return null;

  return <ActiveButton order={order} config={config} mode={mode} />;
}

function configFor(order: Order, mode: Mode): TransitionConfig | null {
  switch (order.status) {
    case 'confirmed':
      return {
        label: mode === 'compact' ? 'Start' : 'Start preparing',
        pendingLabel: mode === 'compact' ? 'Starting…' : 'Starting…',
        successMessage: `Order ${orderShortId(order)} is now preparing`,
        targetStatus: 'preparing',
        action: (input) => markPreparingAction(input),
      };
    case 'preparing':
      return {
        label: mode === 'compact' ? 'Ready' : 'Mark ready',
        pendingLabel: 'Marking…',
        successMessage: `Order ${orderShortId(order)} is ready`,
        targetStatus: 'ready',
        action: (input) => markReadyAction(input),
      };
    case 'ready':
      return {
        label: mode === 'compact' ? 'Done' : 'Mark completed',
        pendingLabel: 'Completing…',
        successMessage: `Order ${orderShortId(order)} is completed`,
        targetStatus: 'completed',
        action: (input) => markCompletedAction(input),
      };
    case 'in_progress':
    case 'completed':
    case 'cancelled':
      return null;
  }
}

function ActiveButton({
  order,
  config,
  mode,
}: {
  order: Order;
  config: TransitionConfig;
  mode: Mode;
}) {
  const [isPending, startTransition] = useTransition();
  const { addOptimistic, clearOptimistic } = useOptimisticStatus();

  function onClick() {
    addOptimistic({
      call_sid: order.call_sid,
      status: config.targetStatus,
    });

    startTransition(async () => {
      const result = await config.action({ call_sid: order.call_sid });
      if (result.success) {
        toast.success(config.successMessage);
        // Don't clear here — OrdersFeed reconciles when onSnapshot catches up.
      } else {
        clearOptimistic(order.call_sid);
        toast.error(result.error);
      }
    });
  }

  // Compact (table) = secondary look. Detail = primary look.
  // shadcn's `secondary` variant maps `--secondary` → `--surface-2`
  // in our globals.css; we add `border` to give the visible outline
  // the design spec asks for ("subtle background, visible border").
  const isCompact = mode === 'compact';

  return (
    <Button
      variant={isCompact ? 'secondary' : 'default'}
      size={isCompact ? 'sm' : 'lg'}
      onClick={onClick}
      disabled={isPending}
      className={cn(isCompact && 'border border-border')}
    >
      {isPending ? config.pendingLabel : config.label}
    </Button>
  );
}
