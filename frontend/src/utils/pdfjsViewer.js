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
const VIEWER_VERSION = '2';

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
  '  function targetScale(vp1){',
  '    var dpr = window.devicePixelRatio || 1;',
  // Render above CSS size so pinch-zoom stays legible without a re-render.
  '    var s = (baseWidth / vp1.width) * Math.min(dpr, 2) * 1.5;',
  '    var w = vp1.width * s, h = vp1.height * s;',
  '    if (w > MAX_CANVAS_EDGE) { s = s * (MAX_CANVAS_EDGE / w); w = vp1.width * s; h = vp1.height * s; }',
  '    if (h > MAX_CANVAS_EDGE) { s = s * (MAX_CANVAS_EDGE / h); w = vp1.width * s; h = vp1.height * s; }',
  '    if (w * h > MAX_CANVAS_PX) s = s * Math.sqrt(MAX_CANVAS_PX / (w * h));',
  '    return s;',
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
  '    doc.getPage(slot.n).then(function(page){',
  '      if (slot.gen !== gen) { slot.busy = false; try { page.cleanup(); } catch (e) {} return null; }',
  '      slot.page = page;',
  '      var vp1 = page.getViewport({ scale: 1 });',
  '      var vp = page.getViewport({ scale: targetScale(vp1) });',
  '      var canvas = document.createElement("canvas");',
  '      canvas.width = Math.max(1, Math.floor(vp.width));',
  '      canvas.height = Math.max(1, Math.floor(vp.height));',
  '      var ctx = canvas.getContext("2d");',
  '      slot.task = page.render({ canvasContext: ctx, viewport: vp });',
  '      return slot.task.promise.then(function(){',
  '        slot.task = null;',
  '        slot.busy = false;',
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
  '  readBytes(fileUrl, function(bytes){',
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
  '    task.promise.then(function(pdf){',
  '      doc = pdf;',
  '      return layout();',
  '    }).then(function(){',
  '      if (msgEl && msgEl.parentNode) msgEl.parentNode.removeChild(msgEl);',
  '      watch();',
  '      post({ type: "pdf-ready", pages: doc.numPages });',
  '    })["catch"](function(e){ fail("parse", e); });',
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
export function localViewerUrlFor(viewerUri, pdfFileUri) {
  if (!viewerUri || !pdfFileUri) return null;
  return `${viewerUri}?file=${encodeURIComponent(pdfFileUri)}#pagemode=none`;
}

/** Directory WKWebView must be granted read access to (iOS allowingReadAccessToURL). */
export function pdfJsViewerDir() {
  return VIEWER_DIR;
}
