/**
 * applyTheme() must leave NO stale keys behind.
 *
 * The bug: the palette merge walked Object.keys(source) and only ever
 * assigned — it never deleted. `glass.cardGradientEnd` is defined in the LIGHT
 * palette and in no other, so applyTheme('light') wrote it onto the shared
 * `colors` object and applyTheme('dark') had no way to take it off again. From
 * the first switch to light, the dark palette permanently carried a light-mode
 * rgba. Nothing reads that key today, which is the only reason it never
 * rendered — the leak itself is structural and applies to any future
 * per-theme-only key.
 *
 * These are behavioural tests, not source greps: theme.js is ESM with no
 * runtime deps, so the harness strips the module syntax, evaluates the real
 * shipped source and drives applyTheme for real (same technique as
 * RiskScoreCircle.bandFor.test.cjs and bin.test.cjs). A fix that only renamed
 * the helper would fail here.
 *
 * Run:  node src/styles/theme.applyTheme.test.cjs
 */
const fs = require('fs');
const path = require('path');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── Load the real theme.js under bare node ───────────────────────────────────
function loadTheme() {
  const src = fs.readFileSync(path.join(__dirname, 'theme.js'), 'utf8');
  const stripped = src
    .replace(/^export default .*$/m, '')
    .replace(/^export const /gm, 'const ')
    .replace(/^export function /gm, 'function ');
  // _dark / _light are module-private; the harness needs them to compare key
  // sets, so they are returned alongside the public surface.
  // eslint-disable-next-line no-new-func
  return new Function(`${stripped}\nreturn { colors, applyTheme, _dark, _light, spacing, borderRadius, typography };`)();
}
const T = loadTheme();

// ── Key-set helpers ──────────────────────────────────────────────────────────
function keyPaths(obj, prefix = '', out = []) {
  for (const k of Object.keys(obj)) {
    const p = prefix ? `${prefix}.${k}` : k;
    out.push(p);
    const v = obj[k];
    if (v && typeof v === 'object' && !Array.isArray(v)) keyPaths(v, p, out);
  }
  return out.sort();
}
const diff = (a, b) => a.filter((x) => !b.includes(x));

const darkKeys = keyPaths(T._dark);
const lightKeys = keyPaths(T._light);

// ── Vacuity guard ────────────────────────────────────────────────────────────
// Every leak assertion below is trivially true if the two palettes have the
// same key set. They do not today (`glass.cardGradientEnd` is light-only), and
// this must stay true or the tests stop testing anything.
const lightOnly = diff(lightKeys, darkKeys);
const darkOnly = diff(darkKeys, lightKeys);
ok(lightOnly.length + darkOnly.length > 0,
  `the palettes still differ in key set — leak tests are not vacuous (light-only: ${JSON.stringify(lightOnly)}, dark-only: ${JSON.stringify(darkOnly)})`);
ok(lightOnly.includes('glass.cardGradientEnd'),
  'glass.cardGradientEnd is still the light-only key this bug was found on');

// ── The regression ───────────────────────────────────────────────────────────
T.applyTheme('light');
ok(Object.prototype.hasOwnProperty.call(T.colors.glass, 'cardGradientEnd'),
  'light: glass.cardGradientEnd is present');
const lightGradient = T.colors.glass.cardGradientEnd;
ok(lightGradient === T._light.glass.cardGradientEnd,
  'light: glass.cardGradientEnd carries the light value');

T.applyTheme('dark');
ok(!Object.prototype.hasOwnProperty.call(T.colors.glass, 'cardGradientEnd'),
  'dark: the light-only key glass.cardGradientEnd is GONE, not merely undefined');
ok(T.colors.glass.cardGradientEnd === undefined,
  'dark: reading glass.cardGradientEnd yields undefined (no stale light rgba)');
ok(!keyPaths(T.colors).includes('glass.cardGradientEnd'),
  'dark: the key does not reappear on a deep walk (e.g. via ThemeContext JSON copy)');

// ── Generalised: any future per-theme-only key is covered too ────────────────
T.applyTheme('dark');
let after = keyPaths(T.colors);
ok(JSON.stringify(after) === JSON.stringify(darkKeys),
  `dark: colors has EXACTLY the dark palette key set${JSON.stringify(after) === JSON.stringify(darkKeys) ? '' : ` — extra ${JSON.stringify(diff(after, darkKeys))}, missing ${JSON.stringify(diff(darkKeys, after))}`}`);

T.applyTheme('light');
after = keyPaths(T.colors);
ok(JSON.stringify(after) === JSON.stringify(lightKeys),
  `light: colors has EXACTLY the light palette key set${JSON.stringify(after) === JSON.stringify(lightKeys) ? '' : ` — extra ${JSON.stringify(diff(after, lightKeys))}, missing ${JSON.stringify(diff(lightKeys, after))}`}`);

// Repeated switching must not accumulate anything.
for (let i = 0; i < 5; i += 1) { T.applyTheme('light'); T.applyTheme('dark'); }
ok(JSON.stringify(keyPaths(T.colors)) === JSON.stringify(darkKeys),
  'ten switches later the key set is still exactly the dark palette');

// ── Values, not just keys: the switch must be a full swap ────────────────────
T.applyTheme('dark');
const darkSnapshot = JSON.stringify(T.colors);
T.applyTheme('light');
const lightSnapshot = JSON.stringify(T.colors);
T.applyTheme('dark');
ok(JSON.stringify(T.colors) === darkSnapshot,
  'dark → light → dark restores the dark palette byte-for-byte');
T.applyTheme('light');
ok(JSON.stringify(T.colors) === lightSnapshot,
  'light → dark → light restores the light palette byte-for-byte');
ok(darkSnapshot !== lightSnapshot, 'the two palettes are actually different (guard)');

// ── Identity: consumers hold live getters over this exact object ─────────────
// semanticColors.js does `import { colors }` and reads colors.text.muted at
// access time. Reassigning `colors` instead of mutating it would break every
// one of those getters, so the fix must not do that.
T.applyTheme('dark');
const ref = T.colors;
const nestedRef = T.colors.text;
T.applyTheme('light');
ok(T.colors === ref, 'applyTheme mutates `colors` in place (top-level identity preserved)');
ok(T.colors.text === nestedRef,
  'nested objects are mutated in place too (a held colors.text reference stays live)');
ok(nestedRef.primary === T._light.text.primary,
  'a reference captured before the switch sees the NEW theme values');

// ── The nested non-colour object survives the prune ──────────────────────────
T.applyTheme('light');
ok(T.colors.shadow.offset.height === T._light.shadow.offset.height,
  'shadow.offset is applied, not flattened (light)');
T.applyTheme('dark');
ok(T.colors.shadow.offset.height === T._dark.shadow.offset.height,
  'shadow.offset is applied, not flattened (dark)');
ok(Object.keys(T.colors.shadow.offset).sort().join(',') === 'height,width',
  'shadow.offset keeps exactly {width, height}');

// ── Default / unknown mode ───────────────────────────────────────────────────
T.applyTheme('light');
T.applyTheme('nonsense');
ok(JSON.stringify(T.colors) === darkSnapshot,
  'an unrecognised mode falls back to dark (unchanged behaviour)');
T.applyTheme('light');
T.applyTheme();
ok(JSON.stringify(T.colors) === darkSnapshot,
  'applyTheme() with no argument falls back to dark (unchanged behaviour)');

// ── Static scales are untouched by a theme switch ────────────────────────────
ok(T.spacing.md === 16 && T.borderRadius.full === 9999 && T.typography.sizes.xs === 11,
  'spacing / borderRadius / typography are unaffected by applyTheme');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
