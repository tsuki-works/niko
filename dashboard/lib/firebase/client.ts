import { type FirebaseApp, getApp, getApps, initializeApp } from 'firebase/app';
import { type Auth, getAuth } from 'firebase/auth';
import { type Firestore, getFirestore } from 'firebase/firestore';

const config = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

/**
 * Whether the Firebase web config has the minimum fields needed to run
 * onSnapshot. When false, subscribers should skip the listener entirely
 * — otherwise the SDK tries to connect to `projects//databases/...`
 * and fills the console with errors until the config lands.
 *
 * Meet owns Firebase web-app registration; see #53 PR notes.
 */
export const isFirebaseConfigured = Boolean(
  config.projectId && config.apiKey && config.appId,
);

let app: FirebaseApp | null = null;
let _db: Firestore | null = null;
let _auth: Auth | null = null;

if (isFirebaseConfigured) {
  app = getApps().length ? getApp() : initializeApp(config);
  _db = getFirestore(app);
  _auth = getAuth(app);
} else if (typeof window !== 'undefined') {
  // One-time dev warning. Keeps the console quiet after that.
  console.warn(
    '[firebase/client] NEXT_PUBLIC_FIREBASE_* not set — live updates disabled. ' +
      'Feed still renders from the FastAPI fetch path; refresh to see new orders.',
  );
}

export const db = _db;
export const auth = _auth;
