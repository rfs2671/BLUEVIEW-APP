/**
 * The `outdoor` group is the app's LIGHT theme, copied.
 *
 * It exists because the CP fills a logbook outdoors, and `colors` is a live
 * view over whichever palette is active — so a screen that consumed it would go
 * dark for anyone with dark mode on, and a dark card in direct sun is
 * unreadable no matter how deliberately it was chosen. Pinning is the point.
 *
 * COPYING IS THE COST OF PINNING, AND THIS IS THE INVOICE. Nothing in the
 * language links `outdoor.text` to `_light.text.primary`; if someone retunes
 * the light theme, the stepper silently keeps the old look and starts drifting
 * away from the app it was restyled to match. Every value below is asserted
 * against its source, so that drift fails here instead of on a jobsite.
 *
 * `_light` is module-private and deliberately stays that way — exporting it
 * would invite screens to read a palette that is not the active one. It is
 * parsed out of the source instead.
 *
 * Run:  node src/styles/outdoorMatchesLight.test.cjs
 */
const fs = require('fs');
const path = require('path');

const THEME = path.join(__dirname, 'theme.js');
const src = fs.readFileSync(THEME, 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/** Evaluate the module with its imports stripped — it has none that matter. */
function loadTheme() {
  const body = src
    .replace(/^import .*$/gm, '')
    .replace(/^export default [\s\S]*$/m, '')
    .replace(/^export (const|function) /gm, '$1 ');
  // eslint-disable-next-line no-new-func
  return new Function(`${body}\nreturn { outdoor, outdoorShadow, applyTheme, colors, borderRadius, spacing, touchTarget };`)();
}
const T = loadTheme();

/** The private _light palette, read as live values by applying it. */
function lightPalette() {
  T.applyTheme('light');
  return JSON.parse(JSON.stringify(T.colors));
}
const L = lightPalette();
// Leave the module on the dark default so this file cannot affect another.
T.applyTheme('dark');

const norm = (v) => String(v).toLowerCase().replace(/\s+/g, '');

// ── The page background ──────────────────────────────────────────────────────
console.log('\n── The background AnimatedBackground paints ──');
ok(norm(T.outdoor.backgroundStart) === norm(L.background.start),
  `backgroundStart matches _light.background.start (${L.background.start})`);
ok(norm(T.outdoor.backgroundMiddle) === norm(L.background.middle),
  `backgroundMiddle matches _light.background.middle (${L.background.middle})`);
ok(norm(T.outdoor.backgroundEnd) === norm(L.background.end),
  `backgroundEnd matches _light.background.end (${L.background.end})`);

// ── The card ─────────────────────────────────────────────────────────────────
console.log('\n── The card fill GlassCard renders in light mode ──');
// GlassCard's LIGHT_GRADIENT is [withAlpha('#ffffff', 0.84), 'rgba(250, 251, 248, 0.80)'].
const glassSrc = fs.readFileSync(
  path.join(__dirname, '..', 'components', 'GlassCard.js'), 'utf8');
const gradMatch = glassSrc.match(/const LIGHT_GRADIENT = \[([\s\S]*?)\];/);
ok(!!gradMatch, 'GlassCard still declares a LIGHT_GRADIENT');
if (gradMatch) {
  const block = gradMatch[1];
  ok(/withAlpha\('#ffffff',\s*0\.84\)/.test(block),
    'GlassCard tops the card at white 0.84');
  ok(norm(T.outdoor.cardTop) === norm('rgba(255,255,255,0.84)'),
    'outdoor.cardTop is that same white 0.84');
  const bottom = (block.match(/'(rgba\([^)]*\))'/) || [])[1];
  ok(!!bottom && norm(T.outdoor.cardBottom) === norm(bottom),
    `outdoor.cardBottom matches GlassCard's bottom stop (${bottom})`);
}
ok(norm(T.outdoor.line) === norm(L.glass.border),
  `outdoor.line matches _light.glass.border (${L.glass.border})`);
ok(norm(T.outdoor.lineStrong) === norm(L.border.strong),
  `outdoor.lineStrong matches _light.border.strong (${L.border.strong})`);
ok(norm(T.outdoor.surface) === norm(L.glass.background),
  `outdoor.surface matches _light.glass.background (${L.glass.background})`);

// ── Text ─────────────────────────────────────────────────────────────────────
console.log('\n── Text ──');
ok(norm(T.outdoor.text) === norm(L.text.primary),
  `outdoor.text matches _light.text.primary (${L.text.primary})`);
ok(norm(T.outdoor.textSoft) === norm(L.text.secondary),
  `outdoor.textSoft matches _light.text.secondary`);
ok(norm(T.outdoor.textDim) === norm(L.text.muted),
  `outdoor.textDim matches _light.text.muted`);
ok(norm(T.outdoor.surfaceSelected) === norm(L.primary),
  `outdoor.surfaceSelected matches _light.primary (${L.primary})`);

ok(norm(T.outdoor.selected) === norm(L.selected),
  `outdoor.selected matches _light.selected (${L.selected})`);
ok(norm(T.outdoor.onSelected) === norm(L.onSelected),
  `outdoor.onSelected matches _light.onSelected (${L.onSelected})`);
ok(norm(T.outdoor.bar) === norm(L.bar),
  `outdoor.bar matches _light.bar (${L.bar})`);
ok(norm(T.outdoor.onBar) === norm(L.onBar),
  `outdoor.onBar matches _light.onBar (${L.onBar})`);

// ── Shadow ───────────────────────────────────────────────────────────────────
console.log('\n── The card aura ──');
ok(norm(T.outdoorShadow.shadowColor) === norm(L.aura.color),
  `shadowColor matches _light.aura.color (${L.aura.color})`);
ok(T.outdoorShadow.shadowRadius === L.aura.radius,
  `shadowRadius matches _light.aura.radius (${L.aura.radius})`);
ok(T.outdoorShadow.shadowOpacity === L.aura.opacity,
  `shadowOpacity matches _light.aura.opacity (${L.aura.opacity})`);
ok(T.outdoorShadow.shadowOffset.height === L.aura.offset.height
  && T.outdoorShadow.shadowOffset.width === L.aura.offset.width,
`shadowOffset matches _light.aura.offset (${JSON.stringify(L.aura.offset)})`);
const auraSrc = fs.readFileSync(path.join(__dirname, 'aura.js'), 'utf8');
ok(/elevation:\s*4/.test(auraSrc),
  'the aura gives Android elevation 4, and outdoorShadow does too');
ok(T.outdoorShadow.elevation === 4, 'outdoorShadow.elevation === 4');

// ── It must NOT flip ─────────────────────────────────────────────────────────
console.log('\n── It is pinned, not live ──');
{
  const before = { ...T.outdoor };
  T.applyTheme('dark');
  const same = Object.keys(before).every((k) => before[k] === T.outdoor[k]);
  T.applyTheme('dark');
  ok(same, 'switching to the dark theme changes NOTHING in outdoor');
}
ok(!/get \w+\(\)/.test(src.slice(src.indexOf('export const outdoor'),
  src.indexOf('export const outdoorShadow'))),
'outdoor holds plain values, not live getters over the active palette');

// ── The card geometry the app uses ───────────────────────────────────────────
console.log('\n── Card geometry ──');
ok(T.borderRadius.xxl === 14, 'borderRadius.xxl is 14 — GlassCard\'s corner');
ok(/borderRadius: borderRadius\.xxl/.test(glassSrc),
  'GlassCard still rounds its container to xxl');
ok(T.spacing.md === 16, 'spacing.md is 16 — GlassCard\'s internal padding');
ok(/padding: spacing\.md/.test(glassSrc),
  'GlassCard still pads its content by md');
ok(T.borderRadius.full === 9999, 'borderRadius.full is the pill radius');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
