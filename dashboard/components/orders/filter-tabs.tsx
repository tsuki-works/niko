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
  { key: 'all', label: 'All', href: '/' },
  { key: 'in_progress', label: 'Live', href: '/?status=in_progress' },
  { key: 'confirmed', label: 'Confirmed', href: '/?status=confirmed' },
  { key: 'cancelled', label: 'Cancelled', href: '/?status=cancelled' },
];

export function FilterTabs({
  active,
  counts,
}: {
  active: OrderStatus | undefined;
  counts: CountsByStatus;
}) {
  return (
    <nav className="flex flex-wrap items-center gap-2">
      {TABS.map((tab) => {
        const isActive = tab.key === 'all' ? !active : active === tab.key;
        const count = counts[tab.key] ?? 0;
        return (
          <Link
            key={tab.key}
            href={tab.href}
            className={cn(
              'inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm transition-colors',
              isActive
                ? 'border-foreground/20 bg-foreground text-background'
                : 'border-border bg-background text-foreground hover:bg-muted',
            )}
            aria-current={isActive ? 'page' : undefined}
          >
            <span>{tab.label}</span>
            <span
              className={cn(
                'rounded-full px-2 py-0.5 text-xs tabular-nums',
                isActive
                  ? 'bg-background/20 text-background'
                  : 'bg-muted text-muted-foreground',
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
