/**
 * IT ACTUALLY PAINTS. Both items, rendered.
 *
 * WHY THIS FILE EXISTS AND WHY IT IS NOT A SOURCE SCAN. Everything else that
 * guards these screens parses source. Mount smoke does execute a component, but
 * it asks ONE question -- did the route mount without throwing -- and a
 * component that returns null passes it. Between the two, a warning line that
 * resolves to `undefined`, to '', or to a branch that returns null is invisible
 * to every gate in this repo:
 *
 *     the JS suite   sees the string in the source and passes
 *     mount smoke    sees no console error and passes
 *     the CP         sees an empty box next to a man holding a card
 *
 * So this executes the REAL components out of app/logbooks/preshift_signin.jsx
 * -- not a copy of them -- through react-dom/server, and asserts the words are
 * in the output. `react-native` is stubbed to host elements because the
 * question is which TEXT the component chooses, not how a View lays out; the
 * conditional logic under test is the component's own and is not stubbed.
 *
 * A COPY OF THE JSX HERE WOULD PROVE NOTHING. That is the failure this repo has
 * hit repeatedly -- an assertion that matched a duplicate rather than the
 * shipped code -- so the components are imported by name from the screen file
 * and the loader THROWS if either export is missing.
 *
 * Run:  node src/utils/sstCardFlagPaints.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'logbooks', 'preshift_signin.jsx');

// ── A thin react-native, and nothing else thin ─────────────────────────────
const HOST = {
  View: 'div', Text: 'span', Pressable: 'button', ScrollView: 'div',
  TextInput: 'input', Image: 'img', ActivityIndicator: 'div',
};
function host(tag) {
  const C = ({ children }) => React.createElement(tag, null, children);
  C.displayName = tag;
  return C;
}
const RN = new Proxy({}, {
  get(_t, k) {
    if (k === '__esModule') return false;
    if (k === 'StyleSheet') return { create: (o) => o, flatten: (o) => o, hairlineWidth: 1 };
    if (k === 'Platform') return { OS: 'web', select: (o) => o.web || o.default };
    if (k === 'Dimensions') return { get: () => ({ width: 400, height: 800 }), addEventListener: () => ({ remove() {} }) };
    if (k === 'Keyboard') return { dismiss() {}, addListener: () => ({ remove() {} }) };
    if (HOST[k]) return host(HOST[k]);
    return host('div');
  },
});
// Everything else on the screen's import list -- router, toasts, theme, the API
// client -- is inert here. Only sstFlagCopy is loaded for real, because it is
// the thing under test.
const REACT_PROBES = new Set([
  'prototype', 'contextType', 'contextTypes', 'childContextTypes',
  'propTypes', 'defaultProps', 'getDerivedStateFromProps',
  'getDerivedStateFromError',
]);
const anything = () => new Proxy(function stub() { return null; }, {
  get(_t, k) {
    if (k === '__esModule') return false;
    // React decides class-vs-function from `prototype.isReactComponent` and
    // then probes the legacy class API; a proxy that answers EVERY property
    // makes each stub look like a half-built class component and floods stderr
    // with dev warnings. Noise in a test file is how a test file stops being
    // read, so the probes are answered honestly: absent.
    if (REACT_PROBES.has(k)) return undefined;
    return anything();
  },
  apply() { return null; },
});

const cache = new Map();
function load(abs) {
  if (cache.has(abs)) return cache.get(abs);
  const { code } = babel.transformSync(fs.readFileSync(abs, 'utf8'), {
    filename: abs,
    presets: [[require.resolve('@babel/preset-react'), { runtime: 'classic' }]],
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const mod = { exports: {} };
  const req = (spec) => {
    if (spec === 'react') return React;
    if (spec === 'react-native') return RN;
    if (spec.startsWith('.') && /sstFlagCopy$/.test(spec)) {
      const base = path.resolve(path.dirname(abs), spec);
      for (const c of [base, `${base}.js`, `${base}.jsx`]) {
        if (fs.existsSync(c) && fs.statSync(c).isFile()) return load(c);
      }
      throw new Error(`sstFlagCopy not resolvable from ${abs}`);
    }
    return anything();
  };
  new Function('module', 'exports', 'require', code)(mod, mod.exports, req);
  cache.set(abs, mod.exports);
  return mod.exports;
}

const screen = load(SCREEN);
const copy = load(path.join(__dirname, 'sstFlagCopy.js'));

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// THE LOADER'S OWN GUARD. If the screen stops exporting these, every assertion
// below would render `undefined` and this file must fail loudly rather than
// quietly measuring nothing.
ok(typeof screen.SstFlagLines === 'function',
  'preshift_signin.jsx exports SstFlagLines (the real component, not a copy)');
ok(typeof screen.CardCheckLines === 'function',
  'preshift_signin.jsx exports CardCheckLines (the real component, not a copy)');
if (typeof screen.SstFlagLines !== 'function' || typeof screen.CardCheckLines !== 'function') {
  console.log(`\n${passed} passed, ${failed + 1} failed`);
  process.exit(1);
}

const paint = (C, props) => renderToStaticMarkup(React.createElement(C, props));
// Text only: the words a CP reads, with the element scaffolding removed.
const words = (html) => html.replace(/<[^>]*>/g, '').replace(/&#x27;/g, "'")
  .replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#x2F;/g, '/');

// ── ITEM 2: the four production rows paint four different sentences ────────
console.log('\nITEM 2 — four states, four sentences, all actually painted');

const FOUR = {
  'SST_LIMITED / XCAS2DYB8G / CLASS_UNVERIFIED (dead scheme)':
    { sstStatus: 'unknown', reviewReason: 'CLASS_UNVERIFIED', unknownReason: null },
  'SST_UNSPECIFIED / no card number / CLASS_UNVERIFIED (nothing read)':
    { sstStatus: 'unknown', reviewReason: 'CLASS_UNVERIFIED', unknownReason: 'BOTH' },
  'SST_UNSPECIFIED / TYPN6JCNJ1 / EXPIRY_UNPARSEABLE':
    { sstStatus: 'unknown', reviewReason: 'EXPIRY_UNPARSEABLE', unknownReason: 'BOTH' },
  'SST_FULL / 4YU1RY8KKM / colour-derived class':
    { sstStatus: 'unknown', reviewReason: 'CLASS_FROM_COLOR_UNCONFIRMED', unknownReason: null },
};

const painted = [];
for (const [label, props] of Object.entries(FOUR)) {
  const text = words(paint(screen.SstFlagLines, props));
  painted.push(text);
  const want = copy.sstFlagCopy(props);
  ok(text.includes(want.title), `${label}: title painted`);
  ok(text.includes(want.detail), `${label}: REASON painted -- "${want.detail}"`);
  ok(text.replace(/\s+/g, '').length > 20,
    `${label}: the component did not render an empty box`);
}
ok(new Set(painted).size === 4,
  `the four rows paint four DIFFERENT texts (${new Set(painted).size} distinct of 4)`);
ok(!painted.some((t) => t.includes('Unknown SST card')),
  'the old one-size string is gone from every one of them');

console.log('\nITEM 2 — the other statuses');
ok(words(paint(screen.SstFlagLines, { sstStatus: 'expired' })).includes('Expired SST card'),
  'expired still paints its own line');
const missing = words(paint(screen.SstFlagLines, { sstStatus: 'missing' }));
ok(missing.includes('No SST card on file'),
  'MISSING reaches the screen -- it never used to enter the flag map at all');
ok(paint(screen.SstFlagLines, { sstStatus: 'valid' }) === '',
  'a valid card paints nothing');
ok(paint(screen.SstFlagLines, {}) === '',
  'no status paints nothing');

// ── ITEM 1: the attestation ────────────────────────────────────────────────
console.log('\nITEM 1 — the card check, painted');

const openHtml = words(paint(screen.CardCheckLines, {
  cardNumber: '4YU1RY8KKM', open: true,
}));
ok(openHtml.includes(copy.CARD_CHECK_STATEMENT),
  'the ruled statement is painted verbatim');
ok(openHtml.includes(copy.cardCheckScopeNote('4YU1RY8KKM')),
  'the scope note is painted, WITH the actual card number in it');
ok(openHtml.includes('4YU1RY8KKM'),
  'the card number is SHOWN, not merely stored');
ok(openHtml.includes(copy.CARD_CHECK_AFFIRM), 'the affirm control is painted');
ok(openHtml.includes(copy.CARD_CHECK_REFUSE),
  'THE REFUSAL PATH IS PAINTED -- if the only way out is to affirm, the '
  + 'attestation is worthless');

const closed = words(paint(screen.CardCheckLines, { cardNumber: '4YU1RY8KKM' }));
ok(closed.includes(copy.CARD_CHECK_AFFIRM),
  'the opener is painted before the dialog is open');
ok(!closed.includes(copy.CARD_CHECK_STATEMENT),
  'and the statement is not affirmed by a single tap -- it is a confirm step');

const noNumber = words(paint(screen.CardCheckLines, { cardNumber: null }));
ok(!noNumber.includes(copy.CARD_CHECK_AFFIRM),
  'NO CARD NUMBER, NO CONTROL -- a clearance keyed on null would carry to '
  + 'every future card');
ok(noNumber.includes(copy.CARD_CHECK_NO_NUMBER),
  'and the screen says why the control is absent rather than showing nothing');
ok(!words(paint(screen.CardCheckLines, { cardNumber: '' })).includes(copy.CARD_CHECK_AFFIRM),
  'an empty card number is the same as none');

const done = words(paint(screen.CardCheckLines, {
  cardNumber: '4YU1RY8KKM',
  checkedByName: 'Carl CP',
  checkedAt: '2026-09-03T14:20:00Z',
  checkedNumber: '4YU1RY8KKM',
}));
ok(done.includes('Carl CP') && done.includes('2026-09-03') && done.includes('4YU1RY8KKM'),
  'once recorded it paints WHO, WHEN and AGAINST WHICH CARD NUMBER');
ok(!done.includes(copy.CARD_CHECK_AFFIRM),
  'and stops offering the control it has already been given');

// THE CARD NUMBER CHANGED SINCE THE CHECK. The clearance does not carry, and
// the screen must not claim it does.
const stale = words(paint(screen.CardCheckLines, {
  cardNumber: 'NEWCARD123',
  checkedByName: 'Carl CP',
  checkedAt: '2026-09-03T14:20:00Z',
  checkedNumber: '4YU1RY8KKM',
}));
ok(stale.includes(copy.CARD_CHECK_AFFIRM),
  'a check recorded against a DIFFERENT card number re-offers the control');
ok(!stale.includes('Card checked by Carl CP'),
  'and does not report the stale check as if it still stood');

// NEVER these words, anywhere in what is painted.
const BANNED = /\b(approve|dismiss|ignore|override|acknowledge)\b/i;
for (const [label, html] of [['open', openHtml], ['closed', closed], ['done', done]]) {
  ok(!BANNED.test(html),
    `${label}: never approve/dismiss/ignore/override/acknowledge`);
}

// ── The three gates that live in renderWorkerFlags ─────────────────────────
// SOURCE ASSERTIONS, AND LABELLED AS SUCH. renderWorkerFlags is a closure over
// component state, so it cannot be rendered from here the way the two
// components above can. These pin the decisions that are made OUTSIDE them and
// that no amount of rendering a leaf would catch. Comments are stripped first
// for the reason recorded in fix1FlaggedWorkerSurfaces.test.cjs: prose about a
// rule is not the rule.
console.log('\nthe gates in renderWorkerFlags (source, not render)');

const screenCode = fs.readFileSync(SCREEN, 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !/^\s*(\/\/|\*)/.test(l)).join('\n');

ok(/canAct && canCardCheck && f\.sst_row_known \?/.test(screenCode),
  'the card check is offered ONLY for a worker the flagged endpoint actually '
  + 'returned — an absent row must not be reported as "no card number recorded"');
ok(/const canCardCheck = f\.sst_status === 'unknown';/.test(screenCode),
  "and only where the CARD is what is in doubt — looking at an expired card "
  + 'does not renew it');
ok(/!sstReviewable \? null :/.test(screenCode),
  'naming a third status on screen did not hand it an approve/deny it never had');
ok((screenCode.match(/styles=\{styles\}/g) || []).length === 2,
  'both components are handed the per-render styles (this screen themes per '
  + 'render; a module-level `styles` here is the "styles is not defined" crash '
  + 'mount smoke was written for)');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
