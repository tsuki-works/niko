'use client';

import { useId, useRef, useState } from 'react';
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
 *
 * Split bg from fg so the icon container can keep the accent bg while
 * the Tier 2 (telemetry) icon color is overridden cleanly to
 * `text-foreground-subtle` without competing utilities on the same
 * element.
 */
const ACCENT_BG = {
  confirmed: 'bg-status-confirmed-bg',
  preparing: 'bg-status-preparing-bg',
  ready: 'bg-status-ready-bg',
  live: 'bg-status-live-bg',
  cancelled: 'bg-status-cancelled-bg',
  log: 'bg-surface-3',
} as const;

const ACCENT_FG = {
  confirmed: 'text-status-confirmed',
  preparing: 'text-status-preparing',
  ready: 'text-status-ready',
  live: 'text-status-live',
  cancelled: 'text-status-cancelled',
  log: 'text-foreground-muted',
} as const;

type AccentKey = keyof typeof ACCENT_BG;

export function CallTimelineView({ timeline }: { timeline: CallTimeline }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [showTelemetry, setShowTelemetry] = useState(false);

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

  const telemetryCount = timeline.events.filter(
    (e) => tierOf(e) === 'telemetry',
  ).length;
  const visibleEvents = showTelemetry
    ? timeline.events
    : timeline.events.filter((e) => tierOf(e) === 'conversation');

  return (
    <section className="mx-auto flex max-w-5xl flex-col p-6">
      <Header timeline={timeline} />

      {recordingUrl && (
        <div className="mt-4">
          <CallRecordingPlayer ref={audioRef} src={recordingUrl} />
        </div>
      )}

      <TelemetryToggle
        enabled={showTelemetry}
        onToggle={() => setShowTelemetry((v) => !v)}
        hiddenCount={telemetryCount}
      />

      <ol className="flex flex-col">
        {visibleEvents.map((event, i) => (
          <TimelineRow
            key={i}
            event={event}
            tier={tierOf(event)}
            onSeek={recordingUrl ? seekTo : undefined}
            callStartMs={callStartMs}
          />
        ))}
      </ol>
    </section>
  );
}

/**
 * AGENT and CALLER are the only Tier 1 (conversation) events. Everything
 * else is Tier 2 (telemetry). Voicemail is intentionally Tier 2 per the
 * literal rule — flip its kind here if you want to promote conversational
 * voicemail content into the always-visible transcript flow.
 */
function tierOf(event: CallEvent): 'conversation' | 'telemetry' {
  return event.kind === 'transcript_final' || event.kind === 'agent_reply'
    ? 'conversation'
    : 'telemetry';
}

/**
 * First role="switch" in the codebase. If you add another, mirror this:
 *   - aria-checked written as a string ("true" / "false")
 *   - explicit Space handler with preventDefault to avoid double-fire
 *     on top of the native button's keypress-to-click translation
 *   - focus-visible ring uses outline + outline-brand-muted +
 *     outline-offset-2 to match the dashboard's keyboard-focus pattern
 *
 * No animation on the rows themselves — only the handle slides. The
 * filtered list re-renders synchronously when `enabled` flips.
 */
function TelemetryToggle({
  enabled,
  onToggle,
  hiddenCount,
}: {
  enabled: boolean;
  onToggle: () => void;
  hiddenCount: number;
}) {
  const labelId = useId();
  const showCount = !enabled && hiddenCount > 0;

  return (
    <div className="mt-4 mb-4 flex items-center justify-between">
      <span id={labelId} className="text-sm text-foreground-muted">
        Show technical events
        {showCount ? (
          <span className="text-foreground-subtle"> ({hiddenCount} hidden)</span>
        ) : null}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={enabled ? 'true' : 'false'}
        aria-labelledby={labelId}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === ' ') {
            e.preventDefault();
            onToggle();
          }
        }}
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
          'focus-visible:outline focus-visible:outline-brand-muted focus-visible:outline-offset-2',
          enabled ? 'bg-brand' : 'bg-surface-3',
        )}
      >
        <span
          className={cn(
            'inline-block size-4 rounded-full bg-background shadow-sm transition-transform',
            enabled ? 'translate-x-4.5' : 'translate-x-0.5',
          )}
        />
      </button>
    </div>
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
  tier,
  onSeek,
  callStartMs,
}: {
  event: CallEvent;
  tier: 'conversation' | 'telemetry';
  onSeek?: (seconds: number) => void;
  callStartMs: number;
}) {
  const ts = new Date(event.timestamp);
  const rendered = renderEvent(event);

  const isTranscript = TRANSCRIPT_KINDS.has(event.kind);
  const offsetSec = Math.max(0, (ts.getTime() - callStartMs) / 1000);
  const canSeek = isTranscript && onSeek !== undefined;

  function handleSeek() {
    if (canSeek) onSeek(offsetSec);
  }

  function handleCopy() {
    if (!rendered.copyText) return;
    void navigator.clipboard.writeText(rendered.copyText).then(
      () => toast.success('Turn copied'),
      () => toast.error('Copy failed'),
    );
  }

  return tier === 'conversation' ? (
    <ConversationRow
      ts={ts}
      rendered={rendered}
      canSeek={canSeek}
      offsetSec={offsetSec}
      onSeek={handleSeek}
      onCopy={handleCopy}
    />
  ) : (
    <TelemetryRow ts={ts} rendered={rendered} onCopy={handleCopy} />
  );
}

function ConversationRow({
  ts,
  rendered,
  canSeek,
  offsetSec,
  onSeek,
  onCopy,
}: {
  ts: Date;
  rendered: RenderedEvent;
  canSeek: boolean;
  offsetSec: number;
  onSeek: () => void;
  onCopy: () => void;
}) {
  const { Icon, accent, label, body, copyText } = rendered;

  const rowContent = (
    <>
      <div
        className={cn(
          'mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full',
          ACCENT_BG[accent],
        )}
      >
        <Icon className={cn('size-3.5', ACCENT_FG[accent])} aria-hidden />
      </div>
      <div className="flex flex-1 flex-col gap-1.5">
        <p className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
          <LocalTime date={ts} mode="absolute" /> · {label}
        </p>
        <div className="text-base leading-normal text-foreground">{body}</div>
      </div>
    </>
  );

  return (
    <li className="group flex items-start gap-3 border-b border-border-subtle py-4 last:border-b-0 hover:bg-surface-2/40">
      {canSeek ? (
        <button
          type="button"
          onClick={onSeek}
          aria-label={`Seek to ${label} at ${formatOffset(offsetSec)}`}
          className={cn(
            'flex flex-1 items-start gap-3 bg-transparent p-0 text-left',
            'cursor-pointer focus-visible:outline focus-visible:outline-brand-muted focus-visible:outline-offset-2',
          )}
        >
          {rowContent}
        </button>
      ) : (
        // Non-seekable rows (e.g. calls with no recording) render a plain
        // div so the transcript text stays selectable — a disabled
        // <button> blocks text selection in most browsers (#249 review).
        <div className="flex flex-1 items-start gap-3">{rowContent}</div>
      )}
      {copyText ? (
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-7 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          aria-label={`Copy ${label} text`}
          onClick={onCopy}
        >
          <Copy className="size-3.5" />
        </Button>
      ) : null}
    </li>
  );
}

function TelemetryRow({
  ts,
  rendered,
  onCopy,
}: {
  ts: Date;
  rendered: RenderedEvent;
  onCopy: () => void;
}) {
  const { Icon, accent, label, body, copyText } = rendered;

  return (
    <li className="flex items-center gap-3 border-b border-border-subtle py-2 last:border-b-0 hover:bg-surface-2/40">
      <div
        className={cn(
          'flex size-7 shrink-0 items-center justify-center rounded-full',
          ACCENT_BG[accent],
        )}
      >
        <Icon className="size-3.5 text-foreground-subtle" aria-hidden />
      </div>
      <div className="flex min-w-0 flex-1 items-baseline gap-2 text-sm text-foreground-muted">
        <span className="shrink-0 font-mono text-xs tabular-nums text-foreground-subtle">
          <LocalTime date={ts} mode="absolute" />
        </span>
        <span className="shrink-0 text-xs font-medium uppercase tracking-wide">
          {label}
        </span>
        <span className="truncate">{body}</span>
      </div>
      {copyText ? (
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-7 shrink-0"
          aria-label={`Copy ${label} text`}
          onClick={onCopy}
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
            <span className="font-mono text-xs text-foreground-subtle">
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
