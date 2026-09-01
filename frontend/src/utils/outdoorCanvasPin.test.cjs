/**
 * The pinned ink finally has a pinned canvas under it.
 *
 * THE DEFECT. `outdoor` is the app's light look, frozen, worn deliberately by
 * the eleven logbook editors: a CP fills a compliance log outdoors, often in
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
 * ELEVEN SCREENS, ONE WRAPPER. Every editor mounts LogbookStepper, so the fix
 * was one prop at two call sites, not ten screen edits — and it is why the
 * eleventh editor inherited a pinned canvas for free, which is exactly what
 * made its own unpinned CONTENT a silent dark-mode blank rather than a visible
 * mismatch.
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

console.log('\n-- every LogbookStepper wrap site is pinned --');
{
  // THE COUNT IS THE ANCHOR, not the point. The point is the assertion
  // below: every wrap carries `pinned`. The count is here so that ADDING a
  // wrap forces someone to look at this test, rather than shipping an
  // unpinned canvas nothing checks. Three since the `unavailable` branch --
  // a log read that FAILED renders read-only instead of an editable empty
  // form. Raise it with the same deliberation if a fourth arrives.
  const wraps = STEPPER.match(/<AnimatedBackground[^>]*>/g) || [];
  ok(wraps.length === 3,
    `ANCHOR: three wrap sites found (${wraps.length}) — the loading branch, `
    + 'the unavailable branch and the main tree');
  ok(wraps.every((w) => /\bpinned\b/.test(w)),
    'EVERY ONE carries pinned. The loading branch matters as much: it tints '
    + `its spinner outdoor.text. Found: ${JSON.stringify(wraps)}`);
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

console.log('\n-- and the eleven pinned editors still route through the stepper --');
{
  const dir = path.join(FRONTEND, 'app', 'logbooks');
  const LIVE = new Set(['index.jsx', 'preshift_signin.jsx', 'review.jsx',
    'subcontractor_orientation.jsx']);
  const pinned = fs.readdirSync(dir)
    .filter((f) => f.endsWith('.jsx') && !LIVE.has(f));
  // TEN BECAME ELEVEN: site_superintendent_log.jsx, the BC 3301.13.13 log.
  //
  // THE ANCHOR EARNED ITS KEEP HERE. That screen was written reaching for
  // useTheme() and mounting an unpinned pad, and it was the CENSUS — not a
  // screenshot, not a review — that caught it. The failure it would have
  // shipped is the same defect this file documents, running the other way:
  // LogbookStepper pins the canvas LIGHT unconditionally, so in dark mode the
  // screen would have drawn dark-theme ink, which is LIGHT, on a light
  // gradient. Blank screen, no error, and invisible to anyone testing in
  // light mode — which is everyone, because the pinned canvas looks identical
  // in both.
  //
  // So the number goes up by one and the reason is written down. Do not bump
  // it again without saying which screen and why.
  ok(pinned.length === 11,
    `ANCHOR: eleven pinned editors (${pinned.length}) — ${pinned.join(', ')}`);

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

console.log('\n-- SignaturePad renders its LIGHT-MODE self on the pinned eleven --');
{
  const PAD = code(read('src/components/SignaturePad.js'));
  ok(/pinned\s*=\s*false/.test(PAD),
    'the prop DEFAULTS TO FALSE - the other six mounters never pass it');
  ok(/const isDark = pinned \? false : themeIsDark/.test(PAD),
    'isDark is forced too, so the two isDark ternaries inside buildStyles '
    + 'resolve to their light branch as well as the palette');
  ok(/const colors = pinned \? PINNED_COLORS : liveColors/.test(PAD),
    'and the palette is substituted once rather than at each call site');

  // FIVE OF SIX ARE IDENTITIES that outdoorMatchesLight.test.cjs already
  // asserts against the private _light palette, so a pinned pad is not an
  // approximation of light mode - it IS light mode. The sixth, text.subtle,
  // has no outdoor pair and lands on textDim: slightly DARKER than light,
  // which errs toward contrast and is the right direction to be wrong in.
  for (const pin of ['outdoor.surface', 'outdoor.line', 'outdoor.text',
    'outdoor.textSoft', 'outdoor.textDim']) {
    ok(PAD.includes(pin), 'the pinned palette maps to ' + pin);
  }

  // THE SIGNING BOX WAS ALREADY RIGHT and stays hardcoded: a man signs on
  // white with black ink whatever the theme. That is why this defect only
  // ever affected the chrome around it.
  ok(/backgroundColor: '#ffffff'/.test(PAD),
    'the signing surface stays hardcoded white, untouched by the pin');
  ok(/strokeColor="#000000"/.test(PAD), 'and the strokes stay black');
}

console.log('\n-- the six other mounters are byte-identical --');
{
  // Only the eleven pinned editors pass it. Everything else - including the four
  // correctly-themed logbook screens - must render exactly as before.
  // THE FOUR THAT ACTUALLY RENDER ONE. `grep -l SignaturePad` returns more
  // files than this, and every extra is a false positive: review.jsx only
  // discusses the pad in comments, and workers/[id].jsx has a local
  // `showSignaturePad` flag over its own inline signature UI. Neither mounts
  // the component, so neither belongs in a list about how it is mounted.
  const OTHERS = [
    'app/daily-log.jsx',
    'app/logbooks/preshift_signin.jsx',
    'app/logbooks/subcontractor_orientation.jsx',
    'app/site/daily-logs.jsx',
  ];
  for (const f of OTHERS) {
    const src = code(read(f));
    ok(/<SignaturePad/.test(src), 'ANCHOR: ' + path.basename(f) + ' mounts a pad');
    ok(!/\bpinned\b/.test(src),
      path.basename(f) + ' passes no pinned - live-themed, unchanged');
  }
}

console.log('\n-- every render site is accounted for, pinned or live --');
{
  // 15 render sites: 11 pinned, 4 live. Pinned so a NEW one cannot appear
  // without someone deciding which half it belongs to - which is exactly
  // the decision that was never made for the canvas.
  //
  // The fifteenth is site_superintendent_log.jsx and it is PINNED. It arrived
  // unpinned and this assertion is what said so.
  const walk = (d, out = []) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p, out);
      else if (/[.]jsx?$/.test(e.name)) out.push(p);
    }
    return out;
  };
  const sites = walk(path.join(FRONTEND, 'app'))
    .map((f) => [f, code(fs.readFileSync(f, 'utf8'))])
    .filter(([, src]) => /<SignaturePad[\s>]/.test(src));
  const live = sites.filter(([, src]) => !/<SignaturePad\s+pinned/.test(src));
  ok(sites.length === 15,
    'ANCHOR: 15 render sites (' + sites.length + ')');
  ok(live.length === 4,
    'exactly four stay live: ' + JSON.stringify(live.map(([f]) => path.basename(f))));
}

console.log('\n-- and every pinned editor that mounts a pad pins it --');
{
  const dir = path.join(FRONTEND, 'app', 'logbooks');
  const LIVE = new Set(['index.jsx', 'preshift_signin.jsx', 'review.jsx',
    'subcontractor_orientation.jsx']);
  const missing = fs.readdirSync(dir)
    .filter((f) => f.endsWith('.jsx') && !LIVE.has(f))
    .filter((f) => {
      const src = code(read(path.join('app', 'logbooks', f)));
      return /<SignaturePad/.test(src) && !/<SignaturePad\s+pinned/.test(src);
    });
  ok(missing.length === 0,
    'otherwise its chrome goes invisible on the now-light canvas. Missing: '
    + JSON.stringify(missing));
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
