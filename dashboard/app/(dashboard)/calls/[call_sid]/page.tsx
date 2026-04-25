import { notFound } from 'next/navigation';

import { CallTimelineView } from '@/components/calls/call-timeline';
import { ComingSoon } from '@/components/shared/coming-soon';
import { getCallTimeline } from '@/lib/api/calls';

export const dynamic = 'force-dynamic';

export default async function CallDetailPage({
  params,
}: {
  params: Promise<{ call_sid: string }>;
}) {
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

  return <CallTimelineView timeline={result.timeline} />;
}
