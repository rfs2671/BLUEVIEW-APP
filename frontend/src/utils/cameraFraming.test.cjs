/**
 * RE-ASSERTING THE FRAMING WHEN THE SESSION STARTS.
 *
 * The defect was confirmed on device across two predictions, not reasoned from
 * source — four earlier diagnoses were reasoned from source and all four were
 * wrong. What is asserted here is what the fix must do differently from those
 * four: send the CURRENT zoom, at the moment the library says the session
 * started, as a value React will actually commit.
 */
const fs = require('fs');
const path = require('path');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); } else {
    failed += 1; console.log('  FAIL ', label);
  }
}

const src = fs.readFileSync(path.join(__dirname, 'cameraFraming.js'), 'utf8');
const M = (() => {
  const body = src.replace(/export function /g, 'function ')
    .replace(/export default[\s\S]*$/, '')
    + '\nreturn { framingNudge, framingTarget };';
  // eslint-disable-next-line no-new-func
  return new Function(body)();
})();

// The operator's phone: one logical camera, wide + ultra-wide + telephoto.
const MIN = 0.508;
const MAX = 30;

// ── 1. THE NUDGE IS A REAL PROP CHANGE ─────────────────────────────────────
console.log('\n-- React does not write a prop whose value has not changed --');

const n = M.framingNudge(MIN, MIN, MAX);
ok(n !== null && n !== MIN,
  'the nudge DIFFERS from the target — an equal value is the no-op the camera is stuck in');
ok(n >= MIN && n <= MAX, 'and stays inside the device range, so it cannot be clamped back to the target');

// AT minZoom THE NUDGE MUST GO UP, and that is the case that matters: ultra-wide
// sits exactly on minZoom, where a downward step leaves the range and would be
// clamped straight back to minZoom — equal to the target, no push, no fix.
ok(n > MIN, 'at minZoom it steps UP, because down would leave the range and be clamped back');

// Anywhere else it prefers DOWN, because up from a low zoom is a step toward
// the 1x this exists to prevent.
ok(M.framingNudge(3, MIN, MAX) < 3, 'away from the floor it steps down, never toward 1x');

// Small enough to be invisible, and gone the next frame regardless.
ok(Math.abs(M.framingNudge(3, MIN, MAX) - 3) < 0.05,
  'the step is far below anything visible');
ok(M.framingNudge(MIN, MIN, MIN + 1e-9) === null,
  'a range with no room returns null rather than a value equal to the target');
ok(M.framingNudge(1, 1, 1) === null, 'a device that cannot zoom has nothing to re-assert');

[[NaN, MIN, MAX], [MIN, NaN, MAX], [MIN, MIN, NaN], [undefined, MIN, MAX],
  ['0.5', MIN, MAX], [MIN, null, MAX], [Infinity, MIN, MAX]].forEach((args, i) => {
  ok(M.framingNudge(...args) === null, `unusable input #${i} returns null rather than a bad zoom`);
});

// ── 2. THE CURRENT ZOOM, NOT minZoom ───────────────────────────────────────
console.log('\n-- prediction 2: a CP who pinched to 3x and reopened must get 3x back --');

ok(M.framingTarget(3, MIN, MAX) === 3,
  'the target is what he was ON, not the wide end');
ok(M.framingTarget(MIN, MIN, MAX) === MIN,
  'and on a fresh open that is minZoom, which is the ultra-wide framing');
ok(M.framingTarget(MAX + 5, MIN, MAX) === MAX
  && M.framingTarget(MIN - 5, MIN, MAX) === MIN,
  'a stale value from another device is clamped into range rather than sent raw');
ok(M.framingTarget(3, undefined, undefined) === 3,
  'with no range known the current value passes through unchanged');
[NaN, undefined, null, '3'].forEach((bad) => {
  ok(M.framingTarget(bad, MIN, MAX) === null,
    `an unusable current zoom (${String(bad)}) re-asserts nothing rather than guessing`);
});

// THE WHOLE POINT, END TO END: nudge then target lands back on what he was on.
{
  const target = M.framingTarget(3, MIN, MAX);
  const nudge = M.framingNudge(target, MIN, MAX);
  ok(nudge !== target && target === 3,
    'two distinct writes, and the second is exactly the zoom he was already on');
}

// ── 3. THE COMPONENT USES THE LIBRARY'S CALLBACKS, NOT A REACT FLAG ────────
console.log('\n-- onStarted is when vision-camera says so; isActive is when React thinks so --');
{
  const scr = fs.readFileSync(
    path.join(__dirname, '..', 'components', 'CameraCaptureModal.jsx'), 'utf8');

  ok(/onStarted=\{reapplyFraming\}/.test(scr), 'onStarted re-asserts the framing');
  ok(/onInitialized=\{reapplyFraming\}/.test(scr),
    'and so does onInitialized, which covers a re-init without a stop');

  // THE RULING. A dependency on a React flag would be fixing a timing bug with
  // a different guess at the timing, and would miss every start that arrives
  // without a re-render — a remount, a recovery after onError, a background
  // return.
  const framingEffect = scr.slice(scr.indexOf('const lensDevice = position'));
  const deps = (framingEffect.match(/\}, \[([^\]]*)\]\);/) || [])[1] || '';
  ok(!/\bactive\b/.test(deps),
    'the framing effect does NOT depend on the React active flag');

  // The captured target, not the ref read late. The `zoom` effect rewrites
  // currentZoomRef on every render, so by the second write the ref holds the
  // NUDGE — reading it there would strand the camera one step off target.
  ok(/const target = framingTarget\(currentZoomRef\.current/.test(scr),
    'the target is captured BEFORE the nudge is written');
  const raf = scr.slice(scr.indexOf('requestAnimationFrame(() => {'));
  ok(/setZoom\(target\)/.test(raf.slice(0, 200)),
    'and the second write sends that captured target, not the ref');
  ok(!/setZoom\(currentZoomRef\.current\)/.test(raf.slice(0, 200)),
    'never the ref, which by then holds the nudge');

  // Two COMMITS. React batches within a handler, so both writes in one tick
  // collapse to a single render and a single prop — the same no-op being fixed.
  const body = scr.slice(scr.indexOf('const reapplyFraming'),
    scr.indexOf('const reapplyFraming') + 1800);
  // NOT a loose "nudge ... somewhere later ... requestAnimationFrame" match:
  // that stayed green against a mutant which wrote both values and RETURNED
  // before ever reaching the rAF, which is precisely the single-batch no-op
  // this whole change exists to break. Assert the SPAN between the two writes
  // instead — nothing may sit between the nudge and the frame boundary.
  const iNudge = body.indexOf('setZoom(nudge);');
  const iRaf = body.indexOf('requestAnimationFrame(');
  ok(iNudge !== -1 && iRaf > iNudge, 'the nudge is written before the frame boundary');
  // COMMENTS STRIPPED FIRST. The span carries a comment explaining why the two
  // writes are separated, and it quotes `setZoom(nudge); setZoom(target)` as
  // the thing NOT to do — matching against the raw text would fail on the
  // documentation of the very rule being asserted.
  const between = body.slice(iNudge + 'setZoom(nudge);'.length, iRaf)
    .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
  ok(!/setZoom\(/.test(between),
    'and the target is NOT written in the same tick — React would batch them into '
    + 'one render and one prop, which is the no-op being fixed');
  ok(!/\breturn\b/.test(between),
    'and nothing returns before the frame boundary is reached');

  // Re-entrancy: both callbacks can fire for one start.
  ok(/if \(reapplyPendingRef\.current\) return;/.test(body),
    'a second callback for the same start cannot strand the camera on the nudge');
  ok(/reapplyPendingRef\.current = false;/.test(raf.slice(0, 400)),
    'and the latch is released in the same frame the target lands');

  // It must not have quietly become a reset-to-wide.
  ok(!/setZoom\(lensDevice\?\.minZoom\)/.test(body) && !/framingTarget\(min/.test(body),
    'the re-apply never sends minZoom — that would reset a CP who had pinched');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
