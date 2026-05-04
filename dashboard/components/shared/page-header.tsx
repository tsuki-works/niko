import type { ReactNode } from 'react';

import { LiveIndicator } from '@/components/shared/live-indicator';
import { cn } from '@/lib/utils';

type Props = {
  title: string;
  subtitle?: ReactNode;
  liveIndicator?: boolean;
  actions?: ReactNode;
  className?: string;
};

export function PageHeader({
  title,
  subtitle,
  liveIndicator = false,
  actions,
  className,
}: Props) {
  const hasRight = liveIndicator || Boolean(actions);
  return (
    <header
      className={cn(
        'mb-6 flex flex-wrap items-center justify-between gap-3',
        className,
      )}
    >
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-[3px] text-sm text-foreground-muted">{subtitle}</p>
        ) : null}
      </div>
      {hasRight ? (
        <div className="flex items-center gap-3">
          {liveIndicator ? <LiveIndicator /> : null}
          {actions}
        </div>
      ) : null}
    </header>
  );
}
