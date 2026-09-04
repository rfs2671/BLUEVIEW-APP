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
const VIEWER_VERSION = '3';

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
  '  var MAX_CANVAS_PX = 16000000;',   // ~16MP per page, keeps big plans off the OOM killer
  '  var MAX_CANVAS_EDGE = 4096;',
  // How far either side of the viewport a page counts as "near". Feeds both
  // the observer's rootMargin and the no-observer sweep, so the two paths
  // agree on what is near.
  '  var BAND = 1.5;',
  // THE WINDOW. At BAND = 1.5 the near set spans four viewport heights, which
  // on a phone is four or five full-width sheets, so anything smaller than
  // that would have the observer and the evictor fighting: a page still inside
  // the band would be freed and then never redrawn, because
  // IntersectionObserver reports threshold CROSSINGS, not steady state. 7 is
  // the near set plus roughly a page of hysteresis each side — a flick back
  // lands on a canvas that is still there — and it caps the page at about 7
  // sheets of bitmap (~30–50 MB) no matter how long the set is.
  '  var KEEP_RENDERED = 7;',
  '',
  '  function post(obj){',
  '    try { if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(JSON.stringify(obj)); } catch (e) {}',
  '  }',
  '  function fail(code, detail){',
  '    if (msgEl) msgEl.textContent = "Could not render this document.";',
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
  '  function pnow(){ try { return performance.now(); } catch (e) { return Date.now(); } }',
  '  function r1(x){ return Math.round(x * 10) / 10; }',
  '  function probePost(kind, data){',
  '    if (!PROBE) return;',
  '    try { post({ type: "pdf-probe", probe: kind, data: data }); } catch (e) {}',
  '  }',
  '',
  // Everything the design questions turn on, read off the device rather than a
  // compatibility table. `transferControlToOffscreen` is checked on a real
  // element because the prototype can carry the method on builds where calling
  // it throws.
  '  function probeEnv(){',
  '    if (!PROBE) return;',
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
  '    d.KEEP_RENDERED = KEEP_RENDERED;',
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
  '    if (!PROBE) return;',
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
  '    if (!PROBE) { if (done) done(false); return; }',
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
  '  var fileUrl = param("file");',
  '  if (!fileUrl) { fail("no-file", "missing ?file="); return; }',
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
  '  function targetScaleInfo(vp1, over){',
  '    var dpr = window.devicePixelRatio || 1;',
  // Render above CSS size so pinch-zoom stays legible without a re-render.
  '    var s = (baseWidth / vp1.width) * Math.min(dpr, 2) * (over === undefined ? 1.5 : over);',
  '    var w = vp1.width * s, h = vp1.height * s;',
  '    var clamp = "none";',
  '    if (w > MAX_CANVAS_EDGE) { s = s * (MAX_CANVAS_EDGE / w); w = vp1.width * s; h = vp1.height * s; clamp = "edge-w"; }',
  '    if (h > MAX_CANVAS_EDGE) { s = s * (MAX_CANVAS_EDGE / h); w = vp1.width * s; h = vp1.height * s; clamp = (clamp === "none" ? "edge-h" : clamp + "+edge-h"); }',
  '    if (w * h > MAX_CANVAS_PX) { s = s * Math.sqrt(MAX_CANVAS_PX / (w * h)); w = vp1.width * s; h = vp1.height * s; clamp = (clamp === "none" ? "maxpx" : clamp + "+maxpx"); }',
  '    return { s: s, w: w, h: h, clamp: clamp, dpr: dpr, baseWidth: baseWidth };',
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
  // Hold the window down to KEEP_RENDERED, oldest first. A page still inside
  // the band is skipped, never freed — the observer would not fire for it
  // again and it would sit blank on screen.
  '  function trim(){',
  '    var i = 0;',
  '    while (rendered.length > KEEP_RENDERED && i < rendered.length) {',
  '      if (rendered[i].visible) { i = i + 1; continue; }',
  '      releaseSlot(rendered.splice(i, 1)[0]);',
  '    }',
  '  }',
  '',
  '  function renderSlot(slot){',
  '    if (slot.done) { touch(slot); return; }',
  '    if (slot.busy) return;',
  '    slot.busy = true;',
  '    var gen = slot.gen;',
  // PROBE: `pt0` and the stamps below are plain locals on the real render
  // path. They cost two subtractions and a branch when the probe is off, and
  // measuring the ACTUAL render is the point — a separate timed render would
  // be measuring a different one, warm, with the operator list already parsed.
  '    var pt0 = PROBE ? pnow() : 0;',
  '    doc.getPage(slot.n).then(function(page){',
  '      if (slot.gen !== gen) { slot.busy = false; try { page.cleanup(); } catch (e) {} return null; }',
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
  '        if (slot.gen !== gen) { canvas.width = 0; canvas.height = 0; return; }',
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
  '      });',
  '    })["catch"](function(e){',
  '      slot.task = null;',
  '      slot.busy = false;',
  '      if (e && e.name === "RenderingCancelledException") return;',
  '      post({ type: "pdf-page-error", page: slot.n, detail: String(e) });',
  '    });',
  '  }',
  '',
  '  function inBand(slot){',
  '    var h = window.innerHeight || document.documentElement.clientHeight || 800;',
  '    var r = slot.el.getBoundingClientRect();',
  '    return r.bottom > -(BAND * h) && r.top < h + (BAND * h);',
  '  }',
  '',
  // The no-IntersectionObserver path, and the same shape as the observer's
  // callback: mark what is near, draw only that, then trim. Bounded by
  // KEEP_RENDERED exactly like the observer path.
  '  function sweep(){',
  '    for (var i = 0; i < slots.length; i++) {',
  '      slots[i].visible = inBand(slots[i]);',
  '      if (slots[i].visible) renderSlot(slots[i]);',
  '    }',
  '    trim();',
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
  '  function watch(){',
  '    if (typeof IntersectionObserver === "undefined") {',
  // WAS: a for-loop over every slot calling renderSlot. That rasterised the
  // whole set at once and uncapped, which is the worst version of this bug.
  '      window.addEventListener("scroll", scheduleSweep, true);',
  '      window.addEventListener("resize", scheduleSweep);',
  '      sweep();',
  '      return;',
  '    }',
  '    io = new IntersectionObserver(function(entries){',
  '      for (var i = 0; i < entries.length; i++) {',
  '        var slot = entries[i].target.__slot;',
  '        if (!slot) continue;',
  '        if (entries[i].isIntersecting) {',
  '          slot.visible = true;',
  '          renderSlot(slot);',
  '        } else {',
  '          slot.visible = false;',
  '        }',
  '      }',
  '      trim();',
  '    }, { rootMargin: (BAND * 100) + "% 0px" });',
  '    for (var j = 0; j < slots.length; j++) io.observe(slots[j].el);',
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
  '                          visible: false, canvas: null, page: null, task: null, gen: 0 };',
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
  '        var best = null, imgs = 0;',
  '        try {',
  '          for (var i = 0; i < ol.fnArray.length; i++) {',
  '            var fn = ol.fnArray[i];',
  '            if (fn !== OPS.paintImageXObject && fn !== OPS.paintJpegXObject && fn !== OPS.paintImageMaskXObject) continue;',
  '            imgs++;',
  '            var nm = ol.argsArray[i] && ol.argsArray[i][0];',
  '            if (!nm) continue;',
  '            var o = null;',
  '            try { o = page.objs.get(nm); } catch (e) { o = null; }',
  '            if (o && o.width && o.height && (!best || o.width * o.height > best.w * best.h)) best = { w: o.width, h: o.height };',
  '          }',
  '        } catch (e) {}',
  '        probePost("native-raster", { page: pageNo, imageOps: imgs, nativeW: best ? best.w : null, nativeH: best ? best.h : null });',
  '        try { page.cleanup(); } catch (e) {}',
  '        cb(best);',
  '      })["catch"](function(){ probePost("native-raster", { page: pageNo, error: "operator-list-failed" }); cb(null); });',
  '    })["catch"](function(){ cb(null); });',
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
  '              function thenWorker(){ probeWorkerAB(function(){ probePost("suite", { done: true }); }); }',
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
  '  probeEnv();',
  '  probeCanvasLimits();',
  '  probeBlobWorker(function(){});',
  '  hbStart();',
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
  '      if (msgEl && msgEl.parentNode) msgEl.parentNode.removeChild(msgEl);',
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
  '    if (msgEl) msgEl.textContent = "Could not read this document from storage.";',
  '    post({ type: "pdf-error", code: code, detail: fileUrl });',
  '  });',
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

/** Directory WKWebView must be granted read access to (iOS allowingReadAccessToURL). */
export function pdfJsViewerDir() {
  return VIEWER_DIR;
}
