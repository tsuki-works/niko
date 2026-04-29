// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// TransitionButton (rendered inside OrdersTable) imports the Server Action
// which transitively pulls in `server-only`. Mock that module so Vitest
// can resolve the import graph in jsdom without a Next.js server runtime.
vi.mock('@/app/actions/transition-order', () => ({
  markPreparingAction: vi.fn(),
  markReadyAction: vi.fn(),
  markCompletedAction: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { OrdersTable } from '@/components/orders/orders-table';
import type { Order, OrderStatus } from '@/lib/schemas/order';

function makeOrder(
  overrides: Partial<Order> & { call_sid: string; status: OrderStatus },
): Order {
  return {
    caller_phone: null,
    restaurant_id: 'r',
    items: [
      {
        name: 'Margherita',
        category: 'pizza',
        size: 'large',
        quantity: 1,
        unit_price: 19.99,
        modifications: [],
        line_total: 19.99,
      },
    ],
    order_type: 'pickup',
    delivery_address: null,
    created_at: new Date('2026-04-29T12:00:00Z'),
    confirmed_at: new Date('2026-04-29T12:01:00Z'),
    subtotal: 19.99,
    ...overrides,
  };
}

describe('OrdersTable Time column', () => {
  it('uses preparing_at as the time anchor for preparing rows', () => {
    const preparingAt = new Date('2026-04-29T12:05:00Z');
    const order = makeOrder({
      call_sid: 'CA1',
      status: 'preparing',
      preparing_at: preparingAt,
    });
    render(<OrdersTable orders={[order]} twilioPhone="+1" />);
    const time = screen.getByTestId(`order-time-${order.call_sid}`);
    expect(time).toHaveAttribute('data-anchor-iso', preparingAt.toISOString());
  });

  it('uses ready_at as the time anchor for ready rows', () => {
    const readyAt = new Date('2026-04-29T12:15:00Z');
    const order = makeOrder({
      call_sid: 'CA2',
      status: 'ready',
      preparing_at: new Date('2026-04-29T12:05:00Z'),
      ready_at: readyAt,
    });
    render(<OrdersTable orders={[order]} twilioPhone="+1" />);
    const time = screen.getByTestId(`order-time-${order.call_sid}`);
    expect(time).toHaveAttribute('data-anchor-iso', readyAt.toISOString());
  });

  it('uses created_at for confirmed rows', () => {
    const createdAt = new Date('2026-04-29T11:55:00Z');
    const order = makeOrder({
      call_sid: 'CA3',
      status: 'confirmed',
      created_at: createdAt,
    });
    render(<OrdersTable orders={[order]} twilioPhone="+1" />);
    const time = screen.getByTestId(`order-time-${order.call_sid}`);
    expect(time).toHaveAttribute('data-anchor-iso', createdAt.toISOString());
  });

  it('uses created_at for completed rows', () => {
    const createdAt = new Date('2026-04-29T11:55:00Z');
    const order = makeOrder({
      call_sid: 'CA4',
      status: 'completed',
      created_at: createdAt,
      preparing_at: new Date('2026-04-29T12:00:00Z'),
      ready_at: new Date('2026-04-29T12:10:00Z'),
      completed_at: new Date('2026-04-29T12:30:00Z'),
    });
    render(<OrdersTable orders={[order]} twilioPhone="+1" />);
    const time = screen.getByTestId(`order-time-${order.call_sid}`);
    expect(time).toHaveAttribute('data-anchor-iso', createdAt.toISOString());
  });
});
