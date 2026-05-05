'use client';

import { useState, useTransition } from 'react';
import { toast } from 'sonner';

import { updateRestaurantAction } from '@/app/actions/update-restaurant';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type {
  DayHours,
  HoursStructured,
  Restaurant,
} from '@/lib/schemas/restaurant';

const DAYS: { key: keyof HoursStructured; label: string }[] = [
  { key: 'mon', label: 'Monday' },
  { key: 'tue', label: 'Tuesday' },
  { key: 'wed', label: 'Wednesday' },
  { key: 'thu', label: 'Thursday' },
  { key: 'fri', label: 'Friday' },
  { key: 'sat', label: 'Saturday' },
  { key: 'sun', label: 'Sunday' },
];

const DEFAULT_DAY: DayHours = { open: '11:00', close: '22:00', closed: false };

function seedHours(r: Restaurant): HoursStructured {
  if (r.hours_structured) return r.hours_structured;
  return {
    mon: { ...DEFAULT_DAY },
    tue: { ...DEFAULT_DAY },
    wed: { ...DEFAULT_DAY },
    thu: { ...DEFAULT_DAY },
    fri: { ...DEFAULT_DAY },
    sat: { ...DEFAULT_DAY },
    sun: { ...DEFAULT_DAY },
  };
}

export function HoursEditor({ restaurant }: { restaurant: Restaurant }) {
  const [hours, setHours] = useState<HoursStructured>(seedHours(restaurant));
  const [pending, startTransition] = useTransition();

  function update(day: keyof HoursStructured, patch: Partial<DayHours>) {
    setHours((prev) => ({
      ...prev,
      [day]: { ...prev[day], ...patch },
    }));
  }

  function handleSave() {
    startTransition(async () => {
      const result = await updateRestaurantAction({ hours_structured: hours });
      if (!result.success) {
        toast.error(`Save failed: ${result.error}`);
        return;
      }
      toast.success('Hours saved.');
    });
  }

  return (
    <section className="rounded-md border border-border-subtle bg-surface-1 p-6">
      <h3 className="text-md font-medium">Hours</h3>
      <p className="mt-1 text-sm text-foreground-subtle">
        Times are local to the restaurant. Use 24-hour format. Niko reads
        these to callers and routes after-hours calls to voicemail.
      </p>

      <div className="mt-4 flex flex-col gap-3">
        {DAYS.map(({ key, label }) => {
          const day = hours[key];
          return (
            <div
              key={key}
              className="flex flex-wrap items-center gap-3"
            >
              <span className="w-25 shrink-0 text-sm font-medium">
                {label}
              </span>
              <Label htmlFor={`open-${key}`} className="sr-only">
                {label} open time
              </Label>
              <Input
                id={`open-${key}`}
                type="time"
                value={day.open}
                disabled={day.closed}
                onChange={(e) => update(key, { open: e.target.value })}
                className="w-28"
              />
              <span className="text-sm text-foreground-muted">to</span>
              <Label htmlFor={`close-${key}`} className="sr-only">
                {label} close time
              </Label>
              <Input
                id={`close-${key}`}
                type="time"
                value={day.close}
                disabled={day.closed}
                onChange={(e) => update(key, { close: e.target.value })}
                className="w-28"
              />
              <label
                htmlFor={`closed-${key}`}
                className="ml-auto inline-flex cursor-pointer items-center gap-2 text-sm text-foreground-muted"
              >
                <input
                  id={`closed-${key}`}
                  type="checkbox"
                  checked={day.closed}
                  onChange={(e) => update(key, { closed: e.target.checked })}
                  aria-label={`${label} closed`}
                  className="size-4 accent-brand"
                />
                Closed
              </label>
            </div>
          );
        })}
      </div>

      <div className="mt-6 flex justify-end">
        <Button type="button" size="lg" onClick={handleSave} disabled={pending}>
          {pending ? 'Saving…' : 'Save hours'}
        </Button>
      </div>
    </section>
  );
}
