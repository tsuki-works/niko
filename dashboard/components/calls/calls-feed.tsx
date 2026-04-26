'use client';

import { useEffect, useRef, useState } from 'react';
import {
  collection,
  limit as fsLimit,
  onSnapshot,
  orderBy,
  query,
} from 'firebase/firestore';

import { CallsTable } from '@/components/calls/calls-table';
import { LiveIndicator } from '@/components/orders/live-indicator';
import { db } from '@/lib/firebase/client';
import { callSessionConverter } from '@/lib/firebase/call-converters';
import type { CallSession } from '@/lib/schemas/call';

type Props = {
  initial: CallSession[];
};

const ANNOUNCE_THROTTLE_MS = 2000;

export function CallsFeed({ initial }: Props) {
  const [calls, setCalls] = useState<CallSession[]>(initial);
  const [announcement, setAnnouncement] = useState('');

  const seenSids = useRef(new Set(initial.map((c) => c.call_sid)));
  const lastAnnouncedAt = useRef(0);

  useEffect(() => {
    if (!db) return;

    const q = query(
      collection(db, 'call_sessions').withConverter(callSessionConverter),
      orderBy('started_at', 'desc'),
      fsLimit(50),
    );

    const unsub = onSnapshot(
      q,
      (snap) => {
        const next = snap.docs.map((d) => d.data());
        setCalls(next);

        const fresh = next.filter((c) => !seenSids.current.has(c.call_sid));
        fresh.forEach((c) => seenSids.current.add(c.call_sid));
        if (fresh.length > 0) {
          const now = Date.now();
          if (now - lastAnnouncedAt.current >= ANNOUNCE_THROTTLE_MS) {
            lastAnnouncedAt.current = now;
            setAnnouncement(`New call ${fresh[0].call_sid.slice(0, 8)}…`);
          }
        }
      },
      (err) => console.error('Calls subscription error', err),
    );
    return unsub;
  }, []);

  return (
    <section className="flex flex-1 flex-col gap-4 p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-lg font-medium">Calls</h1>
          <p className="text-sm text-muted-foreground">
            {calls.length} session{calls.length === 1 ? '' : 's'} · live
          </p>
        </div>
        <LiveIndicator />
      </header>
      <CallsTable calls={calls.map(toRow)} />
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
    </section>
  );
}

function toRow(c: CallSession) {
  return {
    call_sid: c.call_sid,
    started_at: c.started_at.toISOString(),
    ended_at: (c.ended_at ?? c.last_event_at ?? c.started_at).toISOString(),
    transcript_count: c.transcript_count,
    has_error: c.has_error,
    status: c.status,
  };
}
