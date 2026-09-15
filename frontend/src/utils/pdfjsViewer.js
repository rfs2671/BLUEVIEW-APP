import { Platform } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import { Asset } from 'expo-asset';

/**
 * THE ANDROID PDF VIEWER — a locally staged pdf.js.
 *
 * WHY THIS EXISTS
 *   Android's WebView cannot render a PDF, so one has to be supplied. This used
 *   to be a REMOTE viewer hosted by a third party, which was both useless in a
 *   dead zone AND a token leak: the authenticated document url was url-encoded
 *   into that third party's page, JWT and all (see utils/pdfSrc.js). Staging
 *   pdf.js on the device answers both — nothing leaves the device to draw a
 *   document, online or off. It is now the ONLY Android path, not the offline
 *   one. iOS needs none of this — WKWebView hands a PDF to PDFKit.
 *
 * WHY STAGE FILES INSTEAD OF POINTING THE WEBVIEW AT THE BUNDLED ASSETS
 *   expo-asset materialises a bundled asset at a CONTENT-HASHED path
 *   (…/ExponentAsset-<md5>.txt). A viewer HTML page cannot reference its own
 *   library by a relative <script src> if that library's on-disk name is a
 *   hash — and rewriting the HTML with absolute hashed paths is fragile across
 *   OS versions. So we copy the assets ONCE into a stable directory under
 *   documentDirectory, renaming them back to their real names, and write the
 *   viewer HTML next to them. Everything then resolves by plain relative path,
 *   exactly like a normal web directory.
 *
 * WHY documentDirectory AND NOT cacheDirectory
 *   Same reason docCache.js chose it: cacheDirectory is OS-evictable, and an
 *   evicted viewer is a viewer that fails in the dead zone it exists for.
 *
 * THE ANDROID WEBVIEW PROPS THIS REQUIRES (set in PDFViewer.native.jsx)
 *   allowFileAccess=true                  — let the WebView open file:// at all
 *   allowFileAccessFromFileURLs=true      — let the file:// PAGE read file://
 *                                           via XHR; this is the one that
 *                                           matters, pdf.js fetches the PDF
 *                                           bytes with XMLHttpRequest
 *   allowUniversalAccessFromFileURLs=true — belt-and-braces for WebView builds
 *                                           that gate the above behind it
 *   originWhitelist must include 'file://'
 *   On iOS, a file:// source needs allowingReadAccessToURL pointed at the
 *   DIRECTORY, or WKWebView grants read access to the single file only.
 *
 * WHY THE PAGE EVICTS CANVASES INSTEAD OF JUST RENDERING LAZILY
 *   Lazy rendering alone only delays the crash. Every page that scrolled past
 *   left a <canvas> in the DOM holding its backing bitmap — around 4–8 MB a
 *   sheet at the scale below, and the IntersectionObserver had no branch for a
 *   page LEAVING the viewport, so nothing ever came back. A 200-sheet plan set
 *   scrolled end to end accumulated the whole thing and Chromium killed the
 *   renderer, which is what the crash-after-load reports were. The page now
 *   holds the rasterised sheets under a BYTE budget (CANVAS_BUDGET_BYTES) and
 *   frees the rest — removing the element AND zeroing width/height, because
 *   removal on its own does not drop the bitmap. Bytes rather than a page
 *   count because the same seven sheets are 31 MB at the viewport scale and
 *   336 MB once the reader has pinched in, and it is the megabytes that run
 *   out.
 *
 * ⚠️ ASSET PLACEMENT IS A HUMAN STEP. assets/pdfjs/*.txt currently hold
 *    documented placeholders, not the real pdf.js build. `ensurePdfJsViewer()`
 *    detects that by size and returns { ok: false, reason: 'assets-missing' }
 *    so the UI can say so instead of showing a blank page.
 */

// The pdf.js dist files, shipped as `.txt` because Metro bundles `.js` as
// source. `txt` is registered in metro.config.js -> resolver.assetExts.
const PDFJS_LIB_MODULE = require('../../assets/pdfjs/pdf.min.txt');
const PDFJS_WORKER_MODULE = require('../../assets/pdfjs/pdf.worker.min.txt');

const VIEWER_DIR = (FileSystem.documentDirectory || '') + 'pdfjs/';
const LIB_NAME = 'pdf.min.js';
const WORKER_NAME = 'pdf.worker.min.js';
const VIEWER_NAME = 'viewer.html';
const STAMP_NAME = '.stamp';

// Bump when viewer.html or the staging layout changes, so an installed app
// re-stages instead of running last version's viewer.
//   2 — page eviction / bounded canvas window. An app still running the `1`
//       viewer keeps the leak, so this bump is the fix's delivery mechanism.
//   3 — the render-cost probe. INERT unless the page is opened with `probe=1`,
//       but the viewer HTML on disk has to be rewritten for the probe code to
//       exist at all, so the stamp has to move or a device that already staged
//       `2` would keep serving a viewer with no probe in it and report nothing.
//   4 — the probe's second round: Blocker A's second half (can the worker
//       SOURCE be read at all) and the two MBTiles prerequisites. Bumped
//       rather than reused because a device that already staged `3` would
//       report the first round's measurements and silently omit these.
//   5 — the embedded-image compression scan. Same reasoning: a device staged
//       at `4` would report every other measurement and silently omit the one
//       the engine decision turns on.
//   7 — SHARPNESS ON DEMAND. The ppi floor #413 added is no longer applied at
//       first paint; it is switched on by the reader zooming in. THIS BUMP IS
//       THE FIX'S ENTIRE DELIVERY MECHANISM and is not optional: viewer.html
//       is written to disk once and re-used until this string changes, so a
//       device that already staged `6` would keep rasterising 12.58 MP a
//       sheet on every open and the change would reach nobody. The app code
//       would be new and the viewer would be old.
//   9 — ONE RENDER AT A TIME, NEAREST FIRST, AND A BUDGET IN BYTES. A dozen
//       visible sheets started a dozen concurrent rasterisations on one
//       thread and each one's wall clock contained all the others; and
//       `KEEP_RENDERED = 7` never bound anything because `trim()` skips any
//       page still in the band. THIS BUMP IS THE FIX'S DELIVERY MECHANISM and
//       is not optional: viewer.html is written to disk once and re-used until
//       this string changes, so a device already staged at `8` would keep the
//       unbounded queue and the page-count window, and the change would reach
//       nobody. The app code would be new and the viewer would be old.
//       (Stacked above `8`, the two-pass warm-up probe. If that has not landed
//       yet, this is still a move and still correct — the stamp only has to
//       change, not to be consecutive.)
//  10 — PROGRESSIVE RENDER, A MEASURED EDGE CAP, AND THE BUDGET RE-DERIVED.
//       The queue in `9` fixed the ORDER; this fixes what the reader's first
//       sheet COSTS. Also takes `9` off the table because the isolated probe
//       (PR #546) claimed it for a measurement-only change — stacking rather
//       than renumbering, because the stamp only has to CHANGE, not to be
//       consecutive, and a device staged at `9` by either branch must
//       re-stage for this one. THIS BUMP IS THE FIX'S DELIVERY MECHANISM:
//       viewer.html is written once and re-used until this string moves, so a
//       device already staged would keep rasterising the whole band at one
//       tier, keep the 4096 edge cap, and the change would reach nobody.
const VIEWER_VERSION = '10';

// The placeholders are a couple of KB of comments; a real pdf.min.js is ~300KB
// and the worker ~1MB. Anything under this is not a pdf.js build.
const MIN_REAL_ASSET_BYTES = 40000;

const canUseFs = () => Platform.OS !== 'web' && !!FileSystem.documentDirectory;

// ── The viewer page ────────────────────────────────────────────────────────
// Written to disk at stage time. Kept as a plain string (no template
// interpolation) so nothing in the page can be broken by an escaping mistake.
function viewerHtml() {
  return [
    '<!DOCTYPE html>',
    '<html lang="en">',
    '<head>',
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1, minimum-scale=1, maximum-scale=8, user-scalable=yes">',
    '<title>Document</title>',
    '<style>',
    'html,body{margin:0;padding:0;background:#050a12;-webkit-text-size-adjust:100%;}',
    'body{font:14px -apple-system,Roboto,"Helvetica Neue",sans-serif;color:#94a3b8;}',
    '#pages{padding:8px 0 24px;}',
    '.pg{position:relative;margin:0 auto 10px;background:#fff;box-shadow:0 1px 6px rgba(0,0,0,.55);}',
    '.pg canvas{display:block;width:100%;height:100%;}',
    '#msg{position:fixed;left:16px;right:16px;top:44%;text-align:center;line-height:1.5;}',
    '</style>',
    '</head>',
    '<body>',
    '<div id="pages"></div>',
    '<div id="msg">Loading document…</div>',
    // Worker FIRST: defines globalThis.pdfjsWorker, which makes pdf.js skip the
    // real-Worker attempt (blocked from a file:// origin) and go straight to
    // the main-thread handler with no console noise.
    '<script src="' + WORKER_NAME + '"></script>',
    '<script src="' + LIB_NAME + '"></script>',
    '<script>',
    VIEWER_SCRIPT,
    '</script>',
    '</body>',
    '</html>',
    '',
  ].join('\n');
}

// Kept separate purely for readability. Plain ES5 — this runs in whatever
// System WebView the device happens to have.
const VIEWER_SCRIPT = [
  '(function(){',
  '  var msgEl = document.getElementById("msg");',
  '  var pagesEl = document.getElementById("pages");',
  '  var MAX_CANVAS_PX = 16000000;',   // ~16MP per page — now the BINDING cap, see below
  // ── THE EDGE CAP IS AN ABSOLUTE GUARD, NOT A WORKING LIMIT ─────────────
  //
  // WAS 4096, AND IT WAS THE CLAMP THAT BOUND EVERYTHING. A 36x48 sheet asked
  // for 7200 px on the long edge and got 4096 — 85 ppi — so `MAX_CANVAS_PX`
  // was never reached on any large-format sheet and 11 of the 16 megapixels
  // this viewer had already budgeted for were simply never used.
  //
  // 4096 WAS A GUESS ABOUT THE DEVICE. The probe's canvas ladder measured the
  // operator's Pixel 10 Pro XL passing a 16384 square — 268 MP, verified by
  // touching the far corner with getImageData, not by asking a compatibility
  // table. So the cap was costing resolution on the one device the complaint
  // came from, for a limit that device does not have.
  //
  // THE THREE NUMBERS NOW HAVE THREE DIFFERENT JOBS:
  //   MAX_CANVAS_EDGE       the ABSOLUTE guard. Nothing may ever be asked for
  //                         more than this however capable the device reports
  //                         itself, because a WebView that over-reports would
  //                         be handed an allocation that takes the renderer
  //                         down and there is no recovering from that.
  //   CANVAS_EDGE_FALLBACK  what is used when the capability CANNOT be read.
  //                         Deliberately the 4096 this viewer has always
  //                         shipped: an unknown device gets the answer that
  //                         has been in the field for months, never the
  //                         optimistic one.
  //   MAX_CANVAS_PX         the working cap, and now the one that binds. On a
  //                         36x24 sheet 16 MP is 4899 x 3266 — 136 ppi, up
  //                         from 85 — and on a 36x48 it is 3463 x 4618.
  //
  // WHY THE AREA AND NOT THE EDGE IS THE RIGHT THING TO CAP: the area is what
  // costs memory (4 bytes a pixel) and what the byte budget is priced in. An
  // edge cap prices nothing — it penalises long thin sheets hardest and lets a
  // square one through at four times the bytes.
  '  var MAX_CANVAS_EDGE = 16384;',
  '  var CANVAS_EDGE_FALLBACK = 4096;',
  // ── THE FIRST PASS: SOMETHING ON SCREEN IN UNDER HALF A SECOND ─────────
  //
  // THE MEASUREMENT THIS COMES FROM. Uncontended on the operator's phone,
  // 0.5 MP renders in ~465 ms and 11.2 MP in 732 ms. Twenty-two times the
  // pixels for 1.6x the time — so roughly 450 ms of every page render is FIXED
  // per-page decode (these sheets carry 710 Flate and 147 DCT image operators)
  // and only about 25 ms of it is per megapixel.
  //
  // THAT SPLIT IS THE WHOLE DESIGN. It means there is no point drafting
  // anything the reader is not looking at — a draft is barely cheaper than the
  // real thing — but it also means the sheet in front of him can be on screen
  // at ~465 ms instead of blank until 1400, and the sharp pass can follow on
  // the same sheet without ever having been in the way.
  //
  // ⚠️ 0.5 MP IS SOFT, AND THE ARITHMETIC SAYS SO. On a 36x24 sheet it is
  // 866 x 577 — 24 ppi, below even the 32.5 ppi the pre-#413 viewer gave. It
  // is a PLACEHOLDER that shows the drawing's shape, not a readable render;
  // readability arrives with the sharp pass ~950 ms later. Because the cost is
  // mostly fixed, raising this is nearly free: 2 MP would be ~500 ms (35 ms
  // more) and 48 ppi. This is the first constant to revisit once PR #546's
  // isolated medians come back, and it is a named constant so that revisit is
  // one edit.
  '  var DRAFT_CANVAS_PX = 500000;',
  // THE RESOLUTION FLOOR FOR LARGE-FORMAT SHEETS. PDF user units are 1/72",
  // so scale = TARGET_PPI/72 renders at this density whatever the page
  // measures.
  //
  // ⚠️ THE OLD NOTE HERE SAID LOWERING THIS WOULD CHANGE NOTHING, AND THAT IS
  // NO LONGER TRUE. It was true while MAX_CANVAS_EDGE = 4096 clamped every
  // large sheet to 85 ppi whatever this asked for. With the area cap now
  // binding instead, this number is live again on sheets between about 27x27
  // and the 16 MP ceiling. The old table, kept because it explains what
  // changed:
  //
  //   36x48 sheet (2592 x 3456 pt)     WAS (edge 4096)   NOW (16 MP area)
  //   TARGET_PPI 150  scale 2.083      4096 px, 85 ppi   4618 px, 96 ppi
  //   TARGET_PPI 120  scale 1.667      4096 px, 85 ppi   4320 px, 90 ppi
  //   TARGET_PPI  96  scale 1.333      4096 px, 85 ppi   3456 px, 72 ppi
  //
  // So lowering it now DOES cost resolution, on exactly the sheets this viewer
  // exists for. The reason not to lower it is unchanged and is stronger: the
  // cost of a render is mostly fixed per page, so buying speed with pixels
  // buys almost nothing — which is what the draft tier above is for instead.
  //
  // The note below is retained because the trap it describes is still a trap:
  // once a scale drops below the viewport-anchored one, `viewportS` takes over
  // on a phone at 32.5 ppi
  // and every bit of the legibility #413 bought is gone. There is no setting
  // of this constant that trades a little sharpness for a little speed; it is
  // all or nothing, which is precisely why the tier is chosen by WHICH SHEET
  // the reader is looking at rather than by shrinking this.
  '  var TARGET_PPI = 150;',
  // ── WHAT THIS DEVICE WILL ACTUALLY ALLOCATE ────────────────────────────
  //
  // Corrected once at boot by `measureCanvasEdge()`; until then, and forever
  // on a device that cannot answer, it is the conservative fallback.
  //
  // WHY A STRIP AND NOT A SQUARE. The probe's capability ladder allocates
  // edge x edge, and 16384 square is 268 MP — a gigabyte of RGBA. That is the
  // most expensive thing on the probe page and is emphatically not something
  // to do on every open for every reader. What actually has to be known is the
  // DIMENSION limit, and a 16384 x 8 strip answers exactly that question for
  // 512 KB. The AREA is bounded separately and independently by
  // MAX_CANVAS_PX, which is 16 MP — far below any area limit a WebView that
  // accepts a 16384 dimension is likely to impose.
  //
  // READ BACK, NOT ASSUMED. A canvas asked for more than it will give does not
  // throw; it silently keeps its previous width. Comparing the property
  // afterwards is the only reading that is true, and touching the far corner
  // with getImageData is what proves the backing store is real rather than a
  // context that accepts draws and keeps nothing.
  '  var measuredCanvasEdge = 0;',
  '  function canvasEdgeLimit(){',
  '    var e = measuredCanvasEdge > 0 ? measuredCanvasEdge : CANVAS_EDGE_FALLBACK;',
  '    return Math.min(e, MAX_CANVAS_EDGE);',
  '  }',
  '  function measureCanvasEdge(){',
  '    var ladder = [4096, 8192, 12288, 16384], best = 0, i, c, ctx, px;',
  '    for (i = 0; i < ladder.length; i++) {',
  '      if (ladder[i] > MAX_CANVAS_EDGE) break;',
  '      c = null;',
  '      try {',
  '        c = document.createElement("canvas");',
  '        c.width = ladder[i]; c.height = 8;',
  '        if (c.width !== ladder[i]) { c.width = 0; c.height = 0; break; }',
  '        ctx = c.getContext("2d");',
  '        if (!ctx) { c.width = 0; c.height = 0; break; }',
  '        ctx.fillStyle = "#fff";',
  '        ctx.fillRect(ladder[i] - 1, 7, 1, 1);',
  '        px = ctx.getImageData(ladder[i] - 1, 7, 1, 1);',
  '        c.width = 0; c.height = 0;',
  '        if (!(px && px.data && px.data[3] === 255)) break;',
  '        best = ladder[i];',
  '      } catch (e) {',
  '        try { if (c) { c.width = 0; c.height = 0; } } catch (e2) {}',
  '        break;',
  '      }',
  '    }',
  // ZERO IS "UNKNOWN", and unknown means the fallback — never the top of the
  // ladder. A device that fell over on the very first rung has told us
  // something, and what it told us is not "assume 16384".
  '    measuredCanvasEdge = best;',
  '    probePost("canvas-edge", { measured: best, fallback: CANVAS_EDGE_FALLBACK,',
  '      guard: MAX_CANVAS_EDGE, inUse: canvasEdgeLimit(),',
  '      known: best > 0 });',
  '  }',
  // How far either side of the viewport a page counts as "near". Feeds both
  // the observer's rootMargin and the no-observer sweep, so the two paths
  // agree on what is near.
  '  var BAND = 1.5;',
  // ── ONE RASTERISATION AT A TIME, AND THE THREAD IS THE REASON ──────────
  //
  // `renderSlot` guards per slot (`if (slot.busy) return;`) and nothing capped
  // the GLOBAL in-flight count. The observer's first callback arrives with
  // every in-band page in one batch, so a dozen rasterisations started on one
  // thread and each one's wall clock contained all the others. Measured on the
  // operator's phone, 26-sheet plan, 1.2 MP a sheet:
  //
  //     4585 4591 4749 4912 5323 5465 5886 6304 6310 6668
  //     6935 7529 7601 7933 8214 8790 8970 9004 9281 9490
  //
  // A monotonic climb, which is the signature of contention and not of size:
  // the SAME 1.2 MP page renders in 2252 ms uncontended, and 11.2 MP in 727.
  // The ten seconds of white screen was page 1 waiting in a queue nobody
  // bounded.
  //
  // TOTAL WORK IS UNCHANGED. What changes is that the sheet the reader is
  // looking at finishes in its own uncontended time instead of last, behind
  // eleven he cannot see.
  //
  // WHY 1 AND NOT 2. The thread is the resource. There is no worker — a
  // file:// origin forces pdf.js onto the main thread, and the probe measured
  // a real Worker rendering page 1 in 6520 ms, so off-thread is not an option
  // to hold this open for. Two concurrent rasterisations on one thread is the
  // same contention in miniature. If 1 leaves prefetch too slow, 2 is a tuning
  // question and this constant is the one edit that answers it.
  '  var MAX_CONCURRENT_RENDERS = 1;',
  // ── THE RESIDENT BITMAP IS BOUNDED IN BYTES, NOT IN PAGES ──────────────
  //
  // WAS: `KEEP_RENDERED = 7`, which has NEVER BOUND ANYTHING. `trim()` skips
  // any page marked `visible` and the band marks several, so the window could
  // not close below the near set whatever the number said.
  //
  // AND A PAGE COUNT IS THE WRONG UNIT ANYWAY. The same seven pages are 31 MB
  // at the viewport scale and 350 MB once the reader has pinched in — the
  // executing test measures 336 MB held under the old constant at the zoomed
  // scale, which is precisely the figure the renderer was being killed at. A
  // budget has to be in the unit that runs out.
  //
  // ── RE-DERIVED AGAINST THE 64 MB SHEET, WHICH IS WHY IT MOVED ──────────
  //
  // 96 MB was derived when the expensive sheet was 12.58 MP / ~50 MB and every
  // in-band page was rendered at one scale. Both halves of that have changed:
  // the sharp tier now fits MAX_CANVAS_PX and is 16 MP — 64 MB of RGBA — and
  // only ONE sheet is ever at that tier. A budget inherited from arithmetic
  // that no longer applies is a number, not a bound.
  //
  // WHAT HAS TO FIT, and this is the whole derivation:
  //
  //   one sharp sheet            64 MB   16 MP x 4 bytes. NEVER TWO — the
  //                                      demote in `setPrimary()` is what
  //                                      guarantees it, not this number.
  //   the 26-sheet plan as        52 MB   26 x 0.5 MP x 4 bytes. At this size
  //   drafts                             the whole set stays cached, so
  //                                      scroll-back costs no re-decode at
  //                                      all.
  //                             ------
  //                              116 MB
  //
  // 128 MB is that with 12 MB of slack for a sheet whose aspect pushes its
  // draft over 0.5 MP, and it is a round number.
  //
  // AND `trim()` CAN ALWAYS REACH IT. The unfreeable floor — a page still in
  // the band is skipped, never freed — is one sharp sheet plus about seven
  // band drafts: 64 + 14 = 78 MB, comfortably under. A budget below that floor
  // would have `trim()` walking the list every render and freeing nothing.
  //
  // MEASURED CONTEXT: the crash reports were at 250-350 MB, and the executing
  // test measured 336 MB held under the old page-count window. 128 MB is a
  // hard ceiling well under that, on top of which pdf.js still holds the ~30 MB
  // file buffer and its own decode caches.
  //
  // EVICTION IS CHEAPER THAN IT WAS, and the number is smaller for it than it
  // would otherwise be. Under the old single-tier render an evicted sheet cost
  // a full re-decode at the display scale — the operator's 5-6 second
  // scroll-back. It now costs a DRAFT, ~465 ms, because a sheet the reader
  // scrolls back to is not the primary until he stops on it.
  //
  // DERIVED FROM THE ACTUAL CANVAS, never from an assumed scale — and that is
  // precisely why it survived the tier change at all. `canvasBytes()` reads
  // width and height off the bitmap that was really allocated, so it prices a
  // 2 MB draft and a 64 MB sharp sheet correctly with no knowledge of tiers
  // whatsoever. Had it been derived from a scale, this change would have
  // silently invalidated it.
  '  var CANVAS_BUDGET_BYTES = 128 * 1048576;',
  // ── SHARPNESS ON DEMAND, WHICH IS WHAT #413 SHOULD HAVE BEEN ───────────
  //
  // #413 was right about the resolution and wrong about when to pay for it.
  // A 36x48 sheet at a phone's viewport scale is 32.5 ppi and genuinely
  // unreadable, so `TARGET_PPI` had to exist. But it applied on every page of
  // every open: a phone went 1.83 MP a sheet to 12.58 MP, 6.9x, and the band
  // rasterises four or five sheets before the operator has touched anything.
  // That is ~63 MP on the UI thread — with no worker to put it on — to show a
  // drawing nobody has yet asked to read the fine print of. An inspector
  // waits through all of it, every single time.
  //
  // So the floor is attached to the ZOOM instead of to the open. `sharp` is
  // false at first paint and the scale is viewport-anchored — byte for byte
  // what this viewer rendered before #413 — and the first pinch past
  // ZOOM_SHARP switches it on and redraws. The legibility arrives at the
  // moment someone zooms in to read, which is the only moment it was ever
  // wanted.
  //
  // ONE WAY ONLY. `sharp` never returns to false. A reader who has zoomed in
  // once is reading the drawing, and dropping back to 32 ppi on every
  // pinch-out would be a flicker on every gesture and a re-render to pay for
  // it. `trim()` and the band below bound the memory in both directions
  // instead.
  '  var ZOOM_SHARP = 1.25;',
  // THE BAND, ONCE THE EXPENSIVE SCALE IS IN USE. This is the fix for the
  // zoom-then-reload, and a page-count window could not have been: `trim()`
  // never frees a page that is still in the band, so at BAND = 1.5 the four or
  // five near sheets are unfreeable whatever the window is set to. Seven
  // sheets at 12.58 MP is 350 MB of bitmap and five is still 250 MB, which gets
  // a Chromium renderer killed and reloaded. A reader who has pinched in is
  // looking at ONE sheet; 0.25 spans a viewport and a half either side, so
  // the near set is one or two.
  '  var BAND_SHARP = 0.25;',
  '  var sharp = false;',
  // ONE FUNCTION, BOTH READERS. The observer's rootMargin and the
  // no-observer sweep must agree about what "near" means or a page is drawn
  // by one and freed by the other.
  '  function band(){ return sharp ? BAND_SHARP : BAND; }',
  '',
  '  function post(obj){',
  '    try { if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(JSON.stringify(obj)); } catch (e) {}',
  '  }',
  '  function fail(code, detail){',
  '    if (msgEl) { msgEl.style.display = ""; msgEl.textContent = "Could not render this document."; }',
  '    post({ type: "pdf-error", code: code, detail: String(detail || "") });',
  '  }',
  '  function param(name){',
  '    var m = new RegExp("[?&]" + name + "=([^&]*)").exec(window.location.search || "");',
  '    return m ? decodeURIComponent(m[1].replace(/\\+/g, "%20")) : "";',
  '  }',
  '',
  // ══ THE RENDER-COST PROBE ═══════════════════════════════════════════════
  //
  // MEASUREMENT, NOT A FIX. Nothing below changes a pixel or a constant. It
  // runs ONLY when the page is opened with `probe=1`, which only happens when
  // the `pdf_viewer_probe` feature flag resolves true for the signed-in user
  // (PDFViewer.native.jsx). With the flag off, `PROBE` is false, every
  // function here returns immediately, and the viewer behaves exactly as it
  // does today — that is the property pdfRenderProbe.test.cjs asserts.
  //
  // WHY IT MEASURES RATHER THAN ASSUMES. Two static readings of this file have
  // already produced diagnoses that did not survive contact with the numbers.
  // The last one — that MAX_CANVAS_PX was clamping large sheets — is
  // contradicted by the arithmetic in `targetScaleInfo`: the scale is anchored
  // to `baseWidth`, so canvas width is `clientWidth * min(dpr,2) * 1.5`
  // whatever the sheet is, and neither cap is approached. That is still
  // reading. This is what settles it.
  //
  // EIGHT THINGS, in the order they are emitted:
  //   env         device, dpr, viewport, memory, cores, API availability
  //   canvas-lim  the largest square canvas that will actually allocate
  //   blobworker  can a Worker be constructed from a blob: URL on a file://
  //               page — the single fact that gates off-thread rasterisation
  //   page        per page: vp1, scale, canvas w*h, WHICH clamp bound, ppi
  //   timing      per page: getPage / alloc / render / attach, split
  //   uithread    longest main-thread stall across the open
  //   render-ab   the same page at oversample 1.5 vs 1.0 vs the cap ceiling
  //   worker-ab   the same document parsed and rendered through a REAL worker
  //
  // COST, STATED. `render-ab` and `worker-ab` do extra work on purpose. Both
  // run only AFTER `pdf-ready`, so no number they produce contaminates the
  // open they are measuring; every canvas they allocate is zeroed the instant
  // it has been timed; and `worker-ab` re-reads the file from disk rather than
  // retaining the bytes, because holding a second 30 MB buffer on a device
  // that is already being killed for memory would change the thing under test.
  '  var PROBE = param("probe") === "1";',
  // ── THE CAPABILITY READ, WITHOUT A DOCUMENT AND WITHOUT THE FLAG ───────
  //
  // `?caps=1` runs the six DEVICE measurements and stops. No file, no pdf.js
  // parse, no A/B suite, and -- deliberately -- no feature-flag dependency, so
  // it works on a site device that is offline by design and may never take a
  // flag refresh.
  //
  // ONE IMPLEMENTATION, TWO CALLERS, and that is the whole reason this is a
  // MODE rather than a second HTML page. These answers only mean anything when
  // the operator's phone and the site device can be compared line for line, and
  // a separate capability page would drift from the viewer's copy until the
  // comparison quietly stopped being like-for-like.
  '  var CAPS = param("caps") === "1";',
  // Either mode turns the measurements on. Everything that touches the
  // DOCUMENT stays gated on PROBE alone at its call site, so caps mode cannot
  // reach a render, a timing, or the A/B suite.
  '  var MEASURE = PROBE || CAPS;',
  '  function pnow(){ try { return performance.now(); } catch (e) { return Date.now(); } }',
  '  function r1(x){ return Math.round(x * 10) / 10; }',
  '  function probePost(kind, data){',
  '    if (!MEASURE) return;',
  '    try { post({ type: "pdf-probe", probe: kind, data: data }); } catch (e) {}',
  '  }',
  '',
  // Everything the design questions turn on, read off the device rather than a
  // compatibility table. `transferControlToOffscreen` is checked on a real
  // element because the prototype can carry the method on builds where calling
  // it throws.
  // ── THE FIXED COST, WHICH EVERY OTHER MEASUREMENT HERE IS BLIND TO ─────
  //
  // THE PROBE SHIPPED WITH A HOLE IN IT. `ptOpen0` is taken on the first line
  // of this script — and this script does not run until pdf.worker.min.js
  // (1.1 MB) and pdf.min.js (377 KB) have both been read off file:// storage,
  // compiled and executed on the MAIN THREAD, because a real Worker is
  // blocked from a file:// origin. So `open.totalMs` excludes the entire cost
  // of the viewer booting.
  //
  // THAT IS THE ONE COST THAT DOES NOT CARE HOW BIG THE DOCUMENT IS. It is
  // identical for a 16 KB logbook and a 30 MB plan set, which makes it the
  // only candidate that explains the operator seeing both take the same
  // 20-30 seconds. Every number the probe already reports could come back
  // small and the open would still feel slow, and nobody would know why.
  //
  // `scriptStartMs` IS THE ANSWER. performance.now() on a page is measured
  // from navigation start, so read on the first line of the capability
  // sequence it is exactly "how long before any of our code ran". The
  // per-script resource timings underneath it say how that time split between
  // reading the bytes and compiling them, and which of the two files cost it
  // — the 1.1 MB worker is the one that would move off-thread if the
  // blob-worker probe comes back supported.
  '  function probeBoot(){',
  '    if (!MEASURE) return;',
  '    var d = { scriptStartMs: r1(pnow()) };',
  '    try {',
  '      var nav = performance.getEntriesByType("navigation")[0];',
  '      if (nav) {',
  '        d.domInteractiveMs = r1(nav.domInteractive);',
  '        d.responseEndMs = r1(nav.responseEnd);',
  '      }',
  '    } catch (e) { d.navTimingError = String(e); }',
  '    try {',
  '      var res = performance.getEntriesByType("resource") || [];',
  '      d.scripts = [];',
  '      for (var i = 0; i < res.length; i++) {',
  '        var nm = String(res[i].name || "");',
  '        if (nm.indexOf(".js") < 0) continue;',
  '        d.scripts.push({ name: nm.split("/").pop(),',
  '                         startMs: r1(res[i].startTime),',
  '                         durationMs: r1(res[i].duration),',
  '                         bytes: res[i].decodedBodySize || 0 });',
  '      }',
  '    } catch (e) { d.resourceTimingError = String(e); }',
  '    probePost("boot", d);',
  '  }',
  '',
  '  function probeEnv(){',
  '    if (!MEASURE) return;',
  '    var d = {};',
  '    try { d.ua = String(navigator.userAgent || "").slice(0, 200); } catch (e) {}',
  '    try { d.dpr = window.devicePixelRatio || 1; } catch (e) {}',
  '    try { d.clientW = document.documentElement.clientWidth; } catch (e) {}',
  '    try { d.clientH = document.documentElement.clientHeight; } catch (e) {}',
  '    try { d.screenW = screen.width; d.screenH = screen.height; } catch (e) {}',
  '    try { d.deviceMemoryGB = navigator.deviceMemory || null; } catch (e) {}',
  '    try { d.cores = navigator.hardwareConcurrency || null; } catch (e) {}',
  '    d.hasWorker = (typeof Worker !== "undefined");',
  '    d.hasOffscreenCanvas = (typeof OffscreenCanvas !== "undefined");',
  '    d.hasCreateImageBitmap = (typeof createImageBitmap !== "undefined");',
  '    d.hasIntersectionObserver = (typeof IntersectionObserver !== "undefined");',
  '    try { d.hasTransferControl = typeof document.createElement("canvas").transferControlToOffscreen === "function"; } catch (e) { d.hasTransferControl = false; }',
  '    d.MAX_CANVAS_EDGE = MAX_CANVAS_EDGE;',
  '    d.CANVAS_EDGE_FALLBACK = CANVAS_EDGE_FALLBACK;',
  '    d.measuredCanvasEdge = measuredCanvasEdge;',
  '    d.canvasEdgeInUse = canvasEdgeLimit();',
  '    d.DRAFT_CANVAS_PX = DRAFT_CANVAS_PX;',
  '    d.MAX_CANVAS_PX = MAX_CANVAS_PX;',
  '    d.BAND = BAND;',
  '    d.CANVAS_BUDGET_BYTES = CANVAS_BUDGET_BYTES;',
  '    d.MAX_CONCURRENT_RENDERS = MAX_CONCURRENT_RENDERS;',
  '    probePost("env", d);',
  '  }',
  '',
  // WHAT THIS DEVICE WILL ACTUALLY GIVE US, as opposed to what the constants
  // assume. A ladder rather than a binary search: bounded, quick, and it frees
  // each canvas before trying the next, so the measurement cannot itself be
  // the allocation that kills the renderer. Touching the far corner with
  // getImageData is the part that proves the backing store is real — a canvas
  // can accept width/height and hand back a context that draws nothing.
  '  function probeCanvasLimits(){',
  '    if (!MEASURE) return;',
  '    function tryEdge(edge){',
  '      var c = null;',
  '      try {',
  '        c = document.createElement("canvas");',
  '        c.width = edge; c.height = edge;',
  '        if (c.width !== edge || c.height !== edge) { c.width = 0; c.height = 0; return false; }',
  '        var ctx = c.getContext("2d");',
  '        if (!ctx) { c.width = 0; c.height = 0; return false; }',
  '        ctx.fillStyle = "#fff";',
  '        ctx.fillRect(edge - 1, edge - 1, 1, 1);',
  '        var px = ctx.getImageData(edge - 1, edge - 1, 1, 1);',
  '        var ok = !!(px && px.data && px.data[3] === 255);',
  '        c.width = 0; c.height = 0;',
  '        return ok;',
  '      } catch (e) {',
  '        try { if (c) { c.width = 0; c.height = 0; } } catch (e2) {}',
  '        return false;',
  '      }',
  '    }',
  '    var ladder = [2048, 4096, 6144, 8192, 12288, 16384];',
  '    var best = 0, results = [];',
  '    for (var i = 0; i < ladder.length; i++) {',
  '      var t0 = pnow();',
  '      var ok = tryEdge(ladder[i]);',
  '      results.push({ edge: ladder[i], ok: ok, ms: r1(pnow() - t0) });',
  '      if (ok) best = ladder[i]; else break;',
  '    }',
  '    probePost("canvas-lim", { largestSquareEdge: best, ladder: results });',
  '  }',
  '',
  // ── BLOCKER A, ANSWERED ON HIS HARDWARE ────────────────────────────────
  //
  // A real Worker is blocked from a file:// origin, which is why this viewer
  // loads pdf.worker.min.js into the MAIN THREAD and does every parse, decode
  // and rasterise there. A Worker built from a blob: URL usually inherits the
  // creating document's origin instead of the file:// scheme and is therefore
  // allowed — usually, on some builds, which is exactly why this asks rather
  // than assumes. If this reports supported:true, off-thread rasterisation is
  // reachable with no native change and no new build. If it reports false,
  // every tiling design that puts work on a worker is dead in this delivery
  // model and the report has to say so.
  '  function probeBlobWorker(done){',
  '    if (!MEASURE) { if (done) done(false); return; }',
  '    var r = { supported: false, error: "" };',
  '    var settled = false;',
  '    function finish(){',
  '      if (settled) return;',
  '      settled = true;',
  '      probePost("blobworker", r);',
  '      if (done) done(!!r.supported);',
  '    }',
  '    if (typeof Worker === "undefined") { r.error = "no-Worker-constructor"; finish(); return; }',
  '    if (typeof Blob === "undefined" || !window.URL || !URL.createObjectURL) { r.error = "no-blob-url"; finish(); return; }',
  '    var w = null, u = null;',
  '    try {',
  '      var src = "self.onmessage=function(e){self.postMessage(e.data*2);};";',
  '      u = URL.createObjectURL(new Blob([src], { type: "text/javascript" }));',
  '      var t0 = pnow();',
  '      w = new Worker(u);',
  '      w.onmessage = function(ev){',
  '        r.supported = (ev && ev.data === 84);',
  '        r.roundTripMs = r1(pnow() - t0);',
  '        try { w.terminate(); } catch (e) {}',
  '        try { URL.revokeObjectURL(u); } catch (e) {}',
  '        finish();',
  '      };',
  '      w.onerror = function(ev){',
  '        r.error = "onerror:" + String((ev && (ev.message || ev.type)) || "unknown");',
  '        try { w.terminate(); } catch (e) {}',
  '        try { URL.revokeObjectURL(u); } catch (e) {}',
  '        finish();',
  '      };',
  '      w.postMessage(42);',
  '      setTimeout(function(){',
  '        if (settled) return;',
  '        r.error = "timeout-3s";',
  '        try { if (w) w.terminate(); } catch (e) {}',
  '        try { if (u) URL.revokeObjectURL(u); } catch (e) {}',
  '        finish();',
  '      }, 3000);',
  '    } catch (e) {',
  '      r.error = "throw:" + String(e);',
  '      try { if (w) w.terminate(); } catch (e2) {}',
  '      try { if (u) URL.revokeObjectURL(u); } catch (e2) {}',
  '      finish();',
  '    }',
  '  }',
  '',
  // ── BLOCKER A, SECOND HALF: CAN THE SCRIPT TEXT BE OBTAINED AT ALL ─────
  //
  // The blob trick above proves a Worker can be CONSTRUCTED. It says nothing
  // about whether we can get pdf.worker.min.js into a string to put in the
  // Blob — and that is a separate restriction that kills the same plan one
  // step earlier. The worker bundle is staged in documentDirectory, so the
  // text has to be read off a file:// path first.
  //
  // XHR AND fetch ARE MEASURED SEPARATELY AND THAT IS THE POINT. `fetch()` on
  // a file:// URL is blocked outright in Chromium; XMLHttpRequest is not, and
  // is what `allowFileAccessFromFileURLs` grants — it is how `readBytes`
  // already pulls 30 MB of PDF off disk on this very page. So the expected
  // answer is xhr:true / fetch:false, and if that is what comes back then the
  // constructor half above is the only real question. Assuming it would be a
  // guess, and the two failures have completely different fixes.
  //
  // IF XHR FAILS TOO, the text has to come across the React Native bridge as a
  // string — 1.1 MB of JavaScript marshalled through injectedJavaScript rather
  // than read from disk. Different plumbing, its own cost, and this is the
  // measurement that says whether it is needed.
  '  function probeWorkerSource(done){',
  '    if (!MEASURE) { if (done) done(); return; }',
  '    var out = { path: "' + WORKER_NAME + '", xhr: false, xhrBytes: 0, xhrMs: null,',
  '                xhrError: "", fetchSupported: (typeof fetch === "function"),',
  '                fetch: false, fetchMs: null, fetchError: "" };',
  '    var pending = 2;',
  '    function step(){ pending--; if (pending <= 0) { probePost("workersrc", out); if (done) done(); } }',
  '    var t0 = pnow();',
  '    try {',
  '      var x = new XMLHttpRequest();',
  '      x.open("GET", "' + WORKER_NAME + '", true);',
  '      x.onload = function(){',
  '        var t = x.responseText || "";',
  '        out.xhr = t.length > 0;',
  '        out.xhrBytes = t.length;',
  '        out.xhrMs = r1(pnow() - t0);',
  '        step();',
  '      };',
  '      x.onerror = function(){ out.xhrError = "xhr-blocked"; step(); };',
  '      x.send(null);',
  '    } catch (e) { out.xhrError = "throw:" + String(e); step(); }',
  '    if (typeof fetch !== "function") { out.fetchError = "no-fetch"; step(); }',
  '    else {',
  '      var f0 = pnow();',
  '      try {',
  '        fetch("' + WORKER_NAME + '").then(function(res){ return res.text(); })',
  '          .then(function(t){ out.fetch = !!(t && t.length); out.fetchMs = r1(pnow() - f0); step(); })',
  '          ["catch"](function(e){ out.fetchError = "rejected:" + String((e && (e.message || e)) || "unknown"); step(); });',
  '      } catch (e) { out.fetchError = "throw:" + String(e); step(); }',
  '    }',
  '  }',
  '',
  // ── THE MBTiles PREREQUISITES ──────────────────────────────────────────
  //
  // NOT A PYRAMID DESIGN. If the probe forces server-side tiling, the sync
  // shape that keeps the manifest flat is one SQLite file per sheet queried in
  // the page — but sql.js is SQLite compiled to wasm and would be a SECOND
  // bundled binary in a viewer already carrying 1.5 MB of pdf.js. Two things
  // have to be true before that is worth costing, and both are cheap to ask
  // here rather than on a second trip:
  //
  //   wasm     does WebAssembly instantiate at all in this System WebView,
  //            from a file:// page. If not, sql.js is dead and the
  //            one-file-per-sheet shape goes with it.
  //   binread  can a staged BINARY file be read as an ArrayBuffer. A .mbtiles
  //            is a binary blob on disk, and that is exactly the read sql.js
  //            would have to do. Measured against pdf.worker.min.js — ~1.1 MB,
  //            already on disk — so the throughput number is real rather than
  //            a synthetic.
  //
  // WHAT IS DELIBERATELY NOT MEASURED: tile-query cost versus a direct object
  // fetch. That needs sql.js actually present, and bundling a wasm binary to
  // answer a question gated on a probe that has not run yet is the wrong
  // order. If these two come back green it is its own small trip.
  '  function probeWasm(done){',
  '    if (!MEASURE) { if (done) done(); return; }',
  '    var out = { hasWebAssembly: (typeof WebAssembly !== "undefined"), instantiated: false, ms: null, error: "" };',
  '    if (!out.hasWebAssembly) { probePost("wasm", out); if (done) done(); return; }',
  '    try {',
  // The smallest valid module there is: magic number, version, no sections.
  '      var bytes = new Uint8Array([0,97,115,109,1,0,0,0]);',
  '      var t0 = pnow();',
  '      WebAssembly.instantiate(bytes).then(function(){',
  '        out.instantiated = true; out.ms = r1(pnow() - t0);',
  '        probePost("wasm", out); if (done) done();',
  '      })["catch"](function(e){',
  '        out.error = String((e && (e.message || e)) || "unknown");',
  '        probePost("wasm", out); if (done) done();',
  '      });',
  '    } catch (e) { out.error = "throw:" + String(e); probePost("wasm", out); if (done) done(); }',
  '  }',
  '',
  '  function probeBinaryRead(done){',
  '    if (!MEASURE) { if (done) done(); return; }',
  '    var out = { path: "' + WORKER_NAME + '", ok: false, bytes: 0, ms: null, mbPerSec: null, error: "" };',
  '    var t0 = pnow();',
  '    try {',
  '      var x = new XMLHttpRequest();',
  '      x.open("GET", "' + WORKER_NAME + '", true);',
  '      x.responseType = "arraybuffer";',
  '      x.onload = function(){',
  '        var b = x.response;',
  '        out.ok = !!(b && b.byteLength);',
  '        out.bytes = (b && b.byteLength) || 0;',
  '        out.ms = r1(pnow() - t0);',
  '        if (out.ok && out.ms > 0) out.mbPerSec = r1((out.bytes / 1048576) / (out.ms / 1000));',
  '        probePost("binread", out); if (done) done();',
  '      };',
  '      x.onerror = function(){ out.error = "xhr-blocked"; probePost("binread", out); if (done) done(); };',
  '      x.send(null);',
  '    } catch (e) { out.error = "throw:" + String(e); probePost("binread", out); if (done) done(); }',
  '  }',
  '',
  // ── THE COST OF HAVING NO WORKER, PART ONE ─────────────────────────────
  //
  // A 16 ms interval that records the largest gap between its own ticks. On an
  // idle thread the gap is ~16 ms; every millisecond over that is time the UI
  // thread spent inside something it could not be interrupted out of. The
  // LONGEST gap is the number that matters — it is the freeze the operator
  // feels, and on this viewer it is a single page rasterising, because there
  // is no worker to put it on.
  '  var hbTimer = null, hbLast = 0, hbMax = 0, hbTicks = 0, hbOver = 0;',
  '  function hbStart(){',
  '    if (!PROBE || hbTimer) return;',
  '    hbLast = pnow(); hbMax = 0; hbTicks = 0; hbOver = 0;',
  '    hbTimer = setInterval(function(){',
  '      var t = pnow(), gap = t - hbLast; hbLast = t; hbTicks++;',
  '      if (gap > hbMax) hbMax = gap;',
  '      if (gap > 100) hbOver++;',
  '    }, 16);',
  '  }',
  '  function hbStop(label){',
  '    if (!PROBE || !hbTimer) return;',
  '    clearInterval(hbTimer); hbTimer = null;',
  '    probePost("uithread", { label: label, longestStallMs: r1(hbMax), ticks: hbTicks, stallsOver100ms: hbOver });',
  '  }',
  '',
  // ── CAPS MODE ENDS HERE ────────────────────────────────────────────────
  //
  // No document is read, so there is nothing to fail on and nothing to clean
  // up. The `caps` marker is what the admin screen waits for; without it the
  // screen cannot tell "still running" from "this WebView answered nothing".
  '  if (CAPS) {',
  '    if (msgEl) msgEl.textContent = "Reading device capabilities\\u2026";',
  '    capabilityRead(function(){',
  '      if (msgEl) msgEl.textContent = "Device capability read complete.";',
  '      probePost("caps", { done: true });',
  '    });',
  '    return;',
  '  }',
  '',
  // ── THE DOCUMENT IS NO LONGER PART OF THE URL ──────────────────────────
  //
  // THE COST THIS REMOVES, AND WHY THE MEMOISATION NEVER TOUCHED IT.
  // `alreadyStaged()` correctly copies pdf.min.js and pdf.worker.min.js to
  // disk once per VIEWER_VERSION, and it was easy to read that as "the viewer
  // is only set up once". It is not. The page used to take its document from
  // `?file=`, so opening a second document meant a different url, and a
  // different url in a WebView is a NAVIGATION: the page is torn down and
  // 1.5 MB of pdf.js — 1.1 MB of it the worker bundle, which a file:// origin
  // forces onto the MAIN THREAD — is read off storage, compiled and executed
  // again from nothing. The staging was memoised; the PARSE never was, and
  // the parse is the expensive half.
  //
  // THAT IS THE WHOLE OF THE LOGBOOK COMPLAINT. A 16 KB letter-size logbook
  // needs 2.1 MP of canvas and pays exactly the same startup as a 36x48
  // drawing, which is why a small document was as slow as a large one and why
  // no amount of work on the SCALE could have fixed it.
  //
  // So `fileUrl` starts empty and the host sends documents IN, over the
  // channel `post()` already uses in the other direction. The url stays
  // constant for the life of the WebView, the page never navigates, and
  // pdf.js is parsed once per WebView rather than once per open.
  //
  // `?file=` IS STILL HONOURED. It is how the page was always opened, it
  // costs one branch, and keeping it means this change cannot strand a caller
  // that has not been moved over.
  '  var fileUrl = "";',
  '  if (typeof pdfjsLib === "undefined") { fail("no-lib", "pdf.min.js did not load"); return; }',
  '  try { pdfjsLib.GlobalWorkerOptions.workerSrc = "' + WORKER_NAME + '"; } catch (e) {}',
  '',
  // file:// XHR. status is 0 (not 200) on success for file:// — test the body.
  '  function readBytes(url, ok, err){',
  '    var xhr = new XMLHttpRequest();',
  '    try { xhr.open("GET", url, true); } catch (e) { err("open:" + e); return; }',
  '    xhr.responseType = "arraybuffer";',
  '    xhr.onload = function(){',
  '      var buf = xhr.response;',
  '      if (buf && buf.byteLength) ok(new Uint8Array(buf));',
  '      else err("empty-response");',
  '    };',
  '    xhr.onerror = function(){ err("xhr-blocked"); };',
  '    try { xhr.send(null); } catch (e) { err("send:" + e); }',
  '  }',
  '',
  '  var doc = null;',
  '  var slots = [];',
  // Rasterised pages, least-recently-wanted first. The only thing that keeps a
  // canvas alive.
  '  var rendered = [];',
  '  var io = null;',
  '  var baseWidth = 0;',
  '',
  // THE SAME ARITHMETIC AS BEFORE, returning WHY as well as WHAT.
  //
  // Split out of targetScale so the probe can report which clamp actually
  // bound without recomputing it beside the real one and risking the two
  // disagreeing. `targetScale` below is the only caller the renderer uses and
  // it returns exactly what it always did, so with the probe off nothing about
  // this path has changed.
  //
  // OVERSAMPLE IS A PARAMETER, not a literal, for the SAME reason: the A/B
  // measures 1.0 against 1.5 through this function rather than through a
  // second copy of the formula.
  '  function targetScaleInfo(vp1, over, wantFloor){',
  '    var dpr = window.devicePixelRatio || 1;',
  // ── THE SHEET'S OWN SIZE HAD CANCELLED OUT OF THIS ────────────────────────
  //
  // `(baseWidth / vp1.width) * dpr * 1.5` renders `baseWidth * dpr * 1.5`
  // pixels across WHATEVER the page measures — so a 36x48 drawing and a letter
  // page get the same pixel count, and resolution falls as the sheet grows.
  // That is backwards for the one document type this viewer exists to show.
  //
  // Measured consequence on a 36x48 sheet, from those constants alone:
  //   phone      390 CSS px  -> 1170 px  ->  32.5 ppi   (soft, and reported so)
  //   tablet     768         -> 2304     ->  64 ppi
  //   tablet LS  1024        -> 3072     ->  85 ppi     (already at the cap)
  //
  // A PPI FLOOR, NOT A REPLACEMENT. PDF user units are 1/72", so `TARGET_PPI/72`
  // is the scale that renders at that density whatever the page measures. Taking
  // the MAX of the two leaves every page that was already sharper exactly as it
  // was — a letter page on a tablet still renders at the viewport-anchored
  // scale, which is far above 150 ppi — and lifts only the pages the old
  // formula starved. Nothing gets fewer pixels than before.
  //
  // AND THE CEILING IS UNCHANGED. The three clamps below already run
  // unconditionally, so this cannot ask for more than MAX_CANVAS_EDGE and
  // MAX_CANVAS_PX already permit: 4096px on the long edge is 85 ppi on a 48"
  // sheet, which is what a landscape tablet renders today. The worst case is
  // that a phone now does the same work a tablet already does.
  //
  // `over` still multiplies the viewport term only, so the probe's 1.0-vs-1.5
  // A/B still measures what it was written to measure.
  '    var viewportS = (baseWidth / vp1.width) * Math.min(dpr, 2) * (over === undefined ? 1.5 : over);',
  '    var ppiS = TARGET_PPI / 72;',
  // THE FLOOR IS NOW A TIER, NOT A CONSTANT. `wantFloor` left undefined means
  // "whatever the viewer is currently doing", which is what the real render
  // path passes; the probe's A/B passes it explicitly so it can time both
  // tiers without depending on what the reader happened to have done.
  '    var floorOn = (wantFloor === undefined) ? sharp : !!wantFloor;',
  '    var s = floorOn ? Math.max(viewportS, ppiS) : viewportS;',
  '    var anchor = (floorOn && ppiS > viewportS) ? "ppi" : "viewport";',
  '    var w = vp1.width * s, h = vp1.height * s;',
  '    var clamp = "none";',
  // THE EDGE CLAMP IS NOW THE DEVICE'S, NOT A LITERAL. `canvasEdgeLimit()` is
  // min(what this WebView demonstrably allocates, MAX_CANVAS_EDGE) and falls
  // back to the 4096 this viewer always shipped when it cannot be read.
  '    var edgeCap = canvasEdgeLimit();',
  '    if (w > edgeCap) { s = s * (edgeCap / w); w = vp1.width * s; h = vp1.height * s; clamp = "edge-w"; }',
  '    if (h > edgeCap) { s = s * (edgeCap / h); w = vp1.width * s; h = vp1.height * s; clamp = (clamp === "none" ? "edge-h" : clamp + "+edge-h"); }',
  '    if (w * h > MAX_CANVAS_PX) { s = s * Math.sqrt(MAX_CANVAS_PX / (w * h)); w = vp1.width * s; h = vp1.height * s; clamp = (clamp === "none" ? "maxpx" : clamp + "+maxpx"); }',
  '    return { s: s, w: w, h: h, clamp: clamp, dpr: dpr, baseWidth: baseWidth,',
  '             anchor: anchor, floor: floorOn, ppi: 72 * s, targetPpi: TARGET_PPI };',
  '  }',
  '',
  '  function targetScale(vp1){ return targetScaleInfo(vp1).s; }',
  '',
  // THE CEILING THE EXISTING CAPS ALLOW, ignoring the viewport entirely.
  //
  // Not a proposal — a MEASUREMENT. The scale anchor today is baseWidth, so a
  // 36x48 sheet is rasterised at whatever the screen is wide and the caps are
  // never approached. This is the largest scale MAX_CANVAS_EDGE and
  // MAX_CANVAS_PX actually permit for this page, and the A/B renders at it so
  // the unused headroom has a render time and a ppi against it.
  '  function ceilingScaleInfo(vp1){',
  '    var edgeCap = canvasEdgeLimit();',
  '    var s = Math.min(edgeCap / vp1.width, edgeCap / vp1.height);',
  '    var w = vp1.width * s, h = vp1.height * s;',
  '    var clamp = (w >= h) ? "edge-w" : "edge-h";',
  '    if (w * h > MAX_CANVAS_PX) { s = s * Math.sqrt(MAX_CANVAS_PX / (w * h)); w = vp1.width * s; h = vp1.height * s; clamp = clamp + "+maxpx"; }',
  '    return { s: s, w: w, h: h, clamp: clamp };',
  '  }',
  '',
  // ── THE TWO TIERS ──────────────────────────────────────────────────────
  //
  // ONE ENTRY POINT FOR THE RENDER PATH, so a tier cannot be chosen in one
  // place and priced in another. `targetScaleInfo` is untouched and still
  // carries the anchor/floor/clamp reasoning the probe and the scale-anchor
  // gate read; this is the thin thing on top of it that says which of the two
  // a given render is.
  //
  //   draft  fit to DRAFT_CANVAS_PX. Anchored to the SHEET, not to the
  //          viewport, because the point is a fixed, predictable cost per
  //          page — a viewport-anchored draft would be 1.2 MP on this phone
  //          and 5 MP on a tablet, and the whole design rests on the draft
  //          being cheap everywhere.
  //   sharp  the PPI floor, held to the caps: `targetScaleInfo(vp1, 1.5,
  //          true)`. With the edge cap now the device's, the AREA cap binds
  //          and the answer is the 16 MP fit — 4899 x 3266, 136 ppi, on a
  //          36x24 sheet.
  //
  // NEVER FEWER PIXELS THAN THE DRAFT. On a small page — a letter-size
  // logbook — the viewport-anchored sharp scale can be below a 0.5 MP fit, and
  // a "sharp" pass that made the sheet blurrier would be absurd. Taking the
  // max means the promotion can only ever improve the picture.
  '  function draftScaleInfo(vp1){',
  '    var s = Math.sqrt(DRAFT_CANVAS_PX / (vp1.width * vp1.height));',
  '    var edgeCap = canvasEdgeLimit();',
  '    var w = vp1.width * s, h = vp1.height * s;',
  '    if (w > edgeCap) { s = s * (edgeCap / w); w = vp1.width * s; h = vp1.height * s; }',
  '    if (h > edgeCap) { s = s * (edgeCap / h); w = vp1.width * s; h = vp1.height * s; }',
  '    return { s: s, w: w, h: h, clamp: "draft", tier: "draft" };',
  '  }',
  '',
  '  function tierScaleInfo(vp1, tier){',
  '    if (tier === "sharp") {',
  '      var sh = targetScaleInfo(vp1, 1.5, true);',
  '      var dr = draftScaleInfo(vp1);',
  '      if (sh.s < dr.s) { dr.tier = "sharp"; return dr; }',
  '      sh.tier = "sharp";',
  '      return sh;',
  '    }',
  '    return draftScaleInfo(vp1);',
  '  }',
  '',
  // Give a page back. Detaching the <canvas> is NOT enough: the element is
  // still reachable from the slot, and even an unreachable one keeps its
  // backing store until a GC that may never come under memory pressure.
  // Setting width and height to 0 drops the bitmap there and then, which is
  // the only step that actually returns the megabytes.
  '  function releaseSlot(slot){',
  // A slot being given back must not still be waiting in line for a render.
  // Same reason the generation stamp exists below: the work is for a canvas
  // that is about to stop existing.
  '    dequeue(slot);',
  '    if (slot.task) { try { slot.task.cancel(); } catch (e) {} slot.task = null; }',
  // Anything already in flight for this slot renders into a canvas we are
  // about to throw away; the generation stamp tells it not to attach.
  '    slot.gen = slot.gen + 1;',
  '    if (slot.canvas) {',
  '      if (slot.canvas.parentNode) slot.canvas.parentNode.removeChild(slot.canvas);',
  '      try { slot.canvas.width = 0; slot.canvas.height = 0; } catch (e) {}',
  '      slot.canvas = null;',
  '    }',
  // pdf.js caches the parsed operator list and any decoded images on the page
  // object; on a scanned sheet that outweighs the canvas.
  '    if (slot.page) { try { slot.page.cleanup(); } catch (e) {} slot.page = null; }',
  '    slot.el.innerHTML = "";',
  '    slot.done = false;',
  '    slot.busy = false;',
  // The slot is showing nothing, so it is at no tier. Leaving a stale `tier`
  // here would have `enqueue` decide the sheet is already correct and never
  // draw it again.
  '    slot.tier = null;',
  '    slot.wantTier = null;',
  '  }',
  '',
  // ── STOPPING WORK vs DISCARDING A RESULT: TWO MECHANISMS, ONE JOB EACH ──
  //
  // These are NOT interchangeable and neither one covers the other's case.
  //
  //   RenderTask.cancel()  STOPS THE WORK. pdf.js is the only thing that can
  //                        stop rasterising, and this is the only way to ask
  //                        it. With MAX_CONCURRENT_RENDERS = 1 the in-flight
  //                        render holds the only thread there is, so a sheet
  //                        the reader has left is not merely wasted — it is
  //                        the sheet he IS looking at, waiting. Its promise
  //                        rejects with RenderingCancelledException, which the
  //                        catch below already swallows silently.
  //
  //   slot.gen             STOPS THE RESULT BEING USED. cancel() is a request,
  //                        not a guarantee: a render can complete in the
  //                        window between the call and the promise settling,
  //                        and `releaseSlot` may already have thrown the
  //                        canvas away. The generation stamp is what makes
  //                        that late `.then` discard its canvas instead of
  //                        attaching it to a slot that has moved on.
  //
  // SO: `releaseSlot` does BOTH, because it is discarding the slot's identity.
  // Leaving the band does cancel ONLY, because the slot keeps its identity and
  // may be re-rendered later at the same generation — and if cancel loses the
  // race and the render lands anyway, attaching it is harmless and slightly
  // useful: the page is out of band, so `trim()` can now free it on merit.
  '  function cancelInFlight(slot){',
  '    if (!slot.task) return;',
  '    try { slot.task.cancel(); } catch (e) {}',
  '  }',
  '',
  '  function touch(slot){',
  '    var i = rendered.indexOf(slot);',
  '    if (i >= 0) rendered.splice(i, 1);',
  '    rendered.push(slot);',
  '  }',
  '',
  // WHAT A SLOT IS ACTUALLY COSTING, read off the bitmap that was allocated
  // rather than recomputed from a scale. RGBA, four bytes a pixel — the
  // backing store a canvas holds whatever was drawn into it.
  '  function canvasBytes(slot){',
  '    var c = slot.canvas;',
  '    if (!c) return 0;',
  '    return (c.width || 0) * (c.height || 0) * 4;',
  '  }',
  '',
  // Hold the resident bitmap under the byte budget, least-recently-wanted
  // first. A page still inside the band is skipped, never freed — the observer
  // would not fire for it again and it would sit blank on screen.
  '  function trim(){',
  '    var total = 0, i;',
  '    for (i = 0; i < rendered.length; i++) total = total + canvasBytes(rendered[i]);',
  '    i = 0;',
  '    while (total > CANVAS_BUDGET_BYTES && i < rendered.length) {',
  '      if (rendered[i].visible) { i = i + 1; continue; }',
  '      total = total - canvasBytes(rendered[i]);',
  '      releaseSlot(rendered.splice(i, 1)[0]);',
  '    }',
  '  }',
  '',
  // ── THE QUEUE, AND WHY ORDER MATTERS AS MUCH AS THE CAP ────────────────
  //
  // A queue of one that still starts with sheet 12 because sheet 12 came first
  // out of the observer's callback fixes nothing — the reader still watches a
  // white screen while eleven sheets he cannot see are drawn ahead of his.
  //
  // SO THE CHOICE IS RE-MADE EVERY TIME, not fixed when the page was queued.
  // `pumpQueue` scans for the nearest sheet at the instant a slot comes free,
  // which is the only moment it can act on the answer; a page that was nearest
  // when it went in is not nearest ten seconds later, and a priority queue
  // that sorted once would be a FIFO with extra steps.
  //
  // O(n) a pick, on a queue that is the band — a handful of entries. A heap
  // would have to be re-heapified on every scroll anyway, because the key is
  // the reader's position and not a property of the page.
  '  var queue = [];',
  '  var inFlight = 0;',
  '',
  // Distance from the viewport in CSS pixels: 0 for anything on screen, and
  // how far off it is otherwise. Ties among on-screen sheets fall to queue
  // order, which is page order — the top of the viewport, where the reader is
  // looking.
  '  function nearness(slot){',
  '    var h = window.innerHeight || document.documentElement.clientHeight || 800;',
  '    var r = slot.el.getBoundingClientRect();',
  '    if (r.bottom < 0) return -r.bottom;',
  '    if (r.top > h) return r.top - h;',
  '    return 0;',
  '  }',
  '',
  // ── THE PRIMARY SHEET: THE ONE, AND ONLY ONE, THAT GETS A SHARP PASS ───
  //
  // "On screen" is not good enough. On the operator's device a sheet is 886 px
  // against an 883 px viewport, so through most of a scroll TWO pages are
  // partly visible — and two sharp sheets is 128 MB of bitmap before a single
  // draft is counted, which is the budget spent twice over on a question
  // nobody asked. The primary is the single page showing the MOST of itself,
  // which is the one the reader is actually reading.
  '  var primary = null;',
  '  function visibleHeight(slot){',
  '    var h = window.innerHeight || document.documentElement.clientHeight || 800;',
  '    var r = slot.el.getBoundingClientRect();',
  '    var top = r.top > 0 ? r.top : 0;',
  '    var bot = r.bottom < h ? r.bottom : h;',
  '    return bot > top ? bot - top : 0;',
  '  }',
  '',
  // THE DEMOTE IS WHAT MAKES "NEVER TWO SHARP SHEETS" TRUE, and it is not the
  // budget's job — `trim()` cannot free a page that is still in the band, and
  // the sheet that has just stopped being primary almost always still is.
  //
  // TWO WAYS DOWN, chosen by whether the reader can see it:
  //   fully off screen   free the bitmap NOW. 64 MB back immediately and
  //                      nobody sees anything change, because there is
  //                      nothing on screen to change.
  //   still partly on    queue a DRAFT of it instead. `renderSlot` renders
  //   screen             into a fresh canvas and only swaps at the end, so
  //                      the sharp bitmap stays up until its replacement is
  //                      ready and the reader never sees a blank strip.
  '  function setPrimary(next){',
  '    if (primary === next) return;',
  '    var old = primary;',
  '    primary = next;',
  '    if (old && old.tier === "sharp") {',
  '      if (nearness(old) > 0) {',
  '        releaseSlot(old);',
  '        var ri = rendered.indexOf(old);',
  '        if (ri >= 0) rendered.splice(ri, 1);',
  '        if (old.visible || inBand(old)) enqueue(old);',
  '      } else {',
  '        old.wantTier = "draft";',
  '        enqueue(old);',
  '      }',
  '    }',
  '    if (next) {',
  // A sheet with nothing on it is drafted first and promoted when that lands;
  // one that is already drawn goes straight for the sharp pass.
  '      next.wantTier = next.tier ? "sharp" : "draft";',
  '      enqueue(next);',
  '    }',
  '  }',
  '',
  // Re-read after every observer callback and every sweep, because the answer
  // is a property of where the reader is and not of any page.
  '  function refreshPrimary(){',
  '    var best = null, bestH = 0, i, vh;',
  '    for (i = 0; i < slots.length; i++) {',
  '      vh = visibleHeight(slots[i]);',
  '      if (vh > bestH) { bestH = vh; best = slots[i]; }',
  '    }',
  '    setPrimary(bestH > 0 ? best : null);',
  '  }',
  '',
  // What this slot SHOULD be showing, given where it is. Everything the band
  // holds is a draft; the primary alone is sharp.
  '  function wantedTier(slot){ return (slot === primary) ? "sharp" : "draft"; }',
  '',
  // ENQUEUE MEANS "THIS SHEET IS NOT SHOWING WHAT IT SHOULD BE". Under one
  // tier that was the same thing as "has no canvas", which is why the old
  // guard was `if (slot.done) return`. With two tiers a drawn page can still
  // be wrong, and a drawn page that is right must still not be re-queued.
  '  function enqueue(slot){',
  '    if (!slot.wantTier) slot.wantTier = wantedTier(slot);',
  '    if (slot.tier === slot.wantTier) { touch(slot); return; }',
  '    if (slot.busy) return;',
  '    if (queue.indexOf(slot) < 0) queue.push(slot);',
  '  }',
  '',
  // A sheet the reader has scrolled away from comes straight back out. Queued
  // work for a page nobody is looking at is work stolen from the page they
  // are.
  '  function dequeue(slot){',
  '    var i = queue.indexOf(slot);',
  '    if (i >= 0) queue.splice(i, 1);',
  '  }',
  '',
  // ── WHAT COMES FIRST, WHEN TWO SHEETS ARE EQUALLY NEAR ─────────────────
  //
  // Nearness is still the primary key and it is what makes the acceptance
  // arithmetic work: at open exactly one sheet is at distance 0, so its draft
  // runs (~465 ms) and then its sharp pass (~950 ms) — both ahead of the
  // neighbours' drafts, which are at distance 13 px and up. First readable
  // sheet ~465 ms, sharp ~1.4 s.
  //
  // THE TIE-BREAK IS WHERE THE MEMORY INVARIANT LIVES. Two sheets are at
  // distance 0 whenever the reader is mid-scroll, and the order among them
  // decides whether two sharp bitmaps can ever exist at once:
  //
  //   0  a sheet with NOTHING on it            — the reader sees a hole
  //   1  a demote: sharp bitmap to be replaced — 64 MB waiting to come back
  //   2  a promote: draft to be sharpened      — already legible-ish
  //
  // A demote outranking a promote is what guarantees the old sharp sheet is
  // gone before the new one is allocated. It costs the promote one draft
  // (~465 ms) on a scroll, and buys a hard ceiling on the expensive tier.
  '  function pickRank(slot){',
  '    if (!slot.tier) return 0;',
  '    if (slot.tier === "sharp" && slot.wantTier === "draft") return 1;',
  '    return 2;',
  '  }',
  '',
  '  function pumpQueue(){',
  '    while (inFlight < MAX_CONCURRENT_RENDERS && queue.length) {',
  '      var bi = 0, bd = nearness(queue[0]), br = pickRank(queue[0]), i, d, r;',
  '      for (i = 1; i < queue.length; i++) {',
  '        d = nearness(queue[i]);',
  '        r = pickRank(queue[i]);',
  '        if (d < bd || (d === bd && r < br)) { bd = d; br = r; bi = i; }',
  '      }',
  '      var slot = queue.splice(bi, 1)[0];',
  '      if (slot.busy) continue;',
  '      if (slot.tier === slot.wantTier) continue;',
  // RE-CHECKED AT THE MOMENT OF STARTING, not at the moment of queueing. The
  // reader may have moved a long way while this sat in line, and the observer
  // does not always get to report it first.
  '      if (!slot.visible && !inBand(slot)) continue;',
  '      renderSlot(slot);',
  '    }',
  '  }',
  '',
  // THE ONLY CALLER OF THIS IS `pumpQueue`. Everything else enqueues, which is
  // what keeps the cap honest: there is no second door into a rasterisation.
  '  function renderSlot(slot){',
  '    if (slot.busy) return;',
  // THE TIER IS FIXED HERE AND CARRIED THROUGH, not re-read inside the
  // promise. The reader can move while this runs, and a render that computed
  // its scale at the start and its tier at the end would attach a canvas
  // whose size does not match what the slot claims to be holding — which is
  // the byte budget mispricing itself.
  '    var tier = slot.wantTier || wantedTier(slot);',
  '    if (slot.tier === tier) { touch(slot); return; }',
  '    slot.wantTier = tier;',
  '    slot.busy = true;',
  '    inFlight = inFlight + 1;',
  // EXACTLY ONCE, on every path out — resolved, cancelled, generation-stale or
  // thrown. A leaked count is a viewer that stops rendering for good, which is
  // a worse failure than the one being fixed.
  '    var settled = false;',
  '    function finish(){',
  '      if (settled) return;',
  '      settled = true;',
  '      inFlight = inFlight - 1;',
  '      pumpQueue();',
  '    }',
  '    var gen = slot.gen;',
  // PROBE: `pt0` and the stamps below are plain locals on the real render
  // path. They cost two subtractions and a branch when the probe is off, and
  // measuring the ACTUAL render is the point — a separate timed render would
  // be measuring a different one, warm, with the operator list already parsed.
  '    var pt0 = PROBE ? pnow() : 0;',
  '    doc.getPage(slot.n).then(function(page){',
  '      if (slot.gen !== gen) { slot.busy = false; finish(); try { page.cleanup(); } catch (e) {} return null; }',
  '      slot.page = page;',
  '      var ptGetPage = PROBE ? pnow() : 0;',
  '      var vp1 = page.getViewport({ scale: 1 });',
  '      var info = tierScaleInfo(vp1, tier);',
  '      var vp = page.getViewport({ scale: info.s });',
  '      var canvas = document.createElement("canvas");',
  '      var ptAlloc0 = PROBE ? pnow() : 0;',
  '      canvas.width = Math.max(1, Math.floor(vp.width));',
  '      canvas.height = Math.max(1, Math.floor(vp.height));',
  '      var ctx = canvas.getContext("2d");',
  '      var ptAlloc1 = PROBE ? pnow() : 0;',
  '      if (PROBE) {',
  // WHAT THIS PAGE ACTUALLY IS, and what the viewer decided to do with it.
  // `ppi` is the number the quality complaint is about: canvas pixels per inch
  // of drawing, taking the PDF's own 72 points-per-inch as the unit.
  '        probePost("page", {',
  '          page: slot.n,',
  '          ptW: r1(vp1.width), ptH: r1(vp1.height),',
  '          inW: r1(vp1.width / 72), inH: r1(vp1.height / 72),',
  '          scale: Math.round(info.s * 1000) / 1000,',
  '          canvasW: canvas.width, canvasH: canvas.height,',
  '          megapixels: Math.round((canvas.width * canvas.height) / 1e5) / 10,',
  '          ppi: r1(canvas.width / (vp1.width / 72)),',
  '          tier: tier, primary: (slot === primary),',
  '          clamp: info.clamp, dpr: info.dpr, baseWidth: info.baseWidth',
  '        });',
  '      }',
  '      var ptRender0 = PROBE ? pnow() : 0;',
  '      slot.task = page.render({ canvasContext: ctx, viewport: vp });',
  '      return slot.task.promise.then(function(){',
  '        slot.task = null;',
  '        slot.busy = false;',
  '        if (PROBE) {',
  '          var ptRender1 = pnow();',
  '          probePost("timing", {',
  '            page: slot.n,',
  '            getPageMs: r1(ptGetPage - pt0),',
  '            canvasAllocMs: r1(ptAlloc1 - ptAlloc0),',
  '            renderMs: r1(ptRender1 - ptRender0),',
  '            tier: tier,',
  '            totalMs: r1(ptRender1 - pt0)',
  '          });',
  '        }',
  '        if (slot.gen !== gen) { canvas.width = 0; canvas.height = 0; finish(); return; }',
  // A slot released and re-requested mid-render can have two renders land on
  // it. Whatever was here loses its bitmap before it loses its parent.
  '        if (slot.canvas && slot.canvas !== canvas) {',
  '          try { slot.canvas.width = 0; slot.canvas.height = 0; } catch (e) {}',
  '        }',
  '        slot.el.innerHTML = "";',
  '        slot.el.appendChild(canvas);',
  '        slot.canvas = canvas;',
  '        slot.tier = tier;',
  '        slot.done = true;',
  '        touch(slot);',
  '        trim();',
  // ── THE SECOND PASS IS QUEUED ONLY NOW, AND ONLY FOR THIS SHEET ────────
  //
  // Queued after the draft has been ATTACHED, not before it, so the reader has
  // something on screen for the whole of the sharp pass rather than a blank
  // page for both of them. And only when this slot is still the primary — the
  // reader may have scrolled during the ~465 ms the draft took, and promoting
  // a sheet he has left would spend 64 MB and a thread on a page nobody is
  // looking at. `wantedTier` is asked again rather than remembered, because
  // the answer is a property of the moment.
  '        var want = wantedTier(slot);',
  '        if (want !== slot.tier) { slot.wantTier = want; enqueue(slot); }',
  '        finish();',
  '      });',
  '    })["catch"](function(e){',
  '      slot.task = null;',
  '      slot.busy = false;',
  '      finish();',
  '      if (e && e.name === "RenderingCancelledException") return;',
  '      post({ type: "pdf-page-error", page: slot.n, detail: String(e) });',
  '    });',
  '  }',
  '',
  '  function inBand(slot){',
  '    var h = window.innerHeight || document.documentElement.clientHeight || 800;',
  '    var r = slot.el.getBoundingClientRect();',
  '    return r.bottom > -(band() * h) && r.top < h + (band() * h);',
  '  }',
  '',
  // The no-IntersectionObserver path, and the same shape as the observer's
  // callback: mark what is near, QUEUE only that, trim, then let the queue
  // start one. Bounded by the byte budget and the render cap exactly like the
  // observer path — the two must not disagree about either.
  //
  // THE WHOLE BAND GOES IN BEFORE ANYTHING STARTS, which is the point: the
  // nearest sheet can only be chosen once the candidates are all known.
  '  function sweep(){',
  '    for (var i = 0; i < slots.length; i++) {',
  '      slots[i].visible = inBand(slots[i]);',
  '      if (slots[i].visible) { enqueue(slots[i]); }',
  '      else { dequeue(slots[i]); cancelInFlight(slots[i]); }',
  '    }',
  // BEFORE trim() AND BEFORE pumpQueue(). The primary decides which sheet
  // wants the expensive tier, and the demote it may trigger has to be in the
  // queue before the queue is asked to pick.
  '    refreshPrimary();',
  '    trim();',
  '    pumpQueue();',
  '  }',
  '',
  '  var sweepPending = false;',
  '  function scheduleSweep(){',
  '    if (sweepPending) return;',
  '    sweepPending = true;',
  '    setTimeout(function(){ sweepPending = false; sweep(); }, 120);',
  '  }',
  '',
  // Lazy render: only pages near the viewport. A 200-sheet plan set must not
  // rasterise 200 canvases up front — nor keep the ones it has already drawn.
  // `swept` GUARDS THE REBUILD. watch() is no longer called once: goSharp()
  // calls it again through rewatch() to change the band. On the
  // no-IntersectionObserver path that would stack a second pair of scroll
  // listeners every time, so the listeners are registered once and only the
  // sweep is repeated.
  '  var swept = false;',
  '  function watch(){',
  '    if (typeof IntersectionObserver === "undefined") {',
  // WAS: a for-loop over every slot calling renderSlot. That rasterised the
  // whole set at once and uncapped, which is the worst version of this bug.
  '      if (!swept) {',
  '        swept = true;',
  '        window.addEventListener("scroll", scheduleSweep, true);',
  '        window.addEventListener("resize", scheduleSweep);',
  '      }',
  '      sweep();',
  '      return;',
  '    }',
  // THE BATCH IS THE OPPORTUNITY. A callback arrives with every page that
  // crossed the threshold — at first observation, that is the whole band. The
  // old shape called renderSlot on each as it went and started a dozen
  // rasterisations on one thread. This one records the whole batch first and
  // only then asks the queue to start ONE, which is what makes "nearest first"
  // a question that can be answered at all.
  '    io = new IntersectionObserver(function(entries){',
  '      for (var i = 0; i < entries.length; i++) {',
  '        var slot = entries[i].target.__slot;',
  '        if (!slot) continue;',
  '        if (entries[i].isIntersecting) {',
  '          slot.visible = true;',
  '          enqueue(slot);',
  '        } else {',
  '          slot.visible = false;',
  '          dequeue(slot);',
  // AND STOP THE ONE ALREADY RUNNING. `dequeue` only takes a sheet out of the
  // LINE; with one thread, an in-flight render for a sheet the reader has left
  // is the sheet he is looking at, waiting behind it.
  '          cancelInFlight(slot);',
  '        }',
  '      }',
  '      refreshPrimary();',
  '      trim();',
  '      pumpQueue();',
  '    }, { rootMargin: (band() * 100) + "% 0px" });',
  '    for (var j = 0; j < slots.length; j++) io.observe(slots[j].el);',
  '  }',
  '',
  // A rootMargin is fixed at construction, so the only way to change the band
  // is to build a new observer. Disconnecting first is what stops the old one
  // continuing to report against the old margin.
  '  function rewatch(){',
  '    if (io) { io.disconnect(); io = null; }',
  '    watch();',
  '  }',
  '',
  // ── THE TIER CHANGE ────────────────────────────────────────────────────
  //
  // Everything already rasterised is at the wrong scale, so it all goes. The
  // PLACEHOLDERS are untouched — `slot.el` keeps the width and height layout()
  // gave it — so the document does not move under the reader's finger while
  // this happens; pages blank and come back sharper in place.
  // ── WHAT THE PINCH STILL DOES, AND WHAT IT NO LONGER HAS TO ────────────
  //
  // IT USED TO BLANK EVERY SHEET. `sharp` was the RESOLUTION switch: first
  // paint was viewport-anchored at 32.5 ppi and the pinch turned the PPI floor
  // on, so everything already drawn was at the wrong scale and had to go.
  //
  // THAT IS NO LONGER WHAT IT MEANS. The sheet the reader is looking at is
  // already at the sharp tier — it was promoted the moment it became primary,
  // long before any pinch — so releasing every canvas here would blank the
  // page he has just pinched into and redraw it AT THE SAME SCALE. A flicker
  // bought with a second of thread, for nothing.
  //
  // SO `sharp` NOW MEANS ONE THING ONLY: tighten the band. A reader who has
  // pinched in is looking at ONE sheet, and BAND_SHARP 0.25 is what stops the
  // prefetch either side of it from being drawn at all. That is a memory
  // lever, and with a sharp sheet at 64 MB it matters more than it did, not
  // less. `trim()` frees what falls out of the new band on its own merits.
  '  function goSharp(){',
  '    if (sharp) return;',
  '    sharp = true;',
  '    probePost("sharp", { zoom: r1(zoomScale()), band: band() });',
  '    rewatch();',
  '  }',
  '',
  // Native pinch-zoom is the WebView's own, not the page's: it moves the
  // VISUAL viewport and leaves the layout viewport alone, so innerWidth and
  // devicePixelRatio both stay put and only visualViewport.scale reports it.
  '  function zoomScale(){',
  '    try { if (window.visualViewport && window.visualViewport.scale) return window.visualViewport.scale; } catch (e) {}',
  '    return 1;',
  '  }',
  '',
  // FAIL TOWARD THE LEGIBLE RENDER. If this WebView cannot report its zoom,
  // there is no event that could ever switch the floor on — so it goes on at
  // first paint and stays on, exactly as the viewer behaves today. A slow open
  // is an inconvenience; an unreadable 32-ppi sheet in a cellar with no way to
  // ask for more is the defect #413 was raised to fix, and this must never
  // reintroduce it by silence.
  '  var zoomBlind = false;',
  '  function zoomIsSharp(){ return zoomBlind || zoomScale() >= ZOOM_SHARP; }',
  // REGISTERED ONCE, NOT PER DOCUMENT. This page now stays loaded across every
  // document the operator opens, so a listener added on each open would
  // accumulate one per document for the life of the WebView.
  '  var zoomWatched = false;',
  '  function watchZoom(){',
  '    if (zoomWatched) return;',
  '    zoomWatched = true;',
  '    var vv = null;',
  '    try { vv = window.visualViewport || null; } catch (e) { vv = null; }',
  '    if (!vv) { zoomBlind = true; sharp = true; return; }',
  '    function onZoom(){ if (zoomIsSharp()) goSharp(); }',
  '    try { vv.addEventListener("resize", onZoom); } catch (e) { zoomBlind = true; sharp = true; return; }',
  '    onZoom();',
  '  }',
  '',
  // The WebView outlives the document — PDFViewer.native.jsx repoints `source`
  // at the next file rather than tearing the view down — so the observer, the
  // canvases and pdf.js's own caches have to be let go on the way out.
  '  function teardown(){',
  '    if (io) { io.disconnect(); io = null; }',
  '    window.removeEventListener("scroll", scheduleSweep, true);',
  '    window.removeEventListener("resize", scheduleSweep);',
  '    for (var i = 0; i < slots.length; i++) {',
  '      slots[i].visible = false;',
  '      releaseSlot(slots[i]);',
  '    }',
  '    rendered.length = 0;',
  // releaseSlot() takes each one out of the line above; this is the belt to
  // that pair of braces, because `resetDocument` empties `slots` straight
  // after and a slot still queued would be a reference to a page that no
  // longer has a document behind it.
  '    queue.length = 0;',
  // The only point at which the file bytes can go — see the note at
  // getDocument below.
  '    if (doc) { try { doc.destroy(); } catch (e) {} doc = null; }',
  '  }',
  '  window.addEventListener("pagehide", teardown);',
  '',
  '  function layout(){',
  '    baseWidth = Math.max(200, document.documentElement.clientWidth || window.innerWidth || 320);',
  '    var chain = Promise.resolve();',
  '    var n;',
  '    for (n = 1; n <= doc.numPages; n++) {',
  '      (function(pageNo){',
  '        chain = chain.then(function(){',
  '          return doc.getPage(pageNo).then(function(page){',
  '            var vp1 = page.getViewport({ scale: 1 });',
  '            var el = document.createElement("div");',
  '            el.className = "pg";',
  '            el.style.width = baseWidth + "px";',
  '            el.style.height = Math.round(baseWidth * (vp1.height / vp1.width)) + "px";',
  '            var slot = { n: pageNo, el: el, done: false, busy: false,',
  '                          visible: false, canvas: null, page: null, task: null, gen: 0,',
  // `tier` is what the attached canvas IS; `wantTier` is what it should be.
  // Both null on a slot that has never drawn anything, which is what makes
  // `enqueue`'s "already correct" test false for a blank page.
  '                          tier: null, wantTier: null };',
  '            el.__slot = slot;',
  '            slots.push(slot);',
  '            pagesEl.appendChild(el);',
  // Sizing the placeholder is all this page object was wanted for. Without the
  // cleanup, laying out a 200-sheet set leaves 200 parsed pages in pdf.js.
  '            try { page.cleanup(); } catch (e) {}',
  '          });',
  '        });',
  '      })(n);',
  '    }',
  '    return chain;',
  '  }',
  '',
  // ── THE A/B SUITE. Runs only after `pdf-ready`, never before ───────────
  //
  // Every render here is a THROWAWAY: its canvas is zeroed the instant it has
  // been timed and its page is cleaned up, so the suite's peak cost is one
  // extra canvas at a time on top of the window the viewer already holds.
  //
  // ONE PAGE, THE FIRST. Enough to answer the question, and it keeps the suite
  // bounded on a 200-sheet set.
  '  function probeRenderAt(pageNo, scale, label, extra, next){',
  '    if (!PROBE) { if (next) next(); return; }',
  '    doc.getPage(pageNo).then(function(page){',
  '      var vp1 = page.getViewport({ scale: 1 });',
  '      var vp = page.getViewport({ scale: scale });',
  '      var c = document.createElement("canvas");',
  '      var wpx = Math.max(1, Math.floor(vp.width)), hpx = Math.max(1, Math.floor(vp.height));',
  '      var a0 = pnow(); c.width = wpx; c.height = hpx; var ctx = c.getContext("2d"); var a1 = pnow();',
  '      if (!ctx) { try { c.width = 0; c.height = 0; } catch (e) {} probePost("render-ab", { label: label, page: pageNo, error: "no-2d-context", canvasW: wpx, canvasH: hpx }); if (next) next(); return; }',
  '      var r0 = pnow();',
  '      var t = page.render({ canvasContext: ctx, viewport: vp });',
  '      t.promise.then(function(){',
  '        var r1ms = pnow();',
  '        var out = { label: label, page: pageNo,',
  '          scale: Math.round(scale * 1000) / 1000,',
  '          canvasW: wpx, canvasH: hpx,',
  '          megapixels: Math.round((wpx * hpx) / 1e5) / 10,',
  '          ppi: r1(wpx / (vp1.width / 72)),',
  '          canvasAllocMs: r1(a1 - a0), renderMs: r1(r1ms - r0) };',
  '        if (extra) { for (var k in extra) { if (Object.prototype.hasOwnProperty.call(extra, k)) out[k] = extra[k]; } }',
  '        probePost("render-ab", out);',
  '        try { c.width = 0; c.height = 0; } catch (e) {}',
  '        try { page.cleanup(); } catch (e) {}',
  '        if (next) next();',
  '      })["catch"](function(e){',
  '        probePost("render-ab", { label: label, page: pageNo, error: String(e), canvasW: wpx, canvasH: hpx });',
  '        try { c.width = 0; c.height = 0; } catch (e2) {}',
  '        try { page.cleanup(); } catch (e2) {}',
  '        if (next) next();',
  '      });',
  '    })["catch"](function(e){ probePost("render-ab", { label: label, page: pageNo, error: "getPage:" + String(e) }); if (next) next(); });',
  '  }',
  '',
  // THE PLAN'S OWN RESOLUTION, where it has one.
  //
  // A vector sheet has no native raster and the honest answer is null. A
  // SCANNED sheet — which is what a 25-31 MB plan usually is — carries an
  // image XObject whose intrinsic pixel dimensions ARE the native size, and
  // that is the number the on-device render should be compared against. Read
  // after the page has rendered, because `page.objs` is not populated until
  // then; best-effort throughout, and null is a real answer rather than a
  // failure.
  '  function probeNativeRaster(pageNo, cb){',
  '    if (!PROBE) { cb(null); return; }',
  '    var OPS = null;',
  '    try { OPS = pdfjsLib.OPS; } catch (e) {}',
  '    if (!OPS) { cb(null); return; }',
  '    doc.getPage(pageNo).then(function(page){',
  '      page.getOperatorList().then(function(ol){',
  '        var best = null, imgs = 0, kinds = {}, masks = 0;',
  '        try {',
  '          for (var i = 0; i < ol.fnArray.length; i++) {',
  '            var fn = ol.fnArray[i];',
  '            if (fn !== OPS.paintImageXObject && fn !== OPS.paintJpegXObject && fn !== OPS.paintImageMaskXObject) continue;',
  '            imgs++;',
  '            if (fn === OPS.paintImageMaskXObject) masks++;',
  '            var nm = ol.argsArray[i] && ol.argsArray[i][0];',
  '            if (!nm) continue;',
  '            var o = null;',
  '            try { o = page.objs.get(nm); } catch (e) { o = null; }',
  '            if (!o) continue;',
  // THE DECODED SHAPE, WHICH IS AS CLOSE AS THE OPERATOR LIST GETS TO THE
  // COMPRESSION. pdf.js hands back a DECODED bitmap; the source filter is
  // consumed and discarded by then, so it cannot be read here. `kind` is the
  // useful shadow of it: ImageKind 1 is GRAYSCALE_1BPP — bilevel — which is
  // what JBIG2 and CCITT decode to and what a scanned line drawing is. 2 and 3
  // are RGB/RGBA, which is what a DCT (JPEG) photo or a rendered raster gives.
  // The authoritative answer comes from `imgfilters` below, which reads the
  // filter names out of the file itself.
  '            if (o.kind !== undefined && o.kind !== null) kinds["k" + o.kind] = (kinds["k" + o.kind] || 0) + 1;',
  '            if (o.width && o.height && (!best || o.width * o.height > best.w * best.h)) best = { w: o.width, h: o.height };',
  '          }',
  '        } catch (e) {}',
  '        probePost("native-raster", { page: pageNo, imageOps: imgs, imageMasks: masks,',
  '          decodedKinds: kinds, nativeW: best ? best.w : null, nativeH: best ? best.h : null });',
  '        try { page.cleanup(); } catch (e) {}',
  '        cb(best);',
  '      })["catch"](function(){ probePost("native-raster", { page: pageNo, error: "operator-list-failed" }); cb(null); });',
  '    })["catch"](function(){ cb(null); });',
  '  }',
  '',
  // ── WHAT THE EMBEDDED IMAGES ARE ACTUALLY COMPRESSED WITH ──────────────
  //
  // NOT AVAILABLE FROM getOperatorList, AND THAT IS WHY THIS EXISTS. The
  // operator list hands back a DECODED bitmap — `page.objs.get(name)` resolves
  // to width/height/data with the source filter already consumed and thrown
  // away. `decodedKinds` above is the closest shadow of it (kind 1 is
  // GRAYSCALE_1BPP, which is what a bilevel scan decodes to), but it cannot
  // tell JBIG2 from CCITT from a 1-bit Flate raster, and those are three very
  // different decode costs.
  //
  // SO READ THE FILTER NAMES OUT OF THE FILE. Four of the seven are
  // IMAGE-ONLY filters, which is what makes a raw byte scan conclusive rather
  // than suggestive:
  //
  //   JBIG2Decode     bilevel, extremely expensive to decode — the strongest
  //   CCITTFaxDecode  bilevel fax coding, also expensive   } form of the
  //                                                          PDFium argument
  //   DCTDecode       baseline JPEG — cheap, and its presence alone COLLAPSES
  //                   the PDFium argument
  //   JPXDecode       JPEG 2000 — expensive, and pdf.js's implementation is
  //                   its weakest decoder
  //
  // FlateDecode and LZWDecode are counted too but prove nothing on their own:
  // every PDF uses Flate for content streams. They are reported so a sheet
  // with NO image-only filter can be told apart from one this scan failed on.
  //
  // WHY A BYTE SCAN IS SOUND HERE. An image XObject is a STREAM, and a stream
  // cannot live inside an object stream — so its dictionary, and therefore its
  // /Filter entry, is always present verbatim in the file. A compressed xref
  // can hide plenty of other objects from a scan like this; it cannot hide
  // these.
  //
  // WHAT IT CANNOT DO, stated: it counts filters across the WHOLE document,
  // not per page, and it cannot attribute a filter to a particular image. For
  // the question being asked — is this plan set bilevel-scanned or JPEG — that
  // is enough, and anything finer means parsing the PDF a second time.
  '  function probeImageFilters(next){',
  '    if (!PROBE) { if (next) next(); return; }',
  '    readBytes(fileUrl, function(bytes){',
  '      var names = ["JBIG2Decode", "CCITTFaxDecode", "DCTDecode", "JPXDecode",',
  '                   "FlateDecode", "LZWDecode", "RunLengthDecode"];',
  '      var out = { byteLength: bytes.length, scanMs: null };',
  '      var t0 = pnow();',
  '      try {',
  '        for (var n = 0; n < names.length; n++) {',
  '          var pat = names[n], plen = pat.length, first = pat.charCodeAt(0), count = 0;',
  '          var limit = bytes.length - plen;',
  '          for (var i = 0; i <= limit; i++) {',
  '            if (bytes[i] !== first) continue;',
  '            var j = 1;',
  '            while (j < plen && bytes[i + j] === pat.charCodeAt(j)) j++;',
  '            if (j === plen) { count++; i += plen - 1; }',
  '          }',
  '          out[pat] = count;',
  '        }',
  '        out.scanMs = r1(pnow() - t0);',
  // The verdict, spelled out rather than left to be re-derived from seven
  // counts by whoever reads the log.
  '        out.bilevel = (out.JBIG2Decode > 0 || out.CCITTFaxDecode > 0);',
  '        out.jpeg = (out.DCTDecode > 0);',
  '        out.jpeg2000 = (out.JPXDecode > 0);',
  '        out.verdict = out.bilevel ? "bilevel-scan (JBIG2/CCITT) — expensive decode"',
  '          : (out.jpeg2000 ? "jpeg2000 (JPX) — expensive decode"',
  '          : (out.jpeg ? "jpeg (DCT) — cheap decode"',
  '          : "no image-only filter found — likely vector"));',
  '      } catch (e) { out.error = "scan:" + String(e); }',
  '      bytes = null;',
  '      probePost("imgfilters", out);',
  '      if (next) next();',
  '    }, function(code){ probePost("imgfilters", { error: "reread:" + code }); if (next) next(); });',
  '  }',
  '',
  // ── THE COST OF HAVING NO WORKER, PART TWO: THE A/B ────────────────────
  //
  // Part one measures the stall. This measures what removing it would buy, by
  // parsing and rendering the SAME document through a real worker and timing
  // the same two stages. It runs only when `blobworker` reported supported,
  // and only when the device says it has memory to spare — a second parse of a
  // 30 MB file is a real spike, and the measurement must not be the thing that
  // kills the renderer it is measuring.
  //
  // THE BYTES ARE RE-READ FROM DISK rather than retained from the first open,
  // for the same reason: holding a second copy for the life of the session
  // would change the memory profile under test.
  '  function probeWorkerAB(next){',
  '    if (!PROBE) { if (next) next(); return; }',
  '    var mem = null;',
  '    try { mem = navigator.deviceMemory || null; } catch (e) {}',
  '    if (mem !== null && mem < 3) { probePost("worker-ab", { skipped: "deviceMemory<3GB", deviceMemoryGB: mem }); if (next) next(); return; }',
  '    var w = null, u = null, doc2 = null, settled = false;',
  '    function cleanup(){',
  '      try { if (doc2) doc2.destroy(); } catch (e) {}',
  '      doc2 = null;',
  '      try { if (w) w.terminate(); } catch (e) {}',
  '      try { if (u) URL.revokeObjectURL(u); } catch (e) {}',
  '      w = null; u = null;',
  '    }',
  '    function bail(why){',
  '      if (settled) return;',
  '      settled = true;',
  '      probePost("worker-ab", { error: why });',
  '      cleanup();',
  '      if (next) next();',
  '    }',
  '    setTimeout(function(){ if (!settled) bail("timeout-60s"); }, 60000);',
  // The worker bundle is already on disk beside this page; read it as TEXT and
  // re-serve it from a blob: URL, which is the whole trick — the script is the
  // same bytes, the ORIGIN is not file://.
  '    var xhr = new XMLHttpRequest();',
  '    try { xhr.open("GET", "' + WORKER_NAME + '", true); } catch (e) { bail("worker-src-open:" + e); return; }',
  '    xhr.onerror = function(){ bail("worker-src-xhr-blocked"); };',
  '    xhr.onload = function(){',
  '      var src = xhr.responseText;',
  '      if (!src) { bail("worker-src-empty"); return; }',
  '      try { u = URL.createObjectURL(new Blob([src], { type: "text/javascript" })); w = new Worker(u); }',
  '      catch (e) { bail("worker-ctor:" + e); return; }',
  '      readBytes(fileUrl, function(bytes){',
  '        var p0 = pnow();',
  '        var task;',
  '        try {',
  '          task = pdfjsLib.getDocument({ data: bytes, worker: new pdfjsLib.PDFWorker({ port: w }),',
  '            disableRange: true, disableStream: true, disableAutoFetch: true, isEvalSupported: false });',
  '        } catch (e) { bail("getDocument:" + e); return; }',
  '        bytes = null;',
  '        task.promise.then(function(pdf){',
  '          doc2 = pdf;',
  '          var p1 = pnow();',
  '          return pdf.getPage(1).then(function(page){',
  '            var vp1 = page.getViewport({ scale: 1 });',
  '            var vp = page.getViewport({ scale: targetScaleInfo(vp1).s });',
  '            var c = document.createElement("canvas");',
  '            c.width = Math.max(1, Math.floor(vp.width)); c.height = Math.max(1, Math.floor(vp.height));',
  '            var ctx = c.getContext("2d");',
  '            var r0 = pnow();',
  '            return page.render({ canvasContext: ctx, viewport: vp }).promise.then(function(){',
  '              var r1ms = pnow();',
  '              if (!settled) {',
  '                settled = true;',
  '                probePost("worker-ab", { withRealWorker: true, parseMs: r1(p1 - p0),',
  '                  page1RenderMs: r1(r1ms - r0), canvasW: c.width, canvasH: c.height });',
  '              }',
  '              try { c.width = 0; c.height = 0; } catch (e) {}',
  '              try { page.cleanup(); } catch (e) {}',
  '              cleanup();',
  '              if (next) next();',
  '            });',
  '          });',
  '        })["catch"](function(e){ bail("parse-or-render:" + String(e)); });',
  '      }, function(code){ bail("reread:" + code); });',
  '    };',
  '    try { xhr.send(null); } catch (e) { bail("worker-src-send:" + e); }',
  '  }',
  '',
  // The whole suite, sequenced. Each step calls the next, so nothing overlaps
  // and no two renders contend for the UI thread while being timed.
  '  function probeSuite(){',
  '    if (!PROBE) return;',
  '    doc.getPage(1).then(function(page){',
  '      var vp1 = page.getViewport({ scale: 1 });',
  '      var cur = targetScaleInfo(vp1, 1.5);',
  '      var noOver = targetScaleInfo(vp1, 1.0);',
  '      var ceil = ceilingScaleInfo(vp1);',
  '      try { page.cleanup(); } catch (e) {}',
  '      probeRenderAt(1, cur.s, "anchor:viewport over:1.5 (SHIPPING)", { clamp: cur.clamp }, function(){',
  '        probeRenderAt(1, noOver.s, "anchor:viewport over:1.0", { clamp: noOver.clamp }, function(){',
  '          probeRenderAt(1, ceil.s, "anchor:cap-ceiling (HEADROOM)", { clamp: ceil.clamp }, function(){',
  '            probeNativeRaster(1, function(nat){',
  // FILTERS BEFORE THE WORKER A/B. The scan is a read plus a linear pass and
  // frees its buffer immediately; the worker A/B holds a whole second parsed
  // document. Running the cheap one first means a device that dies on the
  // expensive one has still reported the compression, which is the measurement
  // the engine decision turns on.
  '              function thenWorker(){ probeImageFilters(function(){ probeWorkerAB(function(){ probePost("suite", { done: true }); }); }); }',
  '              if (!nat) { thenWorker(); return; }',
  // Anchored to the SCAN's own pixels, then held to the same caps — the
  // "render it at what the plan actually is" case, measured rather than
  // argued.
  '              var sNat = nat.w / vp1.width;',
  '              var wN = vp1.width * sNat, hN = vp1.height * sNat;',
  '              if (wN > MAX_CANVAS_EDGE) { sNat = sNat * (MAX_CANVAS_EDGE / wN); wN = vp1.width * sNat; hN = vp1.height * sNat; }',
  '              if (hN > MAX_CANVAS_EDGE) { sNat = sNat * (MAX_CANVAS_EDGE / hN); wN = vp1.width * sNat; hN = vp1.height * sNat; }',
  '              if (wN * hN > MAX_CANVAS_PX) sNat = sNat * Math.sqrt(MAX_CANVAS_PX / (wN * hN));',
  '              probeRenderAt(1, sNat, "anchor:native-raster (CLAMPED)", { nativeW: nat.w, nativeH: nat.h }, thenWorker);',
  '            });',
  '          });',
  '        });',
  '      });',
  '    })["catch"](function(e){ probePost("suite", { error: String(e) }); });',
  '  }',
  '',
  // ── THE SIX DEVICE MEASUREMENTS ────────────────────────────────────────
  //
  // SEQUENCED, NOT FIRED IN PARALLEL. Three of them issue an XHR against the
  // staged assets, and in viewer mode the document read is starting at the
  // same moment — four concurrent reads off the same storage would distort
  // both the throughput figure and the open being measured.
  //
  // BEFORE THE FILE IS EVEN LOOKED AT, so they still report on a plan that
  // fails to parse. That is exactly when someone wants to know what this
  // WebView can and cannot do.
  '  function capabilityRead(after){',
  '    if (!MEASURE) { if (after) after(); return; }',
  // FIRST, AND THAT ORDER IS THE MEASUREMENT. probeCanvasLimits() below walks
  // a ladder up to 16384x16384 and is the most expensive thing on this page;
  // reading the boot cost after it would fold the probe's own allocations
  // into the number.
  '    probeBoot();',
  '    probeEnv();',
  '    probeCanvasLimits();',
  '    probeBlobWorker(function(){',
  '      probeWorkerSource(function(){',
  '        probeWasm(function(){',
  '          probeBinaryRead(function(){ if (after) after(); });',
  '        });',
  '      });',
  '    });',
  '  }',
  '',
  // ── ONCE, BEFORE ANYTHING IS SIZED ─────────────────────────────────────
  //
  // NOT BEHIND THE PROBE FLAG, and that is the point: the SHIPPING scale now
  // depends on this answer, so it has to be read for every reader and not only
  // for the one being measured. It is cheap enough to do unconditionally — a
  // ladder of thin strips, 512 KB at the top rung, against the probe's own
  // square ladder which reaches a gigabyte and is emphatically not this.
  //
  // BEFORE `capabilityRead`, because the probe's `env` row reports what is in
  // use and would otherwise report the fallback on every device.
  '  measureCanvasEdge();',
  '  capabilityRead(function(){});',
  // ONCE, BEFORE ANY DOCUMENT. The zoom belongs to the WebView, not to the
  // document, so it is watched for the life of the page — and `resetDocument`
  // reads the answer rather than re-registering.
  '  watchZoom();',
  '',
  // ── HANDING THE PAGE BACK BETWEEN DOCUMENTS ────────────────────────────
  //
  // THE TRADE THIS MUST NOT MAKE. Keeping the page alive across documents
  // removes a 1.5 MB parse; it would be a bad bargain if the previous
  // document's canvases stayed with it. `teardown()` is exactly the right
  // thing to call here and is reused rather than reimplemented — it
  // disconnects the observer, releases every slot (detaching AND zeroing each
  // canvas, which is the only step that returns the bitmap) and destroys the
  // pdf.js document, which is what frees the file bytes the parser holds.
  //
  // What teardown() does NOT do, because on `pagehide` there is no next
  // document, is empty the arrays and the DOM. That is this function's whole
  // remaining job.
  '  function resetDocument(){',
  '    teardown();',
  '    slots.length = 0;',
  '    rendered.length = 0;',
  '    pagesEl.innerHTML = "";',
  // THE NEXT DOCUMENT GETS THE FAST TIER AGAIN — unless the WebView is STILL
  // pinched in. Plain `sharp = false` was wrong: native zoom is a property of
  // the WebView, not of the document, so a reader who zoomed into sheet A and
  // then opened sheet B would get the 32-ppi render with no `resize` event
  // coming to correct it, because nothing about the zoom had changed. Asking
  // the viewport is the only reading that is true for both cases, and it
  // keeps the fail-toward-legible answer when the zoom cannot be read at all.
  '    sharp = zoomIsSharp();',
  // The primary is a slot of the document that has just gone. Left set, the
  // next document's first `refreshPrimary` would compare against a slot that
  // is no longer in `slots` and demote something that no longer exists.
  '    primary = null;',
  '    try { window.scrollTo(0, 0); } catch (e) {}',
  '  }',
  '',
  '  function openDocument(url){',
  '    if (!url) { fail("no-file", "no document url"); return; }',
  '    resetDocument();',
  '    fileUrl = url;',
  '    if (msgEl) { msgEl.style.display = ""; msgEl.textContent = "Loading document\\u2026"; }',
  '    hbStart();',
  '    loadCurrent();',
  '  }',
  '',
  // react-native-webview delivers `postMessage` to `document` on Android and
  // to `window` on iOS. Android is the only platform that reaches this file at
  // all — iOS hands a PDF to PDFKit and never loads pdf.js — but registering
  // both costs nothing and the cost of listening on the wrong one is a viewer
  // that silently never opens anything.
  '  function onHostMessage(ev){',
  '    var d = null;',
  '    try { d = JSON.parse((ev && ev.data) || "{}"); } catch (e) { return; }',
  '    if (!d || d.type !== "open-document" || !d.file) return;',
  '    openDocument(d.file);',
  '  }',
  '  try { document.addEventListener("message", onHostMessage); } catch (e) {}',
  '  try { window.addEventListener("message", onHostMessage); } catch (e) {}',
  '',
  // THE HOST CANNOT SEND UNTIL THE PAGE CAN RECEIVE. A document posted before
  // these listeners exist is dropped with no trace, so the page says when it
  // is ready and PDFViewer.native.jsx holds the first document until it hears
  // this.
  '  post({ type: "pdf-viewer-ready" });',
  '',
  '  var initialFile = param("file");',
  '  if (initialFile) openDocument(initialFile);',
  '',
  '  function loadCurrent(){',
  '  var ptOpen0 = PROBE ? pnow() : 0;',
  '  readBytes(fileUrl, function(bytes){',
  '    var ptBytes = PROBE ? pnow() : 0;',
  '    if (PROBE) probePost("bytes", { readMs: r1(ptBytes - ptOpen0), byteLength: (bytes && bytes.length) || 0 });',
  '    var task = pdfjsLib.getDocument({',
  '      data: bytes,',
  '      disableRange: true,',
  '      disableStream: true,',
  '      disableAutoFetch: true,',
  '      isEvalSupported: false',
  '    });',
  // THE BYTES STAY. Tempting to null them here, but it would free nothing:
  // pdf.js parses page content streams lazily out of THIS array, and with
  // disableRange/disableStream there is no second copy to fall back on, so it
  // holds the buffer for the life of the document. Dropping our own reference
  // is still worth doing — it makes doc.destroy() in teardown() the single
  // release point instead of one of two.
  '    bytes = null;',
  '    var ptParse0 = PROBE ? pnow() : 0;',
  '    task.promise.then(function(pdf){',
  '      doc = pdf;',
  '      if (PROBE) probePost("parse", { parseMs: r1(pnow() - ptParse0), pages: pdf.numPages });',
  '      var ptLayout0 = PROBE ? pnow() : 0;',
  '      return layout().then(function(){ if (PROBE) probePost("layout", { layoutMs: r1(pnow() - ptLayout0), pages: doc.numPages }); });',
  '    }).then(function(){',
  // HIDDEN, NOT REMOVED. This page now outlives the document it is showing,
  // so the next `openDocument` needs this element back to say "Loading" with.
  // Removing it from the DOM was safe only while a second document meant a
  // second page.
  '      if (msgEl) msgEl.style.display = "none";',
  '      watch();',
  '      post({ type: "pdf-ready", pages: doc.numPages });',
  // THE OPEN IS OVER. Everything the operator waits for has happened, so the
  // stall figure is closed here and the A/B suite starts only now — after
  // `watch()` has queued the band's renders, on a second turn, so the suite
  // never interleaves with the open it is measuring.
  '      if (PROBE) {',
  '        probePost("open", { totalMs: r1(pnow() - ptOpen0), pages: doc.numPages });',
  '        setTimeout(function(){ hbStop("open"); probeSuite(); }, 2000);',
  '      }',
  '    })["catch"](function(e){ if (PROBE) hbStop("open-failed"); fail("parse", e); });',
  '  }, function(code){',
  '    if (msgEl) { msgEl.style.display = ""; msgEl.textContent = "Could not read this document from storage."; }',
  '    post({ type: "pdf-error", code: code, detail: fileUrl });',
  '  });',
  '  }',
  '})();',
].join('\n');

// ── Staging ────────────────────────────────────────────────────────────────
async function copyAsset(mod, destName) {
  const asset = Asset.fromModule(mod);
  await asset.downloadAsync();
  const from = asset.localUri || asset.uri;
  if (!from) return 0;
  const to = VIEWER_DIR + destName;
  try { await FileSystem.deleteAsync(to, { idempotent: true }); } catch (_e) {}
  try {
    await FileSystem.copyAsync({ from, to });
  } catch (_e) {
    // Fallback for the cases where localUri isn't a plain `file://` we can copy
    // — chiefly the dev Metro server, where the asset is still an http uri.
    const res = await FileSystem.downloadAsync(asset.uri, to);
    if (!res?.uri) return 0;
  }
  const info = await FileSystem.getInfoAsync(to);
  return info.exists ? (info.size || 0) : 0;
}

async function stage() {
  await FileSystem.makeDirectoryAsync(VIEWER_DIR, { intermediates: true }).catch(() => {});

  const libBytes = await copyAsset(PDFJS_LIB_MODULE, LIB_NAME);
  const workerBytes = await copyAsset(PDFJS_WORKER_MODULE, WORKER_NAME);

  // ⚠️ The placeholder check. Until a human drops the real pdf.js build into
  // assets/pdfjs/, say so plainly rather than opening a page that renders
  // nothing.
  if (libBytes < MIN_REAL_ASSET_BYTES || workerBytes < MIN_REAL_ASSET_BYTES) {
    return { ok: false, reason: 'assets-missing' };
  }

  await FileSystem.writeAsStringAsync(VIEWER_DIR + VIEWER_NAME, viewerHtml(), {
    encoding: FileSystem.EncodingType.UTF8,
  });
  await FileSystem.writeAsStringAsync(VIEWER_DIR + STAMP_NAME, VIEWER_VERSION, {
    encoding: FileSystem.EncodingType.UTF8,
  });
  return { ok: true, dir: VIEWER_DIR, viewerUri: VIEWER_DIR + VIEWER_NAME };
}

async function alreadyStaged() {
  try {
    const stamp = await FileSystem.readAsStringAsync(VIEWER_DIR + STAMP_NAME).catch(() => null);
    if (stamp !== VIEWER_VERSION) return null;
    const lib = await FileSystem.getInfoAsync(VIEWER_DIR + LIB_NAME);
    const worker = await FileSystem.getInfoAsync(VIEWER_DIR + WORKER_NAME);
    const html = await FileSystem.getInfoAsync(VIEWER_DIR + VIEWER_NAME);
    if (!lib.exists || !worker.exists || !html.exists) return null;
    if ((lib.size || 0) < MIN_REAL_ASSET_BYTES || (worker.size || 0) < MIN_REAL_ASSET_BYTES) return null;
    return { ok: true, dir: VIEWER_DIR, viewerUri: VIEWER_DIR + VIEWER_NAME };
  } catch (_e) { return null; }
}

let inflight = null;

/**
 * Materialise the offline viewer on disk. Idempotent, memoised for the process
 * lifetime, and never throws — resolves to
 *   { ok: true,  dir, viewerUri }
 *   { ok: false, reason: 'assets-missing' | 'unsupported' | 'stage-failed' }
 */
export function ensurePdfJsViewer() {
  if (!canUseFs()) return Promise.resolve({ ok: false, reason: 'unsupported' });
  if (!inflight) {
    inflight = (async () => {
      try {
        const hit = await alreadyStaged();
        if (hit) return hit;
        return await stage();
      } catch (e) {
        return { ok: false, reason: 'stage-failed', detail: String(e) };
      }
    })().then((res) => {
      // A failed stage must not be memoised forever — a later attempt (e.g.
      // after an update that carries the real assets) should be able to work.
      if (!res || !res.ok) inflight = null;
      return res;
    });
  }
  return inflight;
}

/** `viewer.html?file=<encoded local pdf uri>` for the staged viewer.
 *
 *  #pagemode=none closes pdf.js's thumbnail sidebar -- the library's default,
 *  which eats half a phone screen and persists across documents once opened.
 *  A cellar is exactly where the screen is smallest and the drawing matters
 *  most, and this is now every Android open. */
export function localViewerUrlFor(viewerUri, pdfFileUri, opts) {
  if (!viewerUri || !pdfFileUri) return null;
  // `probe=1` is the ONLY thing that switches the render-cost instrumentation
  // on, and it is set from the `pdf_viewer_probe` feature flag in
  // PDFViewer.native.jsx — never from a source constant, so it can be turned
  // on for one signed-in user without shipping a build to anybody else.
  //
  // OMITTED, NOT `probe=0`, when off: the url is the WebView's `source`, and a
  // url that changes shape when a flag resolves would remount the viewer. With
  // the flag off this returns the byte-identical string it always returned.
  const probe = opts && opts.probe ? '&probe=1' : '';
  return `${viewerUri}?file=${encodeURIComponent(pdfFileUri)}${probe}#pagemode=none`;
}

/** The viewer page with NO document in it — the url an Android WebView is
 *  pointed at once and then left alone.
 *
 *  THIS RETURNING A CONSTANT IS THE POINT. `localViewerUrlFor` puts the
 *  document in the query string, so every open was a different url, and a
 *  different url is a navigation: the page is discarded and 1.5 MB of pdf.js
 *  is read off storage and recompiled on the main thread before anything can
 *  be drawn. Documents are delivered into this page by postMessage instead
 *  (`{ type: "open-document", file }`), so the url never changes and pdf.js is
 *  parsed once per WebView rather than once per document.
 *
 *  The probe flag is the ONLY thing that can vary here, and it resolves once
 *  per session before any document is opened — see the note in
 *  PDFViewer.native.jsx about why it must not move mid-session. */
export function localViewerHostUrl(viewerUri, opts) {
  if (!viewerUri) return null;
  const probe = opts && opts.probe ? '?probe=1' : '';
  return `${viewerUri}${probe}#pagemode=none`;
}

/** Directory WKWebView must be granted read access to (iOS allowingReadAccessToURL). */
export function pdfJsViewerDir() {
  return VIEWER_DIR;
}
