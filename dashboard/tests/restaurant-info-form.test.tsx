// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { RestaurantInfoForm } from '@/components/settings/restaurant-info-form';

vi.mock('@/app/actions/update-restaurant', () => ({
  updateRestaurantAction: vi.fn().mockResolvedValue({ success: true }),
}));
import { updateRestaurantAction } from '@/app/actions/update-restaurant';

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

const BASE = {
  id: 'r1',
  name: 'Niko Pizza Kitchen',
  display_phone: '+15551234567',
  twilio_phone: '+16479058093',
  address: '123 Main',
  hours: 'Mon-Sun 11-22',
  hours_structured: null,
  fallback_phone: null,
  offers_delivery: true,
  menu: {},
  prompt_overrides: {},
  forwarding_mode: 'always' as const,
};

describe('RestaurantInfoForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('submits a patch with edited fields only', async () => {
    render(<RestaurantInfoForm restaurant={BASE} />);

    const nameInput = screen.getByLabelText(/restaurant name/i);
    fireEvent.change(nameInput, { target: { value: 'New Name' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() =>
      expect(updateRestaurantAction).toHaveBeenCalledWith({
        name: 'New Name',
      }),
    );
  });

  it('shows the twilio_phone read-only', () => {
    render(<RestaurantInfoForm restaurant={BASE} />);
    const twilio = screen.getByLabelText(/twilio number/i);
    expect(twilio).toHaveAttribute('readOnly');
    expect(twilio).toHaveValue('+16479058093');
  });

  it('validates fallback_phone format on submit', async () => {
    render(<RestaurantInfoForm restaurant={BASE} />);
    const fallback = screen.getByLabelText(/fallback number/i);
    fireEvent.change(fallback, { target: { value: 'abc' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await screen.findByText(/E\.164/i);
    expect(updateRestaurantAction).not.toHaveBeenCalled();
  });

  it('shows inline E.164 error while typing an invalid fallback number', async () => {
    render(<RestaurantInfoForm restaurant={BASE} />);
    const fallback = screen.getByLabelText(/fallback number/i);
    fireEvent.change(fallback, { target: { value: 'bad' } });
    await screen.findByText(/Must be E\.164 format/i);
    expect(updateRestaurantAction).not.toHaveBeenCalled();
  });

  it('clears inline E.164 error when input becomes valid', async () => {
    render(<RestaurantInfoForm restaurant={BASE} />);
    const fallback = screen.getByLabelText(/fallback number/i);
    fireEvent.change(fallback, { target: { value: 'bad' } });
    await screen.findByText(/Must be E\.164 format/i);
    fireEvent.change(fallback, { target: { value: '+15551234567' } });
    await waitFor(() =>
      expect(screen.queryByText(/Must be E\.164 format/i)).toBeNull(),
    );
  });

  it('includes offers_delivery: false in patch when toggled off', async () => {
    // BASE has offers_delivery: true — toggling the checkbox once → false
    render(<RestaurantInfoForm restaurant={BASE} />);
    const checkbox = screen.getByRole('checkbox', { name: /accept delivery orders/i });
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() =>
      expect(updateRestaurantAction).toHaveBeenCalledWith(
        expect.objectContaining({ offers_delivery: false }),
      ),
    );
  });
});
