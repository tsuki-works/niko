/**
 * Single source of truth for status visuals.
 *
 * Status is the most important signal in the product — see design-system.md.
 * Every status badge in the UI must derive from this map. New status values
 * go here first, then everywhere else.
 *
 * The CSS variables referenced below are defined in app/globals.css.
 */
import type { OrderStatus } from '@/lib/schemas/order';

type StatusStyle = {
  label: string;

  /** Tailwind classes for the badge background + text + border. */
  badgeClass: string;

  /** Inline style for the colored dot — uses CSS variables, not Tailwind, because we want the exact hue not a palette match. */
  dotStyle: { backgroundColor: string };

  /** True only for `in_progress` — drives the pulse animation. */
  pulse: boolean;
};

export const ORDER_STATUS_STYLES: Record<OrderStatus, StatusStyle> = {
  in_progress: {
    label: 'Live',
    badgeClass:
      'bg-[color:var(--status-live-bg)] text-[color:var(--status-live-fg)] border border-[color:var(--status-live)]/20',
    dotStyle: { backgroundColor: 'var(--status-live)' },
    pulse: true,
  },
  confirmed: {
    label: 'Confirmed',
    badgeClass:
      'bg-[color:var(--status-confirmed-bg)] text-[color:var(--status-confirmed-fg)] border border-[color:var(--status-confirmed)]/20',
    dotStyle: { backgroundColor: 'var(--status-confirmed)' },
    pulse: false,
  },
  preparing: {
    label: 'Preparing',
    badgeClass:
      'bg-[color:var(--status-preparing-bg)] text-[color:var(--status-preparing-fg)] border border-[color:var(--status-preparing)]/20',
    dotStyle: { backgroundColor: 'var(--status-preparing)' },
    pulse: false,
  },
  ready: {
    label: 'Ready',
    badgeClass:
      'bg-[color:var(--status-ready-bg)] text-[color:var(--status-ready-fg)] border border-[color:var(--status-ready)]/20',
    dotStyle: { backgroundColor: 'var(--status-ready)' },
    pulse: false,
  },
  completed: {
    label: 'Completed',
    badgeClass:
      'bg-[color:var(--status-completed-bg)] text-[color:var(--status-completed-fg)] border border-[color:var(--status-completed)]/30',
    dotStyle: { backgroundColor: 'var(--status-completed)' },
    pulse: false,
  },
  cancelled: {
    label: 'Cancelled',
    badgeClass:
      'bg-[color:var(--status-cancelled-bg)] text-[color:var(--status-cancelled-fg)] border border-[color:var(--status-cancelled)]/20',
    dotStyle: { backgroundColor: 'var(--status-cancelled)' },
    pulse: false,
  },
};

export function statusStyle(status: OrderStatus): StatusStyle {
  return ORDER_STATUS_STYLES[status];
}

export function statusLabel(status: OrderStatus): string {
  return ORDER_STATUS_STYLES[status].label;
}