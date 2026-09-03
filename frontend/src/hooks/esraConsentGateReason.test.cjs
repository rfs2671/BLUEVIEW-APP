/**
 * THE GATE'S RETURN VALUE — RUN, NOT READ.
 *
 * ── TWO THINGS THIS FILE HOLDS DOWN ─────────────────────────────────────────
 *
 * 1. WHERE IT SENDS HIM. `ensure()` pushes '/consent' on every refusal. For two
 *    days that route was not on RouteGuard's CP allowlist, so the push landed
 *    and the guard replaced it with /logbooks before the agreement painted —
 *    33 GETs, zero POSTs, every signature on the platform blocked. The
 *    destination is asserted here by name; that it is REACHABLE is asserted by
 *    cpConfinement.test.cjs and PAINTED by scripts/consent-paint.cjs.
 *
 * 2. THAT `ensure()` IS STILL A BARE BOOLEAN. Thirteen signing screens write
 *    `if (!(await consent.ensure())) return;`. The four refusals collapse into
 *    one false, which is a real shortcoming — no caller can tell a man who
 *    declined from a man whose server is down — and the fix for it is
 *    `ensureWithReason()`, NOT a richer return from `ensure`. Returning an
 *    object or a reason string from `ensure` would make `!value` false on a
 *    REFUSAL and apply the very signature the line exists to stop. That is a
 *    silent, unsigned-consent regression, so it is asserted rather than trusted
 *    to review.
 *
 * ── WHY IT CAN BE EXECUTED AT ALL ───────────────────────────────────────────
 *
 * The hook uses React only as plumbing — useCallback as identity, useRef as a
 * box, useState for a value nothing here reads. Stubbing those four is not
 * simulating React; it is supplying the three properties this module actually
 * depends on. The consent RULE it applies is real: esraConsentState.js and
 * consentCache.js are loaded for real, recursively, by the harness.
 *
 * Run:  node src/hooks/esraConsentGateReason.test.cjs
 */

const path = require('path');
const { loadEsm } = require('../utils/esmHarness.cjs');

let passed = 0;
let failed = 0;
const ok = (cond, label) => {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
};

// ── The harness ─────────────────────────────────────────────────────────────
//
// One mutable box per run so a case can set the server's answer, the device's
// memory, and then read back where the gate navigated.
const world = {
  payload: null,      // what GET /api/esra-consent resolved to
  throws: false,      // or whether it refused to resolve at all
  storage: {},        // AsyncStorage, keyed exactly as consentCache keys it
  pushed: [],
};

const react = {
  useState: (init) => [init, () => {}],
  useRef: (init) => ({ current: init }),
  useEffect: () => {},
  useCallback: (fn) => fn,
};

function gate() {
  world.pushed = [];
  const M = loadEsm('src/hooks/useEsraConsent.js', {
    stubs: {
      react,
      'expo-router': { useRouter: () => ({ push: (p) => world.pushed.push(p) }) },
      '../utils/api': {
        esraConsentAPI: {
          get: async () => {
            if (world.throws) throw new Error('offline');
            return world.payload;
          },
        },
      },
      '../context/AuthContext': { useAuth: () => ({ user: { id: 'u1' } }) },
      '@react-native-async-storage/async-storage': {
        getItem: async (k) => (k in world.storage ? world.storage[k] : null),
        setItem: async (k, v) => { world.storage[k] = v; },
        removeItem: async (k) => { delete world.storage[k]; },
      },
    },
  });
  return M.useEsraConsent();
}

const VERSION = '2026-08-30.1';
const KEY = 'esra_consent_ok:u1';

const AGREED = { has_consented: true, is_current: true, current_version: VERSION, agreed_version: VERSION };
const NOT_AGREED = { has_consented: false, is_current: false, current_version: VERSION };
const STALE = { has_consented: true, is_current: false, current_version: VERSION, agreed_version: '2026-01-01.1' };
const DECLINED = { has_consented: false, is_current: false, has_declined: true, current_version: VERSION };

function reset({ payload = null, throws = false, storage = {} } = {}) {
  world.payload = payload;
  world.throws = throws;
  world.storage = { ...storage };
}

(async () => {
  console.log('\n1. ensure() IS A BARE BOOLEAN, IN EVERY OUTCOME');
  {
    const cases = [
      ['agreed to the current wording', { payload: AGREED }, true],
      ['never agreed', { payload: NOT_AGREED }, false],
      ['agreed to earlier wording', { payload: STALE }, false],
      ['declined', { payload: DECLINED }, false],
      ['server unreachable, nothing remembered', { throws: true }, false],
      ['server unreachable, a yes remembered',
        { throws: true, storage: { [KEY]: JSON.stringify({ version: VERSION, at: '2026-09-01T00:00:00Z' }) } },
        true],
    ];
    for (const [label, world0, expected] of cases) {
      reset(world0);
      const v = await gate().ensure();
      ok(v === expected,
        `${label}: ensure() === ${expected} (got ${JSON.stringify(v)}) — and it is a `
        + 'primitive, because thirteen call sites negate it directly');
      ok(typeof v === 'boolean', `${label}: and the type is boolean, not an object`);
    }
  }

  console.log('\n2. THE REFUSALS ARE TOLD APART, WHICH ensure() CANNOT DO');
  {
    const cases = [
      ['never agreed', { payload: NOT_AGREED }, 'not_agreed'],
      ['agreed to earlier wording', { payload: STALE }, 'stale'],
      ['declined', { payload: DECLINED }, 'declined'],
      ['server unreachable', { throws: true }, 'unknown'],
    ];
    for (const [label, world0, reason] of cases) {
      reset(world0);
      const r = await gate().ensureWithReason();
      ok(r.ok === false && r.reason === reason,
        `${label}: { ok: false, reason: '${reason}' } (got ${JSON.stringify(r)})`);
    }

    reset({ payload: AGREED });
    const yes = await gate().ensureWithReason();
    ok(yes.ok === true && yes.reason === 'ready', 'agreed: { ok: true, reason: "ready" }');

    reset({ throws: true, storage: { [KEY]: JSON.stringify({ version: VERSION, at: 'x' }) } });
    const offline = await gate().ensureWithReason();
    ok(offline.ok === true && offline.reason === 'cached',
      'an offline yes is CACHED and not READY — "he agreed once and we are '
      + 'honouring it with no signal" is a different sentence from "the server '
      + `confirms he has agreed" (got ${JSON.stringify(offline)})`);
  }

  console.log('\n3. AND IT PUSHES TO /consent — THE ROUTE THE GUARD WAS BOUNCING');
  {
    for (const [label, world0] of [
      ['never agreed', { payload: NOT_AGREED }],
      ['agreed to earlier wording', { payload: STALE }],
      ['declined', { payload: DECLINED }],
      ['server unreachable, nothing remembered', { throws: true }],
    ]) {
      reset(world0);
      const g = gate();
      await g.ensure();
      ok(world.pushed.length === 1 && world.pushed[0] === '/consent',
        `${label}: pushed ${JSON.stringify(world.pushed)}`);
    }

    // AND NOT WHEN HE MAY SIGN. A gate that navigated on the happy path would
    // interrupt every signature instead of none.
    reset({ payload: AGREED });
    const g = gate();
    await g.ensure();
    ok(world.pushed.length === 0, 'a consenting signer is not navigated anywhere');

    reset({ throws: true, storage: { [KEY]: JSON.stringify({ version: VERSION, at: 'x' }) } });
    const g2 = gate();
    await g2.ensure();
    ok(world.pushed.length === 0,
      'nor is a man in a cellar whose device remembers his yes — the whole '
      + 'point of the cache is that he is not sent to a screen that needs a '
      + 'server he cannot reach');
  }

  console.log('\n4. AND ensure() IS STILL WHAT THE CENSUS COUNTS');
  {
    const fs = require('fs');
    const src = fs.readFileSync(
      path.join(__dirname, 'useEsraConsent.js'), 'utf8',
    );
    ok(/return \{ state, busy, ensure, ensureWithReason \}/.test(src),
      'both are exported — ensureWithReason is ADDITIVE, so no signing screen '
      + 'had to change to get this fix');
  }

  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
