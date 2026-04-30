/**
 * Call session schemas — mirror the Firestore documents written by
 * `app/storage/call_sessions.py`.
 *
 * After PR C of #79, the canonical path is
 * `restaurants/{restaurant_id}/call_sessions/{call_sid}` (with an
 * `events` subcollection). The legacy flat `call_sessions` writes
 * are still mirrored until PR F.
 *
 * Field names are snake_case to match the backend writes — do not
 * rename to camelCase on read.
 */
import { z } from 'zod';

export const CallStatusSchema = z.enum([
  'in_progress',
  'ended',
  'confirmed',
]);
export type CallStatus = z.infer<typeof CallStatusSchema>;

export const CallEventKindSchema = z.enum([
  'start',
  'transcript_final',
  'transcript_interim',
  'llm_turn_start',
  'agent_reply',
  'first_audio',
  'barge_in',
  'silence_timeout',
  'stop',
  'order_confirmed',
  'recording_ready',
  'error',
  'log',
]);
export type CallEventKind = z.infer<typeof CallEventKindSchema>;

export const CallSessionSchema = z.object({
  call_sid: z.string().min(1),
  // Optional during the migration window: legacy flat docs predate
  // PR C and don't carry restaurant_id. Once PR F deletes the legacy
  // path we tighten this to .min(1).
  restaurant_id: z.string().optional(),
  started_at: z.coerce.date(),
  ended_at: z.coerce.date().nullable(),
  status: CallStatusSchema,
  transcript_count: z.number().int().min(0).default(0),
  has_error: z.boolean().default(false),
  last_event_at: z.coerce.date().nullish(),
  // Set by the backend once the Twilio recording is processed. Absent on
  // calls that have no recording yet. Frontend never sees the raw URL —
  // it proxies playback through GET /calls/{call_sid}/recording.
  recording_url: z.string().optional(),
});
export type CallSession = z.infer<typeof CallSessionSchema>;

export const CallEventSchema = z.object({
  timestamp: z.coerce.date(),
  kind: CallEventKindSchema.catch('log'),
  text: z.string().default(''),
  detail: z.record(z.string(), z.unknown()).default({}),
});
export type CallEvent = z.infer<typeof CallEventSchema>;

export function callShortId(session: { call_sid: string }): string {
  return session.call_sid.slice(0, 8) + '…';
}
