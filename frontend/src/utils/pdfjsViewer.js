import { Platform } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import { Asset } from 'expo-asset';

/**
 * OFFLINE PDF VIEWER — a locally staged pdf.js, for Android.
 *
 * WHY THIS EXISTS
 *   PDFViewer.native.jsx renders Android PDFs through the REMOTE
 *   mozilla.github.io/pdf.js viewer. That is fine online and useless in a dead
 *   zone: docCache can have the bytes on disk and Android still draws nothing.
 *   iOS needs none of this — WKWebView hands a `file://` PDF to PDFKit.
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
const VIEWER_VERSION = '1';

// The placeholders are a couple of KB of comments; a real pdf.min.js is ~300KB
// and the worker ~1MB. Anything under this is not a pdf.js build.
const MIN_REAL_ASSET_BYTES = 40000;

const canUseFs = () => Platform.OS !== 'web' && !!FileSystem.documentDirectory;

/** True for the `file://` uris docCache hands back. */
export function isLocalFileUri(uri) {
  return typeof uri === 'string' && uri.startsWith('file://');
}

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
  '  function renderSlot(slot){',
  '    if (slot.done || slot.busy) return;',
  '    slot.busy = true;',
  '    doc.getPage(slot.n).then(function(page){',
  '      var vp1 = page.getViewport({ scale: 1 });',
  '      var vp = page.getViewport({ scale: targetScale(vp1) });',
  '      var canvas = document.createElement("canvas");',
  '      canvas.width = Math.max(1, Math.floor(vp.width));',
  '      canvas.height = Math.max(1, Math.floor(vp.height));',
  '      var ctx = canvas.getContext("2d");',
  '      return page.render({ canvasContext: ctx, viewport: vp }).promise.then(function(){',
  '        slot.el.innerHTML = "";',
  '        slot.el.appendChild(canvas);',
  '        slot.done = true;',
  '        slot.busy = false;',
  '      });',
  '    })["catch"](function(e){ slot.busy = false; post({ type: "pdf-page-error", page: slot.n, detail: String(e) }); });',
  '  }',
  '',
  // Lazy render: only pages near the viewport. A 200-sheet plan set must not
  // rasterise 200 canvases up front.
  '  function watch(){',
  '    if (typeof IntersectionObserver === "undefined") {',
  '      for (var i = 0; i < slots.length; i++) renderSlot(slots[i]);',
  '      return;',
  '    }',
  '    var io = new IntersectionObserver(function(entries){',
  '      for (var i = 0; i < entries.length; i++) {',
  '        if (entries[i].isIntersecting) renderSlot(entries[i].target.__slot);',
  '      }',
  '    }, { rootMargin: "150% 0px" });',
  '    for (var j = 0; j < slots.length; j++) io.observe(slots[j].el);',
  '  }',
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
  '            var slot = { n: pageNo, el: el, done: false, busy: false };',
  '            el.__slot = slot;',
  '            slots.push(slot);',
  '            pagesEl.appendChild(el);',
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
 *  The offline path needs it for the same reason the hosted one does; a cellar
 *  is exactly where the screen is smallest and the drawing matters most. */
export function localViewerUrlFor(viewerUri, pdfFileUri) {
  if (!viewerUri || !pdfFileUri) return null;
  return `${viewerUri}?file=${encodeURIComponent(pdfFileUri)}#pagemode=none`;
}

/** Directory WKWebView must be granted read access to (iOS allowingReadAccessToURL). */
export function pdfJsViewerDir() {
  return VIEWER_DIR;
}
