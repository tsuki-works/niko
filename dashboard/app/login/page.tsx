/**
 * Sign-in page (PR D of #81).
 *
 * Client component because Firebase Auth's email/password flow runs
 * in the browser. After a successful sign-in we POST the freshly-
 * minted ID token to `/api/auth/session`, which sets the HTTP-only
 * session cookie that middleware checks. We then redirect to either
 * the `?next=` query param's path or `/`.
 *
 * No "remember me" checkbox in Phase 2 — the session cookie's 5-day
 * lifetime is the only knob, and it always applies.
 */
'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { signIn } from '@/lib/auth/client';
import { NikoMark } from '@/components/shared/niko-mark';

const SAFE_NEXT = /^\/[^/]/; // single leading slash, no protocol-relative URLs

function safeRedirect(raw: string | null): string {
  if (!raw) return '/';
  if (!SAFE_NEXT.test(raw)) return '/';
  if (raw.startsWith('/login')) return '/';
  return raw;
}

export default function LoginPage() {
  const router = useRouter();
  const search = useSearchParams();
  const next = safeRedirect(search.get('next'));

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    const result = await signIn(email, password);
    if (result.success) {
      router.replace(next);
      router.refresh();
      return;
    }
    setError(result.error);
    setPending(false);
  }

  // Clear stale error if the user starts editing again.
  useEffect(() => {
    if (!error) return;
    const timer = setTimeout(() => setError(null), 30_000);
    return () => clearTimeout(timer);
  }, [error]);

  return (
    <main className="flex min-h-svh items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center gap-3 pb-6">
          <NikoMark size={54} />
          <div className="text-center">
            <h1 className="text-2xl font-medium tracking-tight">
              Sign in to Niko
            </h1>
            <p className="pt-1 text-sm text-muted-foreground">
              Use the email your restaurant was provisioned with.
            </p>
          </div>
        </div>
        <form onSubmit={onSubmit} className="flex flex-col gap-3" noValidate>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Email</span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              disabled={pending}
              aria-invalid={Boolean(error)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Password</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              disabled={pending}
              aria-invalid={Boolean(error)}
            />
          </label>
          {error ? (
            <p
              role="alert"
              className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
            >
              {error}
            </p>
          ) : null}
          <button
            type="submit"
            disabled={pending}
            className="mt-2 inline-flex h-9 items-center justify-center rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground shadow-sm transition-opacity disabled:opacity-50"
          >
            {pending ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="pt-4 text-center text-xs text-muted-foreground">
          Trouble signing in? Contact your Tsuki Works admin.
        </p>
      </div>
    </main>
  );
}
