import { CircleAlert } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

/**
 * Pill rendered next to a tenant's name when their `twilio_phone` is
 * empty — the explicit "tenant exists, awaiting number" state.
 *
 * The OKLCH theme doesn't ship a "warning" variant, so this composes
 * the `outline` badge with explicit amber tokens. Kept as a one-off
 * here rather than adding a global `warning` variant — there's
 * exactly one surface that needs it today, and a real warning style
 * (used for >1 thing) belongs in `globals.css` as a token.
 */
export function AwaitingNumberPill({ className }: { className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        'border-amber-500/40 bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200',
        className,
      )}
      aria-label="This restaurant is awaiting a Twilio phone number"
    >
      <CircleAlert className="h-3 w-3" aria-hidden />
      Awaiting Twilio number
    </Badge>
  );
}
