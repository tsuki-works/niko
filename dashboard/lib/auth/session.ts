/**
 * Server-side session helpers (PR D of #81).
 *
 * The dashboard's source of truth for "who's logged in" is the
 * `__session` HTTP-only cookie that `/api/auth/session` mints from a
 * client-side Firebase ID token. Server Components and Route Handlers
 * call `getServerSession()` to read it; the cookie is verified via
 * `firebase-admin` on every server-side render so a forged cookie
 * can't bypass auth.
 *
 * The cookie name `__session` matches Firebase Hosting's reserved
 * cookie convention so we stay compatible if we ever migrate the
 * dashboard there.
 */
import 'server-only';

import { cookies } from 'next/headers';

import { adminAuth } from '@/lib/firebase/admin';
import {
  SESSION_COOKIE_NAME,
  SESSION_MAX_AGE_SECONDS,
} from '@/lib/auth/constants';

// Re-exports for backwards compatibility with existing imports —
// middleware.ts must import from `@/lib/auth/constants` directly to
// stay Edge-runtime safe.
export { SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS };

export type Session = {
  uid: string;
  email: string | null;
  restaurantId: string;
  role: string;
};

/**
 * Read and verify the session cookie. Returns null when there's no
 * cookie, the cookie is invalid, or the user isn't provisioned with
 * a `restaurant_id` claim yet.
 */
export async function getServerSession(): Promise<Session | null> {
  const store = await cookies();
  const cookie = store.get(SESSION_COOKIE_NAME)?.value;
  if (!cookie) return null;

  try {
    const decoded = await adminAuth().verifySessionCookie(cookie, false);
    const restaurantId = (decoded as Record<string, unknown>).restaurant_id;
    if (typeof restaurantId !== 'string' || !restaurantId) {
      // Authenticated but not provisioned. Treat as unauthenticated
      // for routing purposes — middleware will bounce to /login.
      return null;
    }
    return {
      uid: decoded.uid,
      email: decoded.email ?? null,
      restaurantId,
      role:
        (typeof (decoded as Record<string, unknown>).role === 'string'
          ? ((decoded as Record<string, unknown>).role as string)
          : 'owner'),
    };
  } catch {
    return null;
  }
}

/**
 * Read the raw session cookie without verifying it. Used by the
 * server-side fetch helpers when forwarding auth to FastAPI — the
 * backend re-verifies via its own firebase-admin instance, so a
 * second client-side decode here would be wasted work.
 */
export async function getSessionCookieValue(): Promise<string | null> {
  const store = await cookies();
  return store.get(SESSION_COOKIE_NAME)?.value ?? null;
}
