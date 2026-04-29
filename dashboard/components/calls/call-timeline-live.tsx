'use client';

import { useEffect, useState } from 'react';
import {
  collection,
  onSnapshot,
  orderBy,
  query,
} from 'firebase/firestore';

import { CallTimelineView } from '@/components/calls/call-timeline';
import { db } from '@/lib/firebase/client';
import { callEventConverter } from '@/lib/firebase/call-converters';
import type { CallEvent, CallTimeline } from '@/lib/api/calls';
import type { CallEvent as ZodCallEvent } from '@/lib/schemas/call';

type Props = {
  callSid: string;
  restaurantId: string;
  initial: CallTimeline;
};

export function CallTimelineLive({ callSid, restaurantId, initial }: Props) {
  const [events, setEvents] = useState<CallEvent[]>(initial.events);

  useEffect(() => {
    if (!db) return;

    const q = query(
      collection(
        db,
        'restaurants',
        restaurantId,
        'call_sessions',
        callSid,
        'events',
      ).withConverter(callEventConverter),
      orderBy('timestamp'),
    );

    const unsub = onSnapshot(
      q,
      (snap) => {
        const next = snap.docs.map((d) => toApiEvent(d.data()));
        setEvents(next);
      },
      (err) => console.error('Call timeline subscription error', err),
    );
    return unsub;
  }, [callSid, restaurantId]);

  const recording_available =
    initial.recording_available ||
    events.some((e) => e.kind === 'recording_ready');

  return (
    <CallTimelineView
      timeline={{ call_sid: callSid, events, recording_available }}
    />
  );
}

function toApiEvent(e: ZodCallEvent): CallEvent {
  return {
    timestamp: e.timestamp.toISOString(),
    kind: e.kind,
    text: e.text,
    detail: e.detail,
  };
}
