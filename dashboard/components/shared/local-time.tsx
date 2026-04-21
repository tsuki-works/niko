import { formatDistanceToNowStrict } from 'date-fns';

type Mode = 'relative' | 'absolute' | 'datetime';

type Props = {
  date: Date;
  tz?: string;
  mode?: Mode;
  now?: Date;
  className?: string;
};

const DEFAULT_TZ = 'America/Toronto';

export function LocalTime({
  date,
  tz = DEFAULT_TZ,
  mode = 'relative',
  now,
  className,
}: Props) {
  const text = render(date, mode, tz, now);
  return (
    <span className={className} suppressHydrationWarning>
      {text}
    </span>
  );
}

function render(date: Date, mode: Mode, tz: string, now?: Date): string {
  switch (mode) {
    case 'relative': {
      const diffSec = Math.abs(
        ((now?.getTime() ?? Date.now()) - date.getTime()) / 1000,
      );
      if (diffSec < 45) return 'now';
      return formatDistanceToNowStrict(date, { addSuffix: false });
    }
    case 'absolute':
      return new Intl.DateTimeFormat('en-CA', {
        hour: 'numeric',
        minute: '2-digit',
        timeZone: tz,
      }).format(date);
    case 'datetime':
      return new Intl.DateTimeFormat('en-CA', {
        dateStyle: 'medium',
        timeStyle: 'short',
        timeZone: tz,
      }).format(date);
  }
}
