/**
 * The shared stepper's rules — asserted ONCE, for every form that will use it.
 *
 * These are the same rules dailyJobsiteStepper.test.cjs has always enforced on
 * the Daily Jobsite Log. That screen is the only implementation an operator
 * has device-tested and approved, so its shape is the evidence and the chrome
 * was lifted verbatim rather than redesigned. The point of asserting them here
 * as well is that ten forms cannot each drift: a port that loses the 56pt
 * target, the single primary action or the amber pip fails on THIS file,
 * whichever screen it happens to be.
 *
 * Run:  node src/components/logbookStepper/stepper.test.cjs
 */
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const FRONTEND = path.join(HERE, '..', '..', '..');
const raw = (f) => fs.readFileSync(path.join(HERE, f), 'utf8');

function stripComments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\s\/\/[^\n'"`]*$/gm, '');
}
const chromeRaw = raw('LogbookStepper.jsx');
const primsRaw = raw('primitives.jsx');
const stylesRaw = raw('styles.js');
const chrome = stripComments(chromeRaw);
const prims = stripComments(primsRaw);
const styles = stripComments(stylesRaw);

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const block = (src, key) => (
  src.match(new RegExp(`\\n\\s{4}${key}:\\s*\\{([\\s\\S]*?)\\n\\s{4}\\}`)) || [, '']
)[1];

console.log('\n-- One primary action, and it is the largest thing on screen --');

const footer = chrome.slice(chrome.indexOf('<View style={s.footer}>'),
  chrome.lastIndexOf('</SafeAreaView>'));
ok((footer.match(/<Pressable/g) || []).length === 2,
  'the footer renders one button per branch — Next XOR submit');
ok(/step < total \?/.test(footer),
  'the two branches are mutually exclusive, so only one is ever on screen');
ok(/touchTarget\.primary/.test(block(styles, 'primaryBtn')),
  'the primary button uses the LARGER primary target');
ok(/typography\.sizes\.xl/.test(block(styles, 'primaryBtnText')),
  'and its label is the largest type available');
ok(!/Save Draft|saveDraft/.test(chrome), 'there is no Save Draft — forms autosave');

console.log('\n-- 56pt minimum on everything tappable --');

for (const name of ['chip', 'input', 'secondaryBtn', 'primaryBtn', 'headerBack',
  'toggleRow']) {
  const b = block(styles, name);
  ok(/minHeight: touchTarget\.(min|primary)/.test(b)
    || /minWidth: touchTarget\.(min|primary)/.test(b),
  `${name} carries a touchTarget minimum`);
}
ok(!/minHeight:\s*\d/.test(styles), 'no hardcoded minHeight — every target is a token');

console.log('\n-- The pips: position AND completeness, and they never gate --');

ok(/n <= step && s\.progressPipOn/.test(chrome), 'reached steps are filled');
ok(/incompleteSteps\.includes\(n\) && s\.progressPipWarn/.test(chrome),
  'a step LEFT incomplete goes amber');
const pipArr = chrome.slice(chrome.indexOf('s.progressPip,'),
  chrome.indexOf(']}', chrome.indexOf('s.progressPip,')));
ok(pipArr.indexOf('progressPipOn') > -1
  && pipArr.indexOf('progressPipOn') < pipArr.indexOf('progressPipWarn'),
  'and amber outranks "reached" — it is the more important of the two');
ok(/progressPipWarn: \{ backgroundColor: outdoor\.warn \}/.test(styles),
  'from the warn token, not a literal');
ok(/accessibilityRole="progressbar"/.test(chrome),
  'colour alone is weak outdoors, so the row says it out loud');
// It marks; it must never BLOCK.
ok(!/disabled=\{[^}]*incompleteSteps/.test(chrome),
  'an incomplete step never disables anything — a CP must be able to finish his day');

console.log('\n-- Tap only, and locked means locked --');

ok(!/onLongPress|PanResponder|Swipeable|GestureDetector/.test(chrome),
  'no gestures anywhere in the chrome');
ok(/pointerEvents=\{locked \? 'none' : 'auto'\}/.test(chrome),
  'a finalized log renders read-only in ONE place, with no per-field flags to miss');
ok(/\{!locked && \(/.test(chrome), 'and the primary action disappears when locked');
ok(/canFinalize=\{false\}/.test(chrome), 'the lock bar never offers finalize from here');

console.log('\n-- Lifted verbatim, and still token-only --');

ok(/<AnimatedBackground>/.test(chrome), 'the blue gradient background, not a flat grey');
ok(!/backgroundColor/.test(block(styles, 'scroll')),
  'the scroll view paints NO background — a flat fill hid the gradient once');
ok(/colors=\{\[outdoor\.cardTop, outdoor\.cardBottom\]\}/.test(prims),
  'the card is a white->blue gradient, the values GlassCard uses');
ok((prims.match(/<LinearGradient/g) || []).length === 1,
  'and it is ONE Card component, so every surface matches');
for (const [label, src] of [['chrome', chrome], ['styles', styles], ['primitives', prims]]) {
  ok(!/#[0-9a-fA-F]{6}\b/.test(src), `no hex literals in the ${label}`);
  ok(!/rgba\(/.test(src), `no rgba() literals in the ${label}`);
}

console.log('\n-- Module-level components, which is load-bearing --');

// A component declared inside a render function is a new TYPE every render, so
// React remounts every chip on each keystroke. On the phones these screens are
// built for that is the difference between usable and not.
for (const name of ['Card', 'ChipBase', 'StepHeaderBase', 'PromptModal']) {
  ok(new RegExp(`^export function ${name}\\(`, 'm').test(prims),
    `${name} is declared at module level`);
}

console.log('\n-- The step contract the reference settled on --');

ok(/steps\[step - 1\]/.test(chrome), 'steps are 1-indexed, as the reference had them');
ok(/current && current\.render\(\)/.test(chrome),
  'one step renders at a time, where STEPS[step]() used to be');
ok(/const total = steps\.length;/.test(chrome),
  'and the count comes from the list, so a 2-step form is not forced to five');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
