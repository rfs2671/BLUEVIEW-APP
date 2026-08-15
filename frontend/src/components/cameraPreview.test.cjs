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

ok(/androidPreviewViewType="texture-view"/.test(src),
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
ok(/useState\('wide'\)/.test(src),
  "the back lens still defaults to the main wide sensor, not the ultra-wide");
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

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
