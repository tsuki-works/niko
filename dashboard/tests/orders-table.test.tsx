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

// OrdersTable rows call `useRouter()` for click-to-navigate. The hook
// throws "invariant expected app router to be mounted" outside a real
// Next.js render tree — stub it for the unit test surface.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
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

describe('OrdersTable empty states', () => {
  it('renders the status-specific filter-empty state and keeps the table header', () => {
    render(<OrdersTable orders={[]} twilioPhone="+14165551234" statusFilter="preparing" />);
    // Headline is keyed off statusFilter via EMPTY_HEADLINE_BY_STATUS.
    expect(screen.getByText('Nothing in the kitchen right now')).toBeInTheDocument();
    expect(
      screen.getByText('This view will update automatically as orders come in.'),
    ).toBeInTheDocument();
    // The table header stays mounted so the filter tabs don't jump.
    expect(screen.getByText('Order')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    // Not the "provisioning / nothing ever" all-tab surface.
    expect(screen.queryByText('No orders yet')).not.toBeInTheDocument();
  });

  it('uses the headline that matches the active status filter', () => {
    render(<OrdersTable orders={[]} twilioPhone="+14165551234" statusFilter="ready" />);
    expect(screen.getByText('Nothing ready for pickup')).toBeInTheDocument();
    expect(screen.queryByText('Nothing in the kitchen right now')).not.toBeInTheDocument();
  });

  it('renders the all-tab provisioning empty state (no table) when there is no filter', () => {
    render(<OrdersTable orders={[]} twilioPhone="+14165551234" />);
    expect(screen.getByText('No orders yet')).toBeInTheDocument();
    // The whole table (and its header) is replaced, and no filter-empty
    // headline is shown.
    expect(screen.queryByText('Order')).not.toBeInTheDocument();
    expect(screen.queryByText('Nothing in the kitchen right now')).not.toBeInTheDocument();
  });
});
