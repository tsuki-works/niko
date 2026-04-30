/**
 * Tenant isolation tests for `firestore.rules` (PR E of #79/#81).
 *
 * Boots the Firestore emulator via @firebase/rules-unit-testing,
 * loads the repo-root `firestore.rules`, then drives reads/writes
 * as different authenticated identities to assert the gate behaves
 * the way the rules file claims it does.
 *
 * Identities used:
 *   - "alice@niko" — owner of `niko-pizza-kitchen`
 *   - "bob@palace" — owner of `pizza-palace`
 *   - "tsuki-admin" — role=tsuki_admin (cross-tenant)
 *   - "anon" — unauthenticated
 *
 * Run locally:  npm test  (requires Java for the Firestore emulator).
 * In CI:        .github/workflows/firestore-rules-test.yml.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
  initializeTestEnvironment,
  type RulesTestEnvironment,
  assertSucceeds,
  assertFails,
} from '@firebase/rules-unit-testing';
import {
  doc,
  getDoc,
  setDoc,
  collection,
  getDocs,
  setLogLevel,
} from 'firebase/firestore';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

const PROJECT_ID = 'niko-tsuki-rules-test';
const NIKO = 'niko-pizza-kitchen';
const PALACE = 'pizza-palace';

let env: RulesTestEnvironment;

beforeAll(async () => {
  // Quiet the Firestore client's verbose connection logs.
  setLogLevel('error');

  env = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: {
      rules: readFileSync(
        resolve(__dirname, '..', '..', 'firestore.rules'),
        'utf8',
      ),
      // Emulator port matches firebase.json.
      host: '127.0.0.1',
      port: 8080,
    },
  });
});

afterAll(async () => {
  await env.cleanup();
});

beforeEach(async () => {
  // Wipe Firestore between tests so seeded data from one case
  // doesn't leak into another.
  await env.clearFirestore();
});

/** Seed tenant docs + nested order/call_session via the privileged
 * "withSecurityRulesDisabled" context — bypasses rules for setup. */
async function seedTenants() {
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await setDoc(doc(db, 'restaurants', NIKO), { name: "Niko's", menu: {} });
    await setDoc(doc(db, 'restaurants', PALACE), { name: 'Palace', menu: {} });
    await setDoc(doc(db, 'restaurants', NIKO, 'orders', 'CA1'), {
      call_sid: 'CA1',
      restaurant_id: NIKO,
    });
    await setDoc(doc(db, 'restaurants', PALACE, 'orders', 'CA2'), {
      call_sid: 'CA2',
      restaurant_id: PALACE,
    });
    await setDoc(doc(db, 'restaurants', NIKO, 'call_sessions', 'CA1'), {
      call_sid: 'CA1',
      restaurant_id: NIKO,
    });
    await setDoc(
      doc(db, 'restaurants', NIKO, 'call_sessions', 'CA1', 'events', 'e1'),
      { kind: 'start' },
    );
    // Legacy flat docs (PR C dual-write target). Should be unreadable
    // by any client identity post-PR-E.
    await setDoc(doc(db, 'orders', 'CA1'), { call_sid: 'CA1', restaurant_id: NIKO });
    await setDoc(doc(db, 'call_sessions', 'CA1'), {
      call_sid: 'CA1',
      restaurant_id: NIKO,
    });
  });
}

function nikoOwnerCtx() {
  return env.authenticatedContext('alice', {
    restaurant_id: NIKO,
    role: 'owner',
    email: 'alice@niko.com',
  });
}

function palaceOwnerCtx() {
  return env.authenticatedContext('bob', {
    restaurant_id: PALACE,
    role: 'owner',
    email: 'bob@palace.com',
  });
}

function tsukiAdminCtx() {
  return env.authenticatedContext('admin', {
    restaurant_id: '*',
    role: 'tsuki_admin',
    email: 'admin@tsuki.works',
  });
}

function anonCtx() {
  return env.unauthenticatedContext();
}

describe('nested per-tenant reads', () => {
  beforeEach(seedTenants);

  it('owner reads their own restaurant doc', async () => {
    const db = nikoOwnerCtx().firestore();
    await assertSucceeds(getDoc(doc(db, 'restaurants', NIKO)));
  });

  it('owner cannot read another tenant restaurant doc', async () => {
    const db = nikoOwnerCtx().firestore();
    await assertFails(getDoc(doc(db, 'restaurants', PALACE)));
  });

  it('owner reads their own orders subcollection', async () => {
    const db = nikoOwnerCtx().firestore();
    await assertSucceeds(getDocs(collection(db, 'restaurants', NIKO, 'orders')));
  });

  it('owner cannot read another tenant orders', async () => {
    const db = nikoOwnerCtx().firestore();
    await assertFails(
      getDocs(collection(db, 'restaurants', PALACE, 'orders')),
    );
  });

  it('owner reads their own call_session events', async () => {
    const db = nikoOwnerCtx().firestore();
    await assertSucceeds(
      getDocs(
        collection(
          db,
          'restaurants',
          NIKO,
          'call_sessions',
          'CA1',
          'events',
        ),
      ),
    );
  });
});

describe('admin cross-tenant reads', () => {
  beforeEach(seedTenants);

  it('tsuki_admin reads across tenants', async () => {
    const db = tsukiAdminCtx().firestore();
    await assertSucceeds(getDoc(doc(db, 'restaurants', NIKO)));
    await assertSucceeds(getDoc(doc(db, 'restaurants', PALACE)));
  });

  it('tsuki_admin reads any tenant orders', async () => {
    const db = tsukiAdminCtx().firestore();
    await assertSucceeds(
      getDocs(collection(db, 'restaurants', NIKO, 'orders')),
    );
    await assertSucceeds(
      getDocs(collection(db, 'restaurants', PALACE, 'orders')),
    );
  });
});

describe('unauthenticated access', () => {
  beforeEach(seedTenants);

  it('anonymous cannot read restaurant docs', async () => {
    const db = anonCtx().firestore();
    await assertFails(getDoc(doc(db, 'restaurants', NIKO)));
  });

  it('anonymous cannot read orders', async () => {
    const db = anonCtx().firestore();
    await assertFails(
      getDocs(collection(db, 'restaurants', NIKO, 'orders')),
    );
  });
});

describe('writes are always denied to clients', () => {
  beforeEach(seedTenants);

  it('owner cannot write to their own orders subcollection', async () => {
    const db = nikoOwnerCtx().firestore();
    await assertFails(
      setDoc(doc(db, 'restaurants', NIKO, 'orders', 'CAnew'), {
        call_sid: 'CAnew',
        restaurant_id: NIKO,
      }),
    );
  });

  it('admin cannot write either (admin only reads cross-tenant)', async () => {
    const db = tsukiAdminCtx().firestore();
    await assertFails(
      setDoc(doc(db, 'restaurants', NIKO, 'orders', 'CAnew'), {
        call_sid: 'CAnew',
        restaurant_id: NIKO,
      }),
    );
  });

  it('owner cannot mutate the restaurant config doc', async () => {
    const db = nikoOwnerCtx().firestore();
    await assertFails(
      setDoc(doc(db, 'restaurants', NIKO), { name: 'hacked', menu: {} }),
    );
  });
});

describe('legacy flat collections are locked down', () => {
  beforeEach(seedTenants);

  it('owner cannot read legacy flat orders', async () => {
    const db = nikoOwnerCtx().firestore();
    await assertFails(getDoc(doc(db, 'orders', 'CA1')));
  });

  it('admin cannot read legacy flat orders', async () => {
    const db = tsukiAdminCtx().firestore();
    await assertFails(getDoc(doc(db, 'orders', 'CA1')));
  });

  it('owner cannot read legacy flat call_sessions', async () => {
    const db = nikoOwnerCtx().firestore();
    await assertFails(getDoc(doc(db, 'call_sessions', 'CA1')));
  });
});

describe('default deny on undeclared paths', () => {
  it('reads against an unknown collection are rejected', async () => {
    const db = nikoOwnerCtx().firestore();
    await assertFails(getDoc(doc(db, 'unknown_collection', 'x')));
  });
});
