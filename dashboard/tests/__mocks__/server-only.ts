// Stub for 'server-only'. The real package throws at import time when
// bundled outside an RSC context. We swap it for this no-op in vitest
// via the resolve.alias in vitest.config.mts.
export {};
