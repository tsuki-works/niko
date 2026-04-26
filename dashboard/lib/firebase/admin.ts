/**
 * Firebase Admin SDK initialization (server-only).
 *
 * Used by:
 *  - `/api/auth/session` to mint and revoke session cookies after a
 *    successful client-side sign-in
 *  - `lib/auth/server.ts` to verify session cookies on protected
 *    Server Components and Route Handlers
 *
 * Auth resolution:
 *  - In Cloud Run, the service account attached to the dashboard
 *    service auto-auths via the metadata server — no explicit
 *    credential needed.
 *  - Locally, set `FIREBASE_SERVICE_ACCOUNT_KEY` (raw JSON of a
 *    service-account key) or `GOOGLE_APPLICATION_CREDENTIALS`
 *    (path to a JSON file). The SDK picks one up automatically.
 *
 * Lazy init keeps Next.js HMR happy — initializing on every reload
 * would throw `app/duplicate-app`.
 */
import 'server-only';

import {
  type App,
  cert,
  getApp,
  getApps,
  initializeApp,
  applicationDefault,
} from 'firebase-admin/app';
import { type Auth, getAuth } from 'firebase-admin/auth';

let _app: App | null = null;

function _ensureApp(): App {
  if (_app) return _app;
  if (getApps().length) {
    _app = getApp();
    return _app;
  }
  const raw = process.env.FIREBASE_SERVICE_ACCOUNT_KEY;
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      _app = initializeApp({ credential: cert(parsed) });
      return _app;
    } catch (err) {
      throw new Error(
        '[firebase/admin] FIREBASE_SERVICE_ACCOUNT_KEY is set but not valid JSON',
        { cause: err },
      );
    }
  }
  // Falls back to GOOGLE_APPLICATION_CREDENTIALS or the metadata
  // server in Cloud Run. Throws clearly if neither is configured.
  _app = initializeApp({ credential: applicationDefault() });
  return _app;
}

export function adminAuth(): Auth {
  return getAuth(_ensureApp());
}
