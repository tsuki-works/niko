/**
 * Session cookie minting + revocation (PR D of #81).
 *
 * POST  /api/auth/session   { idToken }  → 204, sets `__session` cookie
 * DELETE /api/auth/session              → 204, clears cookie
 *
 * The dashboard's client-side sign-in flow calls POST after a
 * successful `signInWithEmailAndPassword`. We verify the ID token
 * via firebase-admin, then mint a longer-lived session cookie
 * (5 days) so subsequent navigation doesn't need to refresh tokens
 * on every request.
 *
 * Cookie name `__session` matches Firebase Hosting's reserved cookie
 * convention.
 */
import { NextResponse } from 'next/server';

import { adminAuth } from '@/lib/firebase/admin';
import {
  SESSION_COOKIE_NAME,
  SESSION_MAX_AGE_SECONDS,
} from '@/lib/auth/session';

export const runtime = 'nodejs';

export async function POST(req: Request) {
  let idToken: unknown;
  try {
    const body = (await req.json()) as { idToken?: unknown };
    idToken = body.idToken;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  }
  if (typeof idToken !== 'string' || !idToken) {
    return NextResponse.json(
      { error: 'idToken is required' },
      { status: 400 },
    );
  }

  // Verify before minting — if the ID token is invalid we'd rather
  // 401 here than mint a cookie that fails verification on every
  // subsequent request.
  try {
    await adminAuth().verifyIdToken(idToken);
  } catch {
    return NextResponse.json(
      { error: 'Invalid ID token' },
      { status: 401 },
    );
  }

  let sessionCookie: string;
  try {
    sessionCookie = await adminAuth().createSessionCookie(idToken, {
      expiresIn: SESSION_MAX_AGE_SECONDS * 1000,
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: 'Failed to mint session cookie',
        cause: err instanceof Error ? err.message : 'unknown',
      },
      { status: 500 },
    );
  }

  const res = new NextResponse(null, { status: 204 });
  res.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: sessionCookie,
    maxAge: SESSION_MAX_AGE_SECONDS,
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
  });
  return res;
}

export async function DELETE() {
  const res = new NextResponse(null, { status: 204 });
  res.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: '',
    maxAge: 0,
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
  });
  return res;
}
