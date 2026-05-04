/**
 * Status badge — the single most important component in the product.
 * See design-system.md → "Status badge anatomy" for the spec.
 *
 * Anatomy:
 *   [● Confirmed]
 *
 * - 6px dot in the status primary color, optionally pulsing for `live`
 * - 6px gap
 * - Sentence-case label, 12px / weight 500
 * - Tinted background, low-alpha bordered pill (full radius)
 */
import type { OrderStatus } from '@/lib/schemas/order';
import { statusStyle } from '@/lib/status-styles';
import { cn } from '@/lib/utils';

type StatusBadgeProps = {
  status: OrderStatus;
  className?: string;
};

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const style = statusStyle(status);

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
        style.badgeClass,
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn('size-1.5 rounded-full', style.pulse && 'animate-pulse-dot')}
        style={style.dotStyle}
      />
      {style.label}
    </span>
  );
}