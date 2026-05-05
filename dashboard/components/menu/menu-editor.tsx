'use client';

import { useState } from 'react';
import { Plus } from 'lucide-react';
import { toast } from 'sonner';

import { AddCategoryDialog } from '@/components/menu/add-category-dialog';
import { AddItemDialog } from '@/components/menu/add-item-dialog';
import { ItemEditDialog } from '@/components/menu/item-edit-dialog';
import { MenuSection } from '@/components/menu/menu-section';
import { PageHeader } from '@/components/shared/page-header';
import { Button } from '@/components/ui/button';
import { deleteMenuItemAction } from '@/app/actions/edit-menu';
import {
  type Category,
  type MenuItem,
  humanizeCategoryKey,
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
            variant="secondary"
            className="border border-border"
            onClick={() => setAddingCategory(true)}
          >
            <Plus className="size-4" aria-hidden /> Add category
          </Button>
        }
      />

      <div className="flex flex-col gap-8">
        {categories.map((c) => (
          <MenuSection
            key={c.key}
            category={c}
            onAddItem={() => setAddingTo(c.key)}
            onEditItem={(item) => setEditing({ category: c.key, item })}
            onDeleteItem={(item) => void handleDelete(c.key, item.name)}
          />
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
