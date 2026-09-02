/**
 * THE GATE TABLET IS LIGHT.
 *
 * The site device is a fixed tablet bolted up at a construction gate and read
 * in daylight by DOB inspectors. It shipped defaulting to DARK — `useState(true)`
 * in ThemeProvider — and it has no way to change that: the RouteGuard in
 * app/_layout.jsx confines a site device to `/site/*` and `/login`, and both
 * theme switches in the app (app/settings.jsx and the SettingsModal inside
 * src/components/FloatingNav.js) live on routes it can never reach. So the one
 * surface in the product that is read outdoors by someone who did not configure
 * it was the one surface pinned to the palette that is unreadable outdoors.
 *
 * THE CONSTRAINT THIS FIX WORKS AROUND. ThemeProvider mounts OUTSIDE
 * AuthProvider (app/_layout.jsx: ThemeProvider > DatabaseProvider >
 * AuthProvider), so `useAuth()` is not available where the theme is decided.
 * The role therefore has to come from the same place AuthContext itself reads
 * it from on a cold boot — the `blueview_user` blob in AsyncStorage — and from
 * a catch-up call made by AppShell, which IS inside AuthProvider, for the case
 * that has no cold boot at all: provisioning a tablet by logging in.
 *
 * These are behavioural tests. ThemeProvider is executed for real — the shipped
 * ThemeContext.js, compiled through babel with the JSX transform and driven by
 * a minimal hook runtime — against the real src/styles/theme.js palette. A fix
 * that renamed a constant, or that set a flag without ever calling applyTheme,
 * would fail here. The one exception is the last block, which asserts that
 * AppShell is WIRED to the catch-up call: that is read off the _layout.jsx AST,
 * because executing AppShell means executing expo-router.
 *
 * Run:  node src/context/siteDeviceTheme.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');
const parser = require('@babel/parser');
const { loadEsm } = require('../utils/esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── A minimal hook runtime ───────────────────────────────────────────────────
//
// Enough React to run ONE function component that uses useState / useEffect /
// useMemo and renders a single context Provider. Not a React clone: state
// updates re-render synchronously to a fixed point, and effects run after each
// render pass, which is all ThemeProvider needs.
function makeReact() {
  const rt = { hooks: [], idx: 0, effects: [], dirty: false };

  const changed = (deps, prev) => (
    !prev || !deps || !prev.deps
    || deps.length !== prev.deps.length
    || deps.some((d, k) => !Object.is(d, prev.deps[k]))
  );

  const React = {
    createContext(dflt) {
      const ctx = { _default: dflt };
      ctx.Provider = (props) => ({ __provider: true, value: props.value, children: props.children });
      return ctx;
    },
    useState(init) {
      const i = rt.idx; rt.idx += 1;
      if (rt.hooks.length <= i || rt.hooks[i] === undefined) {
        rt.hooks[i] = { v: typeof init === 'function' ? init() : init };
      }
      const h = rt.hooks[i];
      const set = (next) => {
        const nv = typeof next === 'function' ? next(h.v) : next;
        if (Object.is(nv, h.v)) return;
        h.v = nv;
        rt.dirty = true;
      };
      return [h.v, set];
    },
    useEffect(fn, deps) {
      const i = rt.idx; rt.idx += 1;
      const prev = rt.hooks[i];
      const runs = changed(deps, prev);
      rt.hooks[i] = { deps, cleanup: prev && prev.cleanup };
      if (runs) {
        rt.effects.push(() => {
          if (rt.hooks[i].cleanup) { try { rt.hooks[i].cleanup(); } catch (_e) { /* noop */ } }
          const c = fn();
          rt.hooks[i].cleanup = typeof c === 'function' ? c : undefined;
        });
      }
    },
    useMemo(fn, deps) {
      const i = rt.idx; rt.idx += 1;
      const prev = rt.hooks[i];
      if (changed(deps, prev)) rt.hooks[i] = { deps, v: fn() };
      return rt.hooks[i].v;
    },
    useRef(init) {
      const i = rt.idx; rt.idx += 1;
      if (rt.hooks.length <= i || rt.hooks[i] === undefined) rt.hooks[i] = { v: { current: init } };
      return rt.hooks[i].v;
    },
    useContext(ctx) { return ctx._default; },
    createElement(type, props, ...children) {
      const p = { ...(props || {}) };
      if (children.length) p.children = children.length === 1 ? children[0] : children;
      return typeof type === 'function' ? type(p) : { type, props: p };
    },
  };
  React.Fragment = 'Fragment';
  return { React, rt };
}

// ── Compile the shipped ThemeContext.js and run it ───────────────────────────
const THEME_CONTEXT = path.join(__dirname, 'ThemeContext.js');
const COMPILED = babel.transformSync(fs.readFileSync(THEME_CONTEXT, 'utf8'), {
  filename: THEME_CONTEXT,
  configFile: false,
  babelrc: false,
  presets: [],
  plugins: [
    [require.resolve('@babel/plugin-transform-react-jsx'),
      { runtime: 'classic', pragma: 'React.createElement', pragmaFrag: 'React.Fragment' }],
    require.resolve('@babel/plugin-transform-modules-commonjs'),
  ],
}).code;

/**
 * Mount ThemeProvider against a given AsyncStorage.
 *
 * Returns a handle exposing the live context value, the REAL `colors` object
 * out of src/styles/theme.js (so an assertion can look at the palette that was
 * actually applied, not at a boolean), and the fake storage.
 */
function mountProvider({ storedTheme = null, storedUser = null } = {}) {
  const store = {};
  if (storedTheme !== null) store.blueview_theme = storedTheme;
  if (storedUser !== null) store.blueview_user = JSON.stringify(storedUser);

  const AsyncStorage = {
    getItem: (k) => Promise.resolve(Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
    setItem: (k, v) => { store[k] = v; return Promise.resolve(); },
    removeItem: (k) => { delete store[k]; return Promise.resolve(); },
  };

  // The real palette module — no stubs. applyTheme() mutates this `colors`
  // object in place, which is what the assertions below read.
  const theme = loadEsm('src/styles/theme.js');

  const { React, rt } = makeReact();
  const shim = (spec) => {
    if (spec === 'react') return React;
    if (spec === '@react-native-async-storage/async-storage') return AsyncStorage;
    if (spec === '../styles/theme') return theme;
    throw new Error(`ThemeContext imported '${spec}' — the harness has no stub for it.`);
  };
  const mod = { exports: {} };
  // eslint-disable-next-line no-new-func
  new Function('module', 'exports', 'require', COMPILED)(mod, mod.exports, shim);

  const ThemeProvider = mod.exports.ThemeProvider;
  if (typeof ThemeProvider !== 'function') throw new Error('ThemeContext.js no longer exports ThemeProvider');

  let value = null;
  function renderOnce() {
    rt.idx = 0;
    rt.effects = [];
    const tree = ThemeProvider({ children: null });
    if (!tree || !tree.__provider) throw new Error('ThemeProvider did not render a context Provider');
    value = tree.value;
    const queued = rt.effects;
    rt.effects = [];
    queued.forEach((f) => f());
  }
  function render() {
    let guard = 0;
    do {
      rt.dirty = false;
      renderOnce();
      guard += 1;
      if (guard > 50) throw new Error('render loop did not settle');
    } while (rt.dirty);
  }
  // Let the provider's async storage reads resolve, then re-render whatever
  // they queued. Several turns because the read chain is more than one await.
  async function flush() {
    for (let i = 0; i < 12; i += 1) await Promise.resolve();
    if (rt.dirty) render();
    for (let i = 0; i < 12; i += 1) await Promise.resolve();
    if (rt.dirty) render();
  }

  render();
  return {
    get value() { return value; },
    colors: theme.colors,
    store,
    flush,
    rerender: render,
  };
}

// The two palettes, read off the real module so a palette edit cannot make
// these assertions quietly meaningless.
const PALETTE = loadEsm('src/styles/theme.js');
PALETTE.applyTheme('light');
const LIGHT_BG = PALETTE.colors.background.middle;
PALETTE.applyTheme('dark');
const DARK_BG = PALETTE.colors.background.middle;

console.log('\n-- vacuity guard: the harness executes real code --');
ok(LIGHT_BG !== DARK_BG,
  `the two palettes differ (light ${LIGHT_BG} / dark ${DARK_BG}) — an assertion on background.middle can fail`);
{
  const h = mountProvider({ storedTheme: 'light', storedUser: { role: 'owner' } });
  ok(h.value && typeof h.value.toggleTheme === 'function',
    'the shipped ThemeProvider really mounted and exposed its context value');
}

const SITE_DEVICE = {
  id: 'sd1', email: 'site@test.local', role: 'site_device',
  site_mode: true, project_id: 'p1', project_name: 'Gate',
};
const OWNER = { id: 'u1', email: 'boss@test.local', role: 'owner', company_id: 'c1' };
const CP = { id: 'u2', email: 'cp@test.local', role: 'cp', company_id: 'c1' };

// Every block below is async; run them in sequence and report at the end.
(async () => {
  console.log('\n-- a site device boots LIGHT --');
  {
    const h = mountProvider({ storedTheme: null, storedUser: SITE_DEVICE });
    await h.flush();
    ok(h.value.isDark === false, 'cold boot, no stored preference: isDark is false');
    ok(h.colors.background.middle === LIGHT_BG,
      'and the LIGHT palette was actually applied — applyTheme ran, not just a flag');
  }

  console.log('\n-- and it stays light even if a dark preference is stored --');
  {
    // A tablet is provisioned by a person, on the tablet. Whatever that person
    // left in blueview_theme is not the inspector's choice, and the inspector
    // is the one standing in the sun.
    const h = mountProvider({ storedTheme: 'dark', storedUser: SITE_DEVICE });
    await h.flush();
    ok(h.value.isDark === false, 'stored "dark" does not override the pin');
    ok(h.colors.background.middle === LIGHT_BG, 'the light palette is applied anyway');
  }

  console.log('\n-- the role is recognised from either field AuthContext uses --');
  {
    const byRole = mountProvider({ storedTheme: null, storedUser: { id: 'x', role: 'site_device' } });
    await byRole.flush();
    ok(byRole.value.isDark === false, 'role === "site_device" alone is enough');

    const byFlag = mountProvider({ storedTheme: null, storedUser: { id: 'x', role: 'owner', site_mode: true } });
    await byFlag.flush();
    ok(byFlag.value.isDark === false, 'site_mode === true alone is enough (RouteGuard reads both)');
  }

  console.log('\n-- no other role is disturbed --');
  {
    const owner = mountProvider({ storedTheme: null, storedUser: OWNER });
    await owner.flush();
    ok(owner.value.isDark === true, 'an owner with no stored preference still boots DARK');
    ok(owner.colors.background.middle === DARK_BG, 'and the dark palette is what is applied');

    const cp = mountProvider({ storedTheme: null, storedUser: CP });
    await cp.flush();
    ok(cp.value.isDark === true, 'a CP with no stored preference still boots DARK');

    const anon = mountProvider({ storedTheme: null, storedUser: null });
    await anon.flush();
    ok(anon.value.isDark === true, 'no stored user at all (first launch, /login) still boots DARK');

    const chose = mountProvider({ storedTheme: 'light', storedUser: OWNER });
    await chose.flush();
    ok(chose.value.isDark === false, 'an owner who chose light still gets light');
    ok(chose.colors.background.middle === LIGHT_BG, 'and the light palette is applied');

    const choseDark = mountProvider({ storedTheme: 'dark', storedUser: CP });
    await choseDark.flush();
    ok(choseDark.value.isDark === true, 'a CP who chose dark still gets dark');
  }

  console.log('\n-- the pin is a pin, not a default --');
  {
    const h = mountProvider({ storedTheme: null, storedUser: SITE_DEVICE });
    await h.flush();
    ok(h.value.isPinnedLight === true, 'the context reports the device as pinned');
    // TWICE, deliberately. One toggle from an unpinned DARK start also lands on
    // light, so a single call would pass without the pin existing at all.
    await h.value.toggleTheme();
    h.rerender();
    await h.value.toggleTheme();
    h.rerender();
    ok(h.value.isDark === false, 'toggleTheme cannot take a gate tablet to dark');
    ok(h.store.blueview_theme === undefined,
      'and it writes no preference — nothing a later reader inherits');
  }
  {
    const h = mountProvider({ storedTheme: null, storedUser: OWNER });
    await h.flush();
    ok(h.value.isPinnedLight === false, 'a normal account is not pinned');
    await h.value.toggleTheme();
    h.rerender();
    ok(h.value.isDark === false, 'and its toggle still works (dark -> light)');
    ok(h.store.blueview_theme === 'light', 'and still persists the choice');
  }

  console.log('\n-- provisioning: a login is not a cold boot --');
  {
    // The tablet is set up by logging in, which does not restart the app. The
    // boot read above already ran against the PREVIOUS stored user (or none),
    // so without this the device stays dark for the whole session it was
    // installed in — the exact device, the exact day, that the report came from.
    const h = mountProvider({ storedTheme: null, storedUser: null });
    await h.flush();
    ok(h.value.isDark === true, 'before login it is a plain unauthenticated app: dark');
    const hasSetter = typeof h.value.setSiteDevice === 'function';
    ok(hasSetter, 'the provider exposes setSiteDevice for a consumer inside AuthProvider');
    if (hasSetter) {
      h.value.setSiteDevice(true);
      h.rerender();
    }
    ok(hasSetter && h.value.isDark === false, 'logging in as a site device flips it light without a restart');
    ok(hasSetter && h.colors.background.middle === LIGHT_BG, 'and applies the light palette');
    ok(hasSetter && h.value.isPinnedLight === true, 'and pins it');
  }
  {
    const h = mountProvider({ storedTheme: 'dark', storedUser: OWNER });
    await h.flush();
    ok(h.value.isDark === true, 'an owner session starts from its stored dark');
    const hasSetter = typeof h.value.setSiteDevice === 'function';
    if (hasSetter) {
      h.value.setSiteDevice(false);
      h.rerender();
    }
    ok(hasSetter && h.value.isDark === true, 'reporting "not a site device" never touches an existing choice');
    ok(hasSetter && h.value.isPinnedLight === false, 'and leaves it unpinned');
  }

  // ── The wiring, read off the AST ───────────────────────────────────────────
  //
  // setSiteDevice is dead code unless something inside AuthProvider calls it.
  // AppShell is the innermost consumer and already calls useTheme(); executing
  // it would mean executing expo-router, so this half is a source assertion —
  // deliberately, and it is the only one in the file.
  console.log('\n-- AppShell reports the live role to the theme --');
  {
    const raw = fs.readFileSync(path.join(FRONTEND, 'app', '_layout.jsx'), 'utf8');
    const ast = parser.parse(raw, { sourceType: 'module', plugins: ['jsx'] });

    let appShell = null;
    (function walk(n) {
      if (!n || typeof n !== 'object') return;
      if (n.type === 'FunctionDeclaration' && n.id && n.id.name === 'AppShell') appShell = n;
      for (const k of Object.keys(n)) {
        const v = n[k];
        if (Array.isArray(v)) v.forEach(walk);
        else if (v && typeof v.type === 'string') walk(v);
      }
    }(ast.program));
    ok(appShell !== null, 'AppShell is still a function declaration in app/_layout.jsx');

    const calls = [];
    const idents = [];
    (function walk(n) {
      if (!n || typeof n !== 'object') return;
      if (n.type === 'CallExpression' && n.callee && n.callee.type === 'Identifier') calls.push(n);
      if (n.type === 'Identifier') idents.push(n.name);
      for (const k of Object.keys(n)) {
        const v = n[k];
        if (Array.isArray(v)) v.forEach(walk);
        else if (v && typeof v.type === 'string') walk(v);
      }
    }(appShell || {}));

    const names = calls.map((c) => c.callee.name);
    ok(names.includes('useAuth'), 'AppShell reads the auth context');
    ok(names.includes('useTheme'), 'AppShell still reads the theme context');
    ok(names.includes('setSiteDevice'),
      'AppShell CALLS setSiteDevice — without this the provisioning path above is dead code');

    const effects = calls.filter((c) => c.callee.name === 'useEffect');
    const wiring = effects.find((e) => {
      const body = JSON.stringify(e.arguments[0] || {});
      return body.includes('setSiteDevice');
    });
    ok(!!wiring, 'the call lives inside a useEffect');
    if (wiring) {
      const deps = JSON.stringify(wiring.arguments[1] || {});
      ok(deps.includes('siteMode'),
        'and that effect re-runs when siteMode changes — otherwise it never fires on login');
    } else {
      ok(false, 'and that effect re-runs when siteMode changes (no effect found)');
    }
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed === 0 ? 0 : 1);
})().catch((e) => {
  console.error('\nHARNESS ERROR:', e && e.stack ? e.stack : e);
  process.exit(1);
});
