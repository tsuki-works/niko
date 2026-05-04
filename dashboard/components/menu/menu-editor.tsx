'use client';

import { useState } from 'react';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { AddCategoryDialog } from '@/components/menu/add-category-dialog';
import { AddItemDialog } from '@/components/menu/add-item-dialog';
import { ItemEditDialog } from '@/components/menu/item-edit-dialog';
import { PageHeader } from '@/components/shared/page-header';
import { Button } from '@/components/ui/button';
import { deleteMenuItemAction } from '@/app/actions/edit-menu';
import { formatCAD } from '@/lib/formatters/money';
import {
  type Category,
  type MenuItem,
  humanizeCategoryKey,
  isSizedItem,
} from '@/lib/schemas/menu';

type Props = {
  categories: Category[];
  itemCount: number;
  restaurantName: string;
};

export function MenuEditor({
  categories,
  itemCount,
  restaurantName,
}: Props) {
  const [editing, setEditing] = useState<{
    category: string;
    item: MenuItem;
  } | null>(null);
  const [addingTo, setAddingTo] = useState<string | null>(null);
  const [addingCategory, setAddingCategory] = useState(false);

  async function handleDelete(category: string, name: string) {
    if (!confirm(`Delete "${name}" from ${humanizeCategoryKey(category)}?`)) {
      return;
    }
    const result = await deleteMenuItemAction({ category, name });
    if (!result.success) {
      toast.error(`Delete failed: ${result.error}`);
      return;
    }
    toast.success('Item deleted.');
  }

  return (
    <section className="flex flex-1 flex-col p-6 lg:p-10">
      <PageHeader
        title="Menu"
        subtitle={
          <>
            {restaurantName}
            <span className="mx-2 text-foreground-faint">·</span>
            <span className="tabular-nums">{categories.length}</span>{' '}
            {categories.length === 1 ? 'category' : 'categories'}
            <span className="mx-2 text-foreground-faint">·</span>
            <span className="tabular-nums">{itemCount}</span>{' '}
            {itemCount === 1 ? 'item' : 'items'}
          </>
        }
        actions={
          <Button
            type="button"
            variant="outline"
            onClick={() => setAddingCategory(true)}
          >
            <Plus className="size-4" /> Add category
          </Button>
        }
      />

      <div className="flex flex-col gap-14">
        {categories.map((c) => (
          <section
            key={c.key}
            id={`category-${c.key}`}
            className="scroll-mt-8"
          >
            <header className="mb-6 flex items-baseline gap-4 border-b border-border pb-3">
              <h3 className="text-xl font-medium tracking-tight">
                {humanizeCategoryKey(c.key)}
              </h3>
              <span aria-hidden className="h-px flex-1 bg-border/60" />
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setAddingTo(c.key)}
              >
                <Plus className="h-4 w-4" /> Add item
              </Button>
            </header>

            <ul className="grid gap-x-12 gap-y-6 sm:grid-cols-2">
              {c.items.map((item, idx) => (
                <li key={`${c.key}-${idx}-${item.name}`}>
                  <article className="flex flex-col gap-1.5">
                    <div className="flex items-baseline gap-3">
                      <h4
                        className={`font-medium leading-snug ${
                          item.available === false
                            ? 'text-muted-foreground line-through'
                            : 'text-foreground'
                        }`}
                      >
                        {item.name}
                        {item.available === false ? (
                          <span className="ml-2 rounded-md bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                            unavailable
                          </span>
                        ) : null}
                      </h4>
                      <span
                        aria-hidden
                        className="min-w-4 flex-1 translate-y-[-0.25rem] border-b border-dotted border-border"
                      />
                      <span className="font-mono text-sm tabular-nums text-foreground">
                        {isSizedItem(item)
                          ? Object.entries(item.sizes)
                              .map(
                                ([size, price]) =>
                                  `${size} ${formatCAD(price)}`,
                              )
                              .join(' · ')
                          : formatCAD(item.price)}
                      </span>
                      <Button
                        size="icon"
                        variant="ghost"
                        aria-label={`Edit ${item.name}`}
                        onClick={() =>
                          setEditing({ category: c.key, item })
                        }
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        aria-label={`Delete ${item.name}`}
                        onClick={() => handleDelete(c.key, item.name)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                    {item.description ? (
                      <p className="text-xs leading-relaxed text-muted-foreground">
                        {item.description}
                      </p>
                    ) : null}
                  </article>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      {editing ? (
        <ItemEditDialog
          category={editing.category}
          item={editing.item}
          onClose={() => setEditing(null)}
        />
      ) : null}
      {addingTo ? (
        <AddItemDialog
          category={addingTo}
          onClose={() => setAddingTo(null)}
        />
      ) : null}
      {addingCategory ? (
        <AddCategoryDialog onClose={() => setAddingCategory(false)} />
      ) : null}
    </section>
  );
}
