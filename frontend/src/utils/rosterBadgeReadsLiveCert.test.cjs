/**
 * WHAT THE WORKERS ROSTER SAYS ABOUT A CARD, EXECUTED.
 *
 * WHY THIS IS NOT A SOURCE SCAN. app/workers.jsx hardcoded two sentences --
 *
 *     if (sst_status === 'expired') reasons.push('Expired SST card');
 *     if (sst_status === 'unknown') reasons.push('Unknown SST card');
 *
 * -- read off the FROZEN check-in snapshot. Angel Lopez's card was repaired at
 * 12:33 and his 06:57 row went on saying "Unknown SST card" all day, because a
 * snapshot is by design never refreshed. A source scan can see that the screen
 * now imports sstFlagCopy; it cannot see WHICH fields the screen hands it, and
 * handing it the frozen `sst_unknown_reason` beside a live `review_reason` is
 * exactly how Juan's row would go on claiming an expiry problem he no longer
 * has. So the screen's real helpers are imported by name and run.
 *
 * THE LOADER FAILS LOUDLY if those exports go missing, because every assertion
 * below would otherwise evaluate `undefined` and quietly measure nothing --
 * the failure this repo has hit before (see sstCardFlagPaints.test.cjs).
 *
 * Run:  node src/utils/rosterBadgeReadsLiveCert.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');
const React = require('react');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN = path.join(FRONTEND, 'app', 'workers.jsx');

const HOST = { View: 'div', Text: 'span', Pressable: 'button', ScrollView: 'div', Image: 'img' };
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
    if (HOST[k]) return host(HOST[k]);
    return host('div');
  },
});
const REACT_PROBES = new Set([
  'prototype', 'contextType', 'contextTypes', 'childContextTypes',
  'propTypes', 'defaultProps', 'getDerivedStateFromProps',
  'getDerivedStateFromError',
]);
const anything = () => new Proxy(function stub() { return null; }, {
  get(_t, k) {
    if (k === '__esModule') return false;
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
    // sstFlagCopy is the thing whose vocabulary is under test, so it is loaded
    // FOR REAL. Everything else on the screen's import list -- router, theme,
    // the API client, AsyncStorage -- is inert here.
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

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); } else { failed += 1; console.log(`  FAIL  ${label}`); }
}
function eq(actual, want, label) {
  ok(actual === want, `${label}${actual === want ? '' : `\n          got: ${JSON.stringify(actual)}\n          want: ${JSON.stringify(want)}`}`);
}

// ── The loader's own guard ─────────────────────────────────────────────────
console.log('workers.jsx exports the helpers this file runs');
const NEEDED = ['checkinWarnings', 'checkinResolvedNote'];
let missing = false;
for (const n of NEEDED) {
  const have = typeof screen[n] === 'function';
  ok(have, `workers.jsx exports ${n} (the real helper, not a copy)`);
  if (!have) missing = true;
}
if (missing) {
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(1);
}

const { checkinWarnings, checkinResolvedNote } = screen;
const sst = (c) => checkinWarnings(c).find((w) => w.key !== 'No trade assigned') || null;

// ── The two production rows ────────────────────────────────────────────────
//
// Angel tapped at 10:57:53Z with an unreadable expiry; the repair landed at
// 12:33:56Z. Juan's class is still unconfirmed but his expiry is now on file
// -- and his FROZEN reason says `BOTH`, which is the half-truth the roster
// must stop repeating.

const ANGEL = {
  sst_status: 'unknown',           // frozen at 06:57, correct, never rewritten
  sst_unknown_reason: 'EXPIRY',
  sst_status_live: 'valid',        // SST_FULL / RUQ24T3LVF / 2031-03-01
  sst_review_reason: null,
};

const JUAN = {
  sst_status: 'unknown',
  sst_unknown_reason: 'BOTH',      // class AND expiry, as of 06:57
  sst_status_live: 'unknown',      // SST_UNSPECIFIED / TYPN6JCNJ1 / 2029-10-27
  sst_review_reason: 'CLASS_UNVERIFIED',
};

console.log('\nAngel Lopez — repaired since he tapped');
ok(sst(ANGEL) === null, 'no SST warning: there is nothing left for the CP to do');
eq(checkinResolvedNote(ANGEL), 'SST card flagged at check-in — resolved since',
  'the admitted-with-a-warning fact is kept, quietly and in the past tense');

console.log('\nJuan Lopez — still open, but only the class half');
const juan = sst(JUAN);
ok(juan !== null, 'still warns');
eq(juan && juan.label, 'SST card not confirmed', 'the title comes from sstFlagCopy');
eq(juan && juan.detail, 'The card class could not be confirmed.',
  'the LIVE review_reason names the open half');
ok(juan && !/expiry/i.test(juan.detail),
  'the frozen `BOTH` does NOT drag the expiry back in -- his expiry is on file');
ok(juan && juan.label !== 'Unknown SST card', 'the old one-size string is gone');
ok(checkinResolvedNote(JUAN) === null,
  'no resolved note on a row that is still flagged');

console.log('\nthe note is not invented where the two readings agree');
ok(checkinResolvedNote({ sst_status: 'valid', sst_status_live: 'valid' }) === null,
  'clean then, clean now');
ok(checkinResolvedNote({ sst_status: 'unknown', sst_status_live: 'unknown' }) === null,
  'flagged then, flagged now');
ok(checkinResolvedNote({ sst_status: 'valid', sst_status_live: 'expired' }) === null,
  'lapsed SINCE check-in is a warning, not a resolution');
eq(sst({ sst_status: 'valid', sst_status_live: 'expired' }).label, 'Expired SST card',
  '...and it is the live state that raises it');

// ── The offline / stale-cache path ─────────────────────────────────────────
console.log('\nno live fields — the honest fallback');
const CACHED = { sst_status: 'unknown', sst_unknown_reason: 'EXPIRY' };
const cached = sst(CACHED);
ok(cached !== null, 'a cached payload written before this change still warns');
eq(cached && cached.asOf, 'as recorded at check-in',
  'and is DATED, so a reason from 06:57 is never worn as current');
// Juan, not Angel: Angel raises nothing at all, so he could not tell an
// unlabelled badge from an absent one.
ok(!sst(JUAN).asOf, 'a live reading carries no such label');
ok(checkinResolvedNote(CACHED) === null,
  'with no live reading nothing can be called resolved');
eq(cached && cached.detail, 'The expiry date could not be confirmed.',
  'the frozen coarse reason is what the fallback has, and it uses it');

// ── Unchanged neighbours ───────────────────────────────────────────────────
console.log('\nwhat this change does not touch');
const trade = checkinWarnings({ needs_trade_assignment: true });
eq(trade.length, 1, 'a trade warning alone still produces exactly one row');
eq(trade[0].key, 'No trade assigned', 'and its wording is untouched');
eq(checkinWarnings({ sst_status_live: 'valid' }).length, 0,
  'a clean row raises nothing at all');
eq(checkinWarnings(null).length, 0, 'a null row raises nothing and does not throw');
eq(checkinWarnings(JUAN).map((w) => w.key).join('|'), 'SST card not confirmed',
  'the banner tally keys off a stable label, one bucket per reason');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
