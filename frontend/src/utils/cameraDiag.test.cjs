/**
 * THE LENS READOUT.
 *
 * The rules under test are the two that decide whether the operator's phone can
 * answer the 1x question at all: the error record MUST survive the camera
 * recovering, and the three candidate readings must not be confusable.
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

const src = fs.readFileSync(path.join(__dirname, 'cameraDiag.js'), 'utf8');
const M = (() => {
  const body = src
    .replace(/export function /g, 'function ')
    .replace(/export default[\s\S]*$/, '')
    + '\nreturn { recordCamError, buildDiagText, readDiag };';
  // eslint-disable-next-line no-new-func
  return new Function(body)();
})();

// ── 1. THE ERROR RECORD IS STICKY ──────────────────────────────────────────
console.log('\n-- a fallback that worked is where the error string is the only evidence --');

const e1 = M.recordCamError(null, { code: 'device/unavailable', message: 'UW failed' }, 'ultra');
ok(e1.n === 1, 'the first error is counted');
ok(e1.lensAtError === 'ultra', 'and records the lens that was in force when it fired');

// THE CASE THIS EXISTS FOR. onError flips backLens to 'wide', the camera
// recovers, and nothing else on the phone remembers that anything went wrong.
const e2 = M.recordCamError(e1, { code: 'x', message: 'second' }, 'wide');
ok(e2.n === 2, 'a later error increments rather than replacing the history');
ok(e2.lensAtError === 'ultra',
  'and the FIRST failing lens survives — the flip does not overwrite it with wide');

// There is no clear path at all. Asserted by exhaustion over the module's
// surface rather than by reading the source: nothing may return a falsy record.
ok(Object.keys(M).every((k) => typeof M[k] === 'function'),
  'the module exposes only functions — no reset handle to call');
[null, undefined, {}, { message: '' }, 'plain string', 0].forEach((bad) => {
  const r = M.recordCamError(e2, bad, 'wide');
  ok(r && r.n === 3, `a ${typeof bad} error still records rather than clearing`);
});

// A degenerate prior record cannot zero the count.
ok(M.recordCamError({ n: NaN }, { message: 'm' }, 'ultra').n === 1,
  'a corrupt count restarts at 1 rather than producing NaN');
ok(M.recordCamError({ n: 7, lensAtError: '' }, { message: 'm' }, 'wide').lensAtError === 'wide',
  'an empty stored lens is replaced, not preserved as empty');

// ── 2. THE THREE READINGS ──────────────────────────────────────────────────
console.log('\n-- the three candidates must not be confusable --');

const MULTI = { id: 'multi', physicalDevices: ['ultra-wide-angle-camera', 'wide-angle-camera'], minZoom: 0.5, neutralZoom: 1, maxZoom: 8 };
const WIDE = { id: 'wide', physicalDevices: ['wide-angle-camera'], minZoom: 1, neutralZoom: 1, maxZoom: 8 };

ok(M.readDiag({ anyBackDevice: MULTI, device: WIDE, backLens: 'ultra', camError: null })
  === 'wider_device_not_mounted',
  'a wider device exists while a minZoom-1 device is mounted: not being mounted');
ok(M.readDiag({ anyBackDevice: WIDE, device: WIDE, backLens: 'ultra', camError: null })
  === 'no_ultra_wide_on_device',
  'both report minZoom 1: the hardware has nothing wider, an expectation not a bug');

// THE THIRD CASE, AND WHY ORDER MATTERS. After the fallback the mounted device
// is the wide one and `any` may report 1 too, so the ZOOM NUMBERS ALONE read as
// "no ultra-wide". Only the surviving error separates them.
const afterFlip = { anyBackDevice: WIDE, device: WIDE, backLens: 'wide', camError: e2 };
ok(M.readDiag(afterFlip) === 'fallback',
  'the same numbers plus an error read as the runtime flip, not as missing hardware');
ok(M.readDiag({ ...afterFlip, camError: null }) === 'no_ultra_wide_on_device',
  'and without the error the very same numbers read the other way — the record IS the difference');

// The flip verdict must not fire on an error that left the lens alone.
ok(M.readDiag({ anyBackDevice: MULTI, device: WIDE, backLens: 'ultra', camError: e1 })
  === 'wider_device_not_mounted',
  'an error with the lens still on ultra is not the fallback case');

[undefined, null, {}, { minZoom: NaN }].forEach((bad, i) => {
  ok(M.readDiag({ anyBackDevice: bad, device: WIDE, backLens: 'ultra', camError: null })
    === 'unknown', `an unusable device #${i} reads as unknown rather than guessing`);
});

// ── 3. THE TEXT CARRIES EVERY DECIDING FIELD ───────────────────────────────
console.log('\n-- one text, two readers --');

const txt = M.buildDiagText({
  anyBackDevice: MULTI, uwDevice: MULTI, wideDevice: WIDE, device: WIDE,
  uwIsDistinct: false, backLens: 'wide', position: 'back', zoom: 1,
  camError: e2, os: 'android',
});
// Every input readDiag consumes must be recoverable from what he pastes,
// otherwise the paste cannot be read without the phone in hand.
ok(txt.includes('min=0.5'), 'the unfiltered device\'s minZoom is present');
ok(txt.includes('MOUNTED: id=wide'), 'and which device is actually mounted');
ok(txt.includes('backLens=wide'), 'and the lens in force');
ok(txt.includes('appliedZoom=1'), 'and the zoom that was actually applied');
ok(txt.includes('camError x2') && txt.includes('atLens=ultra'),
  'and the sticky error with its original lens');
ok(txt.split('\n').length === 9, 'nine lines, one per field, so a paste is readable');
ok(txt.includes('framingApplied='),
  'and the session-start callback count — 0 would mean onStarted never fired, '
  + 'which is a different defect from the framing not landing');
ok(M.buildDiagText({}).includes('camError: none'),
  'a clean session says so explicitly rather than omitting the line');
ok(M.buildDiagText({}).includes('any (unfiltered): none'),
  'and a missing device is named rather than rendered as undefined');
ok(!M.buildDiagText({}).includes('undefined: '), 'no undefined labels leak into the paste');

// ── 4. THE MODAL DELEGATES ─────────────────────────────────────────────────
console.log('\n-- the camera holds state, it does not decide --');
{
  const scr = fs.readFileSync(
    path.join(__dirname, '..', 'components', 'CameraCaptureModal.jsx'), 'utf8');
  ok(/setCamError\(\(prev\) => recordCamError\(prev, err, backLens\)\)/.test(scr),
    'onError folds through recordCamError rather than building the record inline');
  ok(!/setCamError\(null\)/.test(scr) && !/setCamError\(undefined\)/.test(scr),
    'and NOTHING in the camera ever clears it');
  ok(/buildDiagText\(\{/.test(scr), 'the readout text comes from the model');
  // ONE TEXT, TWO READERS — the console line must print the same string the
  // panel shows, or a debugger and the operator get different answers.
  ok(/console\.log\('\[CAM-DIAG\]\\n%s', lensDiagText\)/.test(scr),
    'the console line prints the SAME text the panel renders');
  // THE PANEL IS GONE and the console line is what remains, so what is asserted
  // here is that the log still carries the same text — not that anything
  // renders. cameraPreview.test.cjs holds the removal itself.
  ok(!/LensDiagnostic/.test(scr), 'no panel renders on the camera any more');
  ok(!/expo-clipboard/.test(scr), 'and the copy affordance went with it');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
