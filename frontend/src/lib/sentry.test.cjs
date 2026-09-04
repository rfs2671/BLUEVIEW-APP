/**
 * THE FILTER THAT DISCARDED A SEVEN-DAY OUTAGE, AND WHAT IT DOES NOW.
 *
 * `beforeSend` dropped every "Network Error" / "Failed to fetch" with a comment
 * naming "misconfigured CORS preflights" as the class. Axios raises precisely
 * `Error: Network Error` when a preflight blocks the request. From 2026-08-28
 * to 2026-09-04 the web build could not sign in, and the only client channel
 * that could have seen it discarded every event — deliberately, by a rule
 * written by someone who had identified the category correctly and judged it
 * on the properties of ONE event.
 *
 * WHY THIS EXECUTES THE PREDICATE INSTEAD OF GREPPING IT. A source-text test
 * proving the filter is WRITTEN proves nothing about what it RETURNS, and what
 * it returns is the entire question: `null` is the bug, a downgraded event is
 * the fix, and both are spelled with the same words. The real `@sentry/react`
 * is stubbed so `Sentry.init` hands back the options object the shipped module
 * passes it, and the beforeSend under test is the one that would ship.
 *
 *   node frontend/src/lib/sentry.test.cjs
 */
const path = require('path');
const { loadEsm } = require('../utils/esmHarness.cjs');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS  ', label); }
  else { failed += 1; console.log('  FAIL  ', label); }
}
function section(t) {
  console.log(`\n-- ${t} ${'-'.repeat(Math.max(0, 58 - t.length))}`);
}

const QUIET = { log: () => {}, warn: () => {}, error: () => {}, info: () => {} };

// A blocked fetch, in the exact shape axios produces it.
const blocked = (value = 'Network Error') => ({
  exception: { values: [{ type: 'Error', value }] },
});
// An ordinary application crash, which must be untouched.
const realCrash = () => ({
  exception: { values: [{ type: 'TypeError', value: "x is not a function" }] },
});

function load({ random = Math.random } = {}) {
  let options = null;
  const mod = loadEsm('src/lib/sentry.js', {
    stubs: {
      '@sentry/react': {
        init: (opts) => { options = opts; },
        setUser: () => {}, setTag: () => {}, captureException: () => {},
      },
    },
    globals: {
      console: QUIET,
      process: { env: { EXPO_PUBLIC_SENTRY_DSN: 'https://k@o0.ingest.sentry.io/1' } },
      window: { addEventListener: () => {} },
      Math: { ...Math, random },
    },
  });
  const started = mod.initSentry();
  return { mod, options, started };
}

section('the module initialises and hands us the real predicate');
const base = load({ random: () => 0.99 });
ok(base.started === true, 'initSentry() ran with a DSN present');
ok(base.options && typeof base.options.beforeSend === 'function',
  'Sentry.init was given a beforeSend, and we are holding the shipped one');

section('an ordinary error is not touched');
{
  const { options } = load({ random: () => 0.0 });
  const ev = realCrash();
  const out = options.beforeSend(ev);
  ok(out === ev, 'a real crash passes through unchanged — same object, not a copy');
  ok(out.level === undefined && out.fingerprint === undefined,
    '...and is neither downgraded nor collapsed into the blocked-request issue');
}

section('a blocked request, when the sample keeps it');
{
  const { options, mod } = load({ random: () => 0.0 });   // always sampled
  const out = options.beforeSend(blocked());
  ok(out !== null, 'IT IS NOT DROPPED — this is the whole change');
  ok(Array.isArray(out.fingerprint) && out.fingerprint.length === 1,
    'a FIXED fingerprint, so every one of these collapses into ONE Sentry issue');
  ok(out.level === 'info',
    "level 'info' — it can never page anyone by existing; the issue's RATE is the alert");
  ok(out.tags && out.tags.client_request_blocked === 'true',
    'tagged, so the issue is findable without knowing the fingerprint string');
  ok(out.extra && out.extra.blocked_this_session === 1,
    'and it carries the per-session count — the number a single event cannot have');

  // THE DISCRIMINATION THE COUNT BUYS. One is a user in a tunnel. Four hundred
  // in one session is an app that cannot reach its API at all, which is the
  // state that ran for seven days.
  for (let i = 0; i < 399; i += 1) options.beforeSend(blocked());
  const late = options.beforeSend(blocked());
  ok(late.extra.blocked_this_session === 401,
    'the count keeps climbing across the session (401 after 401 blocked requests)');
  ok(mod._blockedRequestCount() === 401,
    'and the module agrees — every blocked request is counted, sampled or not');
}

section("'Failed to fetch' is the same class");
{
  const { options } = load({ random: () => 0.0 });
  const out = options.beforeSend(blocked('Failed to fetch'));
  ok(out !== null && out.level === 'info',
    "fetch's wording is handled identically to axios's");
}

section('the sample keeps the quota bounded');
{
  const { options, mod } = load({ random: () => 0.9 });   // never sampled
  ok(options.beforeSend(blocked()) === null,
    'above the sample rate the event is still dropped — an outage cannot flood the quota');
  ok(mod._blockedRequestCount() === 1,
    'BUT IT IS STILL COUNTED. A dropped event that was never counted is how this '
    + 'was invisible; the count is what the next sampled event reports.');
}

section('both branches are reachable with the real Math.random');
{
  const { options } = load();   // the actual shipped sampling
  let kept = 0;
  const N = 20000;
  for (let i = 0; i < N; i += 1) if (options.beforeSend(blocked()) !== null) kept += 1;
  ok(kept > 0, `something survives sampling (${kept}/${N}) — a rate of 0 would be the old bug`);
  ok(kept < N, `and not everything does (${kept}/${N}) — a rate of 1 would flood the quota`);
  // Deliberately loose. This asserts the rate is in the right ORDER, not that a
  // PRNG hit a number; a tight bound here would be a flaky test about nothing.
  ok(kept > N * 0.002 && kept < N * 0.05,
    `the surviving fraction is in the region of the configured 1% (${(100 * kept / N).toFixed(2)}%)`);
}

section('the breadcrumb option, and why it is not this');
{
  // A total blockade produces NO other event to carry a breadcrumb — the app
  // never gets far enough to throw. Asserted as behaviour: after 500 blocked
  // requests and no crash, a breadcrumb-only design would have reported
  // nothing at all. What we have instead is a non-null event.
  const { options } = load({ random: () => 0.0 });
  let reported = 0;
  for (let i = 0; i < 500; i += 1) if (options.beforeSend(blocked()) !== null) reported += 1;
  ok(reported > 0,
    'a session that throws nothing else still reports — the case a breadcrumb would have missed');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) { console.log('FAILURES ABOVE'); process.exit(1); }
console.log('ALL PASSED');
