import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Mic,
  PhoneCall,
  PhoneOff,
  Sparkles,
  Volume2,
  Zap,
} from 'lucide-react';
import Link from 'next/link';

import { TimelineExport } from '@/components/calls/timeline-export';
import { LocalTime } from '@/components/shared/local-time';
import type { CallEvent, CallTimeline } from '@/lib/api/calls';
import { cn } from '@/lib/utils';

export function CallTimelineView({ timeline }: { timeline: CallTimeline }) {
  return (
    <section className="flex flex-1 flex-col gap-4 p-6">
      <header className="flex items-center gap-3">
        <Link
          href="/calls"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          All calls
        </Link>
      </header>

      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h1 className="text-lg font-medium">Call timeline</h1>
          <p className="font-mono text-xs text-muted-foreground">
            {timeline.call_sid}
          </p>
        </div>
        <TimelineExport timeline={timeline} />
      </div>

      <ol className="flex flex-col gap-2 rounded-xl border bg-card p-4">
        {timeline.events.map((event, i) => (
          <TimelineRow key={i} event={event} />
        ))}
      </ol>
    </section>
  );
}

function TimelineRow({ event }: { event: CallEvent }) {
  const ts = new Date(event.timestamp);
  const { Icon, accent, label, body } = renderEvent(event);

  return (
    <li className="flex items-start gap-3 rounded-lg px-2 py-1.5 hover:bg-muted/40">
      <div
        className={cn(
          'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full',
          accent,
        )}
      >
        <Icon className="h-3.5 w-3.5" aria-hidden />
      </div>
      <div className="flex min-w-[5rem] shrink-0 flex-col text-xs text-muted-foreground tabular-nums">
        <LocalTime date={ts} mode="absolute" />
      </div>
      <div className="flex flex-1 flex-col gap-0.5">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className="text-sm">{body}</p>
      </div>
    </li>
  );
}

type RenderedEvent = {
  Icon: typeof Mic;
  accent: string;
  label: string;
  body: React.ReactNode;
};

function renderEvent(event: CallEvent): RenderedEvent {
  switch (event.kind) {
    case 'start':
      return {
        Icon: PhoneCall,
        accent: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
        label: 'call started',
        body: 'Twilio media stream opened',
      };
    case 'stop':
      return {
        Icon: PhoneOff,
        accent: 'bg-muted text-muted-foreground',
        label: 'call ended',
        body: 'Caller hung up',
      };
    case 'order_confirmed':
      return {
        Icon: CheckCircle2,
        accent: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
        label: 'order confirmed',
        body: 'Order persisted to Firestore',
      };
    case 'transcript_final': {
      const text = (event.detail.text as string) || '(empty)';
      return {
        Icon: Mic,
        accent: 'bg-foreground/10 text-foreground',
        label: 'caller',
        body: <span className="italic">“{text}”</span>,
      };
    }
    case 'transcript_interim': {
      const text = (event.detail.text as string) || '';
      return {
        Icon: Mic,
        accent: 'bg-muted text-muted-foreground',
        label: 'interim transcript',
        body: <span className="text-muted-foreground italic">“{text}”</span>,
      };
    }
    case 'llm_turn_start': {
      const transcript = (event.detail.transcript as string) ?? '';
      return {
        Icon: Sparkles,
        accent: 'bg-violet-500/15 text-violet-600 dark:text-violet-400',
        label: 'LLM turn start',
        body: transcript ? `→ "${transcript}"` : 'turn opened',
      };
    }
    case 'agent_reply': {
      const reply = (event.detail.text as string) || event.text || '';
      return {
        Icon: Sparkles,
        accent: 'bg-violet-500/15 text-violet-600 dark:text-violet-400',
        label: 'agent',
        body: <span className="italic">“{reply}”</span>,
      };
    }
    case 'first_audio': {
      const latency = event.detail.latency_seconds as number | undefined;
      const overBudget = typeof latency === 'number' && latency >= 1;
      return {
        Icon: Volume2,
        accent: overBudget
          ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
          : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
        label: 'first audio',
        body:
          typeof latency === 'number'
            ? `${(latency * 1000).toFixed(0)}ms${overBudget ? ' (over <1s budget)' : ''}`
            : 'first audio bytes sent',
      };
    }
    case 'barge_in':
      return {
        Icon: Zap,
        accent: 'bg-orange-500/15 text-orange-700 dark:text-orange-400',
        label: 'barge-in',
        body: 'caller spoke over the AI; in-flight reply cancelled',
      };
    case 'silence_timeout':
      return {
        Icon: AlertTriangle,
        accent: 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
        label: 'silence timeout',
        body: 'no caller activity for 10s — bot prompted',
      };
    case 'error':
      return {
        Icon: AlertTriangle,
        accent: 'bg-destructive/15 text-destructive',
        label: 'error',
        body: <pre className="whitespace-pre-wrap font-mono text-xs">{event.text}</pre>,
      };
    default:
      return {
        Icon: Sparkles,
        accent: 'bg-muted text-muted-foreground',
        label: 'log',
        body: <span className="font-mono text-xs">{event.text}</span>,
      };
  }
}
