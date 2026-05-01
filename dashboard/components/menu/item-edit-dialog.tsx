'use client';

import { useState, useTransition } from 'react';
import { toast } from 'sonner';

import { updateMenuItemAction } from '@/app/actions/edit-menu';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { type MenuItem, isSizedItem } from '@/lib/schemas/menu';

export function ItemEditDialog({
  category,
  item,
  onClose,
}: {
  category: string;
  item: MenuItem;
  onClose: () => void;
}) {
  const [name, setName] = useState(item.name);
  const [price, setPrice] = useState(
    isSizedItem(item) ? '' : String(item.price),
  );
  const [description, setDescription] = useState(item.description ?? '');
  const [available, setAvailable] = useState(item.available !== false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    setError(null);
    const patch: Record<string, unknown> = {};
    if (name.trim() !== item.name) patch.new_name = name.trim();
    if (description.trim() !== (item.description ?? '')) {
      patch.description = description.trim();
    }
    if (available !== (item.available !== false)) {
      patch.available = available;
    }
    if (!isSizedItem(item)) {
      const priceNum = Number(price);
      if (!Number.isFinite(priceNum) || priceNum < 0) {
        setError('Price must be a non-negative number.');
        return;
      }
      if (priceNum !== item.price) patch.price = priceNum;
    }

    if (Object.keys(patch).length === 0) {
      onClose();
      return;
    }

    startTransition(async () => {
      const result = await updateMenuItemAction({
        category,
        name: item.name,
        patch,
      });
      if (!result.success) {
        setError(result.error);
        return;
      }
      toast.success(`${item.name} updated.`);
      onClose();
    });
  }

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit {item.name}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-name">Name</Label>
            <Input
              id="edit-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          {isSizedItem(item) ? (
            <p className="text-xs text-muted-foreground">
              This item has size variants. Editing size prices isn&apos;t yet
              supported in the dashboard — contact support to update.
            </p>
          ) : (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="edit-price">Price (CAD)</Label>
              <Input
                id="edit-price"
                type="number"
                min="0"
                step="0.01"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-desc">Description</Label>
            <Input
              id="edit-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              id="edit-available"
              type="checkbox"
              checked={available}
              onChange={(e) => setAvailable(e.target.checked)}
            />
            <Label htmlFor="edit-available">Available right now</Label>
          </div>
          {error ? (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button onClick={submit} disabled={pending} type="button">
            {pending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
