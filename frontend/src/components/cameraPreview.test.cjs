/**
 * THE CAMERA PREVIEW, AND WHY IT WAS BLACK.
 *
 * Device round 5, finding 28: the CP reached the camera, saw the full chrome —
 * shutter, thumbnails, close — and a BLACK preview. No photo could be taken.
 *
 * The chain, every link read out of the library's own source rather than
 * guessed at:
 *
 *   1. This screen PRE-WARMS the camera: the surface is mounted for the life of
 *      the screen and hidden with `opacity: 0` (overlayHidden), deliberately,
 *      because VisionCamera needs a laid-out non-zero surface to configure
 *      against.
 *   2. VisionCamera v4 defaults androidPreviewViewType to SURFACE_VIEW
 *      (CameraView.kt:91) -> ImplementationMode.PERFORMANCE -> a SurfaceView.
 *   3. A SurfaceView CANNOT BE ALPHA-COMPOSITED. It punches a hole through the
 *      window rather than drawing into the view hierarchy, so a parent with
 *      alpha < 1 forces the subtree into a hardware layer it does not join —
 *      and returning to opacity 1 does not reliably re-attach it.
 *   4. Capture failed for the SAME reason, not a second one. Android's
 *      takeSnapshot is `previewView.bitmap ?: throw SnapshotFailedError()`
 *      (CameraView+TakeSnapshot.kt), and getBitmap() returns null when the
 *      preview is not rendering.
 *
 * So one prop fixes both halves. This file pins the prop AND the reasoning,
 * because the prop looks arbitrary without it and the next person tuning
 * camera performance will be tempted to take it back.
 *
 * Run:  node src/components/cameraPreview.test.cjs
 */
const fs = require('fs');
const path = require('path');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const MODAL = path.join(__dirname, 'CameraCaptureModal.jsx');
const raw = fs.readFileSync(MODAL, 'utf8');

/**
 * Comments stripped before every assertion below.
 *
 * This file EXPLAINS the props it asserts, at length, quoting them by name — so
 * matching raw source would pass with the prop deleted and the explanation
 * intact. That exact shape has defeated a mutation check three times on this
 * project, most recently on keyboardShouldPersistTaps, where the guard existed
 * and was simply not used.
 */
const src = raw
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')
  .replace(/\s\/\/[^\n'"`]*$/gm, '');
ok(/androidPreviewViewType/.test(src) && !/punches a hole/.test(src),
  'the comment stripper removes prose but keeps code');

console.log('\n-- the preview is a TextureView, so opacity cannot black it out --');

// The literal moved into a named constant so the diagnostic can REPORT the
// value that is actually passed rather than a second copy that could drift.
ok(/const PREVIEW_TYPE = 'texture-view';/.test(src)
   && /androidPreviewViewType=\{PREVIEW_TYPE\}/.test(src),
  'the Camera renders into a TextureView, not the default SurfaceView');
// The prewarm is what makes this necessary. If the hiding mechanism ever stops
// being opacity-based, this prop stops being load-bearing — and whoever changes
// it should find out here rather than on a jobsite.
ok(/overlayHidden: \{ opacity: 0/.test(src),
  'the prewarm still hides with opacity, which is what a SurfaceView cannot survive');
ok(/overlayShown: \{ opacity: 1/.test(src),
  'and reveals by returning to opacity 1');
// display:'none' / zero-size would break configuration instead — the comment on
// overlayHidden explains why they are not used, and this stops a "tidier" fix.
ok(!/overlayHidden: \{[^}]*display:/.test(src),
  'hiding is NOT display:none — VisionCamera needs a laid-out surface to configure against');

console.log('\n-- what he sees is what he gets --');

ok(/resizeMode="contain"/.test(src),
  'the preview letterboxes to the sensor aspect rather than cropping to the screen');
// takeSnapshot captures previewView.bitmap — the VIEW, at the view's size,
// cropped by resizeMode. Under the default 'cover' the filed photo was a
// phone-shaped crop of a 4:3 frame. That was the "distortion", not the lens.
ok(!/resizeMode="cover"/.test(src), 'and never the cropping default');
// The lens default was already right and must stay right: Android hardcodes
// neutralZoom to 1.0, so 'wide' opens at 1x.
ok(/useState\('ultra'\)/.test(src),
  'the back lens defaults to ULTRA-WIDE, by ruling');
ok(!/useState\('wide'\)/.test(src), 'and the superseded default is gone, not merely bypassed');
ok(/const showLensToggle = false/.test(src),
  'and the lens chips stay gone — zoom is pinch-only');

console.log('\n-- Android capture reads the preview, so it depends on both --');

// This is why the two findings had one cause. If the capture path ever moves
// back to takePhoto, the coupling changes and this assertion should be revisited
// deliberately rather than silently.
ok(/Platform\.OS === 'android'[\s\S]{0,120}takeSnapshot/.test(src),
  'Android capture is still takeSnapshot — a screenshot of the preview view');
ok(/takePhoto\(\{ flash: 'off'/.test(src),
  'and iOS still takes a real photo');

console.log('\n-- ultra-wide is a ZOOM VALUE, not a device choice --');

// #145 set the default and the camera still opened at 1x. The mounted device is
// ONE logical camera carrying wide + ultra-wide + telephoto, zoom 0.5078-30, so
// the lens IS a position in that range — and the old branch asked for
// neutralZoom, which Android hardcodes to 1.0. Ultra now means the widest the
// MOUNTED device can go, whatever the hardware arrangement.
ok(/backLens === 'ultra'\)[\s\S]{0,60}lensDevice\?\.minZoom/.test(src),
  'ultra framing is the mounted device MIN zoom, not its neutral zoom');
ok(/lensDevice\?\.neutralZoom \?\? 1/.test(src), 'and wide is its neutral zoom, unchanged');
// The bug lived entirely in branching on how the hardware is packaged.
ok(!/uwViaZoom/.test(src), 'the exposure-shape branch is gone — the answer does not depend on it');
ok(!/hasUltraWide/.test(src), 'and so is the flag that only fed the removed toggle');
// The front camera must not be dragged to minZoom by the back-lens state.
ok(/position !== 'front' && backLens === 'ultra'/.test(src),
  'the ultra rule applies to the BACK lens only');
ok(/const lensDevice = position === 'front' \? frontDevice : device;/.test(src),
  'and it reads the zoom range off the device actually mounted');

console.log('\n-- the diagnostic panel is gone, on schedule --');

// It named the lowLightBoost failure in one round after two rounds of guessing,
// and the preview is confirmed live. Temporary instrumentation on a CP-facing
// screen is the shape that outlives its reason.
for (const dead of ['previewFailed', 'diagText', 'noteDiag', 'CAMERA DIAGNOSTIC',
  'diagPanel', 'graceOver', 'expo-clipboard']) {
  ok(!raw.includes(dead), 'fully removed: no ' + dead);
}
// The SHUTTER LOG stays — console-only, never on the CP's screen, and a capture
// that hangs leaves no other trace.
ok(/\[CAM\] shutter/.test(src), 'the shutter log stays — it was never the panel');

console.log('\n-- the concluded instrumentation is gone --');

// TEMP instrumentation on a CP-facing screen is the shape that outlives its
// reason. Both of these were for diagnoses that have finished.
ok(!/item6/.test(raw),
  'the item6 format/capability dump is gone, comments and all');
ok(!/captureTiming/.test(raw),
  'and the on-screen timing badge is gone');
ok(!/timingBadge|timingText/.test(raw), 'along with its styles');
// The LOG survives on purpose: a capture that hangs never reaches any badge,
// and this line is the only record of which device/lens/method it used.
ok(/\[CAM\] shutter/.test(src),
  'the shutter log stays — a hanging capture leaves no other trace');
ok(/const report = \(stage, ms\)/.test(src),
  'and `report` stays, because the CALLER still calls it for stages this modal cannot see');

console.log('\n-- the fix ships without a rebuild --');

// Both props are JS. A native module here would end OTA delivery, which is the
// rule DateField and TimeField were hand-built under.
const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'package.json'), 'utf8'));
ok(pkg.dependencies['react-native-vision-camera'].includes('4'),
  'still vision-camera v4 — no dependency change, so no new native module');
ok(!/require\(|import\(/.test(src.split('export default')[1] || ''),
  'and nothing is lazily pulled in at render time');

console.log('\n-- the lock is re-derived on every load --');

const APP = path.join(__dirname, '..', '..', 'app', 'logbooks');
for (const f of ['daily_jobsite', 'toolbox_talk', 'osha_log', 'scaffold_maintenance',
  'preshift_signin', 'ssc_daily_safety_log']) {
  const form = fs.readFileSync(path.join(APP, f + '.jsx'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  ok(/setLocked\(false\);/.test(form), f + ': a load can UNLOCK, not only lock');
  const reset = form.indexOf('setLocked(false)');
  const firstLock = form.indexOf('setLocked(true)');
  ok(reset > -1 && (firstLock === -1 || reset < firstLock),
    f + ': and it resets BEFORE anything decides to lock');
}

console.log('\n-- the extension that stopped the session ever starting --');

// The readout named it: preview NEVER STARTED, session init=false started=false,
// error "Pixel extensions not supported in framework path". lowLightBoost is not
// a setting — it swaps the cameraSelector for an EXTENSION-backed one and binds
// with it, and onInitialized is the line AFTER that bind
// (CameraSession+Configuration.kt:261-282). The bind threw, so nothing ran.
ok(/lowLightBoost=\{false\}/.test(src),
  'lowLightBoost is OFF unconditionally — a camera that opens beats night mode');
// THE CHECK EXISTS AND WE WERE ALREADY USING IT. supportsLowLightBoost is
// extensionsManager.isExtensionAvailable(..., NIGHT); it returned TRUE on this
// device and the bind then failed. A check that says yes and then throws is not
// a check, so it must not gate this prop again.
ok(!/lowLightBoost=\{device\?\.supportsLowLightBoost/.test(src),
  'and it is NOT gated on supportsLowLightBoost, which claimed support then threw');
ok(/photoHdr=\{false\}/.test(src),
  'the other vendor extension stays off too — the library throws if both are on');
ok(!/lowLightBoost=\{[^}]*supportsLowLightBoost/.test(src),
  'and supportsLowLightBoost can never gate the prop again');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
