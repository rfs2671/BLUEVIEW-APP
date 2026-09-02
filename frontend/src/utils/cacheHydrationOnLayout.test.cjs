/**
 * CACHE HYDRATION BELONGS TO THE LAYOUT, NOT TO WHERE YOU HAPPEN TO LAND.
 *
 * Before this, every cached read was screen-local: app/index.jsx and
 * app/logbooks/index.jsx each awaited readCachedProjectList() inside their own
 * fetch handler. A screen reached DIRECTLY — which is the gate tablet's normal
 * case, where someone opens Log Books and never touches a dashboard — got
 * whatever hydration that one screen happened to implement, and nothing else.
 *
 * The ruling: hydration runs on the parent layout, so it is as available as the
 * nav is. This file is the guard on that.
 *
 * IT IS ALSO THE GUARD ON THE OPPOSITE MISTAKE. Hoisting must be ADDITIVE. The
 * screens' own settleFetch calls, and the fetchState / detailState they derive
 * FROM THE FETCH'S OWN STATUS, are what make a cached screen admit it is
 * cached. A hoist that replaced a screen's fetch with a provider read would
 * leave readOnly permanently 'ok' and a cached roster would render as live —
 * on trades.jsx and report-settings.jsx that is a write-refusal silently
 * lifted, and on workers/[id].jsx it is the edit button coming back over a
 * stale record. Those assertions are below and they are the point.
 *
 * Run:  node src/utils/cacheHydrationOnLayout.test.cjs
 */
const fs = require('fs');
const path = require('path');

const APP = path.join(__dirname, '..', '..', 'app');
const SRC = path.join(__dirname, '..');
const read = (p) => fs.readFileSync(p, 'utf8');

// LINE COMMENTS FIRST, AND THE ORDER IS LOAD-BEARING.
//
// _layout.jsx documents the site-device route rule as `// … on /site/*, /login`
// — a `/*` sitting inside a line comment. Stripping block comments first, the
// non-greedy match opens THERE and runs to the next `*/` anywhere below it,
// which is the close of the JSX comment beside <ProjectCacheProvider>. That
// swallowed <AuthProvider> along with ~130 lines between them, and the nesting
// assertion failed against a layout that was in fact correctly nested.
const strip = (s) => s.replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');

let passed = 0, failed = 0;
const ok = (c, l) => { if (c) { passed += 1; console.log('  PASS  ' + l); } else { failed += 1; console.log('  FAIL  ' + l); } };

// ── 1. The provider exists and is mounted on the ROOT LAYOUT ────────────────
const providerPath = path.join(SRC, 'context', 'ProjectCacheContext.jsx');
ok(fs.existsSync(providerPath), 'src/context/ProjectCacheContext.jsx exists');

const layout = fs.existsSync(path.join(APP, '_layout.jsx')) ? strip(read(path.join(APP, '_layout.jsx'))) : '';
ok(/import\s*\{[^}]*ProjectCacheProvider[^}]*\}\s*from\s*['"][^'"]*ProjectCacheContext['"]/.test(layout),
  'the root layout imports ProjectCacheProvider');
ok(/<ProjectCacheProvider>/.test(layout),
  'the root layout RENDERS ProjectCacheProvider — hydration is layout-level, not screen-level');

// It must sit INSIDE AuthProvider: hydration is exposed only to a device that
// already holds a session, and the provider reads auth to decide that.
const authAt = layout.indexOf('<AuthProvider>');
const pcAt = layout.indexOf('<ProjectCacheProvider>');
ok(authAt >= 0 && pcAt > authAt,
  'ProjectCacheProvider is nested INSIDE AuthProvider (it consumes auth state)');

// And it must wrap the Stack, or a route would mount outside the hydration.
const shellAt = layout.indexOf('<AppShell />');
ok(pcAt >= 0 && shellAt > pcAt,
  'ProjectCacheProvider wraps AppShell — every route mounts inside it');

// ── 2. Hydration does NOT wait on the network ───────────────────────────────
// The whole point on a cold boot in a dead zone: the cached list is in
// AsyncStorage at millisecond zero, and must not sit behind a 25s
// authAPI.getMe() before anything paints.
const provider = fs.existsSync(providerPath) ? strip(read(providerPath)) : '';
ok(/readCachedProjectList/.test(provider),
  'the provider hydrates from readCachedProjectList');
ok(!/projectsAPI|apiClient|axios/.test(provider),
  'the provider makes NO network call — it is a cache reader, nothing else');

// ── 3. THE HONESTY INVARIANT ────────────────────────────────────────────────
// The provider must never mint a fetch status. fetchState/detailState are
// facts about a screen's OWN request; a cache reader that set them would be
// asserting the network answered when it did not.
ok(!/setFetchState|setDetailState|fetchState\s*=/.test(provider),
  'the provider never sets fetchState/detailState — it cannot claim a read succeeded');
ok(/source|cached|provenance/i.test(provider),
  'the provider carries provenance — a consumer can tell cache from live');

// ── 4. The screens that gate on fetch status still do ───────────────────────
// These are the screens that deliberately want a FAILED read rather than a
// cached one. Each must still derive its gate from settleFetch's status.
const GATED = [
  ['project/[id]/trades.jsx', /const\s+readOnly\s*=\s*fetchState\s*!==\s*'ok'/,
    'trades.jsx still derives readOnly from its own fetch status'],
  ['project/[id]/report-settings.jsx', /const\s+readOnly\s*=\s*fetchState\s*!==\s*'ok'/,
    'report-settings.jsx still derives readOnly from its own fetch status'],
];
for (const [rel, re, label] of GATED) {
  const s = strip(read(path.join(APP, rel)));
  ok(re.test(s), label);
  ok(/settleFetch\(/.test(s), `${rel} still runs its own settleFetch`);
  // The cached read stays FAILURE-ONLY: it is reached only when status !== 'ok'.
  ok(/if\s*\(\s*r\.status\s*!==\s*'ok'\s*\)[\s\S]{0,200}readCachedProject\(/.test(s),
    `${rel} reads cache ONLY on a failed fetch`);
  // And the gate must not be fed by the layout provider.
  ok(!/useProjectCache/.test(s),
    `${rel} does not source its gate from the layout cache — that would read as live`);
}

// workers/[id].jsx hides its edit control on a cached/failed read.
{
  const s = strip(read(path.join(APP, 'workers', '[id].jsx')));
  ok(/detailState\s*===\s*'ok'/.test(s),
    "workers/[id].jsx still gates editing on detailState === 'ok'");
  ok(/setDetailState\(r\.status/.test(s),
    'workers/[id].jsx still derives detailState from its own fetch status');
  ok(/const\s+cached\s*=\s*await\s+readCachedWorkerDetail\(/.test(s),
    'workers/[id].jsx still reads its worker cache only in the failure branch');
  ok(!/useProjectCache/.test(s),
    'workers/[id].jsx does not source its gate from the layout cache');
}

// ── 5. The list screens SEED from the layout, and keep their own fetch ──────
for (const rel of ['index.jsx', 'logbooks/index.jsx']) {
  const s = strip(read(path.join(APP, rel)));
  ok(/useProjectCache/.test(s),
    `${rel} seeds from the layout-level hydration`);
  ok(/projectsAPI\.getAll\(\)/.test(s),
    `${rel} STILL makes its own live read — the hoist is additive, not a replacement`);
  ok(/cacheProjectList\(/.test(s),
    `${rel} still writes through on a successful read`);
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
