'use client';

import { useState, useTransition } from 'react';
import { toast } from 'sonner';

import { updateRestaurantAction } from '@/app/actions/update-restaurant';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { Restaurant } from '@/lib/schemas/restaurant';

const E164 = /^\+\d{8,15}$/;

export function RestaurantInfoForm({ restaurant }: { restaurant: Restaurant }) {
  const [name, setName] = useState(restaurant.name);
  const [address, setAddress] = useState(restaurant.address);
  const [displayPhone, setDisplayPhone] = useState(restaurant.display_phone);
  const [fallbackPhone, setFallbackPhone] = useState(
    restaurant.fallback_phone ?? '',
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function buildPatch() {
    const patch: Record<string, unknown> = {};
    if (name !== restaurant.name) patch.name = name;
    if (address !== restaurant.address) patch.address = address;
    if (displayPhone !== restaurant.display_phone)
      patch.display_phone = displayPhone;
    const trimmedFallback = fallbackPhone.trim();
    const restaurantFallback = restaurant.fallback_phone ?? '';
    if (trimmedFallback !== restaurantFallback) {
      patch.fallback_phone = trimmedFallback === '' ? null : trimmedFallback;
    }
    return patch;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const trimmedFallback = fallbackPhone.trim();
    if (trimmedFallback !== '' && !E164.test(trimmedFallback)) {
      setError('Fallback number must be in E.164 format (e.g. +15551234567).');
      return;
    }

    const patch = buildPatch();
    if (Object.keys(patch).length === 0) {
      toast.info('Nothing to save.');
      return;
    }

    startTransition(async () => {
      const result = await updateRestaurantAction(patch);
      if (!result.success) {
        setError(result.error);
        toast.error('Save failed.');
        return;
      }
      toast.success('Saved.');
    });
  }

  return (
    <section className="rounded-md border border-border-subtle bg-surface-1 p-6">
      <h3 className="text-md font-medium">Restaurant info</h3>
      <form className="mt-4 flex flex-col gap-4" onSubmit={handleSubmit}>
        <Field
          id="restaurant-name"
          label="Restaurant name"
          value={name}
          onChange={setName}
        />

        <Field
          id="address"
          label="Address"
          value={address}
          onChange={setAddress}
        />

        <Field
          id="display-phone"
          label="Display number"
          value={displayPhone}
          onChange={setDisplayPhone}
          helper="What customers dial. Forwards into Niko via your carrier."
        />

        <Field
          id="twilio-phone"
          label="Twilio number"
          value={restaurant.twilio_phone || '(awaiting)'}
          readOnly
          helper="Provisioned by Niko — not editable from here."
        />

        <Field
          id="fallback-phone"
          label="Fallback number"
          value={fallbackPhone}
          onChange={setFallbackPhone}
          placeholder="+15551234567"
          helper="Niko transfers callers here when the AI hits a snag or the caller asks for a human. Leave blank to skip the transfer attempt and go straight to voicemail."
        />

        {error ? (
          <p className="text-sm text-status-cancelled" role="alert">
            {error}
          </p>
        ) : null}

        <div className="flex justify-end">
          <Button type="submit" size="lg" disabled={pending}>
            {pending ? 'Saving…' : 'Save info'}
          </Button>
        </div>
      </form>
    </section>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
  helper,
  readOnly,
}: {
  id: string;
  label: string;
  value: string;
  onChange?: (next: string) => void;
  placeholder?: string;
  helper?: string;
  readOnly?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="text-sm text-foreground-muted">
        {label}
      </Label>
      <Input
        id={id}
        value={value}
        readOnly={readOnly}
        placeholder={placeholder}
        onChange={onChange ? (e) => onChange(e.target.value) : undefined}
        className={
          readOnly
            ? 'cursor-not-allowed text-foreground-muted'
            : undefined
        }
      />
      {helper ? (
        <p className="text-sm text-foreground-subtle">{helper}</p>
      ) : null}
    </div>
  );
}
