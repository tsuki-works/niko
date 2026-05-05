'use client';

import { useRef } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  Copy,
  Mic,
  PhoneCall,
  PhoneForwarded,
  PhoneOff,
  Radio,
  Sparkles,
  Voicemail,
  Volume2,
  Zap,
} from 'lucide-react';
import Link from 'next/link';
import { toast } from 'sonner';

import { CallRecordingPlayer } from '@/components/calls/call-recording-player';
import { TimelineExport } from '@/components/calls/timeline-export';
import { Button } from '@/components/ui/button';
import { LocalTime } from '@/components/shared/local-time';
import type { CallEvent, CallTimeline } from '@/lib/api/calls';
import { formatFirstAudioBreakdown } from '@/lib/formatters/call-timeline';
import { cn } from '@/lib/utils';

const TRANSCRIPT_KINDS = new Set(['transcript_final', 'agent_reply']);

/**
 * Event-type accent palette. Five status-token categories + one neutral
 * fallback, per design-system.md → "Stage 6 — Calls list + detail":
 *   confirmed (blue) — system events: call started, recording ready
 *   preparing (violet) — agent / LLM activity
 *   ready (green) — first audio, order confirmed (success states)
 *   live (amber) — caller activity / warnings
 *   cancelled (red) — errors / failed transfers
 *   log (neutral surface-3) — interim transcript, ended, skipped, default
 */
const ACCENT = {
  confirmed: 'bg-status-confirmed-bg text-status-confirmed',
  preparing: 'bg-status-preparing-bg text-status-preparing',
  ready: 'bg-status-ready-bg text-status-ready',
  live: 'bg-status-live-bg text-status-live',
  cancelled: 'bg-status-cancelled-bg text-status-cancelled',
  log: 'bg-surface-3 text-foreground-muted',
} as const;

type AccentKey = keyof typeof ACCENT;

export function CallTimelineView({ timeline }: { timeline: CallTimeline }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const recordingUrl = timeline.recording_available
    ? `/api/calls/${timeline.call_sid}/recording`
    : null;

  // Use the FIRST event's timestamp as the call-start anchor for
  // computing per-turn offsets into the recording. Fallback to 0 if
  // there are no events at all (defensive — shouldn't happen).
  const callStartMs = timeline.events[0]
    ? new Date(timeline.events[0].timestamp).getTime()
    : 0;

  function seekTo(seconds: number) {
    if (!audioRef.current) return;
    audioRef.current.currentTime = Math.max(0, seconds);
    void audioRef.current.play().catch(() => {
      // play() can fail in browsers that require a user gesture per
      // load — the seek still succeeded, the user can press play.
    });
  }

  return (
    <section className="mx-auto flex max-w-5xl flex-col p-6">
      <Header timeline={timeline} />

      {recordingUrl && (
        <div className="mt-4">
          <CallRecordingPlayer ref={audioRef} src={recordingUrl} />
        </div>
      )}

      <ol className="mt-4 flex flex-col">
        {timeline.events.map((event, i) => (
          <TimelineRow
            key={i}
            event={event}
            onSeek={recordingUrl ? seekTo : undefined}
            callStartMs={callStartMs}
          />
        ))}
      </ol>
    </section>
  );
}

function Header({ timeline }: { timeline: CallTimeline }) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="flex flex-col gap-1">
        <Link
          href="/calls"
          className="inline-flex w-fit items-center gap-1 text-sm text-foreground-muted hover:text-foreground"
        >
          <ChevronLeft className="size-4" aria-hidden />
          All calls
        </Link>
        <h2 className="text-lg font-semibold">Call timeline</h2>
        <p className="font-mono text-sm text-foreground-muted">
          {timeline.call_sid}
        </p>
      </div>
      <TimelineExport timeline={timeline} />
    </header>
  );
}

function TimelineRow({
  event,
  onSeek,
  callStartMs,
}: {
  event: CallEvent;
  onSeek?: (seconds: number) => void;
  callStartMs: number;
}) {
  const ts = new Date(event.timestamp);
  const { Icon, accent, label, body, copyText } = renderEvent(event);

  const isTranscript = TRANSCRIPT_KINDS.has(event.kind);
  const offsetSec = Math.max(0, (ts.getTime() - callStartMs) / 1000);
  const canSeek = isTranscript && onSeek !== undefined;

  function handleSeek() {
    if (canSeek) onSeek!(offsetSec);
  }

  function handleCopy() {
    if (!copyText) return;
    void navigator.clipboard.writeText(copyText).then(
      () => toast.success('Turn copied'),
      () => toast.error('Copy failed'),
    );
  }

  const RowTag = canSeek ? 'button' : 'div';

  return (
    <li className="flex items-start gap-3 border-b border-border-subtle py-2.5 last:border-b-0 hover:bg-surface-2/40">
      <RowTag
        type={canSeek ? 'button' : undefined}
        onClick={canSeek ? handleSeek : undefined}
        className={cn(
          'flex flex-1 items-start gap-3 bg-transparent p-0 text-left',
          canSeek && 'cursor-pointer focus-visible:outline-2 focus-visible:outline-brand',
        )}
        aria-label={canSeek ? `Seek to ${label} at ${formatOffset(offsetSec)}` : undefined}
      >
        <div
          className={cn(
            'mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full',
            ACCENT[accent],
          )}
        >
          <Icon className="size-3.5" aria-hidden />
        </div>
        <div className="flex w-15 shrink-0 flex-col text-right text-xs font-mono text-foreground-muted tabular-nums">
          <LocalTime date={ts} mode="absolute" />
        </div>
        <div className="flex flex-1 flex-col gap-0.5">
          <p className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
            {label}
          </p>
          <div className="text-sm">{body}</div>
        </div>
      </RowTag>
      {copyText ? (
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-7 shrink-0"
          aria-label={`Copy ${label} text`}
          onClick={handleCopy}
        >
          <Copy className="size-3.5" />
        </Button>
      ) : null}
    </li>
  );
}

function formatOffset(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

type RenderedEvent = {
  Icon: typeof Mic;
  accent: AccentKey;
  label: string;
  body: React.ReactNode;
  // Plain-text version for clipboard. Only set on transcript-style events.
  copyText?: string;
};

function renderEvent(event: CallEvent): RenderedEvent {
  switch (event.kind) {
    case 'start':
      return {
        Icon: PhoneCall,
        accent: 'confirmed',
        label: 'call started',
        body: 'Twilio media stream opened',
      };
    case 'stop':
      return {
        Icon: PhoneOff,
        accent: 'log',
        label: 'call ended',
        body: 'Caller hung up',
      };
    case 'order_confirmed':
      return {
        Icon: CheckCircle2,
        accent: 'ready',
        label: 'order confirmed',
        body: 'Order persisted to Firestore',
      };
    case 'transcript_final': {
      const text = (event.detail.text as string) || '(empty)';
      return {
        Icon: Mic,
        accent: 'live',
        label: 'caller',
        body: <span className="italic">&ldquo;{text}&rdquo;</span>,
        copyText: text,
      };
    }
    case 'transcript_interim': {
      const text = (event.detail.text as string) || '';
      return {
        Icon: Mic,
        accent: 'log',
        label: 'interim transcript',
        body: <span className="italic text-foreground-muted">&ldquo;{text}&rdquo;</span>,
      };
    }
    case 'llm_turn_start': {
      const transcript = (event.detail.transcript as string) ?? '';
      return {
        Icon: Sparkles,
        accent: 'preparing',
        label: 'LLM turn start',
        body: transcript ? `→ "${transcript}"` : 'turn opened',
      };
    }
    case 'agent_reply': {
      const reply = (event.detail.text as string) || event.text || '';
      return {
        Icon: Sparkles,
        accent: 'preparing',
        label: 'agent',
        body: <span className="italic">&ldquo;{reply}&rdquo;</span>,
        copyText: reply,
      };
    }
    case 'first_audio': {
      const latency = event.detail.latency_seconds as number | undefined;
      const overBudget = typeof latency === 'number' && latency >= 1;
      const breakdown = formatFirstAudioBreakdown(
        event.detail as Record<string, unknown>,
      );
      const headline =
        typeof latency === 'number'
          ? `${(latency * 1000).toFixed(0)}ms${overBudget ? ' (over <1s budget)' : ''}`
          : 'first audio bytes sent';
      return {
        Icon: Volume2,
        accent: overBudget ? 'live' : 'ready',
        label: 'first audio',
        body: breakdown ? (
          <span>
            {headline}{' '}
            <span className="font-mono text-xs text-foreground-faint">
              {breakdown}
            </span>
          </span>
        ) : (
          headline
        ),
      };
    }
    case 'barge_in':
      return {
        Icon: Zap,
        accent: 'live',
        label: 'barge-in',
        body: 'caller spoke over the AI; in-flight reply cancelled',
      };
    case 'silence_timeout':
      return {
        Icon: AlertTriangle,
        accent: 'live',
        label: 'silence timeout',
        body: 'no caller activity for 10s — bot prompted',
      };
    case 'recording_ready': {
      const duration = event.detail.duration_seconds as number | undefined;
      return {
        Icon: Radio,
        accent: 'confirmed',
        label: 'recording ready',
        body: typeof duration === 'number' ? `${duration}s recording available` : 'recording available',
      };
    }
    case 'transfer_requested': {
      const phone = event.detail.fallback_phone as string | undefined;
      return {
        Icon: PhoneForwarded,
        accent: 'preparing',
        label: 'transfer requested',
        body: phone ? <span>routing to {phone}…</span> : <span>routing…</span>,
      };
    }
    case 'transfer_attempted': {
      const status = (event.detail.status as string | undefined) ?? 'attempted';
      const phone = event.detail.fallback_phone as string | undefined;
      const labelByStatus: Record<string, string> = {
        answered: 'Transfer connected',
        no_answer: 'Transfer — no answer',
        busy: 'Transfer — busy',
        failed: 'Transfer — failed',
        skipped: 'Transfer skipped',
      };
      const accentByStatus: Record<string, AccentKey> = {
        answered: 'ready',
        no_answer: 'live',
        busy: 'live',
        failed: 'cancelled',
        skipped: 'log',
      };
      return {
        Icon: PhoneForwarded,
        accent: accentByStatus[status] ?? 'log',
        label: labelByStatus[status] ?? 'transfer',
        body: phone ? <span>to {phone}</span> : <span>{status}</span>,
      };
    }
    case 'voicemail_left': {
      const transcript = (event.text as string) || '';
      const duration = event.detail.duration_seconds as number | undefined;
      return {
        Icon: Voicemail,
        accent: 'live',
        label: 'voicemail',
        body: (
          <div className="flex flex-col gap-1">
            <span className="text-xs text-foreground-muted">
              {typeof duration === 'number' ? `${duration}s` : 'recording available'}
            </span>
            {transcript ? (
              <span className="italic">&ldquo;{transcript}&rdquo;</span>
            ) : (
              <span className="text-xs italic text-foreground-muted">
                Transcript pending…
              </span>
            )}
          </div>
        ),
        copyText: transcript || undefined,
      };
    }
    case 'error':
      return {
        Icon: AlertTriangle,
        accent: 'cancelled',
        label: 'error',
        body: <pre className="whitespace-pre-wrap font-mono text-xs">{event.text}</pre>,
      };
    default:
      return {
        Icon: Sparkles,
        accent: 'log',
        label: 'log',
        body: <span className="font-mono text-xs">{event.text}</span>,
      };
  }
}
