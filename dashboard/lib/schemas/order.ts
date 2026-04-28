/**
 * Order schemas mirrored from the backend Pydantic models in
 * `app/orders/models.py`. Field names are snake_case to match the
 * Firestore documents written by FastAPI — do not rename.
 *
 * Money is stored as `number` (float) to match the backend and
 * Firestore's native number type. Do NOT convert to integer cents on
 * read — the backend writes floats, and reformatting on read would
 * drift. See Phase 2 notes in CLAUDE.md for the migration plan.
 *
 * `line_total` and `subtotal` are Pydantic `computed_field`s on the
 * backend side — they're serialized when the model is written to
 * Firestore, so they're present on every document.
 */
import { z } from 'zod';

export const OrderTypeSchema = z.enum(['pickup', 'delivery']);
export type OrderType = z.infer<typeof OrderTypeSchema>;

export const OrderStatusSchema = z.enum([
  'in_progress',
  'confirmed',
  'preparing',
  'ready',
  'completed',
  'cancelled',
]);
export type OrderStatus = z.infer<typeof OrderStatusSchema>;

// Free-form per-tenant category string. Was a fixed enum
// (`pizza`/`side`/`drink`) during the pizza-shop POC; relaxed to a
// plain string post-#98 so a Caribbean tenant can write
// `category="appetizer"` without parse failure. The dashboard never
// branches on the value — it's just displayed/grouped — so widening
// is a safe schema-only change.
export const ItemCategorySchema = z.string();
export type ItemCategory = z.infer<typeof ItemCategorySchema>;

export const LineItemSchema = z.object({
  name: z.string(),
  category: ItemCategorySchema,
  size: z.string().nullish(),
  quantity: z.number().int().min(1),
  unit_price: z.number().min(0),
  modifications: z.array(z.string()).default([]),
  line_total: z.number(),
});
export type LineItem = z.infer<typeof LineItemSchema>;

export const OrderSchema = z.object({
  call_sid: z.string(),
  caller_phone: z.string().nullish(),
  restaurant_id: z.string(),
  items: z.array(LineItemSchema).default([]),
  order_type: OrderTypeSchema.nullish(),
  delivery_address: z.string().nullish(),
  status: OrderStatusSchema,
  created_at: z.coerce.date(),
  confirmed_at: z.coerce.date().nullish(),
  // Per-transition timestamps stamped by the backend on each
  // successful state change. None for any transition that hasn't
  // happened yet. See app/orders/lifecycle.py for the source.
  preparing_at: z.coerce.date().nullish(),
  ready_at: z.coerce.date().nullish(),
  completed_at: z.coerce.date().nullish(),
  cancelled_at: z.coerce.date().nullish(),
  subtotal: z.number(),
});
export type Order = z.infer<typeof OrderSchema>;

/**
 * Short, human-pronounceable identifier derived from the call_sid.
 * Twilio SIDs look like 'CA1a2b3c4d5e6f...' — we take the last 4 hex
 * chars and uppercase them. Collision odds are low enough for POC.
 *
 * TODO(phase 2): add a real `order_number` field on the backend.
 */
export function orderShortId(order: Pick<Order, 'call_sid'>): string {
  return `#${order.call_sid.slice(-4).toUpperCase()}`;
}

/**
 * Formats a line item as staff read it in the dashboard:
 *   "1 × Large pepperoni pizza"
 * Size is interpolated into the name when present.
 */
export function formatLineItemTitle(item: LineItem): string {
  const sizePart = item.size ? `${capitalize(item.size)} ` : '';
  return `${item.quantity} × ${sizePart}${item.name.toLowerCase()}`;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
