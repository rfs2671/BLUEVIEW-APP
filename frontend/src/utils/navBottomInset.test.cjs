/**
 * The floating navs clear the system navigation bar.
 *
 * API 36 enforces edge-to-edge, so the app draws under the navigation bar and
 * every element has to account for it. Both navs are `position: 'absolute'`,
 * which puts them OUTSIDE the inset flow entirely — no parent padding and no
 * scroll padding reaches an absolutely positioned child. So the screens'
 * `SafeAreaView edges={['top']}` and their `paddingBottom: 120` do nothing at
 * all for these two, and a hardcoded `bottom: 24` is the whole story.
 *
 * 24 approximates a GESTURE bar, which is why it looks right on a gesture
 * device and why an informal look missed it. On 3-button navigation the bar is
 * roughly 48dp and the nav sits underneath the buttons — on every screen, and
 * `CpNav` is on every screen the CP uses.
 *
 * `insets.bottom` is 0 where there is no bar, so this is a no-op on gesture
 * navigation, on iOS without a home indicator, and on web.
 *
 *   node frontend/src/utils/navBottomInset.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const NAVS = ['CpNav', 'FloatingNav'];

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

for (const nav of NAVS) {
  const file = path.join(FRONTEND, 'src', 'components', `${nav}.js`);
  const src = fs.readFileSync(file, 'utf8');

  console.log(`\n-- ${nav} --`);

  ok(/position: 'absolute'/.test(src),
    'ANCHOR: still absolutely positioned, which is why insets do not reach it');

  ok(/import \{ useSafeAreaInsets \} from 'react-native-safe-area-context';/.test(src),
    'reads the real inset rather than assuming a bar height');

  ok(/const insets\s*=\s*useSafeAreaInsets\(\);/.test(src),
    'and calls the hook inside the component');

  // The override must be at the USE SITE. Putting insets in the StyleSheet is
  // impossible (it is created once at module load, before any inset exists),
  // so a fix that "looks right" in the stylesheet would silently be a constant.
  //
  // THE OFFSET MAY BE A LITERAL OR A NAMED CONSTANT. It was `+ 24` in both
  // navs until CpNav needed to EXPORT it: the three CP screens now derive
  // their scroll clearance from the nav's own geometry
  // (CP_NAV_CLEARANCE = offset + pill height + breathing room), and a
  // clearance built on a number typed twice is the drift this whole change
  // removes. Naming it is what lets one value serve both the pill's position
  // and the clearance that keeps content off it.
  //
  // The VALUE is still pinned — see the check below — just pinned at its
  // definition rather than at its use.
  const OFFSET = '(?:24|[A-Z][A-Z0-9_]*_OFFSET)';
  ok(new RegExp(`style=\\{\\[styles\\.container, \\{ bottom: insets\\.bottom \\+ ${OFFSET} \\}\\]\\}`).test(src),
    'the bottom is overridden per render, not baked into the StyleSheet — a '
    + 'StyleSheet is built once at module load, before any inset exists');

  // The offset in the INLINE expression is the real gap above the bar; the
  // stylesheet value is only a fallback, because the inline style REPLACES
  // bottom rather than adding to it. Asserting the stylesheet would be
  // asserting something inert.
  ok(new RegExp(`insets\\.bottom \\+ ${OFFSET}`).test(src),
    'the gap above the bar is applied on top of the measured inset');

  // AND IT IS STILL 24, whichever form it takes. A named constant that drifted
  // to some other value would satisfy the shape checks above while moving the
  // nav — and, for CpNav, moving every CP screen's clearance with it.
  const named = src.match(/^export const ([A-Z][A-Z0-9_]*_OFFSET) = (\d+);$/m);
  ok(named ? Number(named[2]) === 24 : /insets\.bottom \+ 24/.test(src),
    'the gap above the bar is 24' + (named ? ` (via ${named[1]})` : ''));
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
    'both navs still read the inset themselves');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
