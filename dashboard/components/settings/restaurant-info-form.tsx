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
    <section className="flex flex-col gap-4">
      <h3 className="text-base font-medium">Restaurant info</h3>
      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="restaurant-name">Restaurant name</Label>
          <Input
            id="restaurant-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="address">Address</Label>
          <Input
            id="address"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="display-phone">Display number</Label>
          <Input
            id="display-phone"
            value={displayPhone}
            onChange={(e) => setDisplayPhone(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            What customers dial. Forwards into Niko via your carrier.
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="twilio-phone">Twilio number</Label>
          <Input
            id="twilio-phone"
            value={restaurant.twilio_phone || '(awaiting)'}
            readOnly
            className="bg-muted"
          />
          <p className="text-xs text-muted-foreground">
            Provisioned by Niko — not editable from here.
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="fallback-phone">Fallback number</Label>
          <Input
            id="fallback-phone"
            value={fallbackPhone}
            placeholder="+15551234567"
            onChange={(e) => setFallbackPhone(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Niko transfers callers here when the AI hits a snag or the caller
            asks for a human. Leave blank to skip the transfer attempt and go
            straight to voicemail.
          </p>
        </div>

        {error ? (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}

        <div className="flex justify-end">
          <Button type="submit" disabled={pending}>
            {pending ? 'Saving…' : 'Save info'}
          </Button>
        </div>
      </form>
    </section>
  );
}
