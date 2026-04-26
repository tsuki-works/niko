/**
 * Authenticated server-side fetch helper (PR D of #81).
 *
 * Every request from a Server Component or Server Action to the
 * FastAPI backend goes through here. We forward the user's session
 * cookie as a ``Bearer`` token so the backend's ``current_tenant``
 * dependency can verify it via firebase-admin and scope reads to
 * the right restaurant.
 *
 * The session cookie value is itself what the backend's
 * ``verify_session_cookie`` expects — no additional minting needed.
 *
 * Public unauthenticated endpoints (``/``, ``/health``) should not
 * use this helper; just call ``fetch`` directly. Anything that goes
 * through the FastAPI auth dep must use ``apiFetch`` so the
 * Authorization header is set.
 */
import 'server-only';

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
  if (cookie && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${cookie}`);
  }
  const url = path.startsWith('http') ? path : `${apiBase()}${path}`;
  return fetch(url, { ...init, headers, cache: init.cache ?? 'no-store' });
}
