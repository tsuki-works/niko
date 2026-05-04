import { cn } from '@/lib/utils';

export type KpiItem = {
  eyebrow: string;
  value: string;
  caption?: string;
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
      {items.map((item, i) => (
        <div key={i} className="flex flex-1 flex-col p-4">
          <span className="text-eyebrow">{item.eyebrow}</span>
          <span className="mt-2 font-mono text-2xl font-semibold tabular-nums">
            {item.value}
          </span>
          {item.caption ? (
            <span className="mt-1 text-sm text-foreground-subtle">
              {item.caption}
            </span>
          ) : null}
        </div>
      ))}
    </div>
  );
}
