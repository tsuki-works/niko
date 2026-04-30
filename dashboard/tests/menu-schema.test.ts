import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  MenuItemSchema,
  SinglePriceItemSchema,
  SizedItemSchema,
  humanizeCategoryKey,
  isSizedItem,
  itemPriceRange,
  parseMenu,
} from '@/lib/schemas/menu';

describe('MenuItemSchema', () => {
  it('parses a single-priced item', () => {
    const parsed = MenuItemSchema.parse({
      name: 'French Fries',
      price: 7.25,
    });
    expect(parsed).toEqual({ name: 'French Fries', price: 7.25 });
    expect(isSizedItem(parsed)).toBe(false);
  });

  it('parses a single-priced item with description', () => {
    const parsed = MenuItemSchema.parse({
      name: 'Vegetable Spring Roll',
      description: 'Each.',
      price: 2,
    });
    expect(parsed).toMatchObject({ name: 'Vegetable Spring Roll', price: 2 });
  });

  it('parses a sized item', () => {
    const parsed = MenuItemSchema.parse({
      name: 'Deep Fried Chicken',
      sizes: { half: 14, whole: 24.5 },
    });
    expect(isSizedItem(parsed)).toBe(true);
    if (isSizedItem(parsed)) {
      expect(parsed.sizes).toEqual({ half: 14, whole: 24.5 });
    }
  });

  it('rejects items with neither price nor sizes', () => {
    expect(() => MenuItemSchema.parse({ name: 'Mystery' })).toThrow();
  });

  it('rejects sized items with empty sizes object', () => {
    expect(() =>
      SizedItemSchema.parse({ name: 'X', sizes: {} }),
    ).toThrow(/at least one entry/);
  });

  it('rejects negative prices', () => {
    expect(() =>
      SinglePriceItemSchema.parse({ name: 'X', price: -1 }),
    ).toThrow();
  });
});

describe('parseMenu — twilight-family-restaurant fixture', () => {
  // Fixture lives at repo root; tests run from dashboard/, so go up one.
  const fixturePath = resolve(
    __dirname,
    '..',
    '..',
    'restaurants',
    'twilight-family-restaurant.json',
  );
  const fixture = JSON.parse(readFileSync(fixturePath, 'utf-8'));

  it('parses cleanly', () => {
    const result = parseMenu(fixture);
    expect('error' in result).toBe(false);
  });

  it('honors _category_order', () => {
    const result = parseMenu(fixture);
    if ('error' in result) throw new Error(result.error);
    const expectedOrder = fixture._category_order as string[];
    const actualOrder = result.categories.map((c) => c.key);
    expect(actualOrder).toEqual(expectedOrder);
  });

  it('reports a sensible item count', () => {
    const result = parseMenu(fixture);
    if ('error' in result) throw new Error(result.error);
    // Sum the fixture's category arrays directly so the test is robust
    // to menu edits.
    const expected = (Object.entries(fixture) as [string, unknown][])
      .filter(([k]) => !k.startsWith('_'))
      .reduce((acc, [, items]) => acc + (items as unknown[]).length, 0);
    expect(result.itemCount).toBe(expected);
  });

  it('strips reserved underscored keys from categories', () => {
    const result = parseMenu(fixture);
    if ('error' in result) throw new Error(result.error);
    expect(
      result.categories.find((c) => c.key.startsWith('_')),
    ).toBeUndefined();
  });
});

describe('parseMenu — edge cases', () => {
  it('returns empty categories for an empty doc', () => {
    expect(parseMenu({})).toEqual({ categories: [], itemCount: 0 });
  });

  it('drops empty categories from output', () => {
    const result = parseMenu({ pizzas: [], drinks: [{ name: 'Water', price: 1 }] });
    if ('error' in result) throw new Error(result.error);
    expect(result.categories.map((c) => c.key)).toEqual(['drinks']);
  });

  it('appends categories not listed in _category_order', () => {
    const result = parseMenu({
      _category_order: ['pizzas'],
      pizzas: [{ name: 'Margherita', price: 12 }],
      drinks: [{ name: 'Water', price: 1 }],
    });
    if ('error' in result) throw new Error(result.error);
    expect(result.categories.map((c) => c.key)).toEqual(['pizzas', 'drinks']);
  });

  it('skips _category_order entries that do not exist as keys', () => {
    const result = parseMenu({
      _category_order: ['ghost', 'pizzas'],
      pizzas: [{ name: 'Margherita', price: 12 }],
    });
    if ('error' in result) throw new Error(result.error);
    expect(result.categories.map((c) => c.key)).toEqual(['pizzas']);
  });

  it('returns an error for a category that is not an array', () => {
    const result = parseMenu({ pizzas: { name: 'Wrong shape' } });
    expect('error' in result).toBe(true);
  });

  it('returns an error for an item with an unexpected shape', () => {
    const result = parseMenu({ pizzas: [{ name: 'X' }] });
    expect('error' in result).toBe(true);
  });
});

describe('humanizeCategoryKey', () => {
  it('title-cases a single word', () => {
    expect(humanizeCategoryKey('appetizers')).toBe('Appetizers');
  });

  it('title-cases a snake_case key', () => {
    expect(humanizeCategoryKey('caribbean_appetizers')).toBe(
      'Caribbean Appetizers',
    );
  });

  it('title-cases multi-word keys', () => {
    expect(humanizeCategoryKey('specialty_dishes')).toBe('Specialty Dishes');
  });

  it('preserves acronym overrides', () => {
    expect(humanizeCategoryKey('bbq_sauces')).toBe('BBQ Sauces');
  });

  it('handles consecutive underscores gracefully', () => {
    expect(humanizeCategoryKey('drinks__cold')).toBe('Drinks Cold');
  });
});

describe('itemPriceRange', () => {
  it('returns the same min/max for a single-priced item', () => {
    expect(itemPriceRange({ name: 'X', price: 9.5 })).toEqual({
      min: 9.5,
      max: 9.5,
    });
  });

  it('returns min and max across sizes', () => {
    expect(
      itemPriceRange({ name: 'X', sizes: { small: 10, medium: 14, large: 18 } }),
    ).toEqual({ min: 10, max: 18 });
  });
});
