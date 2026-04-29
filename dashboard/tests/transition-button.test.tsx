// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/app/actions/transition-order', () => ({
  markPreparingAction: vi.fn(),
  markReadyAction: vi.fn(),
  markCompletedAction: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import {
  markPreparingAction,
  markReadyAction,
  markCompletedAction,
} from '@/app/actions/transition-order';
import { toast } from 'sonner';

import { TransitionButton } from '@/components/orders/transition-button';
import type { Order, OrderStatus } from '@/lib/schemas/order';

function makeOrder(status: OrderStatus): Order {
  return {
    call_sid: 'CA1234ABCD',
    caller_phone: null,
    restaurant_id: 'r',
    items: [],
    order_type: 'pickup',
    delivery_address: null,
    status,
    created_at: new Date(),
    confirmed_at: new Date(),
    subtotal: 0,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

it('renders nothing for in_progress orders', () => {
  const { container } = render(<TransitionButton order={makeOrder('in_progress')} />);
  expect(container).toBeEmptyDOMElement();
});

it('renders nothing for completed orders', () => {
  const { container } = render(<TransitionButton order={makeOrder('completed')} />);
  expect(container).toBeEmptyDOMElement();
});

it('renders nothing for cancelled orders', () => {
  const { container } = render(<TransitionButton order={makeOrder('cancelled')} />);
  expect(container).toBeEmptyDOMElement();
});

it('renders Start Preparing for confirmed orders and calls markPreparingAction on click', async () => {
  vi.mocked(markPreparingAction).mockResolvedValueOnce({ success: true });
  render(<TransitionButton order={makeOrder('confirmed')} />);

  const button = screen.getByRole('button', { name: /start preparing/i });
  fireEvent.click(button);

  await waitFor(() => {
    expect(markPreparingAction).toHaveBeenCalledWith({ call_sid: 'CA1234ABCD' });
  });
  await waitFor(() => {
    expect(toast.success).toHaveBeenCalled();
  });
});

it('renders Mark Ready for preparing orders and calls markReadyAction on click', async () => {
  vi.mocked(markReadyAction).mockResolvedValueOnce({ success: true });
  render(<TransitionButton order={makeOrder('preparing')} />);

  const button = screen.getByRole('button', { name: /mark ready/i });
  fireEvent.click(button);

  await waitFor(() => {
    expect(markReadyAction).toHaveBeenCalledWith({ call_sid: 'CA1234ABCD' });
  });
});

it('renders Mark Completed for ready orders and calls markCompletedAction on click', async () => {
  vi.mocked(markCompletedAction).mockResolvedValueOnce({ success: true });
  render(<TransitionButton order={makeOrder('ready')} />);

  const button = screen.getByRole('button', { name: /mark completed/i });
  fireEvent.click(button);

  await waitFor(() => {
    expect(markCompletedAction).toHaveBeenCalledWith({ call_sid: 'CA1234ABCD' });
  });
});

it('shows error toast when the action returns failure', async () => {
  vi.mocked(markPreparingAction).mockResolvedValueOnce({
    success: false,
    error: 'order not found',
  });
  render(<TransitionButton order={makeOrder('confirmed')} />);

  fireEvent.click(screen.getByRole('button', { name: /start preparing/i }));

  await waitFor(() => {
    expect(toast.error).toHaveBeenCalledWith('order not found');
  });
  expect(toast.success).not.toHaveBeenCalled();
});
