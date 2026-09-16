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
    'return targetScaleInfo(vp1, over, wantFloor);',
  ].join('\n');
  // `wantFloor` IS A PARAMETER HERE BECAUSE IT IS A PARAMETER THERE. The ppi
  // floor is unconditional on the shipping path again — `targetScaleInfo`
  // defaults it to true — and the probe's A/B passes it explicitly so it can
  // time both anchors. Supplying it here is what lets this file RUN both
  // rather than describe them.
  // eslint-disable-next-line no-new-func
  const fn = new Function('vp1', 'over', 'baseWidth', 'window', 'wantFloor', body);
  return (widthIn, heightIn, cssPx, dpr, wantFloor, over) => fn(
    { width: widthIn * 72, height: heightIn * 72 },
    over,
    cssPx,
    { devicePixelRatio: dpr },
    wantFloor,
  );
}

/**
 * WHAT THE SHIPPING PATH ACTUALLY ASKS FOR: `targetScaleInfo(vp1)`, with no
 * third argument at all. Lifted separately because the question this file now
 * answers is what the DEFAULT is — a helper that always passed the flag could
 * never catch the default being quietly changed back.
 */
function makeShippingScaler(js) {
  const i = js.indexOf('function targetScaleInfo(');
  const end = js.indexOf('\n  }\n', i);
  const num = (name) => Number(js.match(new RegExp(`var ${name} = (\\d+);`))[1]);
  const body = [
    `var MAX_CANVAS_EDGE = ${num('MAX_CANVAS_EDGE')};`,
    `var MAX_CANVAS_PX = ${num('MAX_CANVAS_PX')};`,
    `var TARGET_PPI = ${num('TARGET_PPI')};`,
    js.slice(i, end + 4),
    'return targetScaleInfo(vp1);',
  ].join('\n');
  // eslint-disable-next-line no-new-func
  const fn = new Function('vp1', 'baseWidth', 'window', body);
  // ⚠️ REPORTED, NOT THROWN. Nothing outside `targetScaleInfo` is supplied
  // here on purpose: the shipping path calls it with one argument and the
  // whole point is that it needs nothing else to decide the floor. A default
  // that reached back out to a module-level flag — which is exactly what this
  // file used to assert — makes this reference fail, and that IS the finding.
  // Letting it throw would exit 1 with a stack trace and no name; a named
  // failure says which property broke.
  return (widthIn, heightIn, cssPx, dpr) => {
    try {
      return fn({ width: widthIn * 72, height: heightIn * 72 }, cssPx, { devicePixelRatio: dpr });
    } catch (e) {
      return { s: NaN, w: NaN, h: NaN, anchor: 'threw', floor: null, err: String(e && e.message) };
    }
  };
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
const shippingScale = makeShippingScaler(JS);
const EDGE = Number(JS.match(/var MAX_CANVAS_EDGE = (\d+);/)[1]);
const MAXPX = Number(JS.match(/var MAX_CANVAS_PX = (\d+);/)[1]);

const DEVICES = [
  ['phone       390 css, dpr 3', 390, 3],
  ['phone       360 css, dpr 3', 360, 3],
  ['tablet      768 css, dpr 2', 768, 2],
  ['tablet LS  1024 css, dpr 2', 1024, 2],
];

// ═══════════════════════════════════════════════════════════════════════════
// THE FLOOR IS BACK ON AT FIRST PAINT, AND THE MEASUREMENT IS WHY.
//
// #542 attached #413's ppi floor to the zoom, on the reasoning that a phone
// went 1.83 MP a sheet to 12.58 MP — 6.9x — with no worker to put the work
// on, and that the band rasterised four or five sheets before the operator
// touched anything.
//
// ⚠️ THE PREMISE IS REFUTED. Isolated medians on the operator's Pixel 10 Pro
// XL, three runs each, inflight 0, spread under 90 ms:
//
//     0.5 MP   800 ms
//     1.2 MP   742 ms
//    11.2 MP   701 ms      <- twenty-two times the pixels, and FASTER
//
// The per-page cost is CONTENT DECODE — 710 FlateDecode and 147 DCTDecode
// operators on one of his sheets — and it does not care how many pixels are
// filled. A cheaper tier is not a faster tier; it is the same wait and a
// blurrier drawing. So the deferral bought nothing and cost the reader 32 ppi
// until he thought to pinch.
//
// WHAT THIS FILE ASSERTS NOW is therefore the opposite of what it did, and
// deliberately so: the SHIPPING DEFAULT is the floor, every device clears
// 85 ppi from the first paint, and asking for the viewport anchor explicitly
// (which the probe's A/B still does) never produces MORE pixels than the
// floor does.
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n── ARCH-E 36x48: what the reader gets at first paint ─────────');
let shippingIsTheFloor = true;
let openAtLeast85 = true;
let floorNeverFewer = true;
for (const [label, css, dpr] of DEVICES) {
  const open = shippingScale(36, 48, css, dpr);
  const viewportOnly = scale(36, 48, css, dpr, false);
  const floored = scale(36, 48, css, dpr, true);
  const pre413 = oldScale(36, css, dpr, EDGE, MAXPX, 48);
  console.log(
    `  ${label}   open ${(72 * open.s).toFixed(1).padStart(5)} ppi `
    + `${(open.w * open.h / 1e6).toFixed(2).padStart(5)} MP`
    + `   (viewport-only would be ${(72 * viewportOnly.s).toFixed(1).padStart(5)} ppi `
    + `${(viewportOnly.w * viewportOnly.h / 1e6).toFixed(2).padStart(5)} MP,`
    + ` pre-#413 ${(72 * pre413).toFixed(1)} ppi)`,
  );
  // ⚠️ NaN COMPARES FALSE AGAINST EVERYTHING, so a scaler that could not run
  // at all would sail through `Math.abs(a - b) > eps`. Finiteness is checked
  // first and explicitly — this is the difference between "the default is the
  // floor" and "the default could not be evaluated".
  if (!Number.isFinite(open.s) || Math.abs(open.s - floored.s) > 1e-12) shippingIsTheFloor = false;
  if (!Number.isFinite(open.s) || 72 * open.s < 85) openAtLeast85 = false;
  if (!Number.isFinite(floored.s) || floored.s < viewportOnly.s - 1e-9) floorNeverFewer = false;
}

ok(shippingIsTheFloor,
  'THE SHIPPING DEFAULT IS THE FLOOR — targetScaleInfo(vp1) with no third '
  + 'argument is identical to asking for it, on every device. This is the '
  + 'assertion that catches the default being changed back');
ok(openAtLeast85,
  'so every device is at >= 85 ppi from the FIRST paint, with no pinch — the '
  + 'measured cost of which is ~0 ms, because the per-page cost is decode');
ok(floorNeverFewer,
  'and the floor never renders FEWER pixels than the viewport anchor, so '
  + 'turning it on can only ever sharpen');

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

console.log('\n── small pages: the floor barely touches a letter sheet ──────');
{
  // US Letter, 8.5x11 — the logbook case, 16-93 KB and two pages.
  //
  // THE POINT OF THIS BLOCK. The floor was never the reason a LOGBOOK was
  // slow: it lifts a letter page from 1.77 MP to 2.10 MP, 1.19x, which cannot
  // be 20 seconds. Turning it back on therefore cannot be a logbook
  // REGRESSION either, and this block keeps that honest in both directions —
  // it records the small number rather than letting anyone claim the logbook
  // as a win or fear it as a cost.
  for (const [label, css, dpr] of DEVICES) {
    const open = shippingScale(8.5, 11, css, dpr);
    const viewportOnly = scale(8.5, 11, css, dpr, false);
    console.log(
      `  letter on ${label.trim().padEnd(26)} open ${(72 * open.s).toFixed(1)} ppi `
      + `${(open.w * open.h / 1e6).toFixed(2)} MP  (viewport-only `
      + `${(72 * viewportOnly.s).toFixed(1)} ppi ${
        (viewportOnly.w * viewportOnly.h / 1e6).toFixed(2)} MP)`,
    );
    ok(open.s >= viewportOnly.s - 1e-9,
      `  letter on ${label.trim()} never loses pixels to the floor`);
  }
  const phoneViewport = scale(8.5, 11, 390, 3, false);
  const phoneOpen = shippingScale(8.5, 11, 390, 3);
  const ratio = (phoneOpen.w * phoneOpen.h) / (phoneViewport.w * phoneViewport.h);
  ok(ratio < 1.25,
    `a letter page costs only ${ratio.toFixed(2)}x more at the floor than at `
    + 'the viewport scale — which is why the ppi floor was never the reason a '
    + 'LOGBOOK took 20 seconds, and why putting it back cannot be the reason '
    + 'one gets slower');
  const tablet = shippingScale(8.5, 11, 1024, 2);
  ok(tablet.anchor === 'viewport',
    'a tablet is far above the floor, so the viewport term still wins there '
    + 'even with the floor switched on');
}

console.log('\n── which term wins, in each tier ────────────────────────────');
{
  const open = shippingScale(36, 48, 390, 3);
  const viewportOnly = scale(36, 48, 390, 3, false);
  ok(open.anchor === 'ppi' && open.floor === true,
    'at first paint a phone is ppi-anchored and reports the floor as ON');
  ok(viewportOnly.anchor === 'viewport' && viewportOnly.floor === false,
    'and the probe can still ask for the viewport anchor explicitly, which is '
    + 'what keeps its A/B a comparison of two real things');
  ok(open.targetPpi === Number(JS.match(/var TARGET_PPI = (\d+);/)[1]),
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
console.log('\n── what the pinch still does: it narrows the band ───────────');
{
  // ⚠️ `sharp` NO LONGER MEANS "RESOLUTION". Every sheet is drawn at the floor
  // from the first paint, so a pinch cannot change what is on screen — it
  // changes how much PREFETCH is worth holding. A reader who has zoomed in is
  // looking at one sheet, and with a sharp sheet at 12.58 MP that is a memory
  // lever that matters more than it did, not less.
  ok(/var sharp = false;/.test(JS),
    'the viewer opens with the WIDE band');
  ok(/var ZOOM_SHARP = 1\.25;/.test(JS),
    'there is a zoom threshold that narrows it');
  ok(/function goSharp\(\)\{/.test(JS),
    'and a transition that runs when the threshold is crossed');
  const gs = JS.slice(JS.indexOf('function goSharp(){'));
  ok(/if \(sharp\) return;\s*\n\s*'?\s*sharp = true;/.test(gs.slice(0, 200))
     || /if \(sharp\) return;[\s\S]{0,80}sharp = true;/.test(gs),
    'goSharp is one-way and idempotent — no band thrash on every pinch gesture');
  // ⚠️ DELIBERATELY INVERTED. It used to free every canvas, because the pinch
  // changed the scale and everything drawn was at the wrong one. Releasing
  // them now would blank the sheet the reader has just pinched INTO and redraw
  // it at the identical scale — a flicker bought with a second of the one
  // render slot, for nothing.
  ok(!/releaseSlot\(slots\[i\]\)/.test(gs.slice(0, 600)),
    'and it no longer blanks every sheet — the page the reader just pinched '
    + 'into is already at the scale it would be redrawn at');
  ok(/rewatch\(\);/.test(gs.slice(0, 600)),
    'it rebuilds the observer instead, which is the only way to change a rootMargin');
  ok(/visualViewport/.test(JS),
    'the zoom is read from visualViewport, which is what native pinch-zoom moves');
  // FAIL TOWARD THE SMALLER RESIDENT SET. A WebView that cannot report its
  // zoom gets the narrow band from first paint: it can never be told to
  // narrow later, and holding a wide band of 12.58 MP sheets on a device
  // nothing can correct is the renderer kill this branch exists to stop.
  const wz = JS.slice(JS.indexOf('function watchZoom(){'));
  ok(/if \(!vv\) \{ zoomBlind = true; sharp = true; return; \}/.test(wz.slice(0, 900)),
    'with no visualViewport the NARROW band is used from first paint — a '
    + 'device that cannot report zoom fails toward the smaller resident set, '
    + 'and it loses no sharpness by doing so because the floor is unconditional');
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
  ok(!!m && Number(m[1]) >= 11,
    'VIEWER_VERSION bumped — viewer.html is written to disk once and re-used '
    + 'until this changes, so without a bump every already-staged device keeps '
    + 'the slow viewer and the fix ships to nobody',
    m ? `found '${m[1]}'` : 'not found');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
