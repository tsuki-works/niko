'use client';

import { useState, useTransition } from 'react';
import { toast } from 'sonner';

import { createMenuItemAction } from '@/app/actions/edit-menu';
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

export function AddItemDialog({
  category,
  onClose,
}: {
  category: string;
  onClose: () => void;
}) {
  const [name, setName] = useState('');
  const [price, setPrice] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    setError(null);
    if (!name.trim()) {
      setError('Name is required.');
      return;
    }
    const priceNum = Number(price);
    if (!Number.isFinite(priceNum) || priceNum < 0) {
      setError('Price must be a non-negative number.');
      return;
    }

    startTransition(async () => {
      const result = await createMenuItemAction({
        category,
        name: name.trim(),
        price: priceNum,
        description: description.trim() || undefined,
      });
      if (!result.success) {
        setError(result.error);
        return;
      }
      toast.success(`${name} added.`);
      onClose();
    });
  }

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add item to {category}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="item-name">Name</Label>
            <Input
              id="item-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="item-price">Price (CAD)</Label>
            <Input
              id="item-price"
              type="number"
              min="0"
              step="0.01"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="item-desc">Description (optional)</Label>
            <Input
              id="item-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
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
            {pending ? 'Adding…' : 'Add item'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
