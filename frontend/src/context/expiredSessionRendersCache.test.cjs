/**
 * A GATE TABLET, THIRTY DAYS OFFLINE, WITH A DOB INSPECTOR IN THE TRAILER.
 *
 * This is the scenario the whole change exists for, and it is executed here
 * rather than described: the REAL AuthProvider is transpiled and mounted
 * against a fake `react`, an expired token on disk, a cached site-device user
 * on disk, and a network that answers nothing.
 *
 * WHAT USED TO HAPPEN. AuthContext decoded the JWT locally and threw on
 * `exp` — before any network call, so being offline never protected it. The
 * throw reached the outer catch, which called clearAuth(): token and stored
 * user deleted off the disk of a device with no way to log back in. The
 * offline grace path two branches below it (fall back to storedUser on a
 * network error) was written, correct, and unreachable, because the local
 * expiry threw first. Every /site/* screen then redirects on
 * `!isAuthenticated`, so the tablet landed on a login screen whose password
 * lives in an admin's head, with a full cache of logbooks, plans and documents
 * sitting on the disk, unreachable.
 *
 * WHAT MUST HAPPEN. Expiry stops FETCHING, not READING. The content was
 * approved and downloaded long ago; the session running out does not unapprove
 * it. So the tablet stays authenticated against its cache, in site mode, on
 * its project — and the five site screens, whose /login redirect is gated on
 * `!isAuthenticated`, therefore render.
 *
 * The last block reads those five screens' real source and evaluates their
 * real redirect condition against the context this file just produced, so the
 * claim "it renders cached content instead of redirecting to login" is
 * checked end to end rather than asserted about a variable.
 *
 * Run:  node src/context/expiredSessionRendersCache.test.cjs
 */

const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
function done() {
  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

const CTX = path.join(__dirname, 'AuthContext.js');
if (!fs.existsSync(CTX)) { ok(false, 'AuthContext.js exists'); done(); }

// ── Token fixtures ─────────────────────────────────────────────────────────
const HOUR = 3600 * 1000;
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const jwtOf = (p) => `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64(p)}.sig`;
const EXPIRED = jwtOf({
  sub: 'dev1', role: 'site_device', site_mode: true, project_id: 'proj1',
  exp: (Date.now() - 24 * HOUR) / 1000,
});
const LIVE = jwtOf({
  sub: 'dev1', role: 'site_device', site_mode: true, project_id: 'proj1',
  exp: (Date.now() + 20 * 24 * HOUR) / 1000,
});

const CACHED_DEVICE = {
  id: 'dev1', role: 'site_device', site_mode: true,
  project_id: 'proj1', project_name: '250 Water Street',
  device_name: 'Gate 1', name: 'Gate 1',
};

const offline = () => { const e = new Error('Network Error'); e.request = {}; return e; };
const rejected = () => {
  const e = new Error('Request failed with status code 401');
  e.response = { status: 401, data: { detail: 'Token expired' } };
  return e;
};

// ── A React small enough to run one provider ───────────────────────────────
function makeRuntime() {
  const hooks = [];
  const box = { idx: 0, effects: [] };
  const React = {
    createContext(dflt) {
      const ctx = { _dflt: dflt };
      ctx.Provider = function Provider(props) { return props; };
      return ctx;
    },
    useContext: (ctx) => ctx._dflt,
    useState(init) {
      const i = box.idx++;
      if (!hooks[i]) hooks[i] = { v: typeof init === 'function' ? init() : init };
      const h = hooks[i];
      return [h.v, (nv) => { h.v = typeof nv === 'function' ? nv(h.v) : nv; }];
    },
    useRef(init) {
      const i = box.idx++;
      if (!hooks[i]) hooks[i] = { v: { current: init } };
      return hooks[i].v;
    },
    useEffect(fn, deps) {
      const i = box.idx++;
      const prev = hooks[i];
      const changed = !prev || !deps || !prev.deps
        || deps.length !== prev.deps.length
        || deps.some((d, k) => !Object.is(d, prev.deps[k]));
      hooks[i] = { deps };
      if (changed) box.effects.push(fn);
    },
    useCallback: (fn) => { box.idx += 1; return fn; },
    useMemo: (fn) => { box.idx += 1; return fn(); },
    createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
    Fragment: 'Fragment',
  };
  return { React, box };
}

const tick = async (n = 12) => {
  for (let i = 0; i < n; i += 1) {
    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, 0));
  }
};

/**
 * Transpile and mount the REAL AuthProvider. `require` is shimmed so
 * ./utils/api and ./lib/sentry are fakes and everything else — notably
 * ../utils/sessionSurvival — is the shipped module, compiled and evaluated.
 */
async function mountAuthProvider({ token, storedUser, meAnswers }) {
  const calls = {
    clearAuth: 0, getMe: 0, storedWrites: [], rejectedHandler: null,
  };
  const api = {
    authAPI: {
      getMe: async () => {
        calls.getMe += 1;
        const answer = meAnswers();
        if (answer instanceof Error) throw answer;
        return answer;
      },
      login: async () => ({}),
      logout: async () => {},
    },
    getToken: async () => token,
    getStoredUser: async () => storedUser,
    setStoredUser: async (u) => { calls.storedWrites.push(u); },
    clearAuth: async () => { calls.clearAuth += 1; },
    registerAuthRejectedHandler: (fn) => { calls.rejectedHandler = fn; },
  };
  const sentry = { setSentryUser() {}, clearSentryUser() {} };

  const { React, box } = makeRuntime();

  const compileEsm = (file) => babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    configFile: false,
    babelrc: false,
    plugins: [
      require.resolve('@babel/plugin-transform-modules-commonjs'),
      [require.resolve('@babel/plugin-transform-react-jsx'),
        { runtime: 'classic', pragma: 'React.createElement', pragmaFrag: 'React.Fragment' }],
    ],
  }).code;

  const cache = new Map();
  const shimFor = (fromFile) => {
    const req = (spec) => {
      if (spec === 'react') return React;
      if (/utils\/api$/.test(spec)) return api;
      if (/lib\/sentry$/.test(spec)) return sentry;
      if (!spec.startsWith('.')) return require(spec);
      const target = spec.endsWith('.js') ? spec : `${spec}.js`;
      const abs = path.resolve(path.dirname(fromFile), target);
      if (cache.has(abs)) return cache.get(abs);
      const m = {};
      cache.set(abs, m);
      // eslint-disable-next-line no-new-func
      new Function('exports', 'module', 'require', compileEsm(abs))(
        m, { exports: m }, shimFor(abs));
      return m;
    };
    req.resolve = require.resolve;
    return req;
  };

  const mod = {};
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', compileEsm(CTX))(
    mod, { exports: mod }, shimFor(CTX));
  if (typeof mod.AuthProvider !== 'function') {
    ok(false, 'AuthContext exports AuthProvider');
    done();
  }

  const render = () => {
    box.idx = 0;
    box.effects = [];
    const el = mod.AuthProvider({ children: null });
    const effects = box.effects.slice();
    return { value: el.props.value, effects };
  };

  let { value, effects } = render();
  for (const e of effects) e();
  await tick();
  ({ value } = render());
  await tick();
  ({ value } = render());

  return {
    calls,
    value,
    // Re-read the context after something outside the render loop (the 401
    // notifier) has changed state.
    reread: async () => { await tick(); return render().value; },
  };
}

// ═══════════════════════════════════════════════════════════════════════════
(async () => {
  // ── The scenario ─────────────────────────────────────────────────────────
  console.log('\n── expired token, no network, a full cache on disk ──');
  const dead = await mountAuthProvider({
    token: EXPIRED,
    storedUser: CACHED_DEVICE,
    meAnswers: () => offline(),
  });

  ok(dead.calls.clearAuth === 0,
    'THE CREDENTIALS SURVIVE. clearAuth() on a device that cannot log back '
    + 'in is the defect; it was called on every cold boot past day 30');
  ok(dead.value.isAuthenticated === true,
    'AND THE SCREENS STAY OPEN. Every /site/* screen redirects on '
    + '!isAuthenticated, so this one boolean is the difference between a '
    + 'cached logbook and a login form');
  ok(dead.value.siteMode === true,
    'still in site mode, read back off the cached user');
  ok(dead.value.siteProject && dead.value.siteProject.id === 'proj1',
    'and still on its project — a site screen with no project id fetches '
    + 'and renders nothing at all');
  ok(dead.value.siteProject && dead.value.siteProject.name === '250 Water Street',
    'including the project name the inspector reads off the header');
  ok(dead.value.user && dead.value.user.id === 'dev1',
    'the cached principal is the one in context');
  ok(dead.value.isLoading === false,
    'and the boot completes rather than spinning');
  ok(dead.value.isSessionExpired === true,
    'THE STATE IS NAMED, not faked. The device is authenticated against its '
    + 'own cache and nothing else; a screen that wants to refuse a WRITE has '
    + 'to be able to tell that from a live session');
  ok(dead.calls.getMe === 0,
    'AND IT DOES NOT ASK. A token we know is dead buys nothing at the server '
    + 'and, before this, the 401 it earned was itself a reason to clearAuth()');

  // ── What the five screens do with that ───────────────────────────────────
  console.log('\n── which is exactly what the site screens need ──');
  {
    const SITE = path.join(__dirname, '..', '..', 'app', 'site');
    const screens = ['index.jsx', 'logbooks.jsx', 'documents.jsx',
      'checkins.jsx', 'daily-logs.jsx'];
    const GUARD = /if\s*\(\s*!\s*isAuthenticated\s*\)\s*\{\s*router\.replace\('\/login'\)/;

    for (const screen of screens) {
      const file = path.join(SITE, screen);
      if (!fs.existsSync(file)) { ok(false, `app/site/${screen} exists`); continue; }
      const src = fs.readFileSync(file, 'utf8');
      const guarded = GUARD.test(src);
      ok(guarded,
        `app/site/${screen} sends the device to /login on !isAuthenticated`);
      // The real predicate, against the real context produced above.
      ok(guarded && !dead.value.isAuthenticated === false,
        `app/site/${screen} therefore STAYS PUT and renders its cache`);
      ok(/replace\('\/'\)/.test(src) ? dead.value.siteMode === true : true,
        `app/site/${screen} is not bounced to '/' either (siteMode holds)`);
    }
  }

  // ── Nothing cached is a different situation ──────────────────────────────
  console.log('\n── an expired token with nothing behind it ──');
  {
    const bare = await mountAuthProvider({
      token: EXPIRED, storedUser: null, meAnswers: () => offline(),
    });
    ok(bare.calls.clearAuth === 1,
      'with no cached principal there is nothing to preserve and nothing to '
      + 'render — this one really does belong at the login screen');
    ok(bare.value.isAuthenticated === false, 'and it is not authenticated');
  }

  // ── The grace that already existed must not regress ──────────────────────
  console.log('\n── the pre-existing offline grace still works ──');
  {
    const live = await mountAuthProvider({
      token: LIVE, storedUser: CACHED_DEVICE, meAnswers: () => offline(),
    });
    ok(live.calls.getMe === 1, 'a live token still checks in with the server');
    ok(live.calls.clearAuth === 0, 'a network error still falls back to the stored user');
    ok(live.value.isAuthenticated === true, 'and stays authenticated');
    ok(live.value.siteMode === true, 'and in site mode');
    ok(live.value.isSessionExpired === false,
      'and is NOT flagged expired — offline is not expired, and conflating '
      + 'them would put a perfectly live device into read-only');
  }

  // ── A genuine rejection still logs out, and now does it on time ──────────
  console.log('\n── a live token the server refuses ──');
  {
    const revoked = await mountAuthProvider({
      token: LIVE, storedUser: CACHED_DEVICE, meAnswers: () => rejected(),
    });
    ok(revoked.calls.clearAuth === 1,
      'A DEACTIVATED DEVICE IS STILL LOGGED OUT. The server refused a token '
      + 'that is live by its own clock; that is a real revocation and '
      + 'softening it would be a security regression');
    ok(revoked.value.isAuthenticated === false, 'and the screens send it to /login');
  }

  console.log('\n── and a mid-session rejection no longer waits for a restart ──');
  {
    const live = await mountAuthProvider({
      token: LIVE, storedUser: CACHED_DEVICE, meAnswers: () => ({ ...CACHED_DEVICE }),
    });
    ok(live.value.isAuthenticated === true, 'signed in');
    ok(typeof live.calls.rejectedHandler === 'function',
      'AuthContext registers a handler with api.js. api.js:171 has always '
      + 'claimed "Navigation will be handled by AuthContext" and it was not: '
      + 'AuthContext only re-read auth on mount, so a mid-session 401 wiped '
      + 'the disk and left the screen looking fine until the next cold boot');
    if (typeof live.calls.rejectedHandler === 'function') {
      live.calls.rejectedHandler();
      const after = await live.reread();
      ok(after.isAuthenticated === false,
        'and calling it drops the session immediately, which is what makes '
        + 'the comment true');
      ok(after.siteMode === false, 'site mode drops with it');
    }
  }

  done();
})().catch((e) => {
  console.error(e);
  ok(false, `harness threw: ${e && e.message}`);
  done();
});
