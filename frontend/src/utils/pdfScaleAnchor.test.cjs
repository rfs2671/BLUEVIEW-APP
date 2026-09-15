/**
 * THE SHEET'S OWN SIZE HAD CANCELLED OUT OF THE SCALE, AND THIS RUNS THE MATH.
 *
 * `targetScaleInfo` computed `(baseWidth / vp1.width) * min(dpr,2) * 1.5`, so
 * the rendered pixel width was `baseWidth * min(dpr,2) * 1.5` WHATEVER the page
 * measured. The page cancels. Resolution therefore fell as the sheet grew,
 * which is backwards for the one document type this viewer exists to show:
 *
 *   36x48 sheet, phone at 390 CSS px, dpr 2+  ->  1170 px  ->  32.5 ppi
 *   36x48 sheet, tablet at 768                ->  2304 px  ->  64 ppi
 *   36x48 sheet, tablet at 1024               ->  3072 px  ->  85 ppi
 *
 * A ppi FLOOR fixes it without touching anything that was already sharp: take
 * `max(viewportAnchored, TARGET_PPI/72)`, and the three existing clamps still
 * run unconditionally afterwards.
 *
 * WHY THIS FILE EXECUTES THE FUNCTION INSTEAD OF GREPPING FOR IT. Fifteen
 * source-text tests were written this week against an R2 sweep, all passing,
 * while the code they described deleted nothing — they asserted the CALL and
 * never the EFFECT. A scale formula is arithmetic; arithmetic can be run. Every
 * number below comes from the real `targetScaleInfo` lifted out of the real
 * viewer source, not from a restatement of it.
 *
 * Run:  node src/utils/pdfScaleAnchor.test.cjs
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..');
const VIEWER = path.join(ROOT, 'src', 'utils', 'pdfjsViewer.js');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/**
 * Reconstruct the viewer script exactly as `viewerHtml()` would — the same
 * slice-and-evaluate `pdfRenderProbe.test.cjs` uses, for the same reason:
 * importing the module pulls in react-native and expo.
 */
function viewerScript() {
  const src = fs.readFileSync(VIEWER, 'utf8').replace(/\r\n/g, '\n');
  const start = src.indexOf('const VIEWER_SCRIPT = [');
  if (start < 0) throw new Error('VIEWER_SCRIPT not found');
  const open = src.indexOf('[', start);
  const close = src.indexOf("].join('\\n');", open);
  if (close < 0) throw new Error('VIEWER_SCRIPT terminator not found');
  const WORKER_NAME = 'pdf.worker.min.js';
  // eslint-disable-next-line no-new-func
  const arr = new Function('WORKER_NAME', `return ${src.slice(open, close + 1)};`)(WORKER_NAME);
  return arr.join('\n');
}

/**
 * Lift `targetScaleInfo` and its two caps out of the generated script and run
 * them for real, with `baseWidth` and `devicePixelRatio` supplied per device.
 */
function makeScaler(js) {
  const grab = (name) => {
    const i = js.indexOf(`function ${name}(`);
    if (i < 0) throw new Error(`no ${name} in the viewer script`);
    // functions in this file end at a line that is exactly two spaces + '}'
    const end = js.indexOf('\n  }\n', i);
    if (end < 0) throw new Error(`could not slice ${name}`);
    return js.slice(i, end + 4);
  };
  const constOf = (name) => {
    const m = js.match(new RegExp(`var ${name} = (\\d+);`));
    if (!m) throw new Error(`no ${name} constant`);
    return Number(m[1]);
  };
  const body = [
    `var MAX_CANVAS_EDGE = ${constOf('MAX_CANVAS_EDGE')};`,
    `var MAX_CANVAS_PX = ${constOf('MAX_CANVAS_PX')};`,
    `var TARGET_PPI = ${constOf('TARGET_PPI')};`,
    grab('targetScaleInfo'),
    'return targetScaleInfo(vp1, over);',
  ].join('\n');
  // `sharp` IS A PARAMETER HERE BECAUSE IT IS A VARIABLE THERE. The viewer's
  // ppi floor is no longer unconditional — it is attached to the reader having
  // zoomed in — so the scale function reads a module-level `sharp` flag when it
  // is not told otherwise. Supplying it as an argument is what lets this file
  // run BOTH tiers of the real function rather than describing them.
  // eslint-disable-next-line no-new-func
  const fn = new Function('vp1', 'over', 'baseWidth', 'window', 'sharp', body);
  return (widthIn, heightIn, cssPx, dpr, sharp, over) => fn(
    { width: widthIn * 72, height: heightIn * 72 },
    over,
    cssPx,
    { devicePixelRatio: dpr },
    !!sharp,
  );
}

/** What the OLD formula produced, for the never-fewer-pixels comparison. */
function oldScale(widthIn, cssPx, dpr, maxEdge, maxPx, heightIn) {
  const vw = widthIn * 72;
  const vh = heightIn * 72;
  let s = (cssPx / vw) * Math.min(dpr, 2) * 1.5;
  let w = vw * s; let h = vh * s;
  if (w > maxEdge) { s *= maxEdge / w; w = vw * s; h = vh * s; }
  if (h > maxEdge) { s *= maxEdge / h; w = vw * s; h = vh * s; }
  if (w * h > maxPx) { s *= Math.sqrt(maxPx / (w * h)); }
  return s;
}

const JS = viewerScript();
const scale = makeScaler(JS);
const EDGE = Number(JS.match(/var MAX_CANVAS_EDGE = (\d+);/)[1]);
const MAXPX = Number(JS.match(/var MAX_CANVAS_PX = (\d+);/)[1]);

const DEVICES = [
  ['phone       390 css, dpr 3', 390, 3],
  ['phone       360 css, dpr 3', 360, 3],
  ['tablet      768 css, dpr 2', 768, 2],
  ['tablet LS  1024 css, dpr 2', 1024, 2],
];

// ═══════════════════════════════════════════════════════════════════════════
// THE FLOOR IS NOW ATTACHED TO THE ZOOM, NOT TO THE OPEN.
//
// #413 was right about the resolution and wrong about when to pay for it. A
// 36x48 sheet at a phone's viewport scale is 32.5 ppi and genuinely
// unreadable, so the floor had to exist. But it applied on EVERY page of
// EVERY open, and the band rasterises four or five sheets before the operator
// has touched anything — 63 MP on the UI thread to show a drawing nobody has
// asked to read the fine print of yet. An inspector waits through all of it.
//
// So there are two tiers now, and this file runs both:
//
//   FIRST PAINT  viewport-anchored, floor OFF. Byte-for-byte the scale the
//                viewer used before #413, which is the claim "instant open"
//                actually rests on.
//   ZOOMED IN    floor ON. Exactly what #413 bought, delivered the moment
//                someone pinches in to read.
//
// The two assertions that matter are therefore NOT "always >= 85 ppi" any
// more. They are: first paint costs what it cost before #413, and zooming in
// gets back everything #413 bought. Both are below, and both are run rather
// than described.
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n── ARCH-E 36x48: first paint vs zoomed in ───────────────────');
let firstPaintIsPre413 = true;
let sharpAtLeast85 = true;
let sharpNeverFewer = true;
for (const [label, css, dpr] of DEVICES) {
  const open = scale(36, 48, css, dpr, false);
  const zoom = scale(36, 48, css, dpr, true);
  const pre413 = oldScale(36, css, dpr, EDGE, MAXPX, 48);
  console.log(
    `  ${label}   open ${(72 * open.s).toFixed(1).padStart(5)} ppi `
    + `${(open.w * open.h / 1e6).toFixed(2).padStart(5)} MP`
    + `   ->  zoom ${(72 * zoom.s).toFixed(1).padStart(5)} ppi `
    + `${(zoom.w * zoom.h / 1e6).toFixed(2).padStart(5)} MP`
    + `   (${(zoom.w * zoom.h / (open.w * open.h)).toFixed(1)}x)`,
  );
  if (Math.abs(open.s - pre413) > 1e-9) firstPaintIsPre413 = false;
  if (72 * zoom.s < 85) sharpAtLeast85 = false;
  if (zoom.s < open.s - 1e-9) sharpNeverFewer = false;
}

ok(firstPaintIsPre413,
  'FIRST PAINT is exactly the pre-#413 viewport-anchored scale — a phone is '
  + 'back to 1.83 MP a sheet instead of 12.58, which is the instant open');
ok(sharpAtLeast85,
  'AND ZOOMING IN still reaches >= 85 ppi on every device — #413 is deferred, '
  + 'not reverted');
ok(sharpNeverFewer,
  'the zoomed tier never renders FEWER pixels than first paint, so the '
  + 're-render can only ever sharpen');

console.log('\n── the caps still bind, so the ceiling did not move ──────────');
{
  const a = scale(36, 48, 1024, 2, true);
  ok(Math.max(a.w, a.h) <= EDGE + 0.5,
    `the long edge is still clamped to MAX_CANVAS_EDGE (${EDGE})`);
  ok(a.w * a.h <= MAXPX + 1,
    `and the area to MAX_CANVAS_PX (${(MAXPX / 1e6).toFixed(0)} MP)`);
  ok(a.clamp !== 'none',
    'a sheet this size is clamped, which is why LOWERING TARGET_PPI would '
    + 'change nothing until it drops below ~85 ppi — the reason this branch '
    + 'gates the floor instead of shrinking it');
  // The edge clamp binds in BOTH tiers on a landscape tablet, so that device
  // sees no change at all from this branch. Worth asserting rather than
  // assuming: it is the device the operator is most likely to check first.
  const open = scale(36, 48, 1024, 2, false);
  ok(Math.abs(open.s - a.s) < 1e-12,
    'a landscape tablet is clamped to the same edge either way, so first '
    + 'paint and zoom are identical there and that device is untouched');
}

console.log('\n── small pages: the floor is off at open, so letter is too ───');
{
  // US Letter, 8.5x11 — the logbook case, 16-93 KB and two pages.
  //
  // THE POINT OF THIS BLOCK. The floor was never the reason a LOGBOOK was
  // slow: it lifted a letter page from 1.77 MP to 2.10 MP, 1.19x, which
  // cannot be 20 seconds. Gating the floor therefore CANNOT be the logbook
  // fix, and this block exists to keep that honest — it records the small
  // number rather than letting the branch claim the logbook as a win.
  for (const [label, css, dpr] of DEVICES) {
    const open = scale(8.5, 11, css, dpr, false);
    const zoom = scale(8.5, 11, css, dpr, true);
    const pre413 = oldScale(8.5, css, dpr, EDGE, MAXPX, 11);
    console.log(
      `  letter on ${label.trim().padEnd(26)} open ${(72 * open.s).toFixed(1)} ppi `
      + `${(open.w * open.h / 1e6).toFixed(2)} MP -> zoom ${(72 * zoom.s).toFixed(1)} ppi `
      + `${(zoom.w * zoom.h / 1e6).toFixed(2)} MP`,
    );
    ok(Math.abs(open.s - pre413) < 1e-9,
      `  letter on ${label.trim()} opens at the pre-#413 scale too`);
    ok(zoom.s >= open.s - 1e-9,
      '    ...and zooming in never loses pixels');
  }
  const phoneOpen = scale(8.5, 11, 390, 3, false);
  const phoneZoom = scale(8.5, 11, 390, 3, true);
  const ratio = (phoneZoom.w * phoneZoom.h) / (phoneOpen.w * phoneOpen.h);
  ok(ratio < 1.25,
    `a letter page costs only ${ratio.toFixed(2)}x more at the floor than at `
    + 'the viewport scale — which is why the ppi floor was never the reason a '
    + 'LOGBOOK took 20 seconds');
  const tablet = scale(8.5, 11, 1024, 2, true);
  ok(tablet.anchor === 'viewport',
    'a tablet is far above the floor, so the viewport term still wins there '
    + 'even with the floor switched on');
}

console.log('\n── which term wins, in each tier ────────────────────────────');
{
  const open = scale(36, 48, 390, 3, false);
  const zoom = scale(36, 48, 390, 3, true);
  ok(open.anchor === 'viewport' && open.floor === false,
    'at first paint a phone is viewport-anchored and reports the floor as off');
  ok(zoom.anchor === 'ppi' && zoom.floor === true,
    'once zoomed, the ppi floor is the term that wins for a 36x48 sheet');
  ok(zoom.targetPpi === Number(JS.match(/var TARGET_PPI = (\d+);/)[1]),
    'and the info object still reports the constant, so the probe can see it');
}

console.log('\n── the probe A/B still means something ──────────────────────');
{
  // `over` must still change the viewport term on a page where it dominates.
  const a = scale(8.5, 11, 1024, 2, false, 1.0);
  const b = scale(8.5, 11, 1024, 2, false, 1.5);
  ok(b.s > a.s, 'over=1.5 still renders more than over=1.0 where viewport wins');
}

// ═══════════════════════════════════════════════════════════════════════════
// THE MECHANISM, NOT JUST THE ARITHMETIC.
//
// The arithmetic above proves the two tiers EXIST. It cannot prove the viewer
// ever moves between them, and a floor that nothing switches on is a revert
// with extra steps — which is the one outcome #413 was raised to prevent. So
// these read the generated script.
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── the zoom actually switches the tier ──────────────────────');
{
  ok(/var sharp = false;/.test(JS),
    'the viewer opens with the floor OFF');
  ok(/var ZOOM_SHARP = 1\.25;/.test(JS),
    'there is a zoom threshold that turns it on');
  ok(/function goSharp\(\)\{/.test(JS),
    'and a transition that runs when the threshold is crossed');
  const gs = JS.slice(JS.indexOf('function goSharp(){'));
  ok(/if \(sharp\) return;\s*\n\s*'?\s*sharp = true;/.test(gs.slice(0, 200))
     || /if \(sharp\) return;[\s\S]{0,80}sharp = true;/.test(gs),
    'goSharp is one-way and idempotent — no flicker back to 32 ppi on pinch-out');
  ok(/releaseSlot\(slots\[i\]\)/.test(gs.slice(0, 600)),
    'it frees every canvas drawn at the old scale rather than leaving a '
    + 'mixed-resolution page');
  ok(/visualViewport/.test(JS),
    'the zoom is read from visualViewport, which is what native pinch-zoom moves');
  // FAIL TOWARD LEGIBLE. A WebView that cannot report its zoom must not strand
  // a reader at 32 ppi in a cellar with no way to ask for more; a slow open is
  // an inconvenience, an unreadable sheet is the #413 defect returning.
  const wz = JS.slice(JS.indexOf('function watchZoom(){'));
  ok(/if \(!vv\) \{ zoomBlind = true; sharp = true; return; \}/.test(wz.slice(0, 900)),
    'with no visualViewport the floor stays ON from first paint — a device '
    + 'that cannot report zoom fails toward the legible render, never away');
  // And it must STAY on across documents. `resetDocument` puts the next
  // document back on the fast tier, so a blind device that only set `sharp`
  // once would be reset into the 32-ppi render it can never escape.
  ok(/function zoomIsSharp\(\)\{ return zoomBlind \|\| zoomScale\(\) >= ZOOM_SHARP; \}/.test(JS),
    'and "blind" is a latched fact, not a one-time assignment');
  const rd = JS.slice(JS.indexOf('function resetDocument(){'));
  ok(/sharp = zoomIsSharp\(\);/.test(rd.slice(0, 600)),
    'so the next document re-reads it rather than assuming the fast tier — '
    + 'native zoom belongs to the WebView, not to the document, and a reader '
    + 'who was pinched in on the last sheet gets no resize event for the next');
  // The listener is registered for the life of the PAGE, and the page now
  // outlives every document. Per-document registration would accumulate one
  // handler per open.
  ok(/var zoomWatched = false;/.test(JS) && /if \(zoomWatched\) return;/.test(wz.slice(0, 300)),
    'the zoom listener is registered once, not once per document');
}

console.log('\n── the zoomed tier does not re-create the OOM ───────────────');
{
  // THE ZOOM RELOAD. Seven sheets at 12.58 MP is 350 MB of bitmap and the
  // band alone holds four or five of them — `trim()` never frees a page that
  // is still in the band, so KEEP_RENDERED cannot bound this. The BAND is
  // what has to shrink, and the reader who has zoomed in is looking at one
  // sheet, not four screens of them.
  ok(/var BAND_SHARP = 0\.25;/.test(JS),
    'the near-band tightens once the expensive scale is in use');
  ok(/function band\(\)\{ return sharp \? BAND_SHARP : BAND; \}/.test(JS),
    'one function decides the band, so the observer and the no-observer '
    + 'sweep cannot disagree about what is near');
  ok(!/rootMargin: \(BAND \* 100\)/.test(JS),
    'the observer is built from band(), not the raw constant');
  ok(/rootMargin: \(band\(\) \* 100\)/.test(JS),
    '  ...and says so');
  const ib = JS.slice(JS.indexOf('function inBand(slot){'));
  ok(/band\(\) \* h/.test(ib.slice(0, 400)),
    'the no-observer sweep reads the same band()');
  ok(/function rewatch\(\)\{/.test(JS),
    'the observer is rebuilt when the band changes — a rootMargin is fixed at '
    + 'construction and cannot be edited in place');
  // Rebuilding must not stack a second set of scroll listeners on the
  // no-IntersectionObserver path.
  ok(/var swept = false;/.test(JS),
    'and the no-observer path guards its listeners against the rebuild');
}

console.log('\n── the fixed cost finally gets a number ─────────────────────');
{
  // THE BLIND SPOT THE PROBE SHIPPED WITH. `ptOpen0` is taken on the first
  // line of the viewer script, which does not run until 1.5 MB of pdf.js has
  // been read off file:// storage, compiled and executed on the main thread.
  // So `open.totalMs` excluded the entire fixed cost of the viewer booting —
  // the one cost that is identical for a 16 KB logbook and a 30 MB plan, and
  // therefore the only candidate that explains the operator seeing both take
  // the same 20-30 seconds. The probe could not see it.
  ok(/function probeBoot\(\)\{/.test(JS),
    'the viewer measures how long it took to BOOT, not just to open a file');
  ok(/probePost\("boot"/.test(JS),
    'and reports it under its own key');
  ok(/getEntriesByType\("resource"\)/.test(JS),
    'per-script resource timing, so the 1.1 MB worker can be told from the '
    + '377 KB library');
  const cr = JS.slice(JS.indexOf('function capabilityRead(after){'));
  const bootAt = cr.indexOf('probeBoot()');
  const envAt = cr.indexOf('probeEnv()');
  ok(bootAt > 0 && bootAt < envAt,
    'boot is read FIRST, before the canvas ladder allocates anything — a '
    + 'measurement taken after the measuring has started is not one');
}

console.log('\n── the stamp moved, or none of this reaches a device ─────────');
{
  const m = /const VIEWER_VERSION = '(\d+)';/.exec(fs.readFileSync(VIEWER, 'utf8'));
  ok(!!m && Number(m[1]) >= 9,
    'VIEWER_VERSION bumped — viewer.html is written to disk once and re-used '
    + 'until this changes, so without a bump every already-staged device keeps '
    + 'the slow viewer and the fix ships to nobody',
    m ? `found '${m[1]}'` : 'not found');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
