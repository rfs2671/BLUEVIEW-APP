/**
 * The card sheen answers a pointer: on hover (or press) its hairline stretches from ~80% of the card to all of it and
 * a second wash fades in. This pins the three things that would silently break that:
 *   1. the component animates ONLY transform and opacity (never layout), eases out, and honours reduced motion;
 *   2. every card that carries a sheen tells it when the card is hovered or pressed (an `active` prop);
 *   3. a Pressable that passes `active` reads hover from its children function, not from a style that is not there.
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
ok(/REST_SCALE\s*=\s*0\.8/.test(sheen) && /outputRange:\s*\[REST_SCALE,\s*1\]/.test(sheen), 'the hairline stretches from 80% to the full width');
ok(/transform:\s*\[\{\s*scaleX\s*\}\]/.test(sheen) && /opacity:\s*lineOpacity/.test(sheen), 'the hairline moves by transform and opacity only');
ok(!/Animated\.[a-z]+\([^)]*\b(width|height|left|right|top)\b\s*:/.test(sheen), 'nothing animates a layout property');
ok(/Easing\.out\(/.test(sheen) && /DURATION\s*=\s*240/.test(sheen), 'it eases out over 240ms');
ok(/useNativeDriver:\s*Platform\.OS\s*!==\s*'web'/.test(sheen), 'it uses the native driver wherever there is one');
ok(/prefers-reduced-motion/.test(sheen) && /isReduceMotionEnabled/.test(sheen) && /t\.setValue\(active \? 1 : 0\)/.test(sheen), 'reduced motion jumps to the end state instead of animating');
ok(/run\.stop\(\)/.test(sheen), 'a running animation is stopped when the state changes, so it re-targets from where it is');
ok(/pointerEvents="none"/.test(sheen) && /importantForAccessibility="no-hide-descendants"/.test(sheen), 'it still takes no touches and is hidden from assistive tech');

console.log('\n── Every card tells the sheen when it is hovered ──');
const glass = read('src/components/GlassCard.js');
ok(/<CardSheen radius=\{borderRadius\.xxl\} active=\{isHovered && hoverEffect\} \/>/.test(glass), 'GlassCard (respecting hoverEffect={false})');
ok((glass.match(/<CardSheen radius=\{borderRadius\.xl\} active=\{isHovered\} \/>/g) || []).length === 2, 'StatCard and GlassListItem');
const dash = read('app/index.jsx');
ok(/<CardSheen radius=\{borderRadius\.lg\} active=\{isHovered\} \/>/.test(dash), 'the dashboard tool tile (phone)');
ok(/body = \(active\) =>/.test(dash) && /\{\(\{ hovered, pressed \}\) => body\(!!\(hovered \|\| pressed\)\)\}/.test(dash) && /\{body\(false\)\}/.test(dash), 'the portfolio exposure cards (a zero card has nothing to hover)');
ok(/<CardSheen radius=\{borderRadius\.md\} depth=\{22\} active=\{!!\(hovered \|\| pressed\)\} \/>/.test(dash), 'the desktop tool buttons');
const proj = read('app/project/[id].jsx');
ok(/<CardSheen radius=\{borderRadius\.xl\} active=\{!!\(hovered \|\| pressed\)\} \/>/.test(proj), 'the project quick actions');
ok(!/<CardSheen [^>]*\/>/.test(dash.replace(/<CardSheen [^>]*active=[^>]*\/>/g, '')) && !/<CardSheen [^>]*\/>/.test(proj.replace(/<CardSheen [^>]*active=[^>]*\/>/g, '')), 'no card in those screens was left without the prop');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
