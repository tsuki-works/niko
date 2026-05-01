import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createMenuItem,
  createMenuCategory,
  deleteMenuItem,
  updateMenuItem,
} from '@/lib/api/menu';

vi.mock('@/lib/api/http', () => ({
  apiFetch: vi.fn(),
}));
import { apiFetch } from '@/lib/api/http';

const okJson = (body: unknown) =>
  ({ ok: true, json: async () => body }) as Response;

const FAKE_RESTAURANT = {
  id: 'r1',
  name: 'R',
  display_phone: '+15551234567',
  twilio_phone: '+15551234567',
  address: '1 Main',
  hours: '11-22',
  hours_structured: null,
  fallback_phone: null,
  offers_delivery: true,
  menu: {
    pizzas: [{ name: 'Margherita', price: 12.99, available: true }],
  },
  prompt_overrides: {},
  forwarding_mode: 'always',
};

describe('menu api helpers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('createMenuItem POSTs and returns parsed restaurant', async () => {
    (apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      okJson(FAKE_RESTAURANT),
    );
    const r = await createMenuItem({
      category: 'pizzas',
      name: 'Pepperoni',
      price: 15.99,
    });
    expect(apiFetch).toHaveBeenCalledWith(
      '/restaurants/me/menu/items',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(r.id).toBe('r1');
  });

  it('updateMenuItem PATCHes with URL-encoded names', async () => {
    (apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      okJson(FAKE_RESTAURANT),
    );
    await updateMenuItem({
      category: 'pizzas',
      name: 'Marg & Cheese',
      patch: { price: 14.99 },
    });
    const url = (apiFetch as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).toBe('/restaurants/me/menu/items/pizzas/Marg%20%26%20Cheese');
  });

  it('deleteMenuItem DELETEs', async () => {
    (apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      okJson(FAKE_RESTAURANT),
    );
    await deleteMenuItem({ category: 'pizzas', name: 'Margherita' });
    const init = (apiFetch as ReturnType<typeof vi.fn>).mock.calls[0][1];
    expect(init.method).toBe('DELETE');
  });

  it('createMenuCategory POSTs the key', async () => {
    (apiFetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      okJson(FAKE_RESTAURANT),
    );
    await createMenuCategory({ key: 'drinks' });
    const init = (apiFetch as ReturnType<typeof vi.fn>).mock.calls[0][1];
    expect(init.body).toBe(JSON.stringify({ key: 'drinks' }));
  });
});
