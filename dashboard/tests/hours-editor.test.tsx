// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { HoursEditor } from '@/components/settings/hours-editor';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

vi.mock('@/app/actions/update-restaurant', () => ({
  updateRestaurantAction: vi.fn().mockResolvedValue({ success: true }),
}));
import { updateRestaurantAction } from '@/app/actions/update-restaurant';

const day = { open: '11:00', close: '22:00', closed: false };
const BASE = {
  id: 'r1',
  name: 'R',
  display_phone: '+15551234567',
  twilio_phone: '+15551234567',
  address: '1 Main',
  hours: 'Mon-Sun 11-22',
  hours_structured: {
    mon: day,
    tue: day,
    wed: day,
    thu: day,
    fri: day,
    sat: day,
    sun: day,
  },
  fallback_phone: null,
  offers_delivery: true,
  menu: {},
  prompt_overrides: {},
  forwarding_mode: 'always' as const,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('HoursEditor', () => {
  it('renders one row per day of the week', () => {
    render(<HoursEditor restaurant={BASE} />);
    // Each day-row owns one Closed checkbox; the open/close inputs are
    // type="time" not "checkbox", so checkbox count == day count.
    expect(screen.getAllByRole('checkbox')).toHaveLength(7);
  });

  it('seeds from hours_structured when present', () => {
    render(<HoursEditor restaurant={BASE} />);
    const opens = screen.getAllByLabelText(/open time/i);
    expect(opens[0]).toHaveValue('11:00');
  });

  it('seeds with default 11:00-22:00 when hours_structured is null', () => {
    render(<HoursEditor restaurant={{ ...BASE, hours_structured: null }} />);
    const opens = screen.getAllByLabelText(/open time/i);
    expect(opens[0]).toHaveValue('11:00');
  });

  it('disables open/close inputs when the day is marked closed', () => {
    render(<HoursEditor restaurant={BASE} />);
    const monClosed = screen.getByLabelText(/monday closed/i);
    fireEvent.click(monClosed);
    const opens = screen.getAllByLabelText(/open time/i);
    expect(opens[0]).toBeDisabled();
  });

  it('submits hours_structured when saved', async () => {
    render(<HoursEditor restaurant={BASE} />);
    const monClosed = screen.getByLabelText(/monday closed/i);
    fireEvent.click(monClosed);
    fireEvent.click(screen.getByRole('button', { name: /save hours/i }));

    await waitFor(() => {
      expect(updateRestaurantAction).toHaveBeenCalled();
      const call = (updateRestaurantAction as ReturnType<typeof vi.fn>).mock
        .calls[0][0];
      expect(call.hours_structured.mon.closed).toBe(true);
    });
  });
});
