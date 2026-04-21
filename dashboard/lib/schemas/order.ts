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
  'cancelled',
]);
export type OrderStatus = z.infer<typeof OrderStatusSchema>;

export const ItemCategorySchema = z.enum(['pizza', 'side', 'drink']);
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
  created_at: z.date(),
  confirmed_at: z.date().nullish(),
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
