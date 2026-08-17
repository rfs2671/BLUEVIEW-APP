/**
 * tokens.js is a MEASURED scale, not a designed one: it claims to be a closed
 * set covering every style literal in use on the CP screens. A claim like that
 * rots the moment someone adds a 19th colour or a 14th font size, and nothing
 * in the app would notice — nothing imports tokens.js yet.
 *
 * So this harness re-runs the measurement against the REAL screen source on
 * every CI run and asserts BOTH directions:
 *
 *   COVERAGE — every literal measured in the screens has a token.
 *              Fails when a screen gains an off-scale value.
 *   HONESTY  — every token value is actually measured in the screens.
 *              Fails when someone "tidies" the scale by adding a value nobody
 *              uses, or rounds one that is in use. A token that ships zero
 *              visual change must not invent values.
 *
 * It also locks the three findings recorded in the tokens.js header, because
 * those are the justification for the file existing.
 *
 * The repo has no JS test runner (see RiskScoreCircle.bandFor.test.cjs) and
 * tokens.js is ESM importing semanticColors, so the module is loaded the way
 * this repo already loads ESM under bare node: read the source, strip the
 * module syntax, evaluate. Values are therefore the shipped ones, never a
 * hand-copy.
 *
 * Run:  node src/styles/tokens.test.cjs
 */
const fs = require('fs');
const path = require('path');

const STYLES = __dirname;
const FRONTEND = path.join(__dirname, '..', '..');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── Load tokens.js (ESM) under bare node ─────────────────────────────────────
function loadTokens() {
  const semanticSrc = fs.readFileSync(path.join(STYLES, 'semanticColors.js'), 'utf8');
  const waAt = semanticSrc.indexOf('export function withAlpha(');
  if (waAt < 0) throw new Error('withAlpha not found in semanticColors.js');
  const open = semanticSrc.indexOf('{', waAt);
  let d = 0, i = open;
  for (; i < semanticSrc.length; i += 1) {
    if (semanticSrc[i] === '{') d += 1;
    else if (semanticSrc[i] === '}') { d -= 1; if (d === 0) { i += 1; break; } }
  }
  const withAlphaSrc = semanticSrc.slice(waAt, i).replace('export function', 'function');

  let tokensSrc = fs.readFileSync(path.join(STYLES, 'tokens.js'), 'utf8');
  if (!/^import \{ withAlpha \} from '\.\/semanticColors';$/m.test(tokensSrc)) {
    throw new Error('tokens.js import line changed — this loader is stale');
  }
  tokensSrc = tokensSrc
    .replace(/^import \{ withAlpha \} from '\.\/semanticColors';$/m, '')
    .replace(/^export default [\s\S]*$/m, '')
    .replace(/^export const /gm, 'const ');

  // `shadow` is deliberately absent: tokens.js no longer exports one (the
  // single shadow it was extrapolated from left with the daily_jobsite
  // rebuild). Listing it here would throw a ReferenceError rather than let the
  // `!('shadow' in T)` assertion below do its job, so the loader collects only
  // the scales that exist and that assertion checks the removal.
  const names = ['palette', 'alpha', 'tint', 'MEASURED_TINTS', 'fontSize',
    'fontWeight', 'letterSpacing', 'radius', 'space', 'borderWidth',
    'opacity'];
  // eslint-disable-next-line no-new-func
  return new Function(`${withAlphaSrc}\n${tokensSrc}\nreturn { ${names.join(', ')} };`)();
}
const T = loadTokens();

// ── Re-measure the CP screens ────────────────────────────────────────────────
const FILES = fs.readdirSync(path.join(FRONTEND, 'app', 'logbooks'))
  .filter((f) => f.endsWith('.jsx'))
  .map((f) => path.join('app', 'logbooks', f))
  .concat([
    path.join('app', 'login.jsx'),
    path.join('app', 'settings.jsx'),
    path.join('app', 'documents.jsx'),
  ]);

const measured = {
  withAlphaPairs: new Map(), // "#hex@op" -> count
  rgbaPairs: new Map(),      // "#hex@op" -> count
  opaqueHex: new Map(),
  fontSize: new Map(),
  fontWeight: new Map(),
  letterSpacing: new Map(),
  radius: new Map(),
  space: new Map(),
  borderWidth: new Map(),
  opacity: new Map(),
  shadow: [],
};
const add = (m, k) => m.set(k, (m.get(k) || 0) + 1);
const rgbToHex = (r, g, b) => '#' + [r, g, b]
  .map((n) => Number(n).toString(16).padStart(2, '0')).join('');
// 0.10 and 0.1 are the same alpha; compare numerically, not as text.
const num = (s) => Number(s);

const SPACE_PROPS = ['padding', 'paddingHorizontal', 'paddingVertical', 'paddingTop',
  'paddingBottom', 'paddingLeft', 'paddingRight', 'margin', 'marginHorizontal',
  'marginVertical', 'marginTop', 'marginBottom', 'marginLeft', 'marginRight',
  'gap', 'rowGap', 'columnGap'];
const BORDER_W_PROPS = ['borderWidth', 'borderTopWidth', 'borderBottomWidth',
  'borderLeftWidth', 'borderRightWidth'];

function scanNumeric(src, props, bucket) {
  for (const p of props) {
    const re = new RegExp(`\\b${p}\\s*:\\s*(-?[0-9]+(?:\\.[0-9]+)?)\\b`, 'g');
    let m;
    while ((m = re.exec(src)) !== null) add(bucket, num(m[1]));
  }
}

for (const rel of FILES) {
  const src = fs.readFileSync(path.join(FRONTEND, rel), 'utf8');

  // withAlpha('#hex', op) — the sanctioned helper idiom. Counted SEPARATELY
  // from standalone literals; conflating the two inflates the colour debt from
  // 47 hand-written rgba() strings to 148.
  const waRe = /withAlpha\(\s*(['"])(#[0-9a-fA-F]{3,8})\1\s*,\s*([0-9.]+)\s*\)/g;
  let m;
  while ((m = waRe.exec(src)) !== null) {
    add(measured.withAlphaPairs, `${m[2].toLowerCase()}@${num(m[3])}`);
  }
  const stripped = src.replace(waRe, 'WITHALPHA_CALL');

  const hexRe = /(['"`])(#[0-9a-fA-F]{3,8})\1/g;
  while ((m = hexRe.exec(stripped)) !== null) add(measured.opaqueHex, m[2].toLowerCase());

  const rgbaRe = /(['"`])rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)\1/g;
  while ((m = rgbaRe.exec(stripped)) !== null) {
    add(measured.rgbaPairs, `${rgbToHex(m[2], m[3], m[4])}@${num(m[5])}`);
  }

  scanNumeric(src, ['fontSize'], measured.fontSize);
  scanNumeric(src, ['letterSpacing'], measured.letterSpacing);
  scanNumeric(src, ['borderRadius'], measured.radius);
  scanNumeric(src, ['opacity'], measured.opacity);
  scanNumeric(src, SPACE_PROPS, measured.space);
  scanNumeric(src, BORDER_W_PROPS, measured.borderWidth);

  const fwRe = /fontWeight\s*:\s*(['"])([^'"]+)\1/g;
  while ((m = fwRe.exec(src)) !== null) add(measured.fontWeight, m[2]);

  const shRe = /shadowColor\s*:\s*(['"])(#[0-9a-fA-F]{3,8})\1[\s\S]{0,220}?elevation\s*:\s*(\d+)/g;
  while ((m = shRe.exec(src)) !== null) measured.shadow.push({ color: m[2].toLowerCase(), elevation: num(m[3]) });
}

const sum = (m) => [...m.values()].reduce((a, b) => a + b, 0);

// ── Guard: the scanner itself must still be finding things ───────────────────
// Every assertion below is vacuously true against an empty measurement, so a
// regex that silently stops matching would turn this file green while
// measuring nothing.
ok(FILES.length === 16, `scanner reads 16 CP screens (found ${FILES.length})`);
// SCANNER-IS-ALIVE guards, not debt ceilings. Every assertion below is
// vacuously true against an empty measurement, so these exist to fail loudly
// if a regex silently stops matching. The thresholds track the migration
// DOWNWARDS as screens move onto the token file — 150 -> 120 with the
// toolbox_talk port — and are expected to keep falling as the remaining forms
// are ported. A threshold that never moves would be a debt ceiling, which is
// not what this is.
ok(sum(measured.fontSize) > 120,
  `scanner still finds fontSize literals (${sum(measured.fontSize)})`);
// LOWERED from 80 to 50 by the osha_log + scaffold_maintenance port, which
// moved two more screens onto the token file (88 -> 67). This is a
// SCANNER-IS-ALIVE guard, not a debt ceiling: its job is to fail loudly if a
// regex silently stops matching, because every assertion below is vacuously
// true against an empty measurement. The threshold tracks the migration
// downwards, and the direction of travel is the point — it is expected to keep
// falling as the remaining eight forms are ported.
// LOWERED again, 50 -> 40, by the concrete_operations + crane_operations port
// (67 -> 47). Same reason as the previous drop, and the direction of travel is
// still the point.
ok(sum(measured.withAlphaPairs) > 40,
  `scanner still finds withAlpha() calls (${sum(measured.withAlphaPairs)})`);
ok(sum(measured.opaqueHex) > 40,
  `scanner still finds opaque hex literals (${sum(measured.opaqueHex)})`);

// ── COVERAGE + HONESTY, per scale ────────────────────────────────────────────
function bothWays(label, measuredMap, tokenObj, normalize = (v) => v) {
  const tokenValues = new Set(Object.values(tokenObj).map(normalize));
  const measuredValues = [...measuredMap.keys()].map(normalize);

  const uncovered = measuredValues.filter((v) => !tokenValues.has(v));
  ok(uncovered.length === 0,
    `${label}: every measured value has a token${uncovered.length ? ` — MISSING ${JSON.stringify(uncovered)}` : ''}`);

  const measuredSet = new Set(measuredValues);
  const invented = [...tokenValues].filter((v) => !measuredSet.has(v));
  ok(invented.length === 0,
    `${label}: no token value is invented${invented.length ? ` — NOT IN USE ${JSON.stringify(invented)}` : ''}`);
}

bothWays('fontSize', measured.fontSize, T.fontSize);
bothWays('fontWeight', measured.fontWeight, T.fontWeight);
bothWays('letterSpacing', measured.letterSpacing, T.letterSpacing);
bothWays('radius', measured.radius, T.radius);
bothWays('space', measured.space, T.space);
bothWays('borderWidth', measured.borderWidth, T.borderWidth);
bothWays('opacity', measured.opacity, T.opacity);

// palette covers the opaque literals, matching on COLOUR (#fff === #ffffff).
const expand = (h) => {
  const s = String(h).toLowerCase().replace('#', '');
  return '#' + (s.length === 3 ? s.split('').map((c) => c + c).join('') : s.slice(0, 6));
};
// A palette colour is IN USE if it appears as a standalone opaque literal OR
// as the base of a tint. Checking only the former reported `black` as invented
// the moment the last bare '#000000' left the screens — while
// withAlpha('#000000', 0.6) still depended on it. Both are real uses.
const paletteInUse = new Map(measured.opaqueHex);
for (const m of [measured.withAlphaPairs, measured.rgbaPairs]) {
  for (const [k, c] of m) {
    const base = k.split('@')[0];
    paletteInUse.set(base, (paletteInUse.get(base) || 0) + c);
  }
}
bothWays('palette', paletteInUse, T.palette, expand);

// ── Tints: base × step must still reproduce every alpha colour in use ────────
const paletteByColour = new Map(
  Object.entries(T.palette).map(([k, v]) => [expand(v), k]),
);
const allTintPairs = new Map();
for (const [k, n] of measured.withAlphaPairs) allTintPairs.set(k, (allTintPairs.get(k) || 0) + n);
for (const [k, n] of measured.rgbaPairs) allTintPairs.set(k, (allTintPairs.get(k) || 0) + n);

const alphaValues = new Set(Object.values(T.alpha));
const unrepresentable = [];
for (const key of allTintPairs.keys()) {
  const [hex, op] = key.split('@');
  if (!paletteByColour.has(expand(hex)) || !alphaValues.has(Number(op))) unrepresentable.push(key);
}
ok(unrepresentable.length === 0,
  `tints: palette x alpha reproduces every alpha colour in use${unrepresentable.length ? ` — MISSING ${JSON.stringify(unrepresentable)}` : ''}`);

const unusedAlpha = [...alphaValues].filter((a) =>
  ![...allTintPairs.keys()].some((k) => Number(k.split('@')[1]) === a));
ok(unusedAlpha.length === 0,
  `alpha: no invented step${unusedAlpha.length ? ` — NOT IN USE ${JSON.stringify(unusedAlpha)}` : ''}`);

// MEASURED_TINTS is the migration checklist — it must name real tokens and
// must still describe the code it was measured from.
const badRef = T.MEASURED_TINTS.filter((e) =>
  !(e.base in T.palette) || !(e.step in T.alpha));
ok(badRef.length === 0,
  `MEASURED_TINTS: every entry names a real palette base + alpha step${badRef.length ? ` — BAD ${JSON.stringify(badRef)}` : ''}`);

const listed = new Set(T.MEASURED_TINTS.map((e) => `${expand(T.palette[e.base])}@${T.alpha[e.step]}`));
const actual = new Set([...allTintPairs.keys()].map((k) => {
  const [h, o] = k.split('@');
  return `${expand(h)}@${Number(o)}`;
}));
const missingFromList = [...actual].filter((k) => !listed.has(k));
const staleInList = [...listed].filter((k) => !actual.has(k));
ok(missingFromList.length === 0,
  `MEASURED_TINTS: lists every base@alpha in use${missingFromList.length ? ` — MISSING ${JSON.stringify(missingFromList)}` : ''}`);
ok(staleInList.length === 0,
  `MEASURED_TINTS: lists nothing that is gone${staleInList.length ? ` — STALE ${JSON.stringify(staleInList)}` : ''}`);

const viaCounts = T.MEASURED_TINTS.reduce((a, e) => {
  a[e.via] = (a[e.via] || 0) + e.uses; return a;
}, {});
ok(viaCounts.withAlpha === sum(measured.withAlphaPairs),
  `MEASURED_TINTS: withAlpha occurrence count matches source (${viaCounts.withAlpha} vs ${sum(measured.withAlphaPairs)})`);
ok(viaCounts.rgba === sum(measured.rgbaPairs),
  `MEASURED_TINTS: hand-written rgba() count matches source (${viaCounts.rgba} vs ${sum(measured.rgbaPairs)})`);
ok(viaCounts.rgba < viaCounts.withAlpha,
  'withAlpha idiom is counted apart from raw rgba() literals (the two must not be conflated)');

// ── Shadow: there is no longer one to measure ────────────────────────────────
// tokens.js used to carry `shadow.elevated`, extrapolated from the single
// shadow in the old daily_jobsite.jsx. The U1 rebuild of that screen dropped
// it, so the sample is gone and the token went with it — a measured scale may
// not keep shipping a value nothing measures.
ok(measured.shadow.length === 0,
  `no shadow remains across the CP screens (found ${measured.shadow.length})`);
ok(!('shadow' in T),
  'tokens.js no longer exports a shadow scale it cannot measure');

// ── The three findings recorded in the tokens.js header ──────────────────────
const themeSrc = fs.readFileSync(path.join(STYLES, 'theme.js'), 'utf8');
const sizesLine = themeSrc.match(/sizes:\s*\{([^}]*)\}/);
if (!sizesLine) throw new Error('typography.sizes not found in theme.js');
const themeSizes = new Set(
  [...sizesLine[1].matchAll(/(\w+)\s*:\s*(\d+)/g)].map((m) => Number(m[2])),
);

// (a) 12 and 13 are the two most-used sizes and neither has a theme token.
const ranked = [...measured.fontSize.entries()].sort((a, b) => b[1] - a[1]);
const topTwo = ranked.slice(0, 2).map((e) => e[0]).sort((a, b) => a - b);
ok(topTwo.length === 2 && topTwo[0] === 12 && topTwo[1] === 13,
  `finding (a): 12 and 13 are the two most-used font sizes (got ${JSON.stringify(topTwo)})`);
// RESOLVED by U1: `fine: 12` and `dense: 13` were added to theme.js
// typography.sizes, which is what finding (a) asked for. The ranking assertion
// above still stands (they remain the two most-used sizes, because the other
// fifteen screens still write them as literals), but the gap that made them
// untokenisable is closed. Flipped rather than deleted, so the fix cannot be
// silently reverted.
ok(themeSizes.has(12) && themeSizes.has(13),
  'finding (a) RESOLVED: 12 and 13 now both have entries in theme typography.sizes');

// (b) typography.sizes.xl (24) is referenced nowhere in app/ or src/.
function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(js|jsx)$/.test(e.name)) out.push(p);
  }
  return out;
}
const allSource = [...walk(path.join(FRONTEND, 'app')), ...walk(path.join(FRONTEND, 'src'))]
  .filter((p) => path.resolve(p) !== path.resolve(path.join(STYLES, 'theme.js')));
// Comments are stripped first: tokens.js DOCUMENTS this finding in prose, and
// a prose mention is not a reference. Only real code counts.
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
const xlRefs = allSource.filter((p) => /sizes\.xl\b/.test(stripComments(fs.readFileSync(p, 'utf8'))));
// RESOLVED by U1: sizes.xl is the daily-jobsite stepper's primary-action label,
// which the "one primary action, largest element on screen" rule requires to be
// the biggest type on the page. It is no longer a dead token.
ok(xlRefs.length > 0,
  `finding (b) RESOLVED: typography.sizes.xl (24) now has real callers (${xlRefs.length})`);
ok(themeSizes.has(24), 'finding (b): theme.js still defines sizes.xl = 24');

// (c) how many of the distinct opaque literals already have an EXACT-STRING
// hex token in theme.js. The research claim was 9 of 18; it is 5.
const themeHexes = new Set(
  [...themeSrc.matchAll(/:\s*'(#[0-9a-fA-F]{3,8})'/g)].map((m) => m[1].toLowerCase()),
);
const distinctOpaque = [...measured.opaqueHex.keys()];
const exactMatches = distinctOpaque.filter((h) => themeHexes.has(h));
const colourMatches = distinctOpaque.filter((h) => themeHexes.has(expand(h))
  || [...themeHexes].some((t) => expand(t) === expand(h)));
// Was 18 before U1, then 17 (the rebuild removed the last standalone '#000000'
// from the CP screens; it survives only as a tint base). Now 15: the osha_log
// and scaffold_maintenance port took '#22d3ee' and '#ef4444' with it, and both
// are gone from the palette for the same reason.
ok(distinctOpaque.length === 15,
  `finding (c): 15 distinct opaque hex literals (got ${distinctOpaque.length})`);
// Was 5. The U1 restyle added `outdoor.accent: '#60a5fa'` to theme.js — the
// blue the app's count and status pills are drawn in — so that literal now has
// a token where it did not before. The finding's POINT is unchanged (the
// original research claimed 9, and it was never 9); the count moved because
// one more literal became tokenised, which is the direction of travel.
// Was 6 of 17. Now 5 of 15: '#ef4444' was one of the six (an exact match for
// theme state.critical) and left the measured set with osha_log. The finding's
// POINT is unchanged — the original research claimed 9, and it was never 9.
ok(exactMatches.length === 5,
  `finding (c): 5 of 15 have an exact-string token in theme.js, NOT 9 (got ${exactMatches.length}: ${exactMatches.sort().join(', ')})`);
ok(colourMatches.length === 6,
  `finding (c): 6 of 15 match by colour once #fff is expanded (got ${colourMatches.length})`);

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
