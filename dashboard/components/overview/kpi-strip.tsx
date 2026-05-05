import { cn } from '@/lib/utils';

export type KpiItem = {
  eyebrow: string;
  value: string;
  caption?: string;
  // When set, treat `value` as a designed zero state: render it
  // smaller + muted, and append `zeroHint` as a subtitle line. The
  // page passes this only on KPIs where "0" is meaningful (e.g.
  // Orders today on a quiet morning) — the other KPIs have their own
  // sensible zero/low-value renderings.
  zeroHint?: string;
};

/**
 * Inline KPI strip — replaces the four boxy KPI cards.
 * See design-system.md → "KPI cards (overview page)".
 *
 * Horizontal flex with `divide-x` for the vertical hairlines between
 * cells. No outer border.
 */
export function KpiStrip({
  items,
  className,
}: {
  items: KpiItem[];
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex w-full divide-x divide-border-subtle',
        className,
      )}
    >
      {items.map((item, i) => {
        const isZeroState = item.zeroHint !== undefined && item.value === '0';
        return (
          <div key={i} className="flex flex-1 flex-col p-4">
            <span className="text-eyebrow">{item.eyebrow}</span>
            <span
              className={cn(
                'mt-2 font-mono font-semibold tabular-nums',
                isZeroState
                  ? 'text-xl text-foreground-muted'
                  : 'text-2xl',
              )}
            >
              {item.value}
            </span>
            {isZeroState ? (
              <span className="mt-1 text-sm text-foreground-subtle">
                {item.zeroHint}
              </span>
            ) : item.caption ? (
              <span className="mt-1 text-sm text-foreground-subtle">
                {item.caption}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
