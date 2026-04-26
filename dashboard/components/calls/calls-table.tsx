import Link from 'next/link';
import { AlertTriangle, CheckCircle2, PhoneIncoming, Radio } from 'lucide-react';

import { LocalTime } from '@/components/shared/local-time';
import type { CallStatus, CallSummary } from '@/lib/api/calls';
import { formatPhone } from '@/lib/formatters/phone';
import { cn } from '@/lib/utils';

export function CallsTable({
  calls,
  twilioPhone,
}: {
  calls: CallSummary[];
  twilioPhone: string;
}) {
  if (calls.length === 0) return <EmptyState twilioPhone={twilioPhone} />;

  return (
    <div className="overflow-hidden rounded-xl border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted/40 text-muted-foreground">
          <tr>
            <Th className="w-32">Call ID</Th>
            <Th className="w-32">Started</Th>
            <Th className="w-24 text-right">Duration</Th>
            <Th className="w-24 text-right">Turns</Th>
            <Th className="w-32">Status</Th>
          </tr>
        </thead>
        <tbody>
          {calls.map((call) => (
            <CallRow key={call.call_sid} call={call} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CallRow({ call }: { call: CallSummary }) {
  const startedAt = new Date(call.started_at);
  const endedAt = new Date(call.ended_at);
  const durationSec = Math.max(
    0,
    Math.round((endedAt.getTime() - startedAt.getTime()) / 1000),
  );

  return (
    <tr className="border-t transition-colors hover:bg-muted/40">
      <Td className="py-3">
        <Link
          href={`/calls/${encodeURIComponent(call.call_sid)}`}
          className="flex items-center gap-2 font-medium"
        >
          <PhoneIncoming className="h-4 w-4 text-muted-foreground" aria-hidden />
          <span className="font-mono text-xs">
            {call.call_sid.slice(0, 8)}…
          </span>
        </Link>
      </Td>
      <Td>
        <LocalTime date={startedAt} mode="datetime" />
      </Td>
      <Td className="text-right tabular-nums">{formatDuration(durationSec)}</Td>
      <Td className="text-right tabular-nums">{call.transcript_count}</Td>
      <Td>
        <CallStatusBadge status={call.status} hasError={call.has_error} />
      </Td>
    </tr>
  );
}

function CallStatusBadge({
  status,
  hasError,
}: {
  status: CallStatus;
  hasError: boolean;
}) {
  if (hasError) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-destructive/15 px-2 py-1 text-xs font-medium text-destructive">
        <AlertTriangle className="h-3 w-3" aria-hidden /> errored
      </span>
    );
  }
  if (status === 'confirmed') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-400">
        <CheckCircle2 className="h-3 w-3" aria-hidden /> confirmed
      </span>
    );
  }
  if (status === 'in_progress') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-1 text-xs font-medium text-amber-700 dark:text-amber-400">
        <Radio className="h-3 w-3" aria-hidden /> live
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">
      ended
    </span>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s.toString().padStart(2, '0')}s`;
}

function EmptyState({ twilioPhone }: { twilioPhone: string }) {
  const display = formatPhone(twilioPhone);
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border bg-card p-10 text-center">
      <PhoneIncoming className="h-6 w-6 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium">No calls in the selected window</p>
      <p className="text-xs text-muted-foreground">
        {display
          ? `Dial ${display} — the call will appear here once it ends.`
          : 'No Twilio number is assigned to this restaurant yet.'}
      </p>
    </div>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={cn('px-4 py-2 text-xs font-medium uppercase tracking-wide', className)}>
      {children}
    </th>
  );
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn('px-4 py-3 align-middle', className)}>{children}</td>;
}
