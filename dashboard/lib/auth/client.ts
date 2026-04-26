/**
 * Client-side auth helpers (PR D of #81).
 *
 * Wraps Firebase Auth's email/password flow plus the round-trip to
 * `/api/auth/session` that exchanges the freshly-minted ID token for
 * an HTTP-only session cookie. Pages and components import these
 * helpers — they should never reach into `firebase/auth` directly,
 * because that bypasses the cookie minting step and middleware will
 * keep bouncing them to /login.
 */
'use client';

import {
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
} from 'firebase/auth';

import { auth } from '@/lib/firebase/client';

export type SignInResult =
  | { success: true }
  | { success: false; error: string };

export async function signIn(
  email: string,
  password: string,
): Promise<SignInResult> {
  if (!auth) {
    return {
      success: false,
      error: 'Firebase Auth is not configured. Check NEXT_PUBLIC_FIREBASE_*.',
    };
  }
  try {
    const cred = await signInWithEmailAndPassword(auth, email, password);
    const idToken = await cred.user.getIdToken();
    const res = await fetch('/api/auth/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ idToken }),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText);
      // Roll back the client-side sign-in so we don't leave the user
      // in a half-authenticated state where the SDK thinks they're
      // signed in but the cookie wasn't minted.
      await firebaseSignOut(auth).catch(() => undefined);
      return { success: false, error: detail || 'Session minting failed' };
    }
    return { success: true };
  } catch (err) {
    const message =
      err instanceof Error ? err.message : 'Unknown sign-in error';
    return { success: false, error: friendlyAuthError(message) };
  }
}

export async function signOut(): Promise<void> {
  // Clear the cookie first so a hung Firebase signOut doesn't leave a
  // stale session active. Server-side route handler is the
  // authoritative invalidation step.
  await fetch('/api/auth/session', { method: 'DELETE' }).catch(() => undefined);
  if (auth) {
    await firebaseSignOut(auth).catch(() => undefined);
  }
}

function friendlyAuthError(raw: string): string {
  // Firebase Auth's default messages include the error code which
  // doesn't read well in the UI. Map the ones a real user is most
  // likely to hit; pass everything else through.
  if (raw.includes('auth/invalid-credential')) {
    return 'Email or password is incorrect.';
  }
  if (raw.includes('auth/user-not-found')) {
    return 'No account exists for that email.';
  }
  if (raw.includes('auth/too-many-requests')) {
    return 'Too many attempts. Try again in a few minutes.';
  }
  if (raw.includes('auth/network-request-failed')) {
    return 'Network error. Check your connection and try again.';
  }
  return raw;
}
