import { TriangleAlert } from 'lucide-react';

export function MenuParseError({ reason }: { reason: string }) {
  return (
    <section className="flex flex-1 items-center justify-center p-6">
      <div className="flex max-w-md flex-col items-center gap-2 rounded-md border border-status-cancelled/30 bg-status-cancelled-bg p-6 text-center">
        <TriangleAlert
          className="size-8 text-status-cancelled"
          aria-hidden
        />
        <h2 className="text-md font-medium">Menu unavailable</h2>
        <p className="text-sm text-foreground-muted">{reason}</p>
        <p className="text-xs text-foreground-subtle">
          The agent will keep using whatever menu it last loaded — this is a
          dashboard-side display issue, not a call-flow outage.
        </p>
      </div>
    </section>
  );
}
