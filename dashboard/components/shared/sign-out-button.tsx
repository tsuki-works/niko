'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { LogOut } from 'lucide-react';

import { signOut } from '@/lib/auth/client';

/**
 * Small client-side button that clears the session and bounces to
 * /login. Imported by the layout header — keeps the layout itself
 * a Server Component so it can read the verified session cookie
 * server-side.
 */
export function SignOutButton() {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function handleClick() {
    setPending(true);
    await signOut();
    router.replace('/login');
    router.refresh();
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={pending}
      aria-label="Sign out"
      className="inline-flex h-8 items-center gap-1.5 rounded-md border bg-background px-2.5 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
    >
      <LogOut className="h-3.5 w-3.5" />
      <span>{pending ? 'Signing out…' : 'Sign out'}</span>
    </button>
  );
}
