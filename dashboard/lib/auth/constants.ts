/**
 * Auth-related constants that need to be readable from the Edge
 * runtime (middleware) AND the Node runtime (route handlers,
 * Server Components).
 *
 * Anything Node-specific — `firebase-admin`, `next/headers`,
 * `cookies()` — has to live in `lib/auth/session.ts`. Importing
 * that file from the middleware pulls those Node-only modules into
 * the Edge bundle and crashes at request time with:
 *
 *     Error: The edge runtime does not support Node.js 'process' module.
 *
 * Keep this file tiny and dependency-free.
 */

export const SESSION_COOKIE_NAME = '__session';

// Five days. Long enough that a casual user doesn't get logged out
// during a shift, short enough that a stolen cookie has limited
// utility. Refreshed on every successful sign-in.
export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 5;
