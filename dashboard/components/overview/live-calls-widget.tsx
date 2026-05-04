'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  collection,
  limit as fsLimit,
  onSnapshot,
  orderBy,
  query,
  where,
} from 'firebase/firestore';
import { Phone } from 'lucide-react';

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

    const q = query(
      collection(db, 'restaurants', restaurantId, 'call_sessions').withConverter(
        callSessionConverter,
      ),
      where('status', '==', 'in_progress'),
      orderBy('started_at', 'desc'),
      fsLimit(10),
    );

    const unsub = onSnapshot(
      q,
      (snap) => setCalls(snap.docs.map((d) => d.data())),
      (err) => console.error('Live calls subscription error', err),
    );
    return unsub;
  }, [restaurantId]);

  return (
    <article className="flex flex-col gap-4 rounded-lg border border-border p-6">
      <header className="flex items-baseline justify-between gap-2">
        <div>
          <h3 className="text-base font-medium">Live calls</h3>
          <p className="text-xs text-muted-foreground">
            {calls.length === 0
              ? 'No active calls'
              : `${calls.length} on the line`}
          </p>
        </div>
        {calls.length > 0 ? <LiveIndicator /> : null}
      </header>

      {calls.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="flex flex-col divide-y divide-border">
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
        className="flex items-center justify-between gap-3 text-sm hover:text-primary"
      >
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500"
          />
          <span className="font-medium">{callShortId(call)}</span>
        </div>
        <span className="text-xs text-muted-foreground tabular-nums">
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
    <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border py-8 text-center">
      <Phone className="h-5 w-5 text-muted-foreground" />
      <p className="text-sm text-muted-foreground">
        No callers on the line right now.
      </p>
    </div>
  );
}
