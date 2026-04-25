import type { OrderStatus } from '@/lib/schemas/order';

export type StatusStyle = {
  label: string;
  className: string;
};

// Pills use the semantic color at low-opacity bg and the same color
// saturated for text. The *-foreground tokens are reserved for solid
// surfaces (buttons, toasts) where the color is the background.
const STYLES: Record<OrderStatus, StatusStyle> = {
  in_progress: {
    label: 'Live call',
    className: 'bg-warning/15 text-warning border-warning/30',
  },
  confirmed: {
    label: 'Confirmed',
    className: 'bg-success/15 text-success border-success/40',
  },
  cancelled: {
    label: 'Cancelled',
    className: 'bg-destructive/15 text-destructive border-destructive/30',
  },
};

export function statusStyle(status: OrderStatus): StatusStyle {
  return STYLES[status];
}
