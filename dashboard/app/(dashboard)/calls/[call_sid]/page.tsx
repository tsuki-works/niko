import { notFound, redirect } from 'next/navigation';

import { CallTimelineLive } from '@/components/calls/call-timeline-live';
import { ComingSoon } from '@/components/shared/coming-soon';
import { getCallTimeline } from '@/lib/api/calls';
import { getServerSession } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export default async function CallDetailPage({
  params,
}: {
  params: Promise<{ call_sid: string }>;
}) {
  const session = await getServerSession();
  if (!session) redirect('/login');

  const { call_sid } = await params;
  const result = await getCallTimeline(call_sid);

  if (!result.available) {
    return (
      <ComingSoon
        title="Calls"
        description="Call history, transcripts, and recording playback land in Phase 2."
      />
    );
  }

  if ('notFound' in result) notFound();

  return (
    <CallTimelineLive
      callSid={call_sid}
      restaurantId={session.restaurantId}
      initial={result.timeline}
    />
  );
}
