'use client';

import { useState, useTransition } from 'react';
import { toast } from 'sonner';

import { updateRestaurantAction } from '@/app/actions/update-restaurant';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { DayHours, HoursStructured, Restaurant } from '@/lib/schemas/restaurant';

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
    <section className="flex flex-col gap-4">
      <h3 className="text-base font-medium">Hours</h3>
      <p className="text-xs text-muted-foreground">
        Times are local to the restaurant. Use 24-hour format. Niko reads
        these to callers and routes after-hours calls to voicemail.
      </p>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Day</TableHead>
            <TableHead>Open</TableHead>
            <TableHead>Close</TableHead>
            <TableHead>Closed</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {DAYS.map(({ key, label }) => {
            const day = hours[key];
            return (
              <TableRow key={key}>
                <TableCell className="font-medium">{label}</TableCell>
                <TableCell>
                  <Label htmlFor={`open-${key}`} className="sr-only">
                    {label} open time
                  </Label>
                  <Input
                    id={`open-${key}`}
                    type="time"
                    value={day.open}
                    disabled={day.closed}
                    onChange={(e) => update(key, { open: e.target.value })}
                  />
                </TableCell>
                <TableCell>
                  <Label htmlFor={`close-${key}`} className="sr-only">
                    {label} close time
                  </Label>
                  <Input
                    id={`close-${key}`}
                    type="time"
                    value={day.close}
                    disabled={day.closed}
                    onChange={(e) => update(key, { close: e.target.value })}
                  />
                </TableCell>
                <TableCell>
                  <Label htmlFor={`closed-${key}`} className="sr-only">
                    {label} closed
                  </Label>
                  <input
                    id={`closed-${key}`}
                    type="checkbox"
                    checked={day.closed}
                    onChange={(e) => update(key, { closed: e.target.checked })}
                  />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <div className="flex justify-end">
        <Button type="button" onClick={handleSave} disabled={pending}>
          {pending ? 'Saving…' : 'Save hours'}
        </Button>
      </div>
    </section>
  );
}
