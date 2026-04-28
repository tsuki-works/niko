/**
 * HTTP client for the FastAPI orders endpoints.
 *
 * Only used on the server (RSC fetch + Server Actions) — the dashboard
 * never calls these from the browser, because real-time updates come
 * through Firestore `onSnapshot` instead (see dashboard/CLAUDE.md).
 *
 * Endpoints:
 *   GET  /orders                         ← LIVE (app/main.py)
 *   GET  /orders/{call_sid}              ← NOT YET IMPLEMENTED
 *   POST /orders/{call_sid}/cancel       ← NOT YET IMPLEMENTED
 *
 * The two missing endpoints are stubbed here so the dashboard compiles
 * and the UI paths light up. When Meet lands them on the backend, flip
 * the `STUB_*` constants to `false`.
 */
import 'server-only';

import {
  type Order,
  OrderSchema,
  OrderStatusSchema,
  type OrderStatus,
} from '@/lib/schemas/order';
import { parseOrderFromJson } from '@/lib/firebase/converters';
import { apiFetch } from '@/lib/api/http';

const STUB_GET_ORDER_BY_ID = true;
const STUB_CANCEL_ORDER = false;

export async function listOrders(params: {
  status?: OrderStatus;
  limit?: number;
}): Promise<Order[]> {
  const limit = params.limit ?? 50;
  const path = `/orders?limit=${encodeURIComponent(String(limit))}`;
  const res = await apiFetch(path);
  if (!res.ok) {
    throw new Error(`GET /orders failed: ${res.status} ${res.statusText}`);
  }

  const body = (await res.json()) as { orders: unknown[] };
  const parsed = body.orders.map((raw, i) =>
    parseOrderFromJson(raw, `listOrders[${i}]`),
  );

  if (params.status) {
    return parsed.filter((o) => o.status === params.status);
  }
  return parsed;
}

export async function getOrder(callSid: string): Promise<Order | null> {
  if (STUB_GET_ORDER_BY_ID) {
    // TODO(backend): GET /orders/{call_sid}. Until then, fall back to the
    // list endpoint and filter. Cheap for POC (≤50 docs) — swap this
    // when Meet ships the per-order route.
    const all = await listOrders({ limit: 200 });
    return all.find((o) => o.call_sid === callSid) ?? null;
  }

  const path = `/orders/${encodeURIComponent(callSid)}`;
  const res = await apiFetch(path);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(
      `GET /orders/${callSid} failed: ${res.status} ${res.statusText}`,
    );
  }
  return parseOrderFromJson(await res.json(), `getOrder(${callSid})`);
}

export type CancelResult =
  | { success: true; order: Order }
  | { success: false; error: string };

export async function cancelOrderApi(callSid: string): Promise<CancelResult> {
  if (STUB_CANCEL_ORDER) {
    return {
      success: false,
      error: 'cancel endpoint not yet implemented',
    };
  }

  const path = `/orders/${encodeURIComponent(callSid)}/cancel`;
  const res = await apiFetch(path, { method: 'POST' });

  if (!res.ok) {
    // FastAPI returns { detail: string } on 4xx — surface that detail
    // to the user as the error message.
    let detail: string;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail =
        typeof body.detail === 'string'
          ? body.detail
          : `${res.status} ${res.statusText}`;
    } catch {
      detail = `${res.status} ${res.statusText}`;
    }
    return { success: false, error: detail };
  }

  const body = await res.json();
  const parsed = OrderSchema.safeParse(
    body && typeof body === 'object' && 'order' in body ? body.order : body,
  );
  if (!parsed.success) {
    return { success: false, error: 'Cancel response failed validation' };
  }
  return { success: true, order: parsed.data };
}

export function parseStatusParam(raw: string | undefined): OrderStatus | undefined {
  if (!raw) return undefined;
  const parsed = OrderStatusSchema.safeParse(raw);
  return parsed.success ? parsed.data : undefined;
}
