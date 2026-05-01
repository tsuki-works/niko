'use client';

import { useState, useTransition } from 'react';
import { toast } from 'sonner';

import { createCategoryAction } from '@/app/actions/edit-menu';
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

export function AddCategoryDialog({ onClose }: { onClose: () => void }) {
  const [key, setKey] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    setError(null);
    const cleaned = key.trim().toLowerCase().replace(/\s+/g, '_');
    if (!/^[a-z0-9][a-z0-9_]*$/.test(cleaned)) {
      setError('Use letters, numbers, and underscores only. Must not start with an underscore.');
      return;
    }
    startTransition(async () => {
      const result = await createCategoryAction({ key: cleaned });
      if (!result.success) {
        setError(result.error);
        return;
      }
      toast.success(`Category ${cleaned} added.`);
      onClose();
    });
  }

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add category</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="cat-key">Key</Label>
          <Input
            id="cat-key"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="e.g. drinks or caribbean_appetizers"
            autoFocus
          />
          <p className="text-xs text-muted-foreground">
            Lowercase, underscores instead of spaces. Display name is
            generated automatically.
          </p>
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
            {pending ? 'Adding…' : 'Add category'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
