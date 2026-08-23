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
  ok(/style=\{\[styles\.container, \{ bottom: insets\.bottom \+ 24 \}\]\}/.test(src),
    'the bottom is overridden per render, not baked into the StyleSheet — a '
    + 'StyleSheet is built once at module load, before any inset exists');

  // The +24 in the INLINE expression is the real gap above the bar; the
  // stylesheet value is only a fallback, because the inline style REPLACES
  // bottom rather than adding to it. Asserting the stylesheet would be
  // asserting something inert.
  ok(/insets\.bottom \+ 24/.test(src),
    'the gap above the bar is 24, applied on top of the measured inset');
}

console.log('\n-- the screens themselves are unchanged --');
{
  // This fix must not have quietly added bottom insets at the screen level —
  // that was ruled out, and it would double-pad against paddingBottom: 120.
  const walk = (dir, out = []) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p, out);
      else if (e.name.endsWith('.jsx')) out.push(p);
    }
    return out;
  };
  const withBottom = walk(path.join(FRONTEND, 'app'))
    .map((f) => [f, fs.readFileSync(f, 'utf8')])
    .filter(([, s]) => /edges=\{\[[^\]]*'bottom'/.test(s));
  ok(withBottom.length <= 1,
    'at most one screen insets the bottom at the screen level — the rest use '
    + `scroll padding, measured as adequate. Found: `
    + JSON.stringify(withBottom.map(([f]) => path.basename(f))));
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
