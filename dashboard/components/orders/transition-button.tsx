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
import { type Order, orderShortId } from '@/lib/schemas/order';

type TransitionConfig = {
  label: string;
  pendingLabel: string;
  variant: 'default' | 'outline';
  successMessage: string;
  action: (input: { call_sid: string }) => Promise<TransitionActionResult>;
};

/**
 * Status-aware action button. Renders the next-action button for orders
 * in confirmed/preparing/ready; renders nothing for terminal or
 * not-yet-confirmed orders.
 *
 * No confirmation dialog — kitchen wants single-tap speed. Cancel
 * (which IS destructive) keeps its own dialog in CancelOrderButton.
 */
export function TransitionButton({ order }: { order: Order }) {
  const config = configFor(order);
  if (!config) return null;

  return <ActiveButton order={order} config={config} />;
}

function configFor(order: Order): TransitionConfig | null {
  switch (order.status) {
    case 'confirmed':
      return {
        label: 'Start Preparing',
        pendingLabel: 'Starting…',
        variant: 'default',
        successMessage: `Order ${orderShortId(order)} is now preparing`,
        action: (input) => markPreparingAction(input),
      };
    case 'preparing':
      return {
        label: 'Mark Ready',
        pendingLabel: 'Marking…',
        variant: 'default',
        successMessage: `Order ${orderShortId(order)} is ready`,
        action: (input) => markReadyAction(input),
      };
    case 'ready':
      return {
        label: 'Mark Completed',
        pendingLabel: 'Completing…',
        variant: 'outline',
        successMessage: `Order ${orderShortId(order)} is completed`,
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
}: {
  order: Order;
  config: TransitionConfig;
}) {
  const [isPending, startTransition] = useTransition();

  function onClick() {
    startTransition(async () => {
      const result = await config.action({ call_sid: order.call_sid });
      if (result.success) {
        toast.success(config.successMessage);
      } else {
        toast.error(result.error);
      }
    });
  }

  return (
    <Button
      variant={config.variant}
      size="sm"
      onClick={onClick}
      disabled={isPending}
    >
      {isPending ? config.pendingLabel : config.label}
    </Button>
  );
}
