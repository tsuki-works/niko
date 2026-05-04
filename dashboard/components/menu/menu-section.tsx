'use client';

import { Plus } from 'lucide-react';

import { MenuItemRow } from '@/components/menu/menu-item-row';
import { Button } from '@/components/ui/button';
import {
  type Category,
  type MenuItem,
  humanizeCategoryKey,
} from '@/lib/schemas/menu';

type Props = {
  category: Category;
  onAddItem: () => void;
  onEditItem: (item: MenuItem) => void;
  onDeleteItem: (item: MenuItem) => void;
};

/**
 * Category section: header (name + Add item) and a 2-column grid of
 * <MenuItemRow>. Sections are expected to be stacked with 32px gaps
 * by the parent (handled in MenuEditor's outer flex).
 */
export function MenuSection({
  category,
  onAddItem,
  onEditItem,
  onDeleteItem,
}: Props) {
  const headingId = `heading-${category.key}`;

  return (
    <section
      id={`category-${category.key}`}
      aria-labelledby={headingId}
      className="scroll-mt-8"
    >
      <header className="mb-4 flex items-baseline justify-between gap-3">
        <h3 id={headingId} className="text-lg font-medium">
          {humanizeCategoryKey(category.key)}
        </h3>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          className="border border-border"
          onClick={onAddItem}
        >
          <Plus className="size-4" aria-hidden /> Add item
        </Button>
      </header>

      <ul className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
        {category.items.map((item, idx) => (
          <li key={`${category.key}-${idx}-${item.name}`}>
            <MenuItemRow
              item={item}
              onEdit={() => onEditItem(item)}
              onDelete={() => onDeleteItem(item)}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
