import Link from 'next/link';

import type { OrderStatus } from '@/lib/schemas/order';
import { cn } from '@/lib/utils';

export type CountsByStatus = Record<OrderStatus | 'all', number>;

type Tab = {
  key: 'all' | OrderStatus;
  label: string;
  href: string;
};

const TABS: Tab[] = [
  { key: 'all', label: 'All', href: '/orders' },
  { key: 'in_progress', label: 'Live', href: '/orders?status=in_progress' },
  { key: 'confirmed', label: 'Confirmed', href: '/orders?status=confirmed' },
  { key: 'preparing', label: 'Preparing', href: '/orders?status=preparing' },
  { key: 'ready', label: 'Ready', href: '/orders?status=ready' },
  { key: 'completed', label: 'Completed', href: '/orders?status=completed' },
  { key: 'cancelled', label: 'Cancelled', href: '/orders?status=cancelled' },
];

export function FilterTabs({
  active,
  counts,
}: {
  active: OrderStatus | undefined;
  counts: CountsByStatus;
}) {
  return (
    <nav
      aria-label="Filter orders by status"
      className="flex flex-wrap items-center gap-1 border-t border-border-subtle pt-3"
    >
      {TABS.map((tab) => {
        const isActive = tab.key === 'all' ? !active : active === tab.key;
        const count = counts[tab.key] ?? 0;
        return (
          <Link
            key={tab.key}
            href={tab.href}
            aria-current={isActive ? 'page' : undefined}
            className={cn(
              'inline-flex h-7 items-center gap-2 rounded-sm px-2.5 text-sm transition-colors',
              isActive
                ? 'bg-surface-2 text-foreground'
                : 'text-foreground-muted hover:bg-surface-2/60 hover:text-foreground',
            )}
          >
            <span>{tab.label}</span>
            <span
              className={cn(
                'inline-flex h-4 min-w-4 items-center justify-center rounded-xs px-1 text-xs tabular-nums',
                isActive
                  ? 'bg-surface-3 text-foreground-subtle'
                  : 'bg-surface-1 text-foreground-subtle',
              )}
            >
              {count}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
