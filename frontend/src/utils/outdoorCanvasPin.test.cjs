/**
 * The pinned ink finally has a pinned canvas under it.
 *
 * THE DEFECT. `outdoor` is the app's light look, frozen, worn deliberately by
 * the ten logbook editors: a CP fills a compliance log outdoors, often in
 * direct sun, and a dark card is unreadable there whatever theme he has set.
 * The pin was applied to the CONTENT and never to the CANVAS —
 * AnimatedBackground kept painting the LIVE theme. In dark mode that put
 * #0A1929 ink on a #050a12 gradient:
 *
 *   cards                       visible   (they carry outdoor.cardTop)
 *   back button                 visible   (headerBack carries outdoor.surface)
 *   step title                  INVISIBLE (header has no backgroundColor)
 *   "STEP 1 OF 5"               INVISIBLE (same)
 *   section headers             INVISIBLE (same)
 *   "Saved automatically"       INVISIBLE (footer is padding only)
 *
 * `outdoor.backgroundStart/Middle/End` were defined FOR this, commented "the
 * three stops AnimatedBackground paints", and consumed by nothing.
 *
 * PINNING IS ALL THREE THINGS `isDark` DRIVES, not just the stops: the
 * gradient, the scanline tint, and the two light-only radial overlays. Pinning
 * the stops alone leaves a light canvas with a dark scanline and no tint — a
 * third look matching neither theme.
 *
 * TEN SCREENS, ONE WRAPPER. Every editor mounts LogbookStepper, so the fix is
 * one prop at two call sites, not ten screen edits.
 *
 *   node frontend/src/utils/outdoorCanvasPin.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (p) => fs.readFileSync(path.join(FRONTEND, p), 'utf8');

/** Comments stripped — this file explains the defect at length, and a bare
 *  search would match the explanation and pass for the wrong reason. */
const code = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/.*$/gm, '');

const BG = code(read('src/components/AnimatedBackground.js'));
const STEPPER = code(read('src/components/logbookStepper/LogbookStepper.jsx'));

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

console.log('\n-- AnimatedBackground can paint the pinned canvas --');
{
  ok(/pinned\s*=\s*false/.test(BG),
    'the prop DEFAULTS TO FALSE, so every correctly-themed screen renders '
    + 'byte-identically to before');
  ok(/outdoor\.backgroundStart/.test(BG)
    && /outdoor\.backgroundMiddle/.test(BG)
    && /outdoor\.backgroundEnd/.test(BG),
    'all three pinned stops are consumed — they were defined for this and '
    + 'painted by nothing');
  ok(/const isDark = pinned \? false : themeIsDark/.test(BG),
    'PINNING IS NOT JUST THE STOPS: isDark itself is forced, so the scanline '
    + 'tint and the two light-only radial overlays come along. Pinning the '
    + 'gradient alone would produce a third look, matching neither theme');
  ok(/useTheme\(\)/.test(BG),
    'the hook still runs when pinned — it is what re-renders this subtree on '
    + 'a theme toggle, and a pinned screen must re-render with the rest of the '
    + 'app even though its own colours do not move');
  ok(/colors\.background\.start/.test(BG),
    'ANCHOR: the live path still exists and is still the default');
}

console.log('\n-- both LogbookStepper wrap sites are pinned --');
{
  const wraps = STEPPER.match(/<AnimatedBackground[^>]*>/g) || [];
  ok(wraps.length === 2,
    `ANCHOR: two wrap sites found (${wraps.length}) — the loading branch and `
    + 'the main tree');
  ok(wraps.every((w) => /\bpinned\b/.test(w)),
    'BOTH carry pinned. The loading branch matters as much: it tints its '
    + `spinner outdoor.text. Found: ${JSON.stringify(wraps)}`);
}

console.log('\n-- the four correctly-themed screens are untouched --');
{
  // Ruling: do not touch these. They are live-themed end to end, own their
  // AnimatedBackground, and reference no outdoor token.
  const LIVE = [
    'app/logbooks/index.jsx',
    'app/logbooks/preshift_signin.jsx',
    'app/logbooks/review.jsx',
    'app/logbooks/subcontractor_orientation.jsx',
  ];
  for (const f of LIVE) {
    const src = code(read(f));
    ok(!/\boutdoor\./.test(src), `${path.basename(f)} references no pinned token`);
    ok(!/<AnimatedBackground[^>]*\bpinned\b/.test(src),
      `${path.basename(f)} does not pin its canvas — it is correctly themed `
      + 'today and stays on the live palette');
  }
}

console.log('\n-- and the ten pinned editors still route through the stepper --');
{
  const dir = path.join(FRONTEND, 'app', 'logbooks');
  const LIVE = new Set(['index.jsx', 'preshift_signin.jsx', 'review.jsx',
    'subcontractor_orientation.jsx']);
  const pinned = fs.readdirSync(dir)
    .filter((f) => f.endsWith('.jsx') && !LIVE.has(f));
  ok(pinned.length === 10,
    `ANCHOR: ten pinned editors (${pinned.length}) — ${pinned.join(', ')}`);

  const notStepper = pinned.filter(
    (f) => !/LogbookStepper/.test(read(path.join('app', 'logbooks', f))));
  ok(notStepper.length === 0,
    'every one mounts LogbookStepper, which is what makes this a one-wrapper '
    + `fix rather than ten screen edits. Found outside it: ${JSON.stringify(notStepper)}`);

  const live = pinned.filter((f) => {
    const src = code(read(path.join('app', 'logbooks', f)));
    return /(?<![a-zA-Z_$])colors\./.test(src) || /useTheme\s*\(/.test(src);
  });
  ok(live.length === 0,
    'and none of them mixes a live palette in, so with the canvas pinned every '
    + `pixel they own comes from outdoor. Found: ${JSON.stringify(live)}`);
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
