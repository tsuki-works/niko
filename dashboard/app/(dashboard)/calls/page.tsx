import { ComingSoon } from '@/components/shared/coming-soon';
import { CallsTable } from '@/components/calls/calls-table';
import { listRecentCalls } from '@/lib/api/calls';

export const dynamic = 'force-dynamic';

export default async function CallsPage() {
  const result = await listRecentCalls(24);

  if (!result.available) {
    return (
      <ComingSoon
        title="Calls"
        description="Call history, transcripts, and recording playback land in Phase 2."
      />
    );
  }

  return (
    <section className="flex flex-1 flex-col gap-4 p-6">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-lg font-medium">Calls (dev)</h1>
          <p className="text-sm text-muted-foreground">
            Last 24h · {result.calls.length} session
            {result.calls.length === 1 ? '' : 's'}
          </p>
        </div>
        <p className="text-xs text-muted-foreground">
          Backed by Cloud Logging · gated on{' '}
          <code className="font-mono">NIKO_DEV_ENDPOINTS</code>
        </p>
      </header>
      <CallsTable calls={result.calls} />
    </section>
  );
}
