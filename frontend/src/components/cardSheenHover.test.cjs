/**
 * The card sheen answers you. On hover or press the card lights up (a 3px line, full width, with a glow, a highlight that
 * sweeps across it, a deeper tint); a press is held a moment so a quick tap shows the whole of it; and a card plays it
 * once when it first appears, because a phone has no hover. This pins what would silently break that:
 *   1. the component animates ONLY transform and opacity, eases out, holds a press, and honours reduced motion;
 *   2. every card that carries a sheen tells it when it is hovered or pressed (an `active` prop);
 *   3. the cards that should announce themselves pass `intro`, and the long lists do not.
 *
 * Dependency-free: it reads source.
 */
const fs = require('fs');
const path = require('path');

const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8').replace(/\r\n/g, '\n');
let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const sheen = read('src/components/CardSheen.jsx');
console.log('\n── The animation itself ──');
ok(/REST_SCALE\s*=\s*0\.8/.test(sheen) && /outputRange:\s*\[REST_SCALE,\s*1\]/.test(sheen), 'the line stretches from 80% to the full width');
ok(/THICK\s*=\s*3/.test(sheen) && /styles\.thick/.test(sheen) && /opacity:\s*level/.test(sheen), 'a 3px line fades in as the card lights up');
ok(/styles\.bar/.test(sheen) && /translateX:\s*sweepX/.test(sheen), 'a highlight sweeps along the line');
ok(!/Animated\.[a-z]+\([^)]*\b(width|height|left|right|top)\b\s*:/.test(sheen), 'nothing animates a layout property (transform and opacity only)');
ok(/Easing\.out\(/.test(sheen) && /IN_MS\s*=\s*260/.test(sheen) && /SWEEP_MS\s*=\s*640/.test(sheen), 'it eases out; 260ms in, a 640ms sweep');
ok(/HOLD_MS\s*=\s*420/.test(sheen) && /setTimeout\(\(\) => setHeld\(false\), HOLD_MS\)/.test(sheen), 'a press is held 420ms after it ends so a quick tap shows the whole of it');
ok(/intro/.test(sheen) && /Animated\.sequence\(/.test(sheen) && /introDelay/.test(sheen), 'with `intro` the card plays it once, a beat after it appears, staggered');
ok(/useNativeDriver:\s*native/.test(sheen) && /Platform\.OS\s*!==\s*'web'/.test(sheen), 'it uses the native driver wherever there is one');
ok(/prefers-reduced-motion/.test(sheen) && /isReduceMotionEnabled/.test(sheen) && /lit\.setValue\(on \? 1 : 0\)/.test(sheen) && /if \(!intro \|\| reduce\)/.test(sheen) && /if \(!on \|\| reduce\)/.test(sheen), 'reduced motion: no sweep, no intro, the state just changes');
ok(/run\.stop\(\)/.test(sheen), 'a running animation is stopped when the state changes, so it re-targets from where it is');
ok(/pointerEvents="none"/.test(sheen) && /importantForAccessibility="no-hide-descendants"/.test(sheen), 'it still takes no touches and is hidden from assistive tech');

console.log('\n── Every card tells the sheen when it is hovered ──');
const glass = read('src/components/GlassCard.js');
ok(/<CardSheen radius=\{borderRadius\.xxl\} active=\{isHovered && hoverEffect\} intro \/>/.test(glass), 'GlassCard (respecting hoverEffect={false}), and it announces itself');
ok(/<CardSheen radius=\{borderRadius\.xl\} active=\{isHovered\} intro \/>/.test(glass), 'StatCard, and it announces itself');
ok(/<CardSheen radius=\{borderRadius\.xl\} active=\{isHovered\} \/>/.test(glass), 'GlassListItem answers a hover but does not play the intro (a list can be long)');
const dash = read('app/index.jsx');
ok(/<CardSheen radius=\{borderRadius\.lg\} active=\{isHovered\} intro \/>/.test(dash), 'the dashboard tool tile (phone)');
ok(/body = \(active\) =>/.test(dash) && /\{\(\{ hovered, pressed \}\) => body\(!!\(hovered \|\| pressed\)\)\}/.test(dash) && /\{body\(false\)\}/.test(dash), 'the portfolio exposure cards (a zero card has nothing to press)');
ok(/<CardSheen radius=\{borderRadius\.md\} depth=\{22\} active=\{!!\(hovered \|\| pressed\)\} intro \/>/.test(dash), 'the desktop tool buttons');
ok((dash.match(/translateY: -2/g) || []).length === 3, 'the three dashboard tile kinds lift 2px when lit');
const proj = read('app/project/[id].jsx');
ok(/<CardSheen radius=\{borderRadius\.xl\} active=\{!!\(hovered \|\| pressed\)\} intro \/>/.test(proj), 'the project quick actions');
const logs = read('app/logbooks/index.jsx');
ok((logs.match(/<CardSheen radius=\{borderRadius\.xl\} active=\{!!\(hovered \|\| pressed\)\} intro \/>/g) || []).length === 2, 'both log-book list cards');
ok(/<CardSheen radius=\{borderRadius\.lg\} intro \/>/.test(read('src/components/SyncButton.jsx')), 'the sync card');

console.log('\n── Boxes a screen draws itself ──');
const sv = read('src/components/SheenView.jsx');
ok(/<CardSheen radius=\{typeof radius === 'number' \? radius : 14\}/.test(sv) && /StyleSheet\.flatten\(style\)/.test(sv), 'SheenView reads the corner radius from the box\'s own style');
ok(/\{\.\.\.rest\} style=\{style\}/.test(sv), 'and is a plain View in every other respect');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
