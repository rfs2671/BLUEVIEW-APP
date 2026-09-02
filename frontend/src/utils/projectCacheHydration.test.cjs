/**
 * THE COLD BOOT, WITH NO NETWORK, ON THE GATE TABLET.
 *
 * This executes the REAL hydration routine out of ProjectCacheContext.jsx
 * rather than describing it, and pins the ordering question the ruling turns
 * on: when the parent layout mounts with no network, what is on screen, and
 * for how long.
 *
 * The sequence on origin/main was:
 *   AuthProvider mounts, isLoading=true, renders children immediately
 *   -> the screen mounts with loading=true and paints its spinner
 *   -> the screen's fetch is gated on isAuthenticated, so it does NOT run
 *   -> validateSession() reads the token + stored user from AsyncStorage (ms)
 *   -> then awaits authAPI.getMe(), which offline rejects — up to the 25s
 *      DEFAULT_TIMEOUT_MS when the socket connects but never answers
 *   -> only THEN does isAuthenticated flip and the screen read its cache
 *
 * No error is flashed — the redirect to /login is guarded on !authLoading —
 * but the cached list sat readable in AsyncStorage the whole time, behind a
 * network call, on a device with no network. That is what moving hydration to
 * the layout fixes: the read is keyed on the STORED session, which is present
 * in milliseconds, not on the VALIDATED one.
 *
 * hydrateProjectCache() is therefore required to settle without ever awaiting
 * anything network-shaped. The test proves it by giving it a session whose
 * validation never resolves at all.
 *
 * Run:  node src/utils/projectCacheHydration.test.cjs
 */
const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', 'context', 'ProjectCacheContext.jsx');
if (!fs.existsSync(file)) {
  console.log('  FAIL  src/context/ProjectCacheContext.jsx exists');
  console.log('\n0 passed, 1 failed');
  process.exit(1);
}
const src = fs.readFileSync(file, 'utf8');

// Extract the real `export async function hydrateProjectCache(...) { … }`.
const anchor = 'export async function hydrateProjectCache';
const at = src.indexOf(anchor);
if (at < 0) {
  console.log('  FAIL  hydrateProjectCache is exported from ProjectCacheContext.jsx');
  console.log('\n0 passed, 1 failed');
  process.exit(1);
}
const braceStart = src.indexOf('{', src.indexOf(')', at));
let depth = 0, i = braceStart;
for (; i < src.length; i += 1) {
  if (src[i] === '{') depth += 1;
  else if (src[i] === '}') { depth -= 1; if (depth === 0) { i += 1; break; } }
}
const body = src.slice(braceStart, i);

const PARAMS = ['readCachedProjectList', 'getToken', 'getStoredUser'];
// eslint-disable-next-line no-new-func
const make = new Function(...PARAMS, `return (async (deps) => ${body});`);

let passed = 0, failed = 0;
const ok = (c, l) => { if (c) { passed += 1; console.log('  PASS  ' + l); } else { failed += 1; console.log('  FAIL  ' + l); } };

// GUARD: the harness must inject every free variable the real body uses.
// reportSettingsFetch.test.cjs learned this the hard way — the screen gained a
// dependency, the injected list went stale, and the file died with a
// ReferenceError before a single assertion ran, which reads as "failing" but
// was "not running at all", and CI's `set -e` took the rest of the frontend
// job down with it. This catches that drift as a NAMED failure instead.
const scanBody = body.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
const freeNames = [...new Set(
  [...scanBody.matchAll(/(^|[^.\w$])([A-Za-z_$][A-Za-z0-9_$]*)\s*\(/g)].map((m) => m[2]),
)].filter((n) => !PARAMS.includes(n)
  && !['if', 'for', 'while', 'switch', 'catch', 'return', 'await', 'async',
    'function', 'typeof', 'Array', 'Object', 'String', 'Number', 'Boolean',
    'JSON', 'Promise', 'Error', 'console'].includes(n));
ok(freeNames.length === 0,
  `harness injects every dependency hydrateProjectCache calls${freeNames.length ? ` — MISSING ${JSON.stringify(freeNames)}` : ''}`);

const CACHED =[{ id: 'p1', name: 'One Vanderbilt' }, { id: 'p2', name: '270 Park' }];

function run({ cached = CACHED, token = 'a.b.c', storedUser = { id: 'u1', role: 'cp' } } = {}) {
  const hydrate = make(
    async () => cached,
    async () => token,
    async () => storedUser,
  );
  return hydrate();
}

(async () => {
  // ── The gate tablet, cold, in a dead zone ─────────────────────────────────
  {
    const r = await run();
    ok(Array.isArray(r.projects) && r.projects.length === 2,
      'COLD BOOT OFFLINE: the cached project list is hydrated');
    ok(r.hydrated === true, 'and the result says hydration completed');
    ok(r.source === 'cache',
      "PROVENANCE: the result is stamped source='cache' — never mistakable for live");
  }

  // ── It must not wait on the network ───────────────────────────────────────
  // A promise that never settles stands in for authAPI.getMe() in a dead zone.
  // If hydration awaited anything of that shape this would hang and the runner
  // would time out rather than assert.
  {
    const never = new Promise(() => {});
    const settled = await Promise.race([
      run(),
      never,
      new Promise((res) => setTimeout(() => res('TIMED_OUT'), 500)),
    ]);
    ok(settled !== 'TIMED_OUT',
      'hydration settles without awaiting a network round trip (no 25s spinner)');
  }

  // ── No stored session: hydrate NOTHING ────────────────────────────────────
  // bv_projects_cache is a single global key and clearAuth() does not remove
  // it, so the last user's list outlives their logout. Exposing it on a device
  // with no session would show one man's jobs to whoever picks the tablet up.
  {
    const r = await run({ token: null, storedUser: null });
    ok(Array.isArray(r.projects) && r.projects.length === 0,
      'NO SESSION: nothing is hydrated — the previous user\'s list is not exposed');
    ok(r.source === null, 'and no provenance is claimed for data that was not read');
  }
  {
    const r = await run({ token: 'a.b.c', storedUser: null });
    ok(r.projects.length === 0, 'a token with no stored user is not a session either');
  }

  // ── An unreadable cache is empty, never a throw ───────────────────────────
  // Hydration runs on the layout now. If it could throw, it would take the
  // ErrorBoundary — and the whole app — down on first paint.
  {
    const hydrate = make(
      async () => { throw new Error('AsyncStorage exploded'); },
      async () => 'a.b.c',
      async () => ({ id: 'u1' }),
    );
    let threw = false;
    let r = null;
    try { r = await hydrate(); } catch (_e) { threw = true; }
    ok(!threw, 'a failed cache read never throws out of the layout');
    ok(r && r.projects.length === 0 && r.hydrated === true,
      'it settles as an empty hydration instead');
  }

  // ── The stored user is carried, so a consumer can scope the list ──────────
  {
    const r = await run({ storedUser: { id: 'u1', role: 'cp', assigned_projects: ['p2'] } });
    ok(r.user && r.user.id === 'u1',
      'the stored user rides along so screens can apply their own role filter');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})().catch((e) => { console.error(e); process.exit(2); });
