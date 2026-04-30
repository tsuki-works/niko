import { TriangleAlert } from 'lucide-react';

export function MenuParseError({ reason }: { reason: string }) {
  return (
    <section className="flex flex-1 items-center justify-center p-6">
      <div className="flex max-w-md flex-col items-center gap-3 rounded-xl border border-destructive/40 bg-card p-10 text-center">
        <TriangleAlert className="h-8 w-8 text-destructive" aria-hidden />
        <h2 className="text-lg font-medium">Menu unavailable</h2>
        <p className="text-sm text-muted-foreground">{reason}</p>
        <p className="text-xs text-muted-foreground">
          The agent will keep using whatever menu it last loaded — this is a
          dashboard-side display issue, not a call-flow outage.
        </p>
      </div>
    </section>
  );
}
