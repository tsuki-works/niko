import type { OrderStatus } from '@/lib/schemas/order';

export type StatusStyle = {
  label: string;
  className: string;
};

const STYLES: Record<OrderStatus, StatusStyle> = {
  in_progress: {
    label: 'Live call',
    className:
      'bg-amber-500/15 text-amber-700 border-amber-500/30 dark:text-amber-300',
  },
  confirmed: {
    label: 'Confirmed',
    className:
      'bg-emerald-500/15 text-emerald-700 border-emerald-500/30 dark:text-emerald-300',
  },
  cancelled: {
    label: 'Cancelled',
    className:
      'bg-rose-500/15 text-rose-700 border-rose-500/30 dark:text-rose-300',
  },
};

export function statusStyle(status: OrderStatus): StatusStyle {
  return STYLES[status];
}
