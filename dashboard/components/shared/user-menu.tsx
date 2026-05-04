'use client';

import {
  ChevronsUpDown,
  LogOut,
  Monitor,
  Moon,
  Sun,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { signOut } from '@/lib/auth/client';
import { cn } from '@/lib/utils';

type Props = {
  restaurantName: string;
  userEmail: string;
  buildSha?: string;
};

export function UserMenu({ restaurantName, userEmail, buildSha }: Props) {
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    await signOut();
    router.replace('/login');
    router.refresh();
  }

  const initials = computeInitials(restaurantName, userEmail);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          'group/user-menu flex w-full items-center gap-2 rounded-md p-2 text-left text-sm',
          'transition-colors hover:bg-surface-2 hover:text-foreground',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand',
          'data-[state=open]:bg-surface-2 data-[state=open]:text-foreground',
        )}
        aria-label="Account menu"
      >
        <Avatar className="size-8 shrink-0">
          <AvatarFallback className="bg-brand-muted text-foreground text-xs font-medium">
            {initials}
          </AvatarFallback>
        </Avatar>
        <div className="flex min-w-0 flex-1 flex-col leading-tight">
          <span className="truncate font-medium">{restaurantName}</span>
          {userEmail ? (
            <span className="truncate text-xs text-foreground-muted group-hover/user-menu:text-foreground/80 group-data-[state=open]/user-menu:text-foreground/80">
              {userEmail}
            </span>
          ) : null}
        </div>
        <ChevronsUpDown className="size-4 shrink-0 opacity-60" aria-hidden />
      </DropdownMenuTrigger>

      <DropdownMenuContent
        side="top"
        align="end"
        sideOffset={8}
        className="w-(--radix-dropdown-menu-trigger-width) min-w-56"
      >
        <DropdownMenuLabel className="flex flex-col gap-0.5">
          <span className="truncate font-medium">{restaurantName}</span>
          {userEmail ? (
            <span className="truncate text-xs font-normal text-muted-foreground">
              {userEmail}
            </span>
          ) : null}
        </DropdownMenuLabel>

        <DropdownMenuSeparator />

        <ThemeSubMenu />

        <DropdownMenuSeparator />

        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            void handleSignOut();
          }}
          disabled={signingOut}
          className="text-destructive focus:text-destructive"
        >
          <LogOut className="size-4" aria-hidden />
          <span>{signingOut ? 'Signing out…' : 'Sign out'}</span>
        </DropdownMenuItem>

        {buildSha ? (
          <>
            <DropdownMenuSeparator />
            <div className="px-2 py-1 text-[10px] font-mono text-muted-foreground/60">
              build {buildSha.slice(0, 7)}
            </div>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ThemeSubMenu() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // next-themes can't render the active state correctly on the server —
  // gate the radio reflection on mount to avoid a hydration mismatch.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
  }, []);

  const value = mounted ? theme ?? 'system' : 'system';

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        {value === 'dark' ? (
          <Moon className="size-4" aria-hidden />
        ) : value === 'light' ? (
          <Sun className="size-4" aria-hidden />
        ) : (
          <Monitor className="size-4" aria-hidden />
        )}
        <span>Theme</span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuRadioGroup value={value} onValueChange={setTheme}>
          <DropdownMenuRadioItem value="light">
            <Sun className="size-4" aria-hidden />
            <span>Light</span>
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <Moon className="size-4" aria-hidden />
            <span>Dark</span>
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">
            <Monitor className="size-4" aria-hidden />
            <span>System</span>
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

function computeInitials(restaurantName: string, userEmail: string): string {
  const fromName = restaurantName
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 0)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('');
  if (fromName) return fromName;
  return userEmail.charAt(0).toUpperCase() || '?';
}
