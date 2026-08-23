/**
 * Every SafeAreaView says which edges it insets.
 *
 * API 36 enforces edge-to-edge and it cannot be turned off, so the app draws
 * under the status and navigation bars and each screen has to say what it wants
 * inset. A BARE <SafeAreaView> applies all four edges — which is not wrong so
 * much as unstated, and it quietly disagrees with the 46 screens that ask for
 * ['top'] alone.
 *
 * THE SETTLED PATTERN, which this locks in rather than invents: inset the
 * status bar, handle the bottom with scroll padding (120 on 32 screens). The
 * bottom inset is deliberately NOT applied at the screen level.
 *
 * WHY THAT IS SAFE HERE, checked per file rather than assumed — dropping to
 * ['top'] REMOVES a bottom inset those twelve files had:
 *
 *   9 files  scroll paddingBottom of 120, or spacing.xxl (48)
 *   3 files  login, register, nfc/index — no padding, but all three centre
 *            their content (flexGrow: 1 + justifyContent: 'center'), so
 *            nothing sits at the bottom edge
 *
 * None of the twelve renders a bottom-anchored control.
 *
 *   node frontend/src/utils/safeAreaEdges.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.name.endsWith('.jsx')) out.push(p);
  }
  return out;
}

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

const screens = walk(path.join(FRONTEND, 'app'));
const sources = screens.map((f) => [f, fs.readFileSync(f, 'utf8')]);

console.log('\n-- the library is the one that works on Android --');
{
  // react-native's own SafeAreaView is iOS-ONLY and a silent no-op on Android.
  // Under enforced edge-to-edge that is content under the status bar with
  // nothing in the diff to show for it.
  const wrong = sources.filter(([, s]) =>
    /^import\s*\{[^}]*\bSafeAreaView\b[^}]*\}\s*from\s*'react-native'/m.test(s));
  ok(wrong.length === 0,
    'no SafeAreaView imported from react-native — that one does nothing on '
    + `Android. Found: ${JSON.stringify(wrong.map(([f]) => path.basename(f)))}`);
  const ctx = sources.filter(([, s]) => /from 'react-native-safe-area-context'/.test(s));
  ok(ctx.length > 40, `ANCHOR: safe-area-context is what screens import (${ctx.length})`);
}

console.log('\n-- every usage declares its edges --');
{
  const bare = [];
  for (const [f, s] of sources) {
    for (const m of s.match(/<SafeAreaView[^>]*>/g) || []) {
      if (!m.includes('edges=')) bare.push(`${path.basename(f)} ${m.slice(0, 40)}`);
    }
  }
  ok(bare.length === 0,
    'no bare <SafeAreaView> — a bare one insets all four edges implicitly, '
    + 'which disagrees with the 46 that ask for [\'top\'] and hides the '
    + `intent. Found: ${JSON.stringify(bare)}`);
}

console.log('\n-- and the declared edges are the settled pattern --');
{
  const edges = {};
  for (const [, s] of sources) {
    for (const m of s.match(/edges=\{\[[^\]]*\]\}/g) || []) {
      edges[m] = (edges[m] || 0) + 1;
    }
  }
  const top = edges["edges={['top']}"] || 0;
  ok(top > 50, `['top'] is the dominant form (${top} usages)`);
  // A screen asking for 'bottom' is not forbidden, but it is a decision: the
  // bottom is handled by scroll padding everywhere else, and mixing the two
  // double-pads. One screen does it deliberately today.
  const withBottom = Object.entries(edges).filter(([k]) => k.includes('bottom'));
  ok(withBottom.length <= 1,
    'at most one screen insets the bottom at the screen level — everywhere '
    + `else that is scroll padding's job. Found: ${JSON.stringify(withBottom)}`);
}

console.log('\n-- the provider is still above all of them --');
{
  const layout = fs.readFileSync(path.join(FRONTEND, 'app', '_layout.jsx'), 'utf8');
  ok(/<SafeAreaProvider>/.test(layout),
    'SafeAreaProvider wraps the tree — without it every inset reads zero');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
