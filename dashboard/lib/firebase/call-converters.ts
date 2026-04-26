/**
 * Firestore converters for the live `call_sessions` collection.
 *
 * Mirrors `lib/firebase/converters.ts` for orders. Every Firestore read
 * goes through Zod validation — on parse failure we log and throw rather
 * than silently coercing, so a backend-side schema drift becomes
 * immediately obvious.
 */
import {
  type FirestoreDataConverter,
  type QueryDocumentSnapshot,
  type SnapshotOptions,
  Timestamp,
} from 'firebase/firestore';
import { z } from 'zod';

import {
  type CallEvent,
  CallEventSchema,
  type CallSession,
  CallSessionSchema,
} from '@/lib/schemas/call';

export class CallValidationError extends Error {
  constructor(
    readonly docId: string,
    readonly issues: z.ZodIssue[],
  ) {
    super(
      `Call document ${docId} failed schema validation: ${issues
        .map((i) => `${i.path.join('.')}: ${i.message}`)
        .join('; ')}`,
    );
    this.name = 'CallValidationError';
  }
}

function unwrapTimestamp(v: unknown): unknown {
  if (v == null) return v;
  if (v instanceof Timestamp) return v.toDate();
  if (
    v &&
    typeof v === 'object' &&
    'toDate' in v &&
    typeof (v as { toDate: unknown }).toDate === 'function'
  ) {
    return (v as { toDate: () => Date }).toDate();
  }
  return v;
}

function normalizeSession(raw: Record<string, unknown>): Record<string, unknown> {
  return {
    ...raw,
    started_at: unwrapTimestamp(raw.started_at),
    ended_at: unwrapTimestamp(raw.ended_at),
    last_event_at: unwrapTimestamp(raw.last_event_at),
  };
}

function normalizeEvent(raw: Record<string, unknown>): Record<string, unknown> {
  return {
    ...raw,
    timestamp: unwrapTimestamp(raw.timestamp),
  };
}

export const callSessionConverter: FirestoreDataConverter<CallSession> = {
  toFirestore(session) {
    return session as Record<string, unknown>;
  },
  fromFirestore(snap: QueryDocumentSnapshot, options?: SnapshotOptions): CallSession {
    const raw = snap.data(options) as Record<string, unknown>;
    const parsed = CallSessionSchema.safeParse(normalizeSession(raw));
    if (!parsed.success) {
      console.error(
        '[callSessionConverter] schema validation failed',
        snap.id,
        parsed.error.issues,
      );
      throw new CallValidationError(snap.id, parsed.error.issues);
    }
    return parsed.data;
  },
};

export const callEventConverter: FirestoreDataConverter<CallEvent> = {
  toFirestore(event) {
    return event as Record<string, unknown>;
  },
  fromFirestore(snap: QueryDocumentSnapshot, options?: SnapshotOptions): CallEvent {
    const raw = snap.data(options) as Record<string, unknown>;
    const parsed = CallEventSchema.safeParse(normalizeEvent(raw));
    if (!parsed.success) {
      console.error(
        '[callEventConverter] schema validation failed',
        snap.id,
        parsed.error.issues,
      );
      throw new CallValidationError(snap.id, parsed.error.issues);
    }
    return parsed.data;
  },
};

/**
 * Parse a CallSession-shaped object that came back as JSON from the
 * FastAPI dev route. Used by the RSC fetch path that seeds the initial
 * render before onSnapshot takes over.
 */
export function parseCallSessionFromJson(raw: unknown): CallSession {
  const withDates =
    raw && typeof raw === 'object'
      ? {
          ...(raw as Record<string, unknown>),
          started_at: toDate((raw as Record<string, unknown>).started_at),
          ended_at: toDate((raw as Record<string, unknown>).ended_at),
        }
      : raw;
  const parsed = CallSessionSchema.safeParse(withDates);
  if (!parsed.success) {
    console.error('[parseCallSessionFromJson] failed', parsed.error.issues);
    throw new CallValidationError('api', parsed.error.issues);
  }
  return parsed.data;
}

export function parseCallEventFromJson(raw: unknown): CallEvent {
  const withDates =
    raw && typeof raw === 'object'
      ? {
          ...(raw as Record<string, unknown>),
          timestamp: toDate((raw as Record<string, unknown>).timestamp),
        }
      : raw;
  const parsed = CallEventSchema.safeParse(withDates);
  if (!parsed.success) {
    console.error('[parseCallEventFromJson] failed', parsed.error.issues);
    throw new CallValidationError('api', parsed.error.issues);
  }
  return parsed.data;
}

function toDate(v: unknown): unknown {
  if (v == null) return v;
  if (v instanceof Date) return v;
  if (typeof v === 'string' || typeof v === 'number') return new Date(v);
  return v;
}
