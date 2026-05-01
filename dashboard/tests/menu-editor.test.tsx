// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

window.confirm = vi.fn(() => true);

vi.mock('@/app/actions/edit-menu', () => ({
  deleteMenuItemAction: vi.fn().mockResolvedValue({ success: true }),
  createMenuItemAction: vi.fn().mockResolvedValue({ success: true }),
  updateMenuItemAction: vi.fn().mockResolvedValue({ success: true }),
  createCategoryAction: vi.fn().mockResolvedValue({ success: true }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { MenuEditor } from '@/components/menu/menu-editor';

describe('MenuEditor', () => {
  it('renders edit/delete affordances on each item row', () => {
    render(
      <MenuEditor
        restaurantName="Niko"
        itemCount={1}
        categories={[
          {
            key: 'pizzas',
            items: [
              { name: 'Margherita', price: 12.99, available: true },
            ],
          },
        ]}
      />,
    );
    expect(screen.getByLabelText(/edit margherita/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/delete margherita/i)).toBeInTheDocument();
  });

  it('shows "unavailable" badge on items where available is false', () => {
    render(
      <MenuEditor
        restaurantName="Niko"
        itemCount={1}
        categories={[
          {
            key: 'pizzas',
            items: [
              { name: 'Margherita', price: 12.99, available: false },
            ],
          },
        ]}
      />,
    );
    expect(screen.getByText(/unavailable/i)).toBeInTheDocument();
  });

  it('shows "Add item" buttons per category and a global "Add category"', () => {
    render(
      <MenuEditor
        restaurantName="Niko"
        itemCount={0}
        categories={[
          { key: 'pizzas', items: [] },
          { key: 'drinks', items: [] },
        ]}
      />,
    );
    expect(screen.getAllByRole('button', { name: /add item/i })).toHaveLength(2);
    expect(screen.getByRole('button', { name: /add category/i })).toBeInTheDocument();
  });
});
