import {
  type FirestoreDataConverter,
  type QueryDocumentSnapshot,
  type SnapshotOptions,
  Timestamp,
} from 'firebase/firestore';
import { z } from 'zod';

import { type Order, OrderSchema } from '@/lib/schemas/order';

export class OrderValidationError extends Error {
  constructor(
    readonly docId: string,
    readonly issues: z.ZodIssue[],
  ) {
    super(
      `Order document ${docId} failed schema validation: ${issues
        .map((i) => `${i.path.join('.')}: ${i.message}`)
        .join('; ')}`,
    );
    this.name = 'OrderValidationError';
  }
}

function unwrapTimestamp(v: unknown): unknown {
  if (v instanceof Timestamp) return v.toDate();
  if (v && typeof v === 'object' && 'toDate' in v && typeof (v as { toDate: unknown }).toDate === 'function') {
    return (v as { toDate: () => Date }).toDate();
  }
  return v;
}

function normalize(raw: Record<string, unknown>): Record<string, unknown> {
  return {
    ...raw,
    created_at: unwrapTimestamp(raw.created_at),
    confirmed_at: unwrapTimestamp(raw.confirmed_at),
    preparing_at: unwrapTimestamp(raw.preparing_at),
    ready_at: unwrapTimestamp(raw.ready_at),
    completed_at: unwrapTimestamp(raw.completed_at),
    cancelled_at: unwrapTimestamp(raw.cancelled_at),
  };
}

export const orderConverter: FirestoreDataConverter<Order> = {
  toFirestore(order) {
    return order as Record<string, unknown>;
  },

  fromFirestore(
    snapshot: QueryDocumentSnapshot,
    options?: SnapshotOptions,
  ): Order {
    const raw = snapshot.data(options) as Record<string, unknown>;
    const parsed = OrderSchema.safeParse(normalize(raw));
    if (!parsed.success) {
      console.error(
        '[orderConverter] schema validation failed',
        snapshot.id,
        parsed.error.issues,
      );
      throw new OrderValidationError(snapshot.id, parsed.error.issues);
    }
    return parsed.data;
  },
};

/**
 * Parse an order object whose timestamps are already plain Dates or ISO strings
 * (e.g. coming back from the FastAPI JSON endpoints via `model_dump(mode="json")`).
 * Used by the RSC fetch path; the Firestore `onSnapshot` path goes through
 * `orderConverter` instead.
 */
export function parseOrderFromJson(raw: unknown, contextLabel = 'api'): Order {
  const withDates =
    raw && typeof raw === 'object'
      ? {
          ...(raw as Record<string, unknown>),
          created_at: toDate((raw as Record<string, unknown>).created_at),
          confirmed_at: toDate((raw as Record<string, unknown>).confirmed_at),
          preparing_at: toDate((raw as Record<string, unknown>).preparing_at),
          ready_at: toDate((raw as Record<string, unknown>).ready_at),
          completed_at: toDate((raw as Record<string, unknown>).completed_at),
          cancelled_at: toDate((raw as Record<string, unknown>).cancelled_at),
        }
      : raw;

  const parsed = OrderSchema.safeParse(withDates);
  if (!parsed.success) {
    console.error(
      `[${contextLabel}] order JSON failed schema validation`,
      parsed.error.issues,
    );
    throw new OrderValidationError(contextLabel, parsed.error.issues);
  }
  return parsed.data;
}

function toDate(v: unknown): unknown {
  if (v == null) return v;
  if (v instanceof Date) return v;
  if (typeof v === 'string' || typeof v === 'number') return new Date(v);
  return v;
}
