/**
 * Auth middleware (PR D of #81).
 *
 * Bounces unauthenticated requests to /login. We can't actually
 * verify the cookie's signature here (the Firebase Admin SDK isn't
 * available in the Edge runtime), so middleware does a presence
 * check only — Server Components and Route Handlers re-verify via
 * `getServerSession()` for the actual gate.
 *
 * Skipped paths:
 *  - `/login` itself
 *  - `/api/auth/*` (the session route minted the cookie)
 *  - Next.js asset paths (`/_next/*`, `/favicon.ico`, etc.)
 */
import { NextResponse, type NextRequest } from 'next/server';

import { SESSION_COOKIE_NAME } from '@/lib/auth/session';

const PUBLIC_PREFIXES = ['/login', '/api/auth'];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
    return NextResponse.next();
  }

  const cookie = req.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (cookie) {
    return NextResponse.next();
  }

  // Preserve the requested path so we can redirect back after login.
  const url = req.nextUrl.clone();
  const next = pathname + (req.nextUrl.search || '');
  url.pathname = '/login';
  url.search = `?next=${encodeURIComponent(next)}`;
  return NextResponse.redirect(url);
}

export const config = {
  // Skip Next internals + static files. Everything else runs through
  // the auth check.
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)'],
};
