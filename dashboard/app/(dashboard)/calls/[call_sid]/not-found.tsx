import Link from 'next/link';
import { PhoneOff } from 'lucide-react';

export default function CallNotFound() {
  return (
    <section className="flex flex-1 items-center justify-center p-6">
      <div className="flex max-w-md flex-col items-center gap-3 rounded-xl border bg-card p-10 text-center">
        <PhoneOff className="h-8 w-8 text-muted-foreground" aria-hidden />
        <h2 className="text-lg font-medium">Call not found</h2>
        <p className="text-sm text-muted-foreground">
          No log events for this call_sid in the last 7 days. Older calls have
          rolled off Cloud Logging.
        </p>
        <Link
          href="/calls"
          className="text-sm font-medium text-primary hover:underline"
        >
          ← Back to all calls
        </Link>
      </div>
    </section>
  );
}
