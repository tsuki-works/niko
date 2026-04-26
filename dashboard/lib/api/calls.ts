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
};

export type CallsListResult =
  | { available: true; calls: CallSummary[] }
  | { available: false };

export type CallTimelineResult =
  | { available: true; timeline: CallTimeline }
  | { available: false }
  | { available: true; notFound: true };

function apiBase(): string {
  const base = process.env.NIKO_API_BASE_URL;
  if (!base) throw new Error('NIKO_API_BASE_URL is not set');
  return base.replace(/\/$/, '');
}

export async function listRecentCalls(hours = 24): Promise<CallsListResult> {
  const url = new URL(`${apiBase()}/dev/calls`);
  url.searchParams.set('hours', String(hours));

  const res = await fetch(url, { cache: 'no-store' });
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
  const url = `${apiBase()}/dev/calls/${encodeURIComponent(callSid)}`;
  const res = await fetch(url, { cache: 'no-store' });

  if (res.status === 404) {
    // The backend returns 404 for both "dev disabled" and "call not found".
    // Probe the list endpoint to disambiguate — if it 404s the feature is
    // disabled; otherwise the specific call_sid wasn't in the log window.
    const probe = await fetch(`${apiBase()}/dev/calls?hours=1`, {
      cache: 'no-store',
    });
    if (probe.status === 404) return { available: false };
    return { available: true, notFound: true };
  }

  if (!res.ok) {
    throw new Error(
      `GET /dev/calls/${callSid} failed: ${res.status} ${res.statusText}`,
    );
  }

  const body = (await res.json()) as CallTimeline;
  return { available: true, timeline: body };
}
