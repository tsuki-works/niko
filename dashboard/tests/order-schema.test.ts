import { describe, expect, it } from 'vitest';

import { parseOrderFromJson, OrderValidationError } from '@/lib/firebase/converters';
import {
  OrderSchema,
  formatLineItemTitle,
  orderShortId,
} from '@/lib/schemas/order';

const VALID = {
  call_sid: 'CA1a2b3c4d5e6fF045',
  caller_phone: '+14165550134',
  restaurant_id: 'niko-pizza-kitchen',
  items: [
    {
      name: 'Pepperoni',
      category: 'pizza',
      size: 'large',
      quantity: 1,
      unit_price: 18.99,
      modifications: ['Extra cheese', 'Extra crispy'],
      line_total: 18.99,
    },
  ],
  order_type: 'pickup',
  delivery_address: null,
  status: 'confirmed',
  created_at: '2026-04-20T19:27:00.000Z',
  confirmed_at: '2026-04-20T19:30:42.000Z',
  subtotal: 18.99,
};

describe('OrderSchema / parseOrderFromJson', () => {
  it('parses a valid JSON payload', () => {
    const order = parseOrderFromJson(VALID);
    expect(order.call_sid).toBe('CA1a2b3c4d5e6fF045');
    expect(order.created_at).toBeInstanceOf(Date);
    expect(order.confirmed_at).toBeInstanceOf(Date);
    expect(order.items).toHaveLength(1);
    expect(order.subtotal).toBe(18.99);
  });

  it('throws OrderValidationError for missing required fields', () => {
    const invalid = { ...VALID, status: 'not-a-status' };
    expect(() => parseOrderFromJson(invalid)).toThrow(OrderValidationError);
  });

  it('rejects unknown statuses via OrderSchema directly', () => {
    expect(() =>
      OrderSchema.parse({ ...VALID, status: 'flux-capacitor-engaged' }),
    ).toThrow();
  });

  it('parses orders with the new lifecycle statuses', () => {
    for (const status of ['preparing', 'ready', 'completed'] as const) {
      const order = OrderSchema.parse({ ...VALID, status });
      expect(order.status).toBe(status);
    }
  });

  it('parses orders with new per-transition timestamps populated', () => {
    const order = OrderSchema.parse({
      ...VALID,
      status: 'completed',
      preparing_at: '2026-04-20T19:35:00.000Z',
      ready_at: '2026-04-20T19:42:00.000Z',
      completed_at: '2026-04-20T19:48:00.000Z',
    });
    expect(order.preparing_at).toBeInstanceOf(Date);
    expect(order.ready_at).toBeInstanceOf(Date);
    expect(order.completed_at).toBeInstanceOf(Date);
  });

  it('parses orders without the new optional timestamps (existing docs)', () => {
    // Existing Firestore docs have only confirmed_at — make sure those
    // still parse cleanly without the new fields present.
    const order = OrderSchema.parse(VALID);
    expect(order.preparing_at).toBeFalsy();
    expect(order.ready_at).toBeFalsy();
    expect(order.completed_at).toBeFalsy();
    expect(order.cancelled_at).toBeFalsy();
  });
});

describe('display helpers', () => {
  it('orderShortId takes the last 4 hex chars uppercased', () => {
    expect(orderShortId({ call_sid: 'CA1a2b3c4d5e6ff045' })).toBe('#F045');
  });

  it('formatLineItemTitle interpolates size and lowercases name', () => {
    const item = {
      name: 'Pepperoni Pizza',
      category: 'pizza' as const,
      size: 'large',
      quantity: 1,
      unit_price: 18.99,
      modifications: [],
      line_total: 18.99,
    };
    expect(formatLineItemTitle(item)).toBe('1 × Large pepperoni pizza');
  });
});
