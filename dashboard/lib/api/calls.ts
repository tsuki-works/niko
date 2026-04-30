/**
 * HTTP client for the FastAPI dev call-logs endpoints.
 *
 * These routes are gated on `NIKO_DEV_ENDPOINTS=true` in the backend
 * service. When the flag is off they return 404 — we surface that to the
 * dashboard so it can fall back to the "Coming Soon" treatment.
 *
 * Endpoints:
 *   GET /dev/calls                  ← list of recent call sessions
 *   GET /dev/calls/{call_sid}       ← full event timeline for one call
 *
 * Server-only — same as `lib/api/orders.ts`. No browser-side fetches.
 */
import 'server-only';

import { apiFetch } from '@/lib/api/http';

export type CallStatus = 'confirmed' | 'ended' | 'in_progress';

export type CallEventKind =
  | 'start'
  | 'transcript_final'
  | 'transcript_interim'
  | 'llm_turn_start'
  | 'agent_reply'
  | 'first_audio'
  | 'barge_in'
  | 'silence_timeout'
  | 'stop'
  | 'order_confirmed'
  | 'recording_ready'
  | 'error'
  | 'log';

export type CallSummary = {
  call_sid: string;
  started_at: string;
  ended_at: string;
  transcript_count: number;
  has_error: boolean;
  status: CallStatus;
};

export type CallEvent = {
  timestamp: string;
  kind: CallEventKind;
  text: string;
  detail: Record<string, unknown>;
};

export type CallTimeline = {
  call_sid: string;
  events: CallEvent[];
  // True when Twilio has finished processing the recording. Absent/false
  // while the recording is still processing or if the call has none.
  // The audio player proxies through GET /calls/{call_sid}/recording.
  recording_available?: boolean;
};

export type CallsListResult =
  | { available: true; calls: CallSummary[] }
  | { available: false };

export type CallTimelineResult =
  | { available: true; timeline: CallTimeline }
  | { available: false }
  | { available: true; notFound: true };

export async function listRecentCalls(hours = 24): Promise<CallsListResult> {
  const path = `/dev/calls?hours=${encodeURIComponent(String(hours))}`;
  const res = await apiFetch(path);
  if (res.status === 404) return { available: false };
  if (!res.ok) {
    throw new Error(`GET /dev/calls failed: ${res.status} ${res.statusText}`);
  }

  const body = (await res.json()) as { calls: CallSummary[] };
  return { available: true, calls: body.calls };
}

export async function getCallTimeline(
  callSid: string,
): Promise<CallTimelineResult> {
  const path = `/dev/calls/${encodeURIComponent(callSid)}`;
  const res = await apiFetch(path);

  if (res.status === 404) {
    // The backend returns 404 for both "dev disabled" and "call not found".
    // Probe the list endpoint to disambiguate — if it 404s the feature is
    // disabled; otherwise the specific call_sid wasn't in the log window.
    const probe = await apiFetch('/dev/calls?hours=1');
    if (probe.status === 404) return { available: false };
    return { available: true, notFound: true };
  }

  if (!res.ok) {
    throw new Error(
      `GET /dev/calls/${callSid} failed: ${res.status} ${res.statusText}`,
    );
  }

  const body = (await res.json()) as Omit<CallTimeline, 'recording_available'> & { events: CallEvent[] };
  const recording_available = body.events.some((e) => e.kind === 'recording_ready');
  return { available: true, timeline: { ...body, recording_available } };
}
