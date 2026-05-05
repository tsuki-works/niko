'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { PhoneIncoming } from 'lucide-react';

import { LocalTime } from '@/components/shared/local-time';
import { StatusBadge } from '@/components/orders/status-badge';
import type { CallStatus, CallSummary } from '@/lib/api/calls';
import type { OrderStatus } from '@/lib/schemas/order';
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
    <div className="overflow-hidden">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border-subtle text-foreground-muted">
            <Th className="w-40">Call ID</Th>
            <Th className="w-40">Started</Th>
            <Th className="w-24 text-right">Duration</Th>
            <Th className="w-24 text-right">Turns</Th>
            <Th className="w-24">Status</Th>
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
  const router = useRouter();

  const startedAt = new Date(call.started_at);
  const endedAt = new Date(call.ended_at);
  const durationSec = Math.max(
    0,
    Math.round((endedAt.getTime() - startedAt.getTime()) / 1000),
  );

  const detailHref = `/calls/${encodeURIComponent(call.call_sid)}`;
  const status = mappedStatus(call);
  const shortSid = call.call_sid.slice(0, 8);

  return (
    <tr
      onClick={() => {
        // Don't navigate when the user is selecting text — call SIDs
        // are exactly the kind of thing operators copy out of the table.
        if (window.getSelection()?.toString()) return;
        router.push(detailHref);
      }}
      className="cursor-pointer border-b border-border-subtle transition-colors hover:bg-surface-2/40"
    >
      {/* Cell 1 — the only <Link> in the row. The cell-1 link is the
          single keyboard target per row; cells 2-5 are plain content
          and the <tr> onClick handles mouse navigation. */}
      <Td>
        <Link
          href={detailHref}
          aria-label={`View call ${shortSid}`}
          className="inline-flex items-center gap-2"
        >
          <PhoneIncoming
            className="size-3.5 text-foreground-muted"
            aria-hidden
          />
          <span className="font-mono text-xs">{shortSid}…</span>
        </Link>
      </Td>
      <Td className="text-foreground-muted">
        <LocalTime date={startedAt} mode="datetime" />
      </Td>
      <Td className="text-right font-mono tabular-nums">
        {formatDuration(durationSec)}
      </Td>
      <Td className="text-right font-mono tabular-nums">
        {call.transcript_count}
      </Td>
      <Td>
        <StatusBadge status={status} />
      </Td>
    </tr>
  );
}

/**
 * Map a CallSummary to the closest OrderStatus so we can render with the
 * shared <StatusBadge>. Calls aren't orders, but the badge vocabulary
 * fits: live = caller still on the line, confirmed = order placed,
 * completed = call ended cleanly without an order, cancelled = error.
 */
function mappedStatus(call: CallSummary): OrderStatus {
  if (call.has_error) return 'cancelled';
  switch (call.status as CallStatus) {
    case 'in_progress':
      return 'in_progress';
    case 'confirmed':
      return 'confirmed';
    case 'ended':
      return 'completed';
  }
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
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
      <PhoneIncoming
        className="size-8 text-foreground-faint"
        aria-hidden
      />
      <p className="text-md font-medium">No calls yet</p>
      <p className="max-w-sm text-sm text-foreground-muted">
        {display
          ? `Dial ${display} — the call will appear here once it ends.`
          : 'No Twilio number is assigned to this restaurant yet.'}
      </p>
    </div>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      className={cn(
        'px-2.5 py-2.5 text-xs font-medium uppercase tracking-wide',
        className,
      )}
    >
      {children}
    </th>
  );
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn('px-2.5 py-2.5 align-middle', className)}>{children}</td>;
}
