#!/usr/bin/env node
/**
 * A pinned palette key with no consumer means the pin is incomplete.
 *
 * WHAT THIS CATCHES, and why it is a class and not a screen.
 *
 * `outdoor` (styles/theme.js) is the app's light look, FROZEN. The ten logbook
 * editors wear it deliberately: a CP fills a compliance log standing outdoors,
 * often in direct sun, and a dark card is unreadable there whatever theme he
 * has set. See the block comment above the palette.
 *
 * The pin was applied to the CONTENT and never to the CANVAS.
 * `outdoor.backgroundStart/Middle/End` were defined FOR the canvas — commented
 * "Page background — the three stops AnimatedBackground paints" — and consumed
 * by NOTHING. AnimatedBackground kept painting the live theme, so in dark mode
 * every screen drew #0A1929 ink on a #050a12 gradient. The cards survived
 * (they carry their own fill); the step title, "STEP 1 OF 5", the section
 * headers and "Saved automatically" did not, because their containers have no
 * backgroundColor and sit straight on the canvas.
 *
 * A grep for the symptom finds two cards on one screen. THIS finds the shape:
 * a surface the palette describes and nothing paints. That is what made ten
 * screens fail from one omission, and it is checkable in one line of intent —
 * every key in a pinned palette must have a consumer.
 *
 * SECOND ASSERTION: no module may reference both `outdoor.*` and a LIVE colour
 * source (`colors.*` / `useTheme`) in the same file. Today nothing does — the
 * split is clean, ten pinned screens and four live ones. This guards against
 * the mix migrating INTO a file, which is the same defect at a smaller scale
 * and much harder to see by eye.
 *
 * WHAT IT DOES NOT CATCH, stated so nobody trusts it too far: a live-themed
 * SHARED COMPONENT mounted inside a pinned screen. That crosses a module
 * boundary this script does not follow. SignaturePad and Toast are exactly
 * that case and are audited by hand.
 *
 *   node frontend/scripts/find-unpinned-palette-keys.cjs
 *
 * Exit 1 if anything is found, so it gates CI.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const THEME = path.join(ROOT, 'src', 'styles', 'theme.js');

/** Palettes that are PINNED — frozen, theme-independent — and must be whole. */
const PINNED_PALETTES = ['outdoor'];

const SKIP_DIRS = new Set(['node_modules', 'dist', '.expo', 'android', 'ios', 'build']);

function sourceFiles(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name.startsWith('.') || SKIP_DIRS.has(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) sourceFiles(p, out);
    else if (/\.(js|jsx)$/.test(e.name)) out.push(p);
  }
  return out;
}

/** Comments stripped: prose that NAMES a token is not a consumer of it. */
function code(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/.*$/gm, '');
}

const themeSrc = fs.readFileSync(THEME, 'utf8');
const files = [
  ...sourceFiles(path.join(ROOT, 'app')),
  ...sourceFiles(path.join(ROOT, 'src')),
].filter((f) => f !== THEME && !/\.test\.(c?js)$/.test(f));

const bodies = new Map(files.map((f) => [f, code(fs.readFileSync(f, 'utf8'))]));

let problems = 0;

// ── 1. Every key in a pinned palette has a consumer ─────────────────────────
for (const palette of PINNED_PALETTES) {
  const decl = `export const ${palette} = {`;
  const i = themeSrc.indexOf(decl);
  if (i < 0) {
    console.log(`PALETTE MISSING  ${palette} is not exported from theme.js`);
    problems += 1;
    continue;
  }
  const block = themeSrc.slice(i, themeSrc.indexOf('\n};', i));
  const keys = [...block.matchAll(/^ {2}([a-zA-Z][a-zA-Z0-9]*):/gm)].map((m) => m[1]);

  const dead = keys.filter((k) => {
    const re = new RegExp(`\\b${palette}\\.${k}\\b`);
    for (const body of bodies.values()) if (re.test(body)) return false;
    return true;
  });

  console.log(`\n${palette}: ${keys.length} keys, ${keys.length - dead.length} consumed, ${dead.length} dead`);
  if (dead.length) {
    problems += dead.length;
    console.log(`\n${dead.length} pinned key(s) that nothing paints:\n`);
    for (const k of dead) console.log(`    ${palette}.${k}`);
    console.log('\nA pinned palette describes a surface. A key nothing consumes means');
    console.log('that surface is still being painted by something else — which is how');
    console.log('ten screens ended up with pinned ink on a live canvas. Either wire it,');
    console.log('or delete it from the palette so the palette stops claiming it.');
  }
}

// ── 2. No module mixes a pinned palette with a live colour source ───────────
{
  // A COMPONENT THAT TAKES `pinned` IS DEFINITIONALLY WHERE BOTH PALETTES MEET.
  //
  // This started as a one-file allowlist naming AnimatedBackground. Adding
  // SignaturePad to it would have made it a list, and a list of files exempt
  // from a rule is how a class of defect survives the guard meant to catch it.
  //
  // So the exemption is STRUCTURAL instead: a module that declares a `pinned`
  // prop is implementing the choice, and must see both sides to implement it.
  // Nothing else may. That is the actual rule, it needs no maintenance, and a
  // file cannot join by being typed into a list - it joins by taking the prop,
  // which is a visible design decision in the component's own signature.
  const declaresPinnedProp = (body) => /(?:^|[,{(\s])pinned\s*=\s*false/.test(body);


  const mixed = [];
  for (const [file, body] of bodies) {
    if (declaresPinnedProp(body)) continue;
    const usesPinned = PINNED_PALETTES.some((p) => new RegExp(`\\b${p}\\.`).test(body));
    if (!usesPinned) continue;
    const live = [];
    if (/(?<![a-zA-Z_$])colors\./.test(body)) live.push('colors.*');
    if (/useTheme\s*\(/.test(body)) live.push('useTheme()');
    if (live.length) mixed.push([path.relative(ROOT, file), live]);
  }
  console.log(`\nmodules mixing a pinned palette with a live source: ${mixed.length}`);
  if (mixed.length) {
    problems += mixed.length;
    console.log('\nA file cannot be half-pinned. Whichever half is smaller will be the');
    console.log('one nobody notices going invisible on a theme it was not built for:\n');
    for (const [f, live] of mixed) console.log(`    ${f}  ->  ${live.join(', ')}`);
  }
}

console.log(`\n${files.length} files scanned, ${problems} problem(s)`);
if (problems) process.exit(1);
console.log('Every pinned key is painted, and no module is half-pinned.');
