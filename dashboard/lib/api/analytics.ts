import 'server-only';

import { apiFetch } from '@/lib/api/http';
import {
  OrderSummarySchema,
  type OrderSummary,
} from '@/lib/schemas/analytics';

export async function getOrderSummary(): Promise<OrderSummary> {
  const res = await apiFetch('/analytics/summary');
  if (!res.ok) {
    throw new Error(
      `GET /analytics/summary failed: ${res.status} ${res.statusText}`,
    );
  }
  const body = (await res.json()) as unknown;
  const parsed = OrderSummarySchema.safeParse(body);
  if (!parsed.success) {
    console.error(
      '[lib/api/analytics] /analytics/summary failed validation',
      parsed.error.flatten(),
    );
    throw new Error('analytics summary failed schema validation');
  }
  return parsed.data;
}
