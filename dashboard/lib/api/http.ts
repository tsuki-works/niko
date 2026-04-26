/**
 * Authenticated server-side fetch helper (PR D of #81).
 *
 * Every request from a Server Component or Server Action to the
 * FastAPI backend goes through here. We forward the user's session
 * cookie via the ``Cookie`` header (as ``__session=<value>``) so the
 * backend's ``current_tenant`` dependency can read it as a cookie
 * and verify via ``verify_session_cookie`` — session cookies have a
 * different issuer than ID tokens (``session.firebase.google.com``
 * vs ``securetoken.google.com``), so forwarding via Bearer would
 * tank ``verify_id_token`` with an "iss" claim mismatch.
 *
 * Public unauthenticated endpoints (``/``, ``/health``) should not
 * use this helper; just call ``fetch`` directly. Anything that goes
 * through the FastAPI auth dep must use ``apiFetch`` so the
 * cookie header is set.
 */
import 'server-only';

import { SESSION_COOKIE_NAME } from '@/lib/auth/constants';
import { getSessionCookieValue } from '@/lib/auth/session';

export function apiBase(): string {
  const base = process.env.NIKO_API_BASE_URL;
  if (!base) throw new Error('NIKO_API_BASE_URL is not set');
  return base.replace(/\/$/, '');
}

export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const cookie = await getSessionCookieValue();
  const headers = new Headers(init.headers);
  if (cookie && !headers.has('Cookie')) {
    headers.set('Cookie', `${SESSION_COOKIE_NAME}=${cookie}`);
  }
  const url = path.startsWith('http') ? path : `${apiBase()}${path}`;
  return fetch(url, { ...init, headers, cache: init.cache ?? 'no-store' });
}
