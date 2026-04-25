'use client';

import { Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // next-themes requires gating the icon swap on mount to avoid a
  // hydration mismatch — the server has no way to know the user's
  // resolved theme. This idiom (setState in an empty-deps effect) is
  // exactly what React's `react-hooks/set-state-in-effect` warns
  // against; suppress because the alternative is a visible flash.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
  }, []);

  const isDark = mounted && resolvedTheme === 'dark';

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      className={cn(
        'relative transition-colors',
        // Warm hover/focus state — amber tint matches the brand's warm family.
        'hover:bg-warning/20 hover:text-warning',
        'focus-visible:bg-warning/20 focus-visible:text-warning',
      )}
    >
      {/* Sun = amber-ish to feel sunlit; Moon = cream for brand consistency.
          Icons swap based on the active theme, not the target one — so the
          toggle shows what mode you're *in*, not what you're switching to. */}
      {isDark ? (
        <Moon className="h-5 w-5 text-primary" />
      ) : (
        <Sun className="h-5 w-5 text-warning" />
      )}
    </Button>
  );
}
