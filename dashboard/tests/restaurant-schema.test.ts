import { describe, expect, it } from 'vitest';

import { RestaurantSchema } from '@/lib/schemas/restaurant';

const BASE = {
  id: 'r1',
  name: 'R',
  display_phone: '+15551234567',
  twilio_phone: '+15551234567',
  address: '1 Main',
  hours: 'Mon-Sun 11-22',
};

describe('RestaurantSchema', () => {
  it('accepts a doc without hours_structured or fallback_phone', () => {
    const parsed = RestaurantSchema.safeParse(BASE);
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.hours_structured).toBeNull();
      expect(parsed.data.fallback_phone).toBeNull();
    }
  });

  it('accepts hours_structured with all seven days', () => {
    const day = { open: '11:00', close: '22:00', closed: false };
    const parsed = RestaurantSchema.safeParse({
      ...BASE,
      hours_structured: {
        mon: day,
        tue: day,
        wed: day,
        thu: day,
        fri: day,
        sat: day,
        sun: { open: '00:00', close: '00:00', closed: true },
      },
      fallback_phone: '+15559999999',
    });
    expect(parsed.success).toBe(true);
  });

  it('rejects malformed hour times', () => {
    const parsed = RestaurantSchema.safeParse({
      ...BASE,
      hours_structured: {
        mon: { open: '99', close: '22:00', closed: false },
        tue: { open: '11:00', close: '22:00', closed: false },
        wed: { open: '11:00', close: '22:00', closed: false },
        thu: { open: '11:00', close: '22:00', closed: false },
        fri: { open: '11:00', close: '22:00', closed: false },
        sat: { open: '11:00', close: '22:00', closed: false },
        sun: { open: '11:00', close: '22:00', closed: false },
      },
    });
    expect(parsed.success).toBe(false);
  });
});
