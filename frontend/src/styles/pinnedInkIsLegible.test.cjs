/**
 * A COMPONENT THAT BRINGS ITS OWN PALETTE ONTO A PINNED CANVAS IS INVISIBLE.
 *
 * THE REPORT. On the superintendent log's sign step, CompetentPersonPicker's
 * list rendered WHITE ON WHITE: the search placeholder, all three names, their
 * role/email lines and "Enter a competent person not on this list" were
 * unreadable. Only the static paragraph below the card — a `noteText` styled
 * from the screen's own stylesheet — was legible, which is the tell.
 *
 * ── THE MECHANISM, AND IT IS NOT "SOMEBODY PICKED A BAD COLOUR" ─────────────
 *
 * The twelve logbook editors are PINNED to the light `outdoor` palette. They
 * call `buildStepperStyles()`, which takes no argument on purpose, and
 * LogbookStepper renders `<AnimatedBackground pinned>` unconditionally: a
 * compliance log is filled outdoors in direct sun, where a dark card is
 * unreadable whatever theme the CP set on his own phone.
 *
 * The app's default theme is DARK (`useState(true)` in ThemeContext). So any
 * child of a pinned screen that reaches for `useTheme()` paints DARK-MODE INK,
 * which is near-white, onto a card whose fill is near-white.
 *
 * ── THE CENSUS IS WHY THIS FILE IS A LOOP AND NOT AN ASSERTION ──────────────
 *
 * Four components call `useTheme()` anywhere in the import graph of the twelve
 * pinned screens. THREE WERE ALREADY RIGHT — AnimatedBackground and
 * SignaturePad both carry a `pinned` prop for exactly this, and Toast paints
 * its own opaque surface and never borrows the card's. One was wrong.
 *
 * That ratio is the whole argument for a census rather than a fix: the
 * convention existed, was documented in two components, and the fourth arrived
 * later from a screen where it looked correct. The next component to cross
 * that boundary will arrive the same way, and a one-line assertion naming
 * CompetentPersonPicker would not catch it.
 *
 * ── THE GAP WAS ALREADY WRITTEN DOWN, IN THE GATE THAT SHOULD HAVE CAUGHT IT ─
 *
 * `scripts/find-unpinned-palette-keys.cjs` runs in CI and is about exactly this
 * palette. It says, in its own docstring:
 *
 *     WHAT IT DOES NOT CATCH, stated so nobody trusts it too far: a live-themed
 *     SHARED COMPONENT mounted inside a pinned screen. That crosses a module
 *     boundary this script does not follow. SignaturePad and Toast are exactly
 *     that case and are AUDITED BY HAND.
 *
 * So this was not a blind spot — it was a KNOWN one, honestly declared, with a
 * hand audit standing in for the check. The hand audit was correct on the day
 * it was written and covered the two components that existed then. The picker
 * arrived on this screen months later, from a correctly-themed screen where it
 * looked right, and no hand audit ran again.
 *
 * THIS FILE FOLLOWS THE MODULE BOUNDARY, which is the thing that script says it
 * does not do. The two are complementary and neither replaces the other: that
 * one asks whether every pinned key is painted, this one asks whether anything
 * mounted on a pinned canvas paints something else.
 *
 * ── IT MEASURES THE CONTRAST RATHER THAN NAMING A COLOUR ────────────────────
 *
 * `ok('the names are dark')` would pass on any dark-ish hex, including one
 * nobody checked against this card's actual fill. The surface here is a
 * gradient over a gradient — two Card stops composited over three page stops,
 * six surfaces — so the arithmetic is done and the worst of the six is the
 * verdict. Measured, per the operator: do not eyeball it.
 *
 * Run:  node src/styles/pinnedInkIsLegible.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.resolve(__dirname, '..', '..');
let failures = 0;
function ok(label, cond, hint) {
  if (cond) { console.log(`  ok   ${label}`); return; }
  failures += 1;
  console.log(`  FAIL ${label}${hint ? `\n         ${hint}` : ''}`);
}
const read = (p) => fs.readFileSync(p, 'utf8');

// ── WCAG 2.1 contrast, over composited translucent surfaces ────────────────
const parse = (c) => {
  const m = /rgba?\(([^)]+)\)/.exec(c);
  if (m) {
    const p = m[1].split(',').map((x) => parseFloat(x.trim()));
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  }
  const s = c.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(s.slice(i, i + 2), 16)).concat([1]);
};
const over = (fg, bg) => [0, 1, 2]
  .map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3])).concat([1]);
const lum = (c) => {
  const f = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
};
const contrast = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (hi + 0.05) / (lo + 0.05);
};

// ── THE SURFACE, READ OUT OF theme.js RATHER THAN RETYPED ──────────────────
//
// A hard-coded '#ffffff' here would keep passing after somebody changed the
// card fill, which is the failure mode §12 of the check harness names: a check
// whose SUBJECT is wrong fails toward "fine".
const THEME = read(path.join(FRONTEND, 'src', 'styles', 'theme.js'));
const tok = (name) => {
  const m = new RegExp(`^\\s*${name}:\\s*'([^']+)'`, 'm').exec(
    THEME.slice(THEME.indexOf('export const outdoor = {')),
  );
  return m && m[1];
};
const CARD = ['cardTop', 'cardBottom'].map(tok);
const PAGE = ['backgroundStart', 'backgroundMiddle', 'backgroundEnd'].map(tok);

console.log('\nthe surface, read out of theme.js');
ok(`the card gradient resolved (${CARD.join(' -> ')})`, CARD.every(Boolean),
  'the `outdoor` block moved and this file is measuring against nothing');
ok(`the page gradient resolved (${PAGE.join(' -> ')})`, PAGE.every(Boolean));

const SURFACES = [];
for (const p of PAGE) for (const c of CARD) SURFACES.push(over(parse(c), parse(p)));
const worstOn = (ink) => Math.min(...SURFACES.map(
  (s) => contrast(over(parse(ink), s), s)));

// ── THE MEASUREMENT ────────────────────────────────────────────────────────
//
// Both directions, because only the pair proves the fix did something. The
// dark-theme values are what the picker ACTUALLY painted before `pinned`.
console.log('\nthe measurement');

const DARK_INK = { primary: 'rgba(255, 255, 255, 0.9)', secondary: 'rgba(255, 255, 255, 0.6)' };
for (const [k, v] of Object.entries(DARK_INK)) {
  const r = worstOn(v);
  ok(`dark-theme text.${k} really is invisible here (${r.toFixed(2)}:1)`, r < 1.5,
    'if this now passes 1.5:1 the palettes changed and the premise of this '
    + 'whole file needs re-reading — it does not mean the screen is fixed');
}

const PINNED_INK = { text: 4.5, textSoft: 4.5, textDim: 4.5 };
for (const [name, bar] of Object.entries(PINNED_INK)) {
  const v = tok(name);
  const r = v ? worstOn(v) : 0;
  ok(`outdoor.${name} clears AA on the worst of ${SURFACES.length} surfaces `
    + `(${r.toFixed(2)}:1)`, r >= bar,
    `${v} measures ${r.toFixed(2)}:1 against the darkest card-over-page stop`);
}

// ── THE CENSUS ─────────────────────────────────────────────────────────────
console.log('\nthe census');

function resolve(from, spec) {
  if (!spec.startsWith('.')) return null;
  const base = path.resolve(path.dirname(from), spec);
  const tries = [`${base}.jsx`, `${base}.js`, `${base}.tsx`,
    path.join(base, 'index.jsx'), path.join(base, 'index.js')];
  for (const c of tries) if (fs.existsSync(c) && fs.statSync(c).isFile()) return c;
  return null;
}

// Every editor that pins its chrome. Derived, not listed: a thirteenth editor
// added next month is in this set the day it calls buildStepperStyles().
const LOGBOOKS = path.join(FRONTEND, 'app', 'logbooks');
const PINNED_SCREENS = fs.readdirSync(LOGBOOKS)
  .filter((f) => /\.jsx?$/.test(f))
  .map((f) => path.join(LOGBOOKS, f))
  .filter((f) => read(f).includes('buildStepperStyles'));

ok(`the pinned editors were found (${PINNED_SCREENS.length})`,
  PINNED_SCREENS.length >= 10,
  'app/logbooks moved, or buildStepperStyles was renamed — this census is '
  + 'walking an empty set and everything below it passes for free');

const reach = new Map();          // component file -> [screen basenames]
for (const screen of PINNED_SCREENS) {
  const seen = new Set(); const stack = [screen];
  while (stack.length) {
    const f = stack.pop();
    if (seen.has(f)) continue;
    seen.add(f);
    let src; try { src = read(f); } catch (e) { continue; }
    for (const m of src.matchAll(/from\s+'(\.[^']+)'/g)) {
      const r = resolve(f, m[1]);
      if (r && !seen.has(r)) stack.push(r);
    }
  }
  for (const f of seen) {
    if (f === screen || !/useTheme\s*\(/.test(read(f))) continue;
    if (!reach.has(f)) reach.set(f, []);
    reach.get(f).push(path.basename(screen, path.extname(screen)));
  }
}

const rel = (f) => path.relative(FRONTEND, f).replace(/\\/g, '/');
ok(`components reaching for useTheme() under a pinned screen (${reach.size})`,
  reach.size >= 4,
  'the import walk found fewer than the four measured — it is resolving '
  + 'nothing and the rule below is vacuous');

// TOAST IS EXEMPT, NAMED, WITH THE REASON. It floats ABOVE the card on its own
// opaque `bgColor`, chosen per theme and derived from colors.state.* — it never
// borrows the surface underneath, so dark ink on a dark toast is correct.
// Exempting it by name and in writing is the alternative to weakening the rule
// until it stops catching anything.
const EXEMPT = { 'src/components/Toast.js': 'paints its own opaque surface' };

for (const [f, screens] of [...reach].sort()) {
  const name = rel(f);
  if (EXEMPT[name]) { console.log(`  --   ${name} exempt: ${EXEMPT[name]}`); continue; }
  const src = read(f);
  ok(`${name} offers a pinned palette`, /pinned\s*=\s*false/.test(src),
    `it calls useTheme() and is mounted by ${screens.length} pinned editor(s) `
    + `(${screens.slice(0, 3).join(', ')}). On a dark-theme phone that is `
    + 'near-white ink on a near-white card.');
  ok(`${name} does not read the live palette when pinned`,
    /pinned \? PINNED_COLORS : liveColors|pinned \? false : themeIsDark|pinned$/m.test(src)
      || /colors = pinned \?/.test(src),
    'the prop exists but nothing branches on it');
}

// ── AND THE ONE MOUNT THAT WAS MISSING IT ──────────────────────────────────
//
// The rule above is about the COMPONENT offering the prop. This is about the
// SCREEN passing it, which is the half that was actually wrong: the picker
// would have offered `pinned` all day and still rendered white if the
// superintendent log never passed it.
console.log('\nevery mount inside a pinned editor passes it');

for (const screen of PINNED_SCREENS) {
  const src = read(screen);
  for (const tag of ['CompetentPersonPicker', 'WorkerPicker', 'SignaturePad']) {
    const mounts = (src.match(new RegExp(`<${tag}[\\s>]`, 'g')) || []).length;
    if (!mounts) continue;
    const pinnedMounts = (src.match(
      new RegExp(`<${tag}[^>]*?\\bpinned\\b`, 'gs'),
    ) || []).length;
    ok(`${path.basename(screen)}: all ${mounts} <${tag}> mount(s) are pinned`,
      pinnedMounts === mounts,
      `${pinnedMounts} of ${mounts} pass \`pinned\` — an unpinned one paints `
      + 'dark-theme ink onto the outdoor card');
  }
}

// ── THE PLACEHOLDER TOKEN THAT WAS NEVER IN A PALETTE ──────────────────────
//
// `colors.text.tertiary` was read for placeholderTextColor. Neither `_dark`
// nor `_light` declares it, so the prop received `undefined` on both screens
// in both themes and fell through to whatever the platform chose. Found while
// building the table above; asserted here because a key that does not exist
// resolves silently and reads exactly like one that does.
console.log('\nno component reads a text token that is not in the palette');

const TEXT_KEYS = new Set();
for (const m of THEME.matchAll(/^\s{4}(primary|secondary|muted|subtle):/gm)) {
  TEXT_KEYS.add(m[1]);
}
ok(`the palette's text keys were read (${[...TEXT_KEYS].sort().join(', ')})`,
  TEXT_KEYS.size >= 4);

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== 'node_modules') walk(full, out); }
    else if (/\.(jsx|js)$/.test(e.name) && !/\.test\.(cjs|js)$/.test(e.name)) out.push(full);
  }
  return out;
}
const ALL = [...walk(path.join(FRONTEND, 'app')), ...walk(path.join(FRONTEND, 'src'))];
ok(`the walk found the source tree (${ALL.length} files)`, ALL.length >= 100);

// A READ WITH AN EXPLICIT FALLBACK IS NOT A DEFECT, and the census is what
// showed why the rule needs that clause. `app/onboarding.jsx` reads
// `colors.text.inverse || '#fff'` — a key in neither palette, on a badge over
// `colors.primary`, where '#fff' is the right answer and the author plainly
// knew the key was optional. Failing on it would make this check cost more
// than it catches, and the cure would be to delete the check.
//
// The defect is an undefined value reaching a style prop SILENTLY. So the
// match requires that no `||` follows.
// SCANNED OVER CODE, NOT PROSE. The first run of this rule failed on
// CompetentPersonPicker — on the paragraph THIS CHANGE ADDED explaining that
// `colors.text.tertiary` is in neither palette. A check that a file cannot
// document without breaking is a check people delete.
const stripComments = (src) => src
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(^|[^:])\/\/[^\n]*/g, '$1');

const ghosts = [];
for (const f of ALL) {
  for (const m of stripComments(read(f)).matchAll(/colors\.text\.([A-Za-z0-9_]+)(\s*\|\|)?/g)) {
    if (!TEXT_KEYS.has(m[1]) && !m[2]) ghosts.push(`${rel(f)}: colors.text.${m[1]}`);
  }
}
ok('every unguarded colors.text.* read names a key the palette declares',
  ghosts.length === 0,
  'these resolve to undefined and reach a style prop with nothing behind '
  + `them:\n         ${ghosts.join('\n         ')}`);

if (failures) {
  console.error(`\npinnedInkIsLegible: ${failures} failure(s)`);
  process.exit(1);
}
console.log('\nALL PASS');
