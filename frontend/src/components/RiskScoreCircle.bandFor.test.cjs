/**
 * Unit tests for RiskScoreCircle.bandFor().
 *
 * This repo has NO JavaScript test runner (no jest/vitest, no "test"
 * script, no *.test.js infra — the only runnable suite is backend pytest).
 * RiskScoreCircle.jsx also can't be imported under bare node because it
 * pulls in react / react-native / react-native-svg at module top.
 *
 * So this harness reads the REAL component source, extracts the actual
 * `const BAND_* = {...}` definitions and the shipped `bandFor` function
 * body verbatim, evaluates just those (they are pure and reference no
 * imports), and asserts against them. If a threshold or band label ever
 * changes in the component, this test reflects it — it is not a hand-copy.
 *
 * Run:  node src/components/RiskScoreCircle.bandFor.test.cjs
 *
 * Regression under test: bandFor previously returned the GREEN band for a
 * null score (fail-reassuring) and the RED band for NaN. It must now return
 * the neutral PENDING band for null / undefined / NaN, while 0 — a real
 * score — must still return GREEN.
 */

const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, 'RiskScoreCircle.jsx');
const src = fs.readFileSync(file, 'utf8');

// Extract the BAND_* single-line object consts (no nested braces).
const bandConsts = [...src.matchAll(/^const BAND_\w+\s*=\s*\{[^}]*\};/gm)]
  .map((m) => m[0])
  .join('\n');
if (!/BAND_PENDING/.test(bandConsts)) {
  throw new Error('BAND_PENDING definition not found in source');
}

// Extract the exported bandFor function verbatim (body has no nested braces;
// the first newline-then-brace at column 0 is its closing brace).
const fnMatch = src.match(/export function bandFor\(score\)\s*\{[\s\S]*?\n\}/);
if (!fnMatch) throw new Error('bandFor() not found in source');
const fnSrc = fnMatch[0].replace('export function', 'function');

// eslint-disable-next-line no-eval
const bandFor = eval(`(function () { ${bandConsts}\n${fnSrc}\nreturn bandFor; })()`);

let failed = 0;
function check(name, actual, expected) {
  const ok = actual === expected;
  if (!ok) failed += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`);
}

// ── Missing / uncomputed → PENDING (never green) ──────────────────────────
check('null       -> Scoring', bandFor(null).label, 'Scoring');
check('undefined  -> Scoring', bandFor(undefined).label, 'Scoring');
check('NaN        -> Scoring', bandFor(NaN).label, 'Scoring');
check('non-numeric-> Scoring', bandFor('abc').label, 'Scoring');

// PENDING must not be any of the risk colors.
check('pending fg not green', bandFor(null).fg === '#22c55e', false);

// ── 0 is a REAL score — must be GREEN, not pending ────────────────────────
check('0          -> LOW RISK (green)', bandFor(0).label, 'LOW RISK');

// ── One value in each existing band (thresholds unchanged) ────────────────
check('20         -> LOW RISK',      bandFor(20).label, 'LOW RISK');
check('45         -> MODERATE RISK', bandFor(45).label, 'MODERATE RISK');
check('70         -> HIGH RISK',     bandFor(70).label, 'HIGH RISK');
check('90         -> CRITICAL RISK', bandFor(90).label, 'CRITICAL RISK');

// ── Boundaries (match backend score_band pins) ────────────────────────────
check('30         -> LOW RISK',      bandFor(30).label, 'LOW RISK');
check('31         -> MODERATE RISK', bandFor(31).label, 'MODERATE RISK');
check('60         -> MODERATE RISK', bandFor(60).label, 'MODERATE RISK');
check('61         -> HIGH RISK',     bandFor(61).label, 'HIGH RISK');
check('80         -> HIGH RISK',     bandFor(80).label, 'HIGH RISK');
check('81         -> CRITICAL RISK', bandFor(81).label, 'CRITICAL RISK');

console.log(`\n${failed === 0 ? 'ALL PASSED' : failed + ' FAILED'}`);
process.exit(failed === 0 ? 0 : 1);
