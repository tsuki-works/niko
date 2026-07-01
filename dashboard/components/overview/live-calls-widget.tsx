'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  collection,
  limit as fsLimit,
  onSnapshot,
  orderBy,
  query,
} from 'firebase/firestore';
import { PhoneIncoming } from 'lucide-react';

import { LiveIndicator } from '@/components/shared/live-indicator';
import { db } from '@/lib/firebase/client';
import { callSessionConverter } from '@/lib/firebase/call-converters';
import { type CallSession, callShortId } from '@/lib/schemas/call';

type Props = {
  initial: CallSession[];
  restaurantId: string;
};

export function LiveCallsWidget({ initial, restaurantId }: Props) {
  const [calls, setCalls] = useState<CallSession[]>(initial);

  useEffect(() => {
    if (!db) return;

    // Subscribe to the recent window and filter `in_progress` on the
    // client. A `where('status', '==', 'in_progress')` + `orderBy
    // ('started_at', 'desc')` query needs a composite index that we
    // haven't provisioned for `call_sessions` yet, and the index error
    // crashes the Firestore SDK's internal state for the whole tab.
    // Mirrors the same client-side filter pattern used in
    // active-orders-widget.tsx.
    const q = query(
      collection(db, 'restaurants', restaurantId, 'call_sessions').withConverter(
        callSessionConverter,
      ),
      orderBy('started_at', 'desc'),
      fsLimit(50),
    );

    const unsub = onSnapshot(
      q,
      (snap) => {
        const recent = snap.docs.map((d) => d.data());
        setCalls(
          recent.filter((c) => c.status === 'in_progress').slice(0, 10),
        );
      },
      (err) => console.error('Live calls subscription error', err),
    );
    return unsub;
  }, [restaurantId]);

  return (
    <article className="flex flex-col gap-4 rounded-md border border-border-subtle bg-surface-1 p-4">
      <header className="flex items-center justify-between gap-2">
        <h3 className="text-md font-medium">Live calls</h3>
        {calls.length > 0 ? <LiveIndicator /> : null}
      </header>

      {calls.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="flex flex-col divide-y divide-border-subtle">
          {calls.map((c) => (
            <CallRow key={c.call_sid} call={c} />
          ))}
        </ul>
      )}
    </article>
  );
}

function CallRow({ call }: { call: CallSession }) {
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <Link
        href={`/calls/${encodeURIComponent(call.call_sid)}`}
        className="flex items-center justify-between gap-3 text-sm hover:text-foreground"
      >
        <span className="font-mono font-medium">{callShortId(call)}</span>
        <span className="text-xs text-foreground-muted tabular-nums">
          <CallDuration startedAt={call.started_at} />
          {' · '}
          {call.transcript_count} turn{call.transcript_count === 1 ? '' : 's'}
        </span>
      </Link>
    </li>
  );
}

function CallDuration({ startedAt }: { startedAt: Date }) {
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const seconds = Math.max(0, Math.floor((now - startedAt.getTime()) / 1000));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return (
    <span suppressHydrationWarning>
      {m}:{s.toString().padStart(2, '0')}
    </span>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      <div className="flex size-14 items-center justify-center rounded-[10px] bg-surface-2">
        <PhoneIncoming
          className="size-6 text-foreground-muted"
          aria-hidden
        />
      </div>
      <p className="mt-3 text-base text-foreground">No active calls</p>
      <p className="mt-1.5 text-sm text-foreground-subtle">
        Niko will surface live calls here as they come in.
      </p>
    </div>
  );
}
