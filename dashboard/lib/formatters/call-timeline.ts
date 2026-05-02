/**
 * Plain-text formatter for call timelines (#72).
 *
 * Produces a fixed-width one-line-per-event log suitable for pasting
 * into Slack threads, GitHub issues, or PR comments. Pure function so
 * it's easy to unit-test independent of the React surface.
 */
import type { CallEvent, CallTimeline } from '@/lib/api/calls';

const KIND_LABEL: Record<string, string> = {
  start: 'CALL_START',
  stop: 'CALL_END',
  order_confirmed: 'ORDER_CONFIRMED',
  transcript_final: 'CALLER',
  transcript_interim: 'CALLER_INTERIM',
  llm_turn_start: 'LLM_TURN',
  agent_reply: 'AGENT',
  first_audio: 'FIRST_AUDIO',
  barge_in: 'BARGE_IN',
  silence_timeout: 'SILENCE_TIMEOUT',
  error: 'ERROR',
  log: 'LOG',
};

const KIND_COL_WIDTH = 17;

function pad(s: string, width: number): string {
  return s.length >= width ? s : s + ' '.repeat(width - s.length);
}

function hms(d: Date): string {
  return new Intl.DateTimeFormat('en-CA', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  }).format(d);
}

function isoUtc(d: Date): string {
  return d.toISOString().replace('T', ' ').replace(/\..+$/, '') + ' UTC';
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s.toString().padStart(2, '0')}s`;
}

/**
 * Render the latency-breakdown suffix for `first_audio` events that
 * carry the #146 instrumentation fields. Returns an empty string for
 * legacy events that only have `latency_seconds`, so old timelines
 * still render cleanly.
 */
export function formatFirstAudioBreakdown(detail: Record<string, unknown>): string {
  const ttft = detail.ttft_seconds as number | undefined;
  const networkPrefill = detail.network_prefill_seconds as number | undefined;
  const decode = detail.decode_seconds as number | undefined;
  const toolPrefix = detail.tool_prefix_seconds as number | undefined;
  const firstText = detail.first_text_seconds as number | undefined;
  const cacheRead = detail.cache_read_tokens as number | undefined;
  const cacheCreation = detail.cache_creation_tokens as number | undefined;

  const parts: string[] = [];
  if (typeof ttft === 'number') parts.push(`ttft=${Math.round(ttft * 1000)}ms`);
  // #175 finer breakdown: network+prefill and decode placed after ttft, before cache.
  if (typeof networkPrefill === 'number')
    parts.push(`net+pre=${Math.round(networkPrefill * 1000)}ms`);
  if (typeof decode === 'number') parts.push(`decode=${Math.round(decode * 1000)}ms`);
  if (typeof toolPrefix === 'number')
    parts.push(`tool=${Math.round(toolPrefix * 1000)}ms`);
  if (typeof firstText === 'number')
    parts.push(`text=${Math.round(firstText * 1000)}ms`);
  if (typeof cacheRead === 'number' || typeof cacheCreation === 'number') {
    const hit = (cacheRead ?? 0) > 0 && (cacheCreation ?? 0) === 0;
    parts.push(`cache=${hit ? 'hit' : 'miss'}`);
  }

  return parts.length ? `[${parts.join(' ')}]` : '';
}

function eventBody(event: CallEvent): string {
  switch (event.kind) {
    case 'transcript_final':
    case 'transcript_interim':
      return (event.detail.text as string) ?? '';
    case 'llm_turn_start':
      return (event.detail.transcript as string) ?? '';
    case 'agent_reply':
      return (event.detail.text as string) || event.text || '';
    case 'first_audio': {
      const latency = event.detail.latency_seconds as number | undefined;
      if (typeof latency !== 'number') return '';
      const ms = Math.round(latency * 1000);
      const head = ms >= 1000 ? `${ms}ms (over budget)` : `${ms}ms`;
      const breakdown = formatFirstAudioBreakdown(event.detail);
      return breakdown ? `${head} ${breakdown}` : head;
    }
    case 'error':
      return event.text;
    default:
      return '';
  }
}

export function formatTimelineAsText(timeline: CallTimeline): string {
  const events = timeline.events;
  if (events.length === 0) {
    return `Call ${timeline.call_sid}\n(no events)`;
  }

  const startedAt = new Date(events[0].timestamp);
  const endedAt = new Date(events[events.length - 1].timestamp);
  const durationSec = Math.max(
    0,
    Math.round((endedAt.getTime() - startedAt.getTime()) / 1000),
  );

  const header = [
    `Call ${timeline.call_sid}`,
    `Started: ${isoUtc(startedAt)}`,
    `Duration: ${formatDuration(durationSec)}`,
    '',
  ].join('\n');

  const rows = events.map((event) => {
    const ts = hms(new Date(event.timestamp));
    const label = pad(KIND_LABEL[event.kind] ?? event.kind.toUpperCase(), KIND_COL_WIDTH);
    const body = eventBody(event);
    return body ? `${ts}  ${label}${body}` : `${ts}  ${label.trimEnd()}`;
  });

  return header + rows.join('\n') + '\n';
}

export function timelineFilename(timeline: CallTimeline, now: Date = new Date()): string {
  const date = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: 'UTC',
  })
    .format(now)
    .replaceAll('-', '');
  const shortSid = timeline.call_sid.slice(0, 10);
  return `niko-call-${shortSid}-${date}.txt`;
}
