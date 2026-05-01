import { describe, expect, it, vi } from 'vitest';

import { updateRestaurant } from '@/lib/api/restaurant';

vi.mock('@/lib/api/http', () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from '@/lib/api/http';

describe('updateRestaurant', () => {
  it('PATCHes /restaurants/me with the patch body and parses the response', async () => {
    const updated = {
      id: 'r1',
      name: 'New Name',
      display_phone: '+15551234567',
      twilio_phone: '+15551234567',
      address: '1 Main',
      hours: 'Mon-Sun 11-22',
      hours_structured: null,
      fallback_phone: null,
      offers_delivery: true,
      menu: {},
      prompt_overrides: {},
      forwarding_mode: 'always',
    };
    (apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => updated,
    });

    const result = await updateRestaurant({ name: 'New Name' });

    expect(apiFetch).toHaveBeenCalledWith('/restaurants/me', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'New Name' }),
    });
    expect(result.name).toBe('New Name');
  });

  it('throws when the response is not ok', async () => {
    (apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 422,
      statusText: 'Unprocessable',
    });
    await expect(updateRestaurant({ name: 'X' })).rejects.toThrow();
  });
});
