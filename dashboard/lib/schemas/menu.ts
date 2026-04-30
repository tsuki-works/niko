/**
 * Menu schema — narrows the free-form `restaurant.menu` dict that the
 * backend stores at `restaurants/{id}.menu` (see
 * `app/restaurants/models.py`).
 *
 * Shape per the backend:
 *   {
 *     _category_order?: string[],    // optional ordering hint
 *     <category_key>: MenuItem[],    // each non-underscored key
 *     ...
 *   }
 *
 * Per-item shape is one of:
 *   - { name, price, description? }                       single-priced
 *   - { name, sizes: { small: 12.99, ... }, description? } multi-size
 *
 * The Pydantic model (`Restaurant.menu: dict[str, Any]`) is intentionally
 * loose so different tenants can use different category keys (pizzas vs.
 * caribbean_appetizers vs. fried_rice) — see the comment block in
 * `app/restaurants/models.py`. We tighten validation here at the read
 * boundary so the dashboard never has to handle ad-hoc shapes downstream.
 *
 * Sprint 2.4 owns menu CRUD; this schema is the read-side groundwork.
 * Phase 2+ will move per-item structure to a stricter `MenuItem` Pydantic
 * model in the backend with stable IDs and modifier groups (see deferred
 * list in `dashboard/CLAUDE.md`).
 */
import { z } from 'zod';

const RESERVED_PREFIX = '_';
const CATEGORY_ORDER_KEY = '_category_order';

export const SizedItemSchema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
  sizes: z
    .record(z.string().min(1), z.number().nonnegative())
    .refine((s) => Object.keys(s).length > 0, {
      message: 'sizes must contain at least one entry',
    }),
});
export type SizedItem = z.infer<typeof SizedItemSchema>;

export const SinglePriceItemSchema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
  price: z.number().nonnegative(),
});
export type SinglePriceItem = z.infer<typeof SinglePriceItemSchema>;

// Order matters: an object that has both `sizes` and `price` (shouldn't,
// but defense in depth) is treated as sized.
export const MenuItemSchema = z.union([SizedItemSchema, SinglePriceItemSchema]);
export type MenuItem = z.infer<typeof MenuItemSchema>;

export type Category = {
  key: string;
  items: MenuItem[];
};

export type ParsedMenu = {
  categories: Category[];
  itemCount: number;
};

export type MenuParseFailure = {
  error: string;
};

export function isSizedItem(item: MenuItem): item is SizedItem {
  return 'sizes' in item;
}

/**
 * Parse and order a raw menu dict.
 *
 * Returns either the ordered categories (with item counts) or a string-
 * keyed error describing which category failed validation. The page-level
 * error boundary renders the message verbatim — keep it human-readable.
 *
 * Empty categories are dropped from the rendered list (an owner viewing
 * the menu doesn't need to see "Drinks (0)").
 */
export function parseMenu(
  raw: Record<string, unknown>,
): ParsedMenu | MenuParseFailure {
  const orderHint = z.array(z.string()).safeParse(raw[CATEGORY_ORDER_KEY]);
  const explicitOrder = orderHint.success ? orderHint.data : null;

  const categoryKeys = Object.keys(raw).filter(
    (k) => !k.startsWith(RESERVED_PREFIX),
  );

  // Honor _category_order, then append any keys not mentioned in it
  // (insertion order). Keys in the hint that don't exist are skipped.
  const orderedKeys = explicitOrder
    ? [
        ...explicitOrder.filter((k) => categoryKeys.includes(k)),
        ...categoryKeys.filter((k) => !explicitOrder.includes(k)),
      ]
    : categoryKeys;

  const categories: Category[] = [];
  let itemCount = 0;

  for (const key of orderedKeys) {
    const parsed = z.array(MenuItemSchema).safeParse(raw[key]);
    if (!parsed.success) {
      return {
        error: `Category "${key}" has an unexpected shape — backend menu doc may be out of sync with the dashboard schema.`,
      };
    }
    if (parsed.data.length === 0) continue;
    categories.push({ key, items: parsed.data });
    itemCount += parsed.data.length;
  }

  return { categories, itemCount };
}

export function itemPriceRange(item: MenuItem): { min: number; max: number } {
  if (isSizedItem(item)) {
    const values = Object.values(item.sizes);
    return { min: Math.min(...values), max: Math.max(...values) };
  }
  return { min: item.price, max: item.price };
}

const CATEGORY_LABEL_OVERRIDES: Record<string, string> = {
  bbq: 'BBQ',
  llb: 'LLB',
};

/**
 * `caribbean_appetizers` → `Caribbean Appetizers`. Acronym overrides keep
 * `bbq` from rendering as `Bbq`.
 */
export function humanizeCategoryKey(key: string): string {
  return key
    .split('_')
    .filter((part) => part.length > 0)
    .map((part) => {
      const lower = part.toLowerCase();
      if (CATEGORY_LABEL_OVERRIDES[lower]) {
        return CATEGORY_LABEL_OVERRIDES[lower];
      }
      return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
    })
    .join(' ');
}
