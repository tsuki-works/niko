import { redirect } from 'next/navigation';

import { CallsFeed } from '@/components/calls/calls-feed';
import { ComingSoon } from '@/components/shared/coming-soon';
import { listRecentCalls } from '@/lib/api/calls';
import { parseCallSessionFromJson } from '@/lib/firebase/call-converters';
import { getServerSession } from '@/lib/auth/session';
import type { CallSession } from '@/lib/schemas/call';

export const dynamic = 'force-dynamic';

export default async function CallsPage() {
  const session = await getServerSession();
  if (!session) redirect('/login');

  const result = await listRecentCalls(24);

  if (!result.available) {
    return (
      <ComingSoon
        title="Calls"
        description="Call history, transcripts, and recording playback land in Phase 2."
      />
    );
  }

  const initial: CallSession[] = result.calls.map((c) =>
    parseCallSessionFromJson({
      call_sid: c.call_sid,
      started_at: c.started_at,
      ended_at: c.ended_at,
      status: c.status,
      transcript_count: c.transcript_count,
      has_error: c.has_error,
    }),
  );

  return <CallsFeed initial={initial} restaurantId={session.restaurantId} />;
}
