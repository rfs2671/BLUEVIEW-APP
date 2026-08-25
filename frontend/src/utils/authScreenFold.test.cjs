/**
 * The signup link is REACHABLE, not merely present in the tree.
 *
 * THIS BUG HAS SHIPPED TWICE.
 *
 *   02649d3  2026-07-20  fixed it — the centred stack (logo + card + link) was
 *                        taller than the viewport with no ScrollView, so the
 *                        "Don't have an account? Sign up" link fell below the
 *                        fold with no way to scroll to it.
 *   0e87696  2026-08-23  reintroduced it — changed these two SafeAreaViews to
 *                        edges={['top']}, removing ~34pt of bottom clearance
 *                        from that same centred layout.
 *
 * A fix with no test defending it lasted five weeks. This is that test.
 *
 * WHY THESE TWO SCREENS AND NOT THE OTHER TEN that took the same edges change:
 * only login and register have a CENTRED scroll container
 * (`flexGrow: 1 + justifyContent: 'center'`) whose last child is a link. A
 * centred container clips BOTH ends when its content exceeds it, so the
 * bottom-most element is the one at risk. The other ten carry
 * `paddingBottom: 120` or `spacing.xxl`, and `nfc/index.jsx` has no ScrollView
 * at all.
 *
 * REACHABLE means four things together, and each fails differently:
 *
 *   rendered unconditionally   no ancestor can hide it
 *   inside a ScrollView        it can be scrolled to when the stack overflows
 *   bottom safe-area edge      it does not sit on the home indicator
 *   trailing scroll padding    it clears a raised keyboard rather than resting
 *                              flush against it
 *
 *   node frontend/src/utils/authScreenFold.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');

const SCREENS = [
  {
    file: 'app/login.jsx',
    linkPush: "router.push('/register')",
    linkText: "Don't have an account?",
    what: 'signup link',
  },
  {
    file: 'app/register.jsx',
    linkPush: "router.push('/login')",
    linkText: 'Already have an account?',
    what: 'sign-in link',
  },
];

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

for (const s of SCREENS) {
  const src = fs.readFileSync(path.join(FRONTEND, s.file), 'utf8');
  const name = path.basename(s.file);
  console.log(`\n-- ${name}: is the ${s.what} reachable? --`);

  ok(src.includes(s.linkText), `ANCHOR: the ${s.what} exists at all`);

  // 1. UNCONDITIONAL. A link behind a conditional is not reachable on first
  //    paint, and an App Store reviewer only gets first paint.
  const linkAt = src.indexOf(s.linkPush);
  ok(linkAt > -1, 'ANCHOR: the link navigates somewhere');
  const before = src.slice(Math.max(0, linkAt - 400), linkAt);
  ok(!/\{\s*\w+[^}]{0,40}&&\s*\($/.test(before.trim()),
    'not wrapped in a conditional immediately above it');

  // 2. SCROLLABLE. The centred stack exceeds a short viewport; without a
  //    ScrollView the ends are clipped with no way to reach them. This is what
  //    02649d3 added.
  ok(/<ScrollView/.test(src),
    'inside a ScrollView — a centred stack taller than the viewport is '
    + 'otherwise clipped at both ends with no way to scroll (02649d3)');
  ok(/contentContainerStyle=\{s\.scrollContent\}/.test(src),
    'and the scroll content style is the one asserted below');

  // 3. THE BOTTOM SAFE-AREA EDGE. This is the assertion 0e87696 would fail.
  //    A centred layout whose last child is a link must keep the bottom inset
  //    or that link lands on the home indicator.
  ok(/<SafeAreaView[^>]*edges=\{\['top', 'bottom'\]\}/.test(src),
    "edges={['top', 'bottom']} — dropping the bottom edge on a CENTRED layout "
    + 'puts the last element on the home indicator. 0e87696 did exactly that '
    + 'and this assertion is what would have caught it');

  // 4. TRAILING SCROLL EXTENT. With the keyboard up the viewport loses ~336pt
  //    on a 6.1" device and the stack overflows; without padding the link's
  //    last pixel is the content edge and can rest flush against the keyboard.
  // The style DEFINITION, not the JSX usage: contentContainerStyle=
  // {s.scrollContent} appears first in the file, so indexOf lands on the
  // render tree and the window never reaches the StyleSheet.
  const style = src.slice(src.indexOf('scrollContent:'));
  ok(/paddingBottom: spacing\.xxl/.test(style.slice(0, 400)),
    'scrollContent has trailing paddingBottom so the link can be scrolled '
    + 'CLEAR of a raised keyboard, not merely up against it');

  // 5. And the centring that makes all of the above necessary is still there —
  //    if someone removes it, these assertions are guarding a shape that no
  //    longer exists and should be revisited rather than silently passing.
  ok(/flexGrow: 1/.test(style.slice(0, 400))
    && /justifyContent: 'center'/.test(style.slice(0, 400)),
    "ANCHOR: the layout is still centred (flexGrow + justifyContent 'center'), "
    + 'which is the shape these guards exist for');
}

console.log('\n-- the ten other screens 0e87696 touched are NOT centred --');
{
  // Scoping check: if one of them ever gains a centred scroll container with
  // no bottom padding, it joins the two above and this test should be extended.
  const others = [
    'app/admin/users.jsx', 'app/checkin/index.jsx', 'app/project/[id].jsx',
    'app/project/[id]/dob-logs.jsx', 'app/project/[id]/permit-renewal.jsx',
    'app/project/[id]/report-settings.jsx', 'app/project/[id]/trades.jsx',
    'app/workers/[id].jsx',
  ];
  const risky = [];
  for (const f of others) {
    const src = fs.readFileSync(path.join(FRONTEND, f), 'utf8');
    const i = src.indexOf('scrollContent:');
    if (i < 0) continue;
    const style = src.slice(i, i + 400);
    if (/justifyContent: 'center'/.test(style) && !/paddingBottom/.test(style)) {
      risky.push(f);
    }
  }
  ok(risky.length === 0,
    'none of them has a centred scroll container without bottom padding — if '
    + `one gains it, it carries the same defect. Found: ${JSON.stringify(risky)}`);
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
