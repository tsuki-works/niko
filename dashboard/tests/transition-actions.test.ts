import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the API client and Next.js cache before importing the actions.
vi.mock('@/lib/api/orders', () => ({
  markPreparingApi: vi.fn(),
  markReadyApi: vi.fn(),
  markCompletedApi: vi.fn(),
}));

vi.mock('next/cache', () => ({
  revalidatePath: vi.fn(),
}));

import {
  markPreparingApi,
  markReadyApi,
  markCompletedApi,
} from '@/lib/api/orders';
import { revalidatePath } from 'next/cache';

import {
  markPreparingAction,
  markReadyAction,
  markCompletedAction,
} from '@/app/actions/transition-order';

import type { OrderStatus } from '@/lib/schemas/order';

const okOrder = (call_sid: string, status: OrderStatus) => ({
  success: true as const,
  order: {
    call_sid,
    caller_phone: null,
    restaurant_id: 'r',
    items: [],
    order_type: 'pickup' as const,
    delivery_address: null,
    status,
    created_at: new Date(),
    confirmed_at: new Date(),
    subtotal: 0,
  },
});

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('markPreparingAction', () => {
  it('returns success and revalidates paths on 200', async () => {
    vi.mocked(markPreparingApi).mockResolvedValueOnce(
      okOrder('CAtest', 'preparing'),
    );
    const result = await markPreparingAction({ call_sid: 'CAtest' });
    expect(result).toEqual({ success: true });
    expect(markPreparingApi).toHaveBeenCalledWith('CAtest');
    expect(revalidatePath).toHaveBeenCalledWith('/');
    expect(revalidatePath).toHaveBeenCalledWith('/orders/CAtest');
  });

  it('returns failure when the API client returns failure', async () => {
    vi.mocked(markPreparingApi).mockResolvedValueOnce({
      success: false,
      error: 'Cannot transition order CAtest to preparing: ...',
    });
    const result = await markPreparingAction({ call_sid: 'CAtest' });
    expect(result).toEqual({
      success: false,
      error: 'Cannot transition order CAtest to preparing: ...',
    });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it('rejects empty call_sid input', async () => {
    const result = await markPreparingAction({ call_sid: '' });
    expect(result).toEqual({ success: false, error: 'Invalid input' });
    expect(markPreparingApi).not.toHaveBeenCalled();
  });
});

describe('markReadyAction', () => {
  it('returns success and revalidates paths on 200', async () => {
    vi.mocked(markReadyApi).mockResolvedValueOnce(okOrder('CAtest', 'ready'));
    const result = await markReadyAction({ call_sid: 'CAtest' });
    expect(result).toEqual({ success: true });
    expect(markReadyApi).toHaveBeenCalledWith('CAtest');
    expect(revalidatePath).toHaveBeenCalledWith('/');
    expect(revalidatePath).toHaveBeenCalledWith('/orders/CAtest');
  });

  it('returns failure when the API client returns failure', async () => {
    vi.mocked(markReadyApi).mockResolvedValueOnce({
      success: false,
      error: 'Cannot transition',
    });
    const result = await markReadyAction({ call_sid: 'CAtest' });
    expect(result).toEqual({ success: false, error: 'Cannot transition' });
  });

  it('rejects empty call_sid input', async () => {
    const result = await markReadyAction({ call_sid: '' });
    expect(result).toEqual({ success: false, error: 'Invalid input' });
  });
});

describe('markCompletedAction', () => {
  it('returns success and revalidates paths on 200', async () => {
    vi.mocked(markCompletedApi).mockResolvedValueOnce(
      okOrder('CAtest', 'completed'),
    );
    const result = await markCompletedAction({ call_sid: 'CAtest' });
    expect(result).toEqual({ success: true });
    expect(markCompletedApi).toHaveBeenCalledWith('CAtest');
    expect(revalidatePath).toHaveBeenCalledWith('/');
    expect(revalidatePath).toHaveBeenCalledWith('/orders/CAtest');
  });

  it('returns failure when the API client returns failure', async () => {
    vi.mocked(markCompletedApi).mockResolvedValueOnce({
      success: false,
      error: 'Cannot transition',
    });
    const result = await markCompletedAction({ call_sid: 'CAtest' });
    expect(result).toEqual({ success: false, error: 'Cannot transition' });
  });

  it('rejects empty call_sid input', async () => {
    const result = await markCompletedAction({ call_sid: '' });
    expect(result).toEqual({ success: false, error: 'Invalid input' });
  });
});
