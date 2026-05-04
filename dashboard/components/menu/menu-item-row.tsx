'use client';

import { Pencil, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { formatCAD } from '@/lib/formatters/money';
import { type MenuItem, isSizedItem } from '@/lib/schemas/menu';
import { cn } from '@/lib/utils';

type Props = {
  item: MenuItem;
  onEdit: () => void;
  onDelete: () => void;
};

/**
 * Single menu item row inside a <MenuSection>. Name on the left, price
 * on the right (mono tabular-nums); description below; edit/delete
 * affordances appear at full strength on icon hover, muted on row hover,
 * faint at rest.
 */
export function MenuItemRow({ item, onEdit, onDelete }: Props) {
  const unavailable = item.available === false;

  return (
    <article className="group/row flex flex-col gap-1">
      <div className="flex items-baseline gap-3">
        <h4
          className={cn(
            'font-medium leading-snug',
            unavailable ? 'text-foreground-muted line-through' : 'text-foreground',
          )}
        >
          {item.name}
          {unavailable ? (
            <span className="text-eyebrow ml-2 rounded-xs bg-surface-2 px-1.5 py-0.5">
              unavailable
            </span>
          ) : null}
        </h4>
        <PriceTag item={item} />
        <div className="flex items-center gap-2 text-foreground-faint group-hover/row:text-foreground-muted">
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={`Edit ${item.name}`}
            onClick={onEdit}
            className="size-7 hover:text-foreground"
          >
            <Pencil className="size-3.5" aria-hidden />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={`Delete ${item.name}`}
            onClick={onDelete}
            className="size-7 hover:text-foreground"
          >
            <Trash2 className="size-3.5" aria-hidden />
          </Button>
        </div>
      </div>
      {item.description ? (
        <p className="text-sm leading-relaxed text-foreground-muted">
          {item.description}
        </p>
      ) : null}
    </article>
  );
}

function PriceTag({ item }: { item: MenuItem }) {
  if (isSizedItem(item)) {
    const sizes = Object.entries(item.sizes);
    return (
      <span className="ml-auto flex items-baseline gap-2 font-mono text-sm tabular-nums">
        {sizes.map(([size, price], i) => (
          <span key={size} className="flex items-baseline gap-1.5">
            {i > 0 ? (
              <span aria-hidden className="text-foreground-faint">·</span>
            ) : null}
            <span className="text-eyebrow">{size}</span>
            <span>{formatCAD(price)}</span>
          </span>
        ))}
      </span>
    );
  }
  return (
    <span className="ml-auto font-mono text-sm font-medium tabular-nums">
      {formatCAD(item.price)}
    </span>
  );
}
