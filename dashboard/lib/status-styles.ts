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
  // Active in the kitchen — amber tone signals "this needs attention".
  // Reuses the warning token; intentionally adjacent to in_progress
  // visually because both are "active" states from the kitchen's POV.
  preparing: {
    label: 'Preparing',
    className: 'bg-amber-500/15 text-amber-600 border-amber-500/30 dark:text-amber-400',
  },
  // Done cooking, awaiting handoff. Uses success tones (different shade
  // than confirmed) — emerald is the brand "things are going well" color.
  ready: {
    label: 'Ready',
    className: 'bg-emerald-500/15 text-emerald-600 border-emerald-500/40 dark:text-emerald-400',
  },
  // Terminal, no action required. Muted neutral so the eye skips past
  // them in a busy queue.
  completed: {
    label: 'Completed',
    className: 'bg-muted text-muted-foreground border-border',
  },
  cancelled: {
    label: 'Cancelled',
    className: 'bg-destructive/15 text-destructive border-destructive/30',
  },
};

export function statusStyle(status: OrderStatus): StatusStyle {
  return STYLES[status];
}
