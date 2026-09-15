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
 *   holds a bounded window of rasterised sheets (KEEP_RENDERED) and frees the
 *   rest — removing the element AND zeroing width/height, because removal on
 *   its own does not drop the bitmap.
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
//   8 — THE WARM-UP READING. The A/B suite now runs its three scales TWICE in
//       one session, which is the only measurement that can tell "the first
//       rasterisation of a page is the expensive one" from "the suite is
//       measuring something else". Probe-only — the shipping render path is
//       byte-identical — but viewer.html is written to disk once per stamp, so
//       a device already staged at `7` would run last version's suite, report
//       three numbers instead of six, and the question would stay open.
//   9 — THE A/B IS ISOLATED, RUN THREE TIMES, AND SAYS WHAT `layout()` AND THE
//       WORKER PATH COST. Every render-ab row taken so far is worthless: the
//       suite starts 2000 ms after `pdf-ready` while the band's own sheets are
//       still rasterising (they reported 5109 ms on the operator's phone), so
//       each variant's wall clock contained the queue's wait and the three
//       numbers were being compared through a shared, moving contention term.
//       PROBE-ONLY — the shipping render path is byte-identical — but
//       viewer.html is written to disk once per stamp, so a device already
//       staged at `8` would run last version's contaminated suite, report six
//       numbers instead of nine, emit no `layoutMs` split and no worker-path
//       verdict, and every question this round exists to settle would stay
//       open. THIS BUMP IS THE MEASUREMENT'S ENTIRE DELIVERY MECHANISM.
//  11 — A REAL WORKER, ONE RENDER AT A TIME, AND A BUDGET IN MEGAPIXELS.
//       The three things this stamp delivers are all IN THE PAGE and nowhere
//       else: the worker is now built from a blob: URL by the page itself
//       (the `<script src="pdf.worker.min.js">` tag is gone, which is what
//       made pdf.js short-circuit to the main-thread handler), the render
//       queue and its cap of 1 live in the page, and so does `trim()`'s
//       megapixel budget. viewer.html is written to disk once per stamp, so a
//       device already staged at `9` would keep parsing and rasterising every
//       sheet on the UI thread, keep starting a dozen rasterisations at once,
//       and keep a window measured in pages — the app code would be new and
//       the viewer would be old, and the change would reach nobody.
//       `11` and not `10` because `10` was taken by an earlier draft of this
//       branch that is being replaced; the stamp only has to MOVE, and a
//       device staged at `10` by that draft must re-stage for this one.
const VIEWER_VERSION = '11';

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
    // ⚠️ THE WORKER IS NOT LOADED HERE ANY MORE, AND MUST NOT BE.
    //
    // This page used to carry `<script src="pdf.worker.min.js">` ahead of
    // pdf.js, with a comment saying it "makes pdf.js skip the real-Worker
    // attempt (blocked from a file:// origin)". That tag defines
    // `globalThis.pdfjsWorker`, and pdf.js short-circuits on it to the
    // main-thread handler — so the 1.1 MB worker bundle was read off storage,
    // COMPILED ON THE UI THREAD at every boot, and then used to parse and
    // rasterise every sheet on that same thread.
    //
    // THE REASON GIVEN FOR IT IS FALSE ON THIS DEVICE. `new Worker("pdf.worker
    // .min.js")` is indeed blocked from a file:// origin. A Worker built from
    // a blob: URL is not, and the operator's Pixel 10 Pro XL proved it:
    // blob workers supported, page 1 through a real worker in 618 ms. The page
    // now reads the worker SOURCE as text (XHR — fetch() is rejected on this
    // origin) and constructs one itself; see `ensureWorker` below.
    //
    // Putting the tag back would silently restore the fake worker whatever
    // `ensureWorker` does, because pdf.js checks the global first.
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
  '  var MAX_CANVAS_PX = 16000000;',   // ~16MP per page, keeps big plans off the OOM killer
  '  var MAX_CANVAS_EDGE = 4096;',
  // THE RESOLUTION FLOOR FOR LARGE-FORMAT SHEETS. PDF user units are 1/72",
  // so scale = TARGET_PPI/72 renders at this density whatever the page
  // measures. 150 is a statement of intent, not a promise: the two caps above
  // bind first on anything bigger than about 27x27 inches, so an arch-E sheet
  // lands at 4096px on the long edge — 85 ppi — and asking for more here
  // changes nothing until those move.
  //
  // ⚠️ DO NOT "JUST LOWER THIS" TO MAKE THE VIEWER FASTER. An earlier note
  // here said to, and it is a trap. Run the arithmetic on a 36x48 sheet
  // (2592 x 3456 pt) before touching the number:
  //
  //   TARGET_PPI  scale  long edge          effect
  //   150         2.083  7200 -> clamped    4096 px, 85.3 ppi
  //   120         1.667  5760 -> clamped    4096 px, 85.3 ppi   — no change
  //    96         1.333  4608 -> clamped    4096 px, 85.3 ppi   — no change
  //    85         1.181  4082                4082 px, 85.0 ppi  — barely
  //    84         1.167  4032                4032 px, 84.0 ppi  — now it moves
  //
  // MAX_CANVAS_EDGE is the binding clamp, so ANY value from ~85 upward
  // produces a byte-identical render and costs exactly the same. The first
  // value that makes a phone faster is one that has already dropped below the
  // clamp — and once below it, `viewportS` takes over on a phone at 32.5 ppi
  // and every bit of the legibility #413 bought is gone. There is no setting
  // of this constant that trades a little sharpness for a little speed; it is
  // all or nothing, which is precisely why the floor is now gated on the zoom
  // (see `sharp` below) rather than shrunk.
  '  var TARGET_PPI = 150;',
  // How far either side of the viewport a page counts as "near". Feeds both
  // the observer's rootMargin and the no-observer sweep, so the two paths
  // agree on what is near.
  //
  // ⚠️ THIS USED TO BE `var KEEP_RENDERED = 7;` AND IT NEVER BOUND ANYTHING.
  // `trim()` skipped any page still marked `visible`, and `visible` was set by
  // an IntersectionObserver whose rootMargin IS THE BAND — so the band marked
  // several sheets unfreeable at once and a "window of 7" could sit at
  // whatever size the band happened to be. Measured: the same seven sheets are
  // 27.4 MB un-zoomed and 336 MB zoomed in. 336 MB is the figure a Chromium
  // renderer gets killed at, which is what the crash-after-load reports were.
  //
  // A PAGE COUNT WAS THE WRONG UNIT REGARDLESS. What runs out is pixels. See
  // CANVAS_BUDGET_MP below, which is read off the canvas that was ACTUALLY
  // allocated, and whose protection rule is ON SCREEN rather than in-band —
  // the two halves that make it a ceiling instead of a hope.
  //
  // ── HOW FAR EITHER SIDE TO PREFETCH ──────────────────────────────────
  //
  // 1.5 spanned four viewport heights — four or five full-width sheets — and
  // was sized for a viewer that drew a cheap 1.2 MP sheet with the PPI floor
  // switched off until someone pinched. Every sheet is now drawn at the floor
  // (see `targetScaleInfo`), which is 12.58 MP on an arch-E drawing, so a band
  // of five is 63 MP of bitmap queued before the reader has touched anything —
  // work the budget below would immediately throw away.
  //
  // 0.6 is a viewport height either side, which on a device whose sheets are
  // about a viewport tall is the reader's sheet PLUS ONE EITHER SIDE. That is
  // the prefetch depth the budget can actually hold, so the queue and the
  // evictor stop fighting: what gets drawn is what gets kept.
  '  var BAND = 0.6;',
  // ── ONE RASTERISATION AT A TIME ────────────────────────────────────────
  //
  // `renderSlot` guards per slot (`if (slot.busy) return;`). NOTHING capped
  // the global in-flight count, and the IntersectionObserver's first callback
  // arrives with the ENTIRE BAND — so it called renderSlot on every page as it
  // walked the entries and every sheet's wall clock contained all the others.
  // On the operator's phone, twenty sheets of a 26-sheet plan:
  //
  //   4585 4591 4749 4912 5323 5465 5886 6304 6310 6668
  //   6935 7529 7601 7933 8214 8790 8970 9004 9281 9490
  //
  // A monotonic climb is the signature of CONTENTION, not of size — the same
  // sheet renders in 742 ms uncontended. His white screen was page 1 waiting
  // in a queue nobody bounded.
  //
  // 1 AND NOT 2. Total work is unchanged; what changes is that the sheet the
  // reader is looking at finishes in its own uncontended time instead of last,
  // behind eleven he cannot see. Two concurrent rasterisations is the same
  // contention in miniature — and with a real worker (see `ensureWorker`) the
  // resource being protected is now pdf.js's single worker thread plus the one
  // UI thread that paints, which is still one of each.
  '  var MAX_CONCURRENT_RENDERS = 1;',
  // ── THE RESIDENT BITMAP, IN MEGAPIXELS ─────────────────────────────────
  //
  // THE UNIT IS PIXELS BECAUSE PIXELS ARE WHAT RUN OUT. A canvas holds RGBA,
  // four bytes each, whatever was drawn into it, so megapixels x 4 is
  // megabytes with no assumption about scale, tier or sheet size anywhere in
  // it. `canvasPixels()` reads width and height off the bitmap that was
  // ACTUALLY allocated; a budget computed from a constant "MB per sheet" would
  // be a page count wearing a different name and wrong by an order of
  // magnitude the moment the scale moved.
  //
  // THE DERIVATION, on the operator's 31.7 MB set and this viewer's caps:
  //
  //   the floor that cannot be freed   `trim()` may not free a sheet that is
  //     2 sheets, 32 MP worst case     ON SCREEN, and page height is close
  //                                    enough to viewport height that two are
  //                                    partly visible for most of a scroll.
  //                                    At the absolute MAX_CANVAS_PX ceiling
  //                                    that is 2 x 16 MP. THE BUDGET MUST
  //                                    CLEAR THIS or trim() spins on a set it
  //                                    cannot reduce — which is precisely the
  //                                    failure KEEP_RENDERED had, except that
  //                                    one protected the whole BAND.
  //   what is worth keeping            the reader's sheet and one either side,
  //     3 x 12.58 MP = 37.7 MP         so a one-page scroll is not a re-decode.
  //                                    12.58 MP is a 36x48 sheet at the 4096
  //                                    edge cap; his measured ceiling render
  //                                    was 11.2 MP.
  //
  // 32 MP = 128 MB of RGBA. It holds the on-screen sheet and one neighbour
  // outright and most of a second, against renderer kills reported at
  // 250-350 MB and pdf.js additionally retaining the 31.7 MB file buffer and
  // its decode caches. A scroll of more than one page costs a re-render — now
  // ~700 ms, and off the UI thread — which is the deliberate trade.
  '  var CANVAS_BUDGET_MP = 32;',
  // ── SHARPNESS IS NO LONGER ON DEMAND, BECAUSE IT NO LONGER COSTS ───────
  //
  // #413 put a PPI floor on every sheet. #542 took it off first paint and
  // attached it to the pinch, on the reasoning that a phone went 1.83 MP a
  // sheet to 12.58 MP — 6.9x — with no worker to put the work on, and the
  // band rasterised four or five sheets before the operator touched anything.
  //
  // ⚠️ THE PREMISE OF THAT REASONING IS REFUTED BY MEASUREMENT. Isolated
  // medians on the operator's Pixel 10 Pro XL, three runs each, inflight 0,
  // spread under 90 ms:
  //
  //     0.5 MP   800 ms
  //     1.2 MP   742 ms
  //    11.2 MP   701 ms      <- twenty-two times the pixels, and FASTER
  //
  // MEGAPIXELS DO NOT DRIVE THE COST OF A SHEET. The per-page cost is fixed
  // and it is CONTENT DECODE — 710 FlateDecode and 147 DCTDecode operators on
  // one of his sheets — not fill. A tier that renders fewer pixels pays the
  // same ~750 ms and hands the reader a blurrier drawing, which is why the
  // low-resolution first pass this branch used to carry has been DELETED
  // rather than tuned: it cost 800 ms to save nothing and the sharp pass ran
  // afterwards anyway.
  //
  // SO THE FLOOR IS BACK ON AT FIRST PAINT, for every sheet, and
  // `targetScaleInfo` defaults `wantFloor` to true. What used to be bought
  // with a resolution tier is bought with the queue (one sheet at a time,
  // the reader's first) and the megapixel budget above instead.
  //
  // ⚠️ IF A LATER PROBE FINDS A VECTOR-HEAVY SET THAT DOES SCALE WITH PIXELS —
  // many Flate ops, few DCT — this is the constant to revisit, and the
  // evidence to bring is per-page `renderMs` against `megapixels` on that set.
  // Do not reinstate a tier without it.
  '  var ZOOM_SHARP = 1.25;',
  // WHAT `sharp` STILL MEANS: TIGHTEN THE BAND. It is no longer a resolution
  // switch — every sheet is already at the floor — so a pinch no longer blanks
  // and redraws anything. What a pinch does change is how much prefetch is
  // worth holding: a reader who has zoomed in is looking at ONE sheet, and
  // 0.25 spans a quarter of a viewport either side, so the near set is one or
  // two. With a sharp sheet at 12.58 MP that is a memory lever and it matters
  // more than it did, not less; `trim()` frees whatever falls out of the new
  // band on its own merits.
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
  // THE MIDDLE VALUE, WHICH IS THE WHOLE POINT OF TAKING THREE.
  //
  // A mean of three is dragged a third of the way by a single first-run
  // warm-up cost, and that cost is precisely what the repeat passes exist to
  // separate out — averaging it back in would undo the measurement. The median
  // of three ignores one outlier in either direction and reports what the
  // variant actually does. The raw three are emitted beside it regardless, so
  // nobody has to trust this function to see the spread.
  '  function median(a){',
  '    if (!a || !a.length) return null;',
  '    var s = a.slice().sort(function(x, y){ return x - y; });',
  '    var m = Math.floor(s.length / 2);',
  '    return (s.length % 2) ? s[m] : r1((s[m - 1] + s[m]) / 2);',
  '  }',
  '  function sum(a){ var t = 0, i; for (i = 0; i < (a ? a.length : 0); i++) t = t + a[i]; return r1(t); }',
  '  function minOf(a){ if (!a || !a.length) return null; return a.reduce(function(x, y){ return x < y ? x : y; }); }',
  '  function maxOf(a){ if (!a || !a.length) return null; return a.reduce(function(x, y){ return x > y ? x : y; }); }',
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
  '    d.MAX_CANVAS_PX = MAX_CANVAS_PX;',
  '    d.BAND = BAND;',
  '    d.CANVAS_BUDGET_MP = CANVAS_BUDGET_MP;',
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
  // Same door, TEXT instead of bytes. `fetch()` on a file:// URL is rejected
  // outright in Chromium and the probe confirmed it on the device; XHR is not,
  // and is what `allowFileAccessFromFileURLs` grants — it is already how 30 MB
  // of PDF gets off disk on this very page.
  '  function readText(url, ok, err){',
  '    var xhr = new XMLHttpRequest();',
  '    try { xhr.open("GET", url, true); } catch (e) { err("open:" + e); return; }',
  '    xhr.onload = function(){',
  '      var t = xhr.responseText;',
  '      if (t && t.length) ok(String(t));',
  '      else err("empty-response");',
  '    };',
  '    xhr.onerror = function(){ err("xhr-blocked"); };',
  '    try { xhr.send(null); } catch (e) { err("send:" + e); }',
  '  }',
  '',
  // ══ A REAL WORKER ═══════════════════════════════════════════════════════
  //
  // WHAT WAS HERE BEFORE, AND WHY IT WAS WRONG. The page loaded
  // pdf.worker.min.js as a <script>, which defines `globalThis.pdfjsWorker`,
  // which makes pdf.js skip the real-Worker attempt and install its MAIN
  // THREAD message handler instead. The comment justifying it said a real
  // Worker is "blocked from a file:// origin".
  //
  // THAT IS TRUE OF ONE CONSTRUCTION AND FALSE OF THE OTHER.
  // `new Worker("pdf.worker.min.js")` from a file:// page is blocked. A Worker
  // constructed from a `blob:` URL inherits the creating document's origin and
  // is allowed — and the operator's device settled it rather than a
  // compatibility table:
  //
  //     workerpath verdict: FAKE — parse AND rasterise on the MAIN thread
  //     fetch() of workerSrc is REJECTED; XHR works; blob workers ARE supported
  //     worker-ab on the SAME device: a REAL worker works, page 1 = 618 ms
  //
  // So: XHR the worker source as text -> Blob -> createObjectURL -> Worker ->
  // `GlobalWorkerOptions.workerPort`. `workerPort` and not `workerSrc`,
  // because workerSrc would send pdf.js back through the blocked construction.
  //
  // ⚠️ WHAT MOVES OFF THE UI THREAD AND WHAT DOES NOT. The worker does the
  // PARSE and the IMAGE DECODE — the 710 Flate and 147 DCT operators that are
  // the fixed per-page cost. It does NOT paint: pdf.js replays the operator
  // list through a real CanvasRenderingContext2D on the main thread, and
  // nothing short of running CanvasGraphics inside the worker against an
  // OffscreenCanvas would change that. pdf.js does not support it, and this
  // page does not attempt it. The residual main-thread stall is PAINT, and
  // the `uithread` probe's `longestStallMs` is the number that measures it.
  //
  // ⚠️ THE FALLBACK IS LOUD, ON PURPOSE. A silent fallback is exactly how the
  // main-thread worker survived: every reading taken afterwards gets
  // interpreted against the wrong model and nothing in the log says so. Every
  // path out of here posts `pdf-worker` on the ORDINARY channel, probe flag or
  // no probe flag.
  '  var workerMode = "unset";',
  '  var workerReason = "";',
  '  var workerSettled = false;',
  '  var workerStarted = false;',
  '  var workerWaiters = [];',
  '  var workerObj = null;',
  '  var workerBlobUrl = "";',
  // The worker source has to be long enough to BE the bundle. A Worker built
  // out of a truncated read is a Worker that never answers, and a hang with no
  // error is worse than the main-thread path it was replacing. The real
  // pdf.worker.min.js is ~1.1 MB; anything under 50 KB is not it.
  '  var MIN_WORKER_SOURCE_CHARS = 50000;',
  '',
  '  function settleWorker(mode, reason){',
  '    if (workerSettled) return;',
  '    workerMode = mode;',
  '    workerReason = reason || "";',
  '    workerSettled = true;',
  '    post({ type: "pdf-worker", mode: mode, reason: workerReason });',
  '    try { console.log("[pdfjs] worker: " + mode + (workerReason ? " (" + workerReason + ")" : "")); } catch (e) {}',
  '    probePost("worker-setup", { mode: mode, reason: workerReason });',
  '    var ws = workerWaiters;',
  '    workerWaiters = [];',
  '    for (var i = 0; i < ws.length; i++) { try { ws[i](); } catch (e) {} }',
  '  }',
  '',
  // THE OLD PATH, ON PURPOSE AND BY NAME. Injecting the <script> the page no
  // longer carries is what defines `globalThis.pdfjsWorker` and puts pdf.js
  // back on its main-thread handler — the exact behaviour that shipped for
  // months, so a device that cannot give us a Worker is no worse off than it
  // was. `workerSrc` is set either way: it is what the probe reads, and on a
  // build where the injection fails it is pdf.js's own last resort.
  '  function useMainThreadWorker(reason){',
  '    var el = null, parent = null;',
  '    function land(extra){',
  '      try { pdfjsLib.GlobalWorkerOptions.workerSrc = "' + WORKER_NAME + '"; } catch (e) {}',
  '      settleWorker("main-thread", reason + (extra || ""));',
  '    }',
  '    try { el = document.createElement("script"); } catch (e) { el = null; }',
  '    try { parent = document.head || document.body || null; } catch (e) { parent = null; }',
  '    if (!el || !parent || typeof parent.appendChild !== "function") { land("; no-script-injection"); return; }',
  '    el.onload = function(){ land(""); };',
  '    el.onerror = function(){ land("; worker-script-load-failed"); };',
  '    try { el.src = "' + WORKER_NAME + '"; parent.appendChild(el); }',
  '    catch (e) { land("; inject-threw:" + e); }',
  '  }',
  '',
  // A Worker whose script throws on load reports it here, asynchronously and
  // possibly AFTER `getDocument` has already been handed the port — at which
  // point the document never resolves and the reader sees "Loading…" for ever.
  // So this does not merely log: it tears the port down, falls back, and
  // re-opens whatever document was in flight.
  '  function workerBlewUp(reason){',
  '    if (workerMode !== "real") return;',
  // MARKED DEAD ON THE FIRST LINE, not when the fallback lands. A Worker can
  // report more than one error, and `useMainThreadWorker` settles on a later
  // turn (the injected <script> has to load) — so a second `onerror` arriving
  // in that window would pass the guard above and re-open the document twice.
  '    workerMode = "dying";',
  '    try { if (workerObj) workerObj.terminate(); } catch (e) {}',
  '    try { if (workerBlobUrl) URL.revokeObjectURL(workerBlobUrl); } catch (e) {}',
  '    workerObj = null; workerBlobUrl = "";',
  '    try { pdfjsLib.GlobalWorkerOptions.workerPort = null; } catch (e) {}',
  // Re-opened rather than resumed: the half-built document behind the dead
  // port cannot be recovered, and `workerStarted` stays true so the blob path
  // is never attempted a second time.
  '    workerSettled = false;',
  '    var reopen = fileUrl;',
  '    workerWaiters.push(function(){ if (reopen) openDocument(reopen); });',
  '    useMainThreadWorker("worker-error:" + reason);',
  '  }',
  '',
  '  function ensureWorker(done){',
  '    if (workerSettled) { if (done) done(); return; }',
  '    if (done) workerWaiters.push(done);',
  '    if (workerStarted) return;',
  '    workerStarted = true;',
  '    var canBlob = false;',
  '    try {',
  '      canBlob = (typeof Worker !== "undefined") && (typeof Blob !== "undefined")',
  '        && !!window.URL && typeof URL.createObjectURL === "function";',
  '    } catch (e) { canBlob = false; }',
  '    if (!canBlob) { useMainThreadWorker("no-Worker-or-Blob-in-this-WebView"); return; }',
  '    readText("' + WORKER_NAME + '", function(text){',
  '      if (!text || text.length < MIN_WORKER_SOURCE_CHARS) {',
  '        useMainThreadWorker("worker-source-short:" + (text ? text.length : 0));',
  '        return;',
  '      }',
  '      var w = null, u = "";',
  '      try {',
  '        u = URL.createObjectURL(new Blob([text], { type: "text/javascript" }));',
  '        w = new Worker(u);',
  '      } catch (e) {',
  '        try { if (u) URL.revokeObjectURL(u); } catch (e2) {}',
  '        useMainThreadWorker("worker-construct:" + e);',
  '        return;',
  '      }',
  '      workerObj = w; workerBlobUrl = u;',
  '      try { w.onerror = function(ev){ workerBlewUp(String((ev && (ev.message || ev.type)) || "unknown")); }; } catch (e) {}',
  '      try { pdfjsLib.GlobalWorkerOptions.workerPort = w; }',
  '      catch (e) {',
  '        try { w.terminate(); } catch (e2) {}',
  '        try { URL.revokeObjectURL(u); } catch (e2) {}',
  '        workerObj = null; workerBlobUrl = "";',
  '        useMainThreadWorker("workerPort-assign:" + e);',
  '        return;',
  '      }',
  '      settleWorker("real", "");',
  '    }, function(code){ useMainThreadWorker("worker-source-" + code); });',
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
  // THE FLOOR IS ON, ALWAYS. It was briefly attached to `sharp` — the reader
  // having pinched in — on the reasoning that 12.58 MP a sheet was too
  // expensive to pay for at first paint. The operator's isolated medians
  // refute that: 11.2 MP renders in 701 ms and 0.5 MP in 800 ms on the same
  // device and the same sheet, because the per-page cost is content decode and
  // not fill. A sheet that is cheaper in pixels is not cheaper in time, so
  // there was nothing to defer and the reader was being handed 32 ppi for
  // nothing. `wantFloor` survives as a PARAMETER so the probe's A/B can still
  // time both anchors without depending on what the reader happened to do.
  '    var floorOn = (wantFloor === undefined) ? true : !!wantFloor;',
  '    var s = floorOn ? Math.max(viewportS, ppiS) : viewportS;',
  '    var anchor = (floorOn && ppiS > viewportS) ? "ppi" : "viewport";',
  '    var w = vp1.width * s, h = vp1.height * s;',
  '    var clamp = "none";',
  '    if (w > MAX_CANVAS_EDGE) { s = s * (MAX_CANVAS_EDGE / w); w = vp1.width * s; h = vp1.height * s; clamp = "edge-w"; }',
  '    if (h > MAX_CANVAS_EDGE) { s = s * (MAX_CANVAS_EDGE / h); w = vp1.width * s; h = vp1.height * s; clamp = (clamp === "none" ? "edge-h" : clamp + "+edge-h"); }',
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
  '    var s = Math.min(MAX_CANVAS_EDGE / vp1.width, MAX_CANVAS_EDGE / vp1.height);',
  '    var w = vp1.width * s, h = vp1.height * s;',
  '    var clamp = (w >= h) ? "edge-w" : "edge-h";',
  '    if (w * h > MAX_CANVAS_PX) { s = s * Math.sqrt(MAX_CANVAS_PX / (w * h)); w = vp1.width * s; h = vp1.height * s; clamp = clamp + "+maxpx"; }',
  '    return { s: s, w: w, h: h, clamp: clamp };',
  '  }',
  '',
  // Give a page back. Detaching the <canvas> is NOT enough: the element is
  // still reachable from the slot, and even an unreachable one keeps its
  // backing store until a GC that may never come under memory pressure.
  // Setting width and height to 0 drops the bitmap there and then, which is
  // the only step that actually returns the megabytes.
  '  function releaseSlot(slot){',
  // A slot being given back must not still be waiting in line for a render.
  // Same reason the generation stamp exists below: the work is queued for a
  // canvas that is about to stop existing.
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
  '  }',
  '',
  '  function touch(slot){',
  '    var i = rendered.indexOf(slot);',
  '    if (i >= 0) rendered.splice(i, 1);',
  '    rendered.push(slot);',
  '  }',
  '',
  // ── STOPPING WORK vs DISCARDING A RESULT: TWO MECHANISMS, ONE JOB EACH ──
  //
  // These are NOT interchangeable and neither covers the other's case.
  //
  //   RenderTask.cancel()  STOPS THE WORK. pdf.js is the only thing that can
  //                        stop rasterising, and this is the only way to ask
  //                        it. With MAX_CONCURRENT_RENDERS = 1 the in-flight
  //                        render holds the only slot there is, so a sheet the
  //                        reader has left is not merely wasted — it is the
  //                        sheet he IS looking at, waiting. Its promise
  //                        rejects with RenderingCancelledException, which the
  //                        catch below already swallows silently.
  //
  //   slot.gen             STOPS THE RESULT BEING USED. cancel() is a request,
  //                        not a guarantee: a render can complete in the window
  //                        between the call and the promise settling, into a
  //                        canvas `releaseSlot` has already thrown away.
  //
  // `releaseSlot` does BOTH, because it is discarding the slot's identity.
  // Leaving the band does cancel ONLY: the slot keeps its identity and may be
  // re-rendered later at the same generation, and if cancel loses the race the
  // late canvas is harmless and slightly useful — the page is out of band, so
  // `trim()` can free it on merit.
  '  function cancelInFlight(slot){',
  '    if (!slot.task) return;',
  '    try { slot.task.cancel(); } catch (e) {}',
  '  }',
  '',
  // WHAT A SLOT IS ACTUALLY COSTING, read off the bitmap that was allocated
  // rather than recomputed from a scale. A canvas holds four bytes a pixel
  // whatever was drawn into it, so this prices any sheet at any scale with no
  // knowledge of the render path whatsoever.
  '  function canvasPixels(slot){',
  '    var c = slot.canvas;',
  '    if (!c) return 0;',
  '    return (c.width || 0) * (c.height || 0);',
  '  }',
  '',
  // ── WHAT MAY NOT BE FREED IS WHAT IS ON SCREEN ─────────────────────────
  //
  // ⚠️ THIS IS THE HALF OF THE OLD EVICTOR THAT WAS WRONG. `trim()` skipped
  // any page marked `visible`, and `visible` was set by an observer whose
  // rootMargin is the BAND — so a band of five marked five sheets unfreeable
  // and no budget, in pages or in pixels, could bind. The rule that actually
  // has to hold is narrower and is the one a reader would state: DO NOT FREE
  // A SHEET HE CAN SEE. Everything else is fair game, and freeing it is
  // correct — the observer's `near` set keeps it queued, so if he scrolls back
  // it is redrawn rather than left blank.
  '  function onScreen(slot){',
  '    return visibleHeight(slot) > 0;',
  '  }',
  '',
  // Hold the resident bitmap under the megapixel budget, FARTHEST FROM THE
  // READER FIRST. Least-recently-used answers the wrong question here: a
  // reader who scrolls back to a sheet he drew three sheets ago wants that
  // one kept and the one he has just left freed, and recency says the
  // opposite. Distance in pages from the sheet he is looking at is the key,
  // which is the same key `pumpQueue` picks by — one notion of "near the
  // reader", used in both directions.
  '  function trim(){',
  '    var budget = CANVAS_BUDGET_MP * 1000000;',
  '    var total = 0, i;',
  '    for (i = 0; i < rendered.length; i++) total = total + canvasPixels(rendered[i]);',
  '    while (total > budget) {',
  '      var wi = -1, wd = -1, d;',
  '      for (i = 0; i < rendered.length; i++) {',
  '        if (onScreen(rendered[i])) continue;',
  '        d = focus ? Math.abs(rendered[i].n - focus.n) : 0;',
  '        if (d > wd) { wd = d; wi = i; }',
  '      }',
  // Everything left is on screen. The budget is sized to clear that floor
  // (see CANVAS_BUDGET_MP), so this is the "two enormous sheets are both
  // visible" case and the honest answer is to stop rather than blank one.
  '      if (wi < 0) break;',
  '      total = total - canvasPixels(rendered[wi]);',
  '      releaseSlot(rendered.splice(wi, 1)[0]);',
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
  // sorted once would be a FIFO with extra steps.
  //
  // O(n) a pick, on a queue that is the band — a handful of entries. A heap
  // would have to be re-keyed on every scroll anyway, because the key is the
  // reader's position and not a property of the page.
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
  // How much of this sheet the reader can actually see. Feeds both `onScreen`
  // (trim's one protection rule) and `focus` (which sheet the eviction order
  // is measured from), so the two cannot drift apart.
  '  function visibleHeight(slot){',
  '    var h = window.innerHeight || document.documentElement.clientHeight || 800;',
  '    var r = slot.el.getBoundingClientRect();',
  '    var top = r.top > 0 ? r.top : 0;',
  '    var bot = r.bottom < h ? r.bottom : h;',
  '    return bot > top ? bot - top : 0;',
  '  }',
  '',
  // THE SHEET THE READER IS ON. "On screen" is not specific enough: page
  // height is close enough to viewport height that two sheets are partly
  // visible through most of a scroll. The focus is the one showing the most of
  // itself. It is recomputed after every observer callback and every sweep,
  // because the answer is a property of where the reader is and not of any
  // page — and it KEEPS ITS LAST VALUE when nothing is on screen, so a
  // momentary gap does not make every resident sheet equidistant.
  '  var focus = null;',
  '  function refreshFocus(){',
  '    var best = null, bestH = 0, i, vh;',
  '    for (i = 0; i < slots.length; i++) {',
  '      if (!slots[i].near) continue;',
  '      vh = visibleHeight(slots[i]);',
  '      if (vh > bestH) { bestH = vh; best = slots[i]; }',
  '    }',
  '    if (best) focus = best;',
  '  }',
  '',
  '  function enqueue(slot){',
  '    if (slot.done) { touch(slot); return; }',
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
  '  function pumpQueue(){',
  // The probe suite suspends the render path while it measures; the queue IS
  // the deferred list, so nothing has to be put aside anywhere else and
  // `abResume` only has to pump again. Inert with the flag off.
  '    if (PROBE && abSuspend) return;',
  '    while (inFlight < MAX_CONCURRENT_RENDERS && queue.length) {',
  '      var bi = 0, bd = nearness(queue[0]), i, d;',
  '      for (i = 1; i < queue.length; i++) {',
  '        d = nearness(queue[i]);',
  '        if (d < bd) { bd = d; bi = i; }',
  '      }',
  '      var slot = queue.splice(bi, 1)[0];',
  '      if (slot.busy || slot.done) continue;',
  // RE-CHECKED AT THE MOMENT OF STARTING, not at the moment of queueing. The
  // reader may have moved a long way while this sat in line, and the observer
  // does not always get to report it first.
  '      if (!slot.near && !inBand(slot)) continue;',
  '      renderSlot(slot);',
  '    }',
  '  }',
  '',
  // ── THE MEASUREMENT HAS TO BE ABLE TO STOP THE THING IT IS MEASURING ───
  //
  // WHY EVERY `render-ab` ROW TAKEN SO FAR IS WORTHLESS. `probeSuite` starts
  // 2000 ms after `pdf-ready`, and on the operator's phone the band's own
  // sheets were still rasterising at that point — pages 6, 7 and 8 each
  // reported renderMs 5109, which is three pages that started together and
  // finished together, i.e. a number that is queue wait and not work. The
  // suite's three variants ran INTERLEAVED with that, so each one's wall clock
  // contained a share of the same contention, and the three were then compared
  // to each other as though the only difference between them was pixels.
  //
  // SO THE SUITE SUSPENDS THE NORMAL PATH AND WAITS FOR IT TO GO QUIET, and
  // then says in every row that it did. Three probe-only pieces of state:
  //
  //   inFlight     how many REAL slot rasterisations are running right now.
  //                NOT a probe counter any more — the render cap needs the
  //                same number, and two counters for one fact is how they
  //                drift apart. Declared with the queue above.
  //   abSuspend    when true, `pumpQueue` starts nothing. The band keeps being
  //                observed, `trim()` keeps running and pages keep being
  //                QUEUED; only the rasterisation is deferred.
  //   the queue    is itself the deferred list, so there is no second array to
  //                replay from and no way for the two to disagree about what
  //                was put aside. `abResume` pumps, and the viewer ends up in
  //                the state it would have been in anyway, a few seconds later.
  //
  // INERT WITH THE FLAG OFF. `abSuspend` is only ever read behind `PROBE`, and
  // the executing test asserts it by driving a six-sheet band with the probe
  // off and checking the cap still holds and every sheet is still drawn.
  '  var abSuspend = false;',
  // A hard stop, so a device where something never settles still reports
  // rather than hanging the suite forever. `drained:false` in the row is then
  // the honest answer and the reader can discount the numbers themselves.
  '  var AB_DRAIN_MAX_MS = 60000;',
  '',
  // THE ONLY CALLER OF THIS IS `pumpQueue`. Everything else enqueues, which is
  // what keeps the cap honest: there is no second door into a rasterisation,
  // and `pdfjsViewerMemory` asserts that from the call graph rather than by
  // inspection.
  '  function renderSlot(slot){',
  '    if (slot.done) { touch(slot); return; }',
  '    if (slot.busy) return;',
  '    slot.busy = true;',
  '    inFlight = inFlight + 1;',
  // EXACTLY ONCE ON EVERY PATH OUT — resolved, cancelled, generation-stale or
  // thrown. A leaked count is a viewer that stops rendering for good, which is
  // a worse failure than the one being fixed, and a drain that never completes
  // on the one device that most needs to report.
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
  '      var info = targetScaleInfo(vp1);',
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
  '        slot.done = true;',
  '        touch(slot);',
  '        trim();',
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
  // start one. Bounded by the megapixel budget and the render cap exactly like
  // the observer path — the two must not disagree about either.
  //
  // THE WHOLE BAND GOES IN BEFORE ANYTHING STARTS, which is the point: the
  // nearest sheet can only be chosen once the candidates are all known.
  '  function sweep(){',
  '    for (var i = 0; i < slots.length; i++) {',
  '      slots[i].near = inBand(slots[i]);',
  '      if (slots[i].near) { enqueue(slots[i]); }',
  '      else { dequeue(slots[i]); cancelInFlight(slots[i]); }',
  '    }',
  // BEFORE trim(), because the focus is the sheet eviction distance is
  // measured from, and BEFORE pumpQueue(), because it is also what the next
  // pick is measured against.
  '    refreshFocus();',
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
  // rasterisations on one thread. This one records the whole batch FIRST and
  // only then asks the queue to start ONE, which is what makes "nearest first"
  // a question that can be answered at all.
  '    io = new IntersectionObserver(function(entries){',
  '      for (var i = 0; i < entries.length; i++) {',
  '        var slot = entries[i].target.__slot;',
  '        if (!slot) continue;',
  '        if (entries[i].isIntersecting) {',
  '          slot.near = true;',
  '          enqueue(slot);',
  '        } else {',
  '          slot.near = false;',
  '          dequeue(slot);',
  // AND STOP THE ONE ALREADY RUNNING. `dequeue` only takes a sheet out of the
  // LINE; with one thread, an in-flight render for a sheet the reader has left
  // is the sheet he is looking at, waiting behind it.
  '          cancelInFlight(slot);',
  '        }',
  '      }',
  '      refreshFocus();',
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
  // ── WHAT THE PINCH STILL DOES, AND WHAT IT NO LONGER HAS TO ────────────
  //
  // IT USED TO BLANK EVERY SHEET. `sharp` was the RESOLUTION switch: first
  // paint was viewport-anchored at 32.5 ppi and the pinch turned the PPI floor
  // on, so everything already drawn was at the wrong scale and had to go.
  //
  // THAT IS NO LONGER WHAT IT MEANS. Every sheet is drawn at the floor from
  // first paint (the measurement that killed the tier is in the comment above
  // ZOOM_SHARP), so releasing every canvas here would blank the page the
  // reader has just pinched into and redraw it AT THE SAME SCALE — a flicker
  // bought with a second of thread, for nothing.
  //
  // SO `sharp` NOW MEANS ONE THING ONLY: TIGHTEN THE BAND. A reader who has
  // pinched in is looking at one sheet, and BAND_SHARP is what stops the
  // prefetch either side of it being drawn at all. `trim()` frees what falls
  // out of the new band on its own merits.
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
  '      slots[i].near = false;',
  '      releaseSlot(slots[i]);',
  '    }',
  '    rendered.length = 0;',
  // releaseSlot() takes each one out of the line above; this is the belt to
  // that pair of braces, because `resetDocument` empties `slots` straight
  // after and a slot still queued would be a reference to a page that no
  // longer has a document behind it.
  '    queue.length = 0;',
  '    focus = null;',
  // The only point at which the file bytes can go — see the note at
  // getDocument below.
  '    if (doc) { try { doc.destroy(); } catch (e) {} doc = null; }',
  '  }',
  '  window.addEventListener("pagehide", teardown);',
  '',
  // ── WHAT `layout()` COSTS, PAGE BY PAGE ────────────────────────────────
  //
  // THE SUSPICION THIS EXISTS TO SETTLE. This function chains
  // `doc.getPage(n)` for EVERY page before a single pixel is drawn — on a
  // 26-sheet plan that is 26 sequential page parses on the main thread (there
  // is no worker; a file:// origin forces pdf.js's rasteriser and parser onto
  // the UI thread), purely to read `getViewport({scale:1})` so the placeholder
  // <div> can be given a height. The comment below admits the MEMORY
  // motivation for the `cleanup()` and says nothing at all about the time.
  //
  // `layoutMs` ALONE CANNOT SETTLE IT, which is why the split is here. A
  // layout that is slow because ONE page is pathological and a layout that is
  // slow because all 26 cost the same amount are different defects with
  // different fixes, and the total reads identically for both. `getPage` is
  // timed apart from the sizing-and-DOM work for the same reason: if the cost
  // is in `getPage` the fix is to stop calling it 26 times, and if it is in
  // the DOM the fix is somewhere else entirely.
  //
  // PROBE-ONLY, AND THE ARRAYS ARE NOT ALLOCATED OTHERWISE. With the flag off
  // this is the same function it has always been plus one branch per page.
  '  var layoutGetPageMs = null;',
  '  var layoutSizeMs = null;',
  '  function layout(){',
  '    baseWidth = Math.max(200, document.documentElement.clientWidth || window.innerWidth || 320);',
  '    var chain = Promise.resolve();',
  '    var n;',
  '    var lgGet = PROBE ? [] : null;',
  '    var lgSize = PROBE ? [] : null;',
  '    for (n = 1; n <= doc.numPages; n++) {',
  '      (function(pageNo){',
  '        chain = chain.then(function(){',
  '          var lt0 = PROBE ? pnow() : 0;',
  '          return doc.getPage(pageNo).then(function(page){',
  '            var lt1 = PROBE ? pnow() : 0;',
  '            var vp1 = page.getViewport({ scale: 1 });',
  '            var el = document.createElement("div");',
  '            el.className = "pg";',
  '            el.style.width = baseWidth + "px";',
  '            el.style.height = Math.round(baseWidth * (vp1.height / vp1.width)) + "px";',
  '            var slot = { n: pageNo, el: el, done: false, busy: false,',
  '                          near: false, canvas: null, page: null, task: null, gen: 0 };',
  '            el.__slot = slot;',
  '            slots.push(slot);',
  '            pagesEl.appendChild(el);',
  // Sizing the placeholder is all this page object was wanted for. Without the
  // cleanup, laying out a 200-sheet set leaves 200 parsed pages in pdf.js.
  '            try { page.cleanup(); } catch (e) {}',
  // Taken AFTER cleanup() on purpose: cleanup is part of what laying a page
  // out costs, and a split that omitted it would under-report the half of this
  // function that is not `getPage`.
  '            if (PROBE) { lgGet.push(r1(lt1 - lt0)); lgSize.push(r1(pnow() - lt1)); }',
  '          });',
  '        });',
  '      })(n);',
  '    }',
  '    return chain.then(function(){ layoutGetPageMs = lgGet; layoutSizeMs = lgSize; });',
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
  // variant name -> { runs: [ms, ms, ms], meta: the last row }. Filled by
  // `probeRenderAt` and summarised once the three passes are done.
  '  var abRuns = {};',
  '  function probeRenderAt(pageNo, scale, label, extra, next){',
  '    if (!PROBE) { if (next) next(); return; }',
  '    doc.getPage(pageNo).then(function(page){',
  '      var vp1 = page.getViewport({ scale: 1 });',
  '      var vp = page.getViewport({ scale: scale });',
  '      var c = document.createElement("canvas");',
  '      var wpx = Math.max(1, Math.floor(vp.width)), hpx = Math.max(1, Math.floor(vp.height));',
  '      var a0 = pnow(); c.width = wpx; c.height = hpx; var ctx = c.getContext("2d"); var a1 = pnow();',
  '      if (!ctx) { try { c.width = 0; c.height = 0; } catch (e) {} probePost("render-ab", { label: label, page: pageNo, error: "no-2d-context", canvasW: wpx, canvasH: hpx }); if (next) next(); return; }',
  // ── THE ISOLATION CLAIM RIDES IN THE ROW ───────────────────────────────
  //
  // Read at the instant this variant STARTS, not at the end, because the
  // question is what else was running while it was timed.
  //
  // WHY IT IS A FIELD AND NOT A COMMENT. Whoever reads these numbers next has
  // a phone screenshot of a log, not this file. "The suite drains first" is a
  // promise they cannot check; `inflight: 0, suspended: true` on the row is a
  // fact they can. And if a later change breaks the drain, the rows say so
  // themselves instead of quietly going back to measuring contention.
  //
  // ⚠️ `pending` IS NOT PART OF THE CLAIM AND MUST NOT BE READ AS IF IT WERE.
  // Sheets legitimately sit in the queue while the suite runs — the band is
  // still being observed and pages are still being enqueued. They are not
  // contention because `pumpQueue` starts nothing while `abSuspend` is set,
  // and `suspended` is the field that says that. `pending` is reported beside
  // it so a reader can see there was something being held back, which is what
  // makes the suspension meaningful rather than vacuous.
  '      var qIn = inFlight, qPend = queue.length, qSusp = !!abSuspend;',
  '      var r0 = pnow();',
  '      var t = page.render({ canvasContext: ctx, viewport: vp });',
  '      t.promise.then(function(){',
  '        var r1ms = pnow();',
  '        var out = { label: label, page: pageNo,',
  '          scale: Math.round(scale * 1000) / 1000,',
  '          canvasW: wpx, canvasH: hpx,',
  '          megapixels: Math.round((wpx * hpx) / 1e5) / 10,',
  '          ppi: r1(wpx / (vp1.width / 72)),',
  '          inflight: qIn, pending: qPend, suspended: qSusp,',
  '          canvasAllocMs: r1(a1 - a0), renderMs: r1(r1ms - r0) };',
  '        if (extra) { for (var k in extra) { if (Object.prototype.hasOwnProperty.call(extra, k)) out[k] = extra[k]; } }',
  '        if (extra && extra.variant) {',
  '          if (!abRuns[extra.variant]) abRuns[extra.variant] = { runs: [], meta: out };',
  '          abRuns[extra.variant].runs.push(out.renderMs);',
  '        }',
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
  //
  // ── THE THREE SCALES RUN TWICE, AND THE SECOND PASS IS THE MEASUREMENT ──
  //
  // WHAT THE FIRST ROUND FOUND, on a 26-page plan on the operator's phone:
  //
  //     cur     over 1.5    1.2 MP  ->  2252 ms    (run FIRST)
  //     noOver  over 1.0    0.5 MP  ->   488 ms
  //     ceil    headroom   11.2 MP  ->   727 ms    (9x the pixels of `cur`,
  //                                                 a third of the time)
  //
  // PIXELS CANNOT EXPLAIN THAT. These three run uncontended and in this order,
  // so the ONLY thing distinguishing `cur` is that it was first. The reading
  // that fits is that the first rasterisation of a page pays a one-off cost —
  // decoding its 710 Flate and 147 DCT image operators — and the renders after
  // it reuse the result, which would make the shipping viewer's monotonic
  // 4585 -> 9490 ms climb across twelve concurrent pages a CONTENTION story
  // and not a pixel story.
  //
  // That reading is about to have two fixes built on it, so it is measured
  // rather than assumed. A second identical pass separates the two candidates
  // with no arithmetic at all: if pass 2 is uniformly fast INCLUDING the
  // 11.2 MP case, the cost was one-off and reusable; if `cur` is slow again in
  // pass 2, first-ness is not what made it slow and the model is wrong.
  //
  // IT MUST BE THE SAME SESSION AND THE SAME PAGE. A reload re-parses the
  // document and puts back everything the first pass warmed, which is why
  // "run the probe twice" would answer nothing and this is one run of six.
  //
  // WHAT IT ALSO SETTLES, FOR FREE, AND THE READER SHOULD KNOW IT.
  // `probeRenderAt` calls `page.cleanup()` after every render — that is
  // pre-existing and deliberately left alone — and `releaseSlot()` on the real
  // path calls exactly the same thing when it evicts a canvas. So pass 2 is
  // not measuring a page held warm in memory; it is measuring whatever
  // survives the same cleanup an eviction performs. A fast pass 2 therefore
  // says the warm-up is NOT in pdf.js's per-page cache, and any claim that
  // eviction costs a full re-decode has to account for that.
  //
  // COST, STATED. The suite does three extra throwaway renders. It runs only
  // under `probe=1`, only after `pdf-ready`, and each canvas is still zeroed
  // the instant it is timed, so the peak footprint is unchanged.
  // ── DRAIN FIRST, AND SAY SO ────────────────────────────────────────────
  //
  // Suspends the normal render path, then waits for whatever is already in
  // flight to finish. It cannot cancel them — a half-drawn sheet is a blank
  // sheet in front of the reader, and the suite is a measurement, not a reason
  // to take the drawing away — so it waits, and reports how long it waited.
  //
  // THAT WAIT IS ITSELF A MEASUREMENT. It starts 2000 ms after `pdf-ready`, so
  // `waitedMs + 2000` is how long the band's own rasterisations actually take
  // from the open — the number behind the operator's 6.3 s to first visible
  // page, measured rather than stopwatched.
  '  var abDrainStartInflight = 0;',
  '  function abDrain(next, waited){',
  // Recorded on the FIRST call only. Without it the row would say how many
  // were left at the end (always 0) and never how many there were to drain —
  // and a drain of nothing looks identical to a drain that worked.
  '    if (waited === undefined) abDrainStartInflight = inFlight;',
  '    abSuspend = true;',
  '    var w = waited || 0;',
  '    if (inFlight <= 0 || w >= AB_DRAIN_MAX_MS) { next(w, inFlight); return; }',
  '    setTimeout(function(){ abDrain(next, w + 50); }, 50);',
  '  }',
  '',
  // HANDED BACK ON EVERY PATH OUT, including the failure ones. A suspension
  // that is never lifted is a viewer that draws no more pages for the rest of
  // the session — a far worse defect than the measurement error being fixed,
  // and one that would only ever be seen by the single user the flag is on for.
  '  function abResume(){',
  '    if (!PROBE) return;',
  '    abSuspend = false;',
  '    var pending = queue.length;',
  '    probePost("resume", { suspended: false, replayed: pending });',
  // NOTHING TO REPLAY FROM, because nothing was ever taken out. The suspension
  // stopped `pumpQueue` starting work; the queue kept filling exactly as it
  // would have. So the resume is one call and there is no second list that can
  // disagree with the first about what was deferred.
  '    pumpQueue();',
  '  }',
  '',
  // ── THE MEDIAN ROWS ────────────────────────────────────────────────────
  //
  // One per variant, carrying the three raw values IN PASS ORDER beside the
  // middle one. Pass order is not decoration: sorted raws would throw away
  // which run was the slow one, and "was the FIRST render the expensive one"
  // is the entire question the repeat passes were added to answer.
  '  function abSummarise(order){',
  '    for (var i = 0; i < order.length; i++) {',
  '      var v = order[i], rec = abRuns[v];',
  '      if (!rec || !rec.runs.length) { probePost("render-ab-median", { variant: v, error: "no-runs" }); continue; }',
  '      probePost("render-ab-median", {',
  '        variant: v,',
  '        runs: rec.runs.slice(),',
  '        medianMs: median(rec.runs),',
  '        minMs: minOf(rec.runs), maxMs: maxOf(rec.runs),',
  '        scale: rec.meta.scale, megapixels: rec.meta.megapixels, ppi: rec.meta.ppi,',
  '        canvasW: rec.meta.canvasW, canvasH: rec.meta.canvasH, clamp: rec.meta.clamp,',
  '        inflight: rec.meta.inflight, pending: rec.meta.pending,',
  '        suspended: rec.meta.suspended',
  '      });',
  '    }',
  '  }',
  '',
  '  function probeSuite(){',
  '    if (!PROBE) return;',
  '    abDrain(function(waitedMs, stillInflight){',
  '      probePost("drain", { waitedMs: waitedMs, inflightAtStart: abDrainStartInflight,',
  '        inflightNow: stillInflight, drained: stillInflight <= 0,',
  '        deferred: queue.length, capMs: AB_DRAIN_MAX_MS });',
  '      probeSuiteIsolated();',
  '    });',
  '  }',
  '',
  '  function probeSuiteIsolated(){',
  '    doc.getPage(1).then(function(page){',
  '      var vp1 = page.getViewport({ scale: 1 });',
  // ── THE THREE VARIANTS HAVE TO SPAN REAL PIXEL COUNTS ─────────────────
  //
  // THEY STOPPED DOING SO AND IT WOULD HAVE BEEN SILENT. `cur` and `noOver`
  // were `targetScaleInfo(vp1, 1.5)` and `(vp1, 1.0)` — a comparison of the
  // viewport oversample. With the PPI floor unconditional again, the floor
  // term wins on any large sheet and the edge clamp binds both, so on a 36x48
  // drawing all three variants land on THE SAME SCALE. Three identical renders
  // reported as an A/B is worse than no A/B: it looks like an answer.
  //
  // So the low variant asks for the VIEWPORT ANCHOR EXPLICITLY — the third
  // argument `targetScaleInfo` kept for exactly this. On the operator's phone
  // that is ~1.2 MP against the shipping 12.58 MP and the ~16 MP ceiling,
  // which is a real spread across an order of magnitude.
  //
  // ⚠️ THIS IS THE MEASUREMENT THAT SETTLES THE NEXT QUESTION. His set is
  // image-heavy — 147 DCTDecode operators a sheet — and on it the cost is
  // fixed: 0.5 MP took 800 ms and 11.2 MP took 701 ms. A VECTOR-heavy set
  // (many Flate, few DCT) might genuinely scale with pixels, and if it does,
  // a cheaper first pass becomes worth having again. `imgfilters` already
  // reports the operator census; these three rows are the renderMs-against-
  // megapixels half of the same question, and they only mean something while
  // the three scales differ.
  '      var cur = targetScaleInfo(vp1, 1.5);',
  '      var noOver = targetScaleInfo(vp1, 1.0, false);',
  '      var ceil = ceilingScaleInfo(vp1);',
  '      try { page.cleanup(); } catch (e) {}',
  // ONE DEFINITION, THREE PASSES. Written once so a later pass cannot drift
  // from the first — a pass that differed in scale or order would not be a
  // repeat and the comparison would be worthless.
  //
  // The pass number goes in the LABEL as well as in its own field:
  // PDFViewer.native.jsx logs `label` verbatim into the report the operator
  // shares, and two identically-labelled rows would be unreadable in exactly
  // the artefact this was built to produce.
  '      var V_CUR = "ppi-floor/over1.5 (SHIPPING)";',
  '      var V_NOOVER = "viewport-anchor/no-floor (CHEAP)";',
  '      var V_CEIL = "cap-ceiling (HEADROOM)";',
  '      function threeScales(pass, after){',
  '        var tag = "pass" + pass + " ";',
  '        probeRenderAt(1, cur.s, tag + "anchor:" + cur.anchor + " over:1.5 (SHIPPING)", { pass: pass, clamp: cur.clamp, variant: V_CUR }, function(){',
  '          probeRenderAt(1, noOver.s, tag + "anchor:viewport floor:off (CHEAP)", { pass: pass, clamp: noOver.clamp, variant: V_NOOVER }, function(){',
  '            probeRenderAt(1, ceil.s, tag + "anchor:cap-ceiling (HEADROOM)", { pass: pass, clamp: ceil.clamp, variant: V_CEIL }, after);',
  '          });',
  '        });',
  '      }',
  // ── THREE PASSES, AND WHY NOT TWO ──────────────────────────────────────
  //
  // Two readings of the same variant have no middle. If they disagree there is
  // nothing to prefer between them, and a mean of two is dragged the whole way
  // by one outlier — which is fatal here, because the outlier is the thing
  // under investigation: the first rasterisation of a page pays a one-off
  // decode cost (857 image operators on these sheets) that the ones after it
  // reuse. Three is the smallest count that has a median, and the median is
  // the one statistic that first-run cost cannot move.
  //
  // COST, STATED. Nine throwaway renders instead of six, each still zeroed the
  // instant it is timed, all of them after `pdf-ready` AND after the drain —
  // so the peak footprint is one extra canvas, exactly as before, and none of
  // it touches the open being measured.
  '      threeScales(1, function(){',
  '        threeScales(2, function(){',
  '        threeScales(3, function(){',
  '          abSummarise([V_CUR, V_NOOVER, V_CEIL]);',
  '          probeNativeRaster(1, function(nat){',
  // FILTERS BEFORE THE WORKER A/B. The scan is a read plus a linear pass and
  // frees its buffer immediately; the worker A/B holds a whole second parsed
  // document. Running the cheap one first means a device that dies on the
  // expensive one has still reported the compression, which is the measurement
  // the engine decision turns on.
  // THE SUSPENSION IS LIFTED WITH THE LAST MEASUREMENT AND NOT BEFORE. Every
  // step from here on is still a render or a second parsed document, and the
  // band starting up underneath any of them would put the contention straight
  // back into the numbers that are left.
  '            function thenWorker(){ probeImageFilters(function(){ probeWorkerAB(function(){ abResume(); probePost("suite", { done: true }); }); }); }',
  '            if (!nat) { thenWorker(); return; }',
  // Anchored to the SCAN's own pixels, then held to the same caps — the
  // "render it at what the plan actually is" case, measured rather than
  // argued.
  '            var sNat = nat.w / vp1.width;',
  '            var wN = vp1.width * sNat, hN = vp1.height * sNat;',
  '            if (wN > MAX_CANVAS_EDGE) { sNat = sNat * (MAX_CANVAS_EDGE / wN); wN = vp1.width * sNat; hN = vp1.height * sNat; }',
  '            if (hN > MAX_CANVAS_EDGE) { sNat = sNat * (MAX_CANVAS_EDGE / hN); wN = vp1.width * sNat; hN = vp1.height * sNat; }',
  '            if (wN * hN > MAX_CANVAS_PX) sNat = sNat * Math.sqrt(MAX_CANVAS_PX / (wN * hN));',
  '            probeRenderAt(1, sNat, "anchor:native-raster (CLAMPED)", { nativeW: nat.w, nativeH: nat.h }, thenWorker);',
  '          });',
  '        });',
  '        });',
  '      });',
  // AND LIFTED HERE TOO. A suite that fell over halfway must not leave the
  // render path switched off — the reader would be looking at a viewer that
  // never draws another sheet, with nothing on screen to say why.
  '    })["catch"](function(e){ abResume(); probePost("suite", { error: String(e) }); });',
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
  '  capabilityRead(function(){});',
  // STARTED AT BOOT, NOT AT FIRST OPEN. Reading 1.1 MB off file:// storage and
  // constructing a Worker from it is work that does not depend on the
  // document, and the WebView is created well before the host posts one — so
  // paying it here takes it off the open's critical path entirely.
  '  ensureWorker(function(){});',
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
  // THE NEXT DOCUMENT MUST NOT INHERIT THE LAST ONE'S SUSPENSION. The page
  // outlives the document, so a reader who opens a second plan while the
  // probe suite is mid-flight would otherwise get a viewer with its render
  // path switched off and nothing on screen to explain it. The deferred slots
  // belong to a document that no longer exists, so they go rather than
  // replay.
  '    if (PROBE) { abSuspend = false; abRuns = {}; }',
  // THE NEXT DOCUMENT GETS THE FAST TIER AGAIN — unless the WebView is STILL
  // pinched in. Plain `sharp = false` was wrong: native zoom is a property of
  // the WebView, not of the document, so a reader who zoomed into sheet A and
  // then opened sheet B would get the 32-ppi render with no `resize` event
  // coming to correct it, because nothing about the zoom had changed. Asking
  // the viewport is the only reading that is true for both cases, and it
  // keeps the fail-toward-legible answer when the zoom cannot be read at all.
  '    sharp = zoomIsSharp();',
  '    try { window.scrollTo(0, 0); } catch (e) {}',
  '  }',
  '',
  '  function openDocument(url){',
  '    if (!url) { fail("no-file", "no document url"); return; }',
  '    resetDocument();',
  '    fileUrl = url;',
  '    if (msgEl) { msgEl.style.display = ""; msgEl.textContent = "Loading document\\u2026"; }',
  '    hbStart();',
  // THE WORKER HAS TO BE DECIDED BEFORE `getDocument`, because that is the
  // call that binds it. Memoised: the setup runs once for the life of the
  // WebView and every later open goes straight through. It is also kicked off
  // at boot below, so by the time the host posts a document the answer is
  // usually already in.
  '    ensureWorker(function(){ loadCurrent(); });',
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
  // ── WHICH WORKER IS ACTUALLY LIVE, SAID BY THE RUNNING CODE ────────────
  //
  // EVERY PERFORMANCE CONCLUSION IN THIS FILE RESTS ON A COMMENT. The note
  // above `<script src="pdf.worker.min.js">` says loading the worker bundle
  // first defines `globalThis.pdfjsWorker`, which makes pdf.js skip the
  // real-Worker attempt (blocked from a file:// origin) and use the
  // main-thread handler instead. That single fact is why "there is no worker
  // to put it on" appears in four separate comments here and why the render
  // cap in #544 is sized to one thread — and NOTHING HAS EVER CHECKED IT.
  //
  // A pdf.js upgrade that stopped honouring the global, or a staging order
  // that wrote the two <script> tags the other way round, would flip the
  // answer silently. Every reading taken afterwards would then be interpreted
  // against the wrong model, and the readings themselves would look fine.
  //
  // READ BEFORE `getDocument`, WHICH IS THE ONLY MOMENT IT MEANS ANYTHING.
  // Afterwards pdf.js may have populated things itself and the global no
  // longer distinguishes "was already there" from "was created on demand".
  //
  // ⚠️ `task._worker._webWorker` IS THE WRONG FIELD NOW, AND READING IT WOULD
  // SCORE THE ACCEPTANCE CRITERION BACKWARDS. pdf.js takes two different
  // branches: `_initialize()` when it has to construct a Worker itself, which
  // assigns `_webWorker`, and `_initializeFromPort()` when it is HANDED one —
  // which is the branch this page now takes, and which never assigns it. A
  // verdict read off that field reports "FAKE" on a document being parsed
  // entirely off the UI thread.
  //
  // SO THE VERDICT COMES FROM THE PAGE'S OWN SETUP, which is the only thing
  // that actually knows: `workerMode` is set by `settleWorker` on every path,
  // including every fallback, and it is the same value posted on the ordinary
  // `pdf-worker` channel. The pdf.js internals ride along as CORROBORATION —
  // `workerPortType` is "object" exactly when the port was accepted, and
  // `workerMessageHandlerPresent` is true exactly when the main-thread handler
  // is installed — so a reader can see the two agree rather than trust one.
  '  function probeWorkerPath(task, hadGlobal){',
  '    if (!PROBE) return;',
  '    var d = { globalWorkerDefinedBeforeGetDocument: !!hadGlobal, workerSrc: null,',
  '              workerMessageHandlerPresent: false, workerPortType: "undefined",',
  '              taskWebWorker: "unreadable", mode: workerMode, reason: workerReason,',
  '              verdict: "unknown" };',
  '    try { d.workerSrc = pdfjsLib.GlobalWorkerOptions.workerSrc || null; } catch (e) {}',
  '    try { d.workerPortType = typeof pdfjsLib.GlobalWorkerOptions.workerPort; } catch (e) {}',
  '    try { d.workerMessageHandlerPresent = !!(globalThis.pdfjsWorker && globalThis.pdfjsWorker.WorkerMessageHandler); } catch (e) {}',
  '    try {',
  '      if (task && task._worker && Object.prototype.hasOwnProperty.call(task._worker, "_webWorker")) {',
  '        d.taskWebWorker = task._worker._webWorker ? "present" : "null";',
  '      }',
  '    } catch (e) { d.taskWebWorkerError = String(e); }',
  '    if (workerMode === "real") {',
  '      d.verdict = "REAL Worker (blob: port) — parse and image decode are off the UI thread; '
    + 'canvas paint is not";',
  '    } else if (workerMode === "main-thread") {',
  '      d.verdict = "FAKE worker — pdf.js parses and rasterises on the MAIN thread (fell back: "',
  '        + workerReason + ")";',
  '    }',
  '    probePost("workerpath", d);',
  '  }',
  '',
  // ONE OPEN AT A TIME, AND THE LAST ONE WINS.
  //
  // Two opens can be in flight at once — the host posts a second document
  // while the first is still parsing, or (new here) the worker dies mid-parse
  // and `workerBlewUp` re-opens through the main-thread fallback. `resetDocument`
  // sets `doc = null`, but it cannot reach INTO the pending `task.promise` of
  // the open it superseded: that promise still resolves later and assigns
  // `doc = pdf`, laying a second set of slots over the document the reader is
  // actually looking at.
  //
  // A generation stamp is the same mechanism `slot.gen` already uses for a
  // render, applied to the open. A superseded chain destroys the document it
  // just parsed and stops, rather than publishing it.
  '  var loadGen = 0;',
  '  function loadCurrent(){',
  '  var ptOpen0 = PROBE ? pnow() : 0;',
  '  var ptLayoutMs = 0, ptParseMs = 0, ptBytesMs = 0;',
  '  loadGen = loadGen + 1;',
  '  var myGen = loadGen;',
  '  readBytes(fileUrl, function(bytes){',
  '    if (myGen !== loadGen) return;',
  '    var ptBytes = PROBE ? pnow() : 0;',
  '    if (PROBE) { ptBytesMs = r1(ptBytes - ptOpen0); probePost("bytes", { readMs: ptBytesMs, byteLength: (bytes && bytes.length) || 0 }); }',
  // Captured on the line BEFORE the call, because the call itself is what
  // would create one.
  '    var hadGlobalWorker = false;',
  '    try { hadGlobalWorker = (typeof globalThis.pdfjsWorker !== "undefined") && !!globalThis.pdfjsWorker; } catch (e) {}',
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
  '    if (PROBE) probeWorkerPath(task, hadGlobalWorker);',
  '    var ptParse0 = PROBE ? pnow() : 0;',
  '    task.promise.then(function(pdf){',
  '      if (myGen !== loadGen) { try { pdf.destroy(); } catch (e) {} return null; }',
  '      doc = pdf;',
  '      if (PROBE) { ptParseMs = r1(pnow() - ptParse0); probePost("parse", { parseMs: ptParseMs, pages: pdf.numPages }); }',
  '      var ptLayout0 = PROBE ? pnow() : 0;',
  '      return layout().then(function(){',
  '        if (!PROBE) return;',
  '        ptLayoutMs = r1(pnow() - ptLayout0);',
  '        var g = layoutGetPageMs || [], z = layoutSizeMs || [];',
  // `pages` is kept beside `numPages` so an existing reader of these logs is
  // not broken by the addition; `numPages` is the name the report asked for.
  // The per-page array is capped because a 200-sheet set would otherwise put
  // 200 numbers through the bridge, and min/median/max already answer the
  // question the array is only there to corroborate.
  '        probePost("layout", {',
  '          layoutMs: ptLayoutMs,',
  '          numPages: doc.numPages,',
  '          pages: doc.numPages,',
  '          getPageTotalMs: sum(g),',
  '          getPageMinMs: minOf(g), getPageMedianMs: median(g), getPageMaxMs: maxOf(g),',
  '          sizeTotalMs: sum(z),',
  '          sizeMinMs: minOf(z), sizeMedianMs: median(z), sizeMaxMs: maxOf(z),',
  '          perPageGetPageMs: g.slice(0, 40),',
  '          perPageTruncated: g.length > 40',
  '        });',
  '      });',
  '    }).then(function(){',
  // The superseded chain stops HERE too, not just at the parse. Without this
  // it would hide the newer open's "Loading", build a second observer over
  // slots that belong to nothing, and post a `pdf-ready` naming a document
  // that was destroyed two lines up.
  '      if (myGen !== loadGen || !doc) return;',
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
  // THE OPEN'S OWN BREAKDOWN, IN ONE ROW. `layoutMs` has been emitted since
  // the first probe round, but in a SEPARATE post — so settling "is layout()
  // the open stall?" meant cross-referencing two lines of a log the operator
  // reads off a phone. Carried beside the total, the answer is the row itself:
  // if layoutMs is a small fraction of totalMs, layout is not the stall, and
  // no arithmetic is needed to see it.
  '      if (PROBE) {',
  '        probePost("open", { totalMs: r1(pnow() - ptOpen0), bytesMs: ptBytesMs,',
  '          parseMs: ptParseMs, layoutMs: ptLayoutMs, pages: doc.numPages, numPages: doc.numPages });',
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
