/**
 * The bottom navs clear the system navigation bar.
 *
 * API 36 enforces edge-to-edge, so the app draws under the navigation bar and
 * every element has to account for it. All three navs are `position:
 * 'absolute'`, which puts them OUTSIDE the inset flow entirely — no parent
 * padding and no scroll padding reaches an absolutely positioned child. So the
 * screens' `SafeAreaView edges={['top']}` and their `paddingBottom: 120` do
 * nothing at all for these, and the nav has to read the inset itself.
 *
 * THE GEOMETRY CHANGED, THE INVARIANT DID NOT. These were floating pills
 * (`bottom: insets.bottom + 24`). They are now solid, full-width bars flush to
 * the bottom edge: the container is `bottom: 0` and the BAR's own
 * `paddingBottom` is `insets.bottom + <a named constant>`. The bar grows
 * upward by the inset and its fill runs under the system bar, so the labels
 * sit above the buttons on 3-button navigation (inset ~48) exactly as the
 * pill did, and the colour reaches the screen edge instead of leaving a gap.
 *
 * `insets.bottom` is 0 where there is no bar, so this is a no-op on gesture
 * navigation, on iOS without a home indicator, and on web.
 *
 *   node frontend/src/utils/navBottomInset.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const NAVS = ['CpNav', 'FloatingNav', 'SiteNav'];

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

// Comment-free source, so a rule explained in prose is not mistaken for code.
const stripComments = (src) => src
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(?<!:)\/\/[^\n]*/g, '');

for (const nav of NAVS) {
  const file = path.join(FRONTEND, 'src', 'components', `${nav}.js`);
  const src = fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
  const code = stripComments(src);

  console.log(`\n-- ${nav} --`);

  // The container block of the NAV's stylesheet (FloatingNav also carries a
  // modal stylesheet, which is why this anchors on `container:`).
  const containerBlock = (code.match(/^\s*container: \{[\s\S]*?\n\s*\},?$/m) || [''])[0];
  const sheet = code.slice(code.lastIndexOf('StyleSheet.create'));

  ok(/position: 'absolute'/.test(containerBlock),
    'ANCHOR: still absolutely positioned, which is why insets do not reach it');

  ok(/import \{ useSafeAreaInsets \} from 'react-native-safe-area-context';/.test(src),
    'reads the real inset rather than assuming a bar height');

  ok(/const insets\s*=\s*useSafeAreaInsets\(\);/.test(code),
    'and calls the hook inside the component');

  // Flush to the bottom edge, full width: no float gap, no inset in `bottom`.
  ok(/\bbottom: 0\b/.test(containerBlock)
    && /\bleft: 0\b/.test(containerBlock)
    && /\bright: 0\b/.test(containerBlock),
    'the bar is flush to the bottom edge and spans the full width');
  ok(!/borderRadius/.test(containerBlock),
    'and is a flat strip, not a rounded pill');
  ok(!/\bbottom: insets\.bottom/.test(code),
    'the inset is NOT added to `bottom` (the old float) — the bar stays at '
    + '0 and grows upward');

  // The override must be at the USE SITE. Putting insets in the StyleSheet is
  // impossible (it is created once at module load, before any inset exists),
  // so a fix that "looks right" in the stylesheet would silently be a constant.
  const PAD = '([A-Z][A-Z0-9_]*_(?:PADDING|OFFSET))';
  const inline = code.match(new RegExp(`paddingBottom: insets\\.bottom \\+ ${PAD}`));
  ok(!!inline,
    "the bar's paddingBottom is overridden per render as insets.bottom + a "
    + 'named constant — a StyleSheet is built once at module load, before any '
    + 'inset exists');
  ok(!!inline && /styles\.container/.test(
      code.slice(Math.max(0, inline.index - 220), inline.index)),
    'and that override is on the same element as styles.container, the bar');

  // The StyleSheet must not try to carry the inset: it cannot, and reading
  // `insets` there would make the "per render" claim above a constant.
  ok(!/\binsets\b/.test(sheet),
    'the StyleSheet itself never references insets (no inset exists when it '
    + 'is built)');

  // THE CONSTANT IS A SMALL NUMBER, NOT A FLOAT GAP. insets.bottom already
  // carries the home indicator / nav bar, so the constant is only the
  // breathing room under the labels. A value that drifted back to 24 would
  // satisfy the shape checks above while pushing the labels up off the edge.
  const name = inline && inline[1];
  const decl = name && code.match(new RegExp(`^(?:export )?const ${name} = (.+?);$`, 'm'));
  ok(!!decl && (decl[1] === 'spacing.sm' || decl[1] === '8'),
    `the constant (${name}) is 8 — the small breathing room under the labels `
    + `(got ${decl && decl[1]})`);

  // The colour is a theme token resolved at render, not a baked-in constant.
  ok(/\b(?:colors?|c)\.bar\b/.test(code),
    'the bar fill comes from the theme `bar` token');
}

console.log('\n-- no screen both insets the bottom AND pads for it --');
{
  // THIS WAS A COUNT, AND THE COUNT WAS THE WRONG INVARIANT. It read "at most
  // one screen insets the bottom at the screen level", which was really asking
  // "did the nav fix quietly add bottom insets to screens?". It then failed the
  // moment login and register legitimately needed the bottom edge back
  // (0e87696 had removed it and pushed their signup link onto the home
  // indicator) — a test blocking a correct fix for a reason it never meant.
  //
  // The real hazard is DOUBLE PADDING: a screen that insets the bottom AND
  // carries the 120pt scroll padding pads for the same bar twice, leaving a
  // visible dead band above the nav.
  //
  // login and register inset the bottom deliberately and pad only
  // spacing.xxl (48) for keyboard clearance, which is not the 120pt scroll
  // pattern and does not stack into a dead band.
  const walk = (dir, out = []) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p, out);
      else if (e.name.endsWith('.jsx')) out.push(p);
    }
    return out;
  };
  const doubled = walk(path.join(FRONTEND, 'app'))
    .map((f) => [f, fs.readFileSync(f, 'utf8')])
    .filter(([, src]) => /edges=\{\[[^\]]*'bottom'/.test(src)
      && /paddingBottom: 1[024]0/.test(src));
  ok(doubled.length === 0,
    'no screen pads for the navigation bar twice — once via the safe-area '
    + 'inset and again via 120pt of scroll padding. Found: '
    + JSON.stringify(doubled.map(([f]) => path.basename(f))));

  // And the navs themselves are still the only things reading insets for their
  // own position, which is what this file is actually about.
  ok(NAVS.every((n) => /useSafeAreaInsets/.test(
    fs.readFileSync(path.join(FRONTEND, 'src', 'components', `${n}.js`), 'utf8'))),
    'every nav still reads the inset itself');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
