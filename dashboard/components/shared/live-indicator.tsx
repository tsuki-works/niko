import { cn } from '@/lib/utils';

type Props = {
  className?: string;
};

// Phase 1 ships green-only ("Live"). Disconnected/reconnecting states
// are noted in design-system.md but not wired until Phase 2.
export function LiveIndicator({ className }: Props) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-[7px] text-sm text-foreground-muted',
        className,
      )}
    >
      <span
        aria-hidden
        className="block size-[7px] rounded-full animate-pulse-dot"
        style={{ backgroundColor: 'var(--status-ready)' }}
      />
      Live
    </span>
  );
}
