// Share a plan-sheet note as ONE composed image from the PHONE app.
//
// The same image the web viewer makes (planNoteShare.js, #946): the plan crop
// with the marker, the optional site photo, and a caption bar with the context,
// project name, sheet id and date. The LAYOUT is not re-implemented here:
// composeShareImage() from planNoteShare.js runs unchanged, against a canvas
// that only RECORDS what it is asked to draw.
//
// WHY A RECORDING CANVAS AND A HIDDEN WEBVIEW. A phone has no DOM canvas, and
// the installed 1.3.0 binary carries no view-shot / Skia / canvas module, so
// nothing native can rasterise. It does carry react-native-webview, and a
// WebView has a real <canvas>. So:
//
//   1. "prepare": the page loads the plan crop and the photo (data: URIs) and
//      measures the caption's words with the font the image is drawn in. Text
//      wrapping is greedy and needs a measureText it can call synchronously,
//      which a WebView cannot offer across the bridge; the widths of every word,
//      character and space come back in one round trip instead.
//   2. composeShareImage() runs HERE with those widths and the images' real
//      sizes, against the recorder. Its output is a plain list of canvas calls.
//   3. "draw": the page replays that list on a real canvas and returns a JPEG
//      as base64. Only an allowlisted set of canvas calls is replayed.
//
// The base64 is written to the app's cache directory and handed to the OS
// share sheet (expo-sharing) as a FILE: no message, no text, no url, no title.
// The user picks WhatsApp (or anything else) in the sheet the OS draws.
//
// No network: the page has no fetch/XHR, its images are data: URIs, and its
// Content-Security-Policy refuses every connection. Every platform module is
// injected so all of this runs under node in planNoteShareNative.test.cjs.

import {
  CAPTION_FONT, IMAGE_WIDTH, captionFields, composeShareImage,
} from './planNoteShare';

export const SHARE_MIME = 'image/jpeg';
export const SHARE_UTI = 'public.jpeg';
export const COMPOSE_TIMEOUT_MS = 20000;
export const PHOTO_JPEG_QUALITY = 0.85;

const isImageDataUri = (v) => typeof v === 'string' && /^data:image\/[a-z.+-]+;base64,/i.test(v);
export { isImageDataUri };

// ── 1. what the page has to measure ─────────────────────────────────────────
// Every word of the context and of the meta line, every distinct character
// (a word longer than the line is broken by characters) and a single space.
export function measureRequest({ context, projectName, sheetLabel, date }) {
  const f = captionFields({ context, projectName, sheetLabel, date });
  const text = `${f.context}\n${f.meta.join('  |  ')}`;
  const seen = new Set([' ']);
  for (const w of text.split(/\s+/)) {
    if (!w) continue;
    seen.add(w);
    for (const ch of Array.from(w)) seen.add(ch);
  }
  return Array.from(seen);
}

// measure(s) from the page's widths: a known string is exact; anything else is
// the sum of its words and spaces; an unknown word is the sum of its characters.
export function tableMeasure(texts, widths, fallbackPx = 40) {
  const table = new Map();
  (texts || []).forEach((t, i) => {
    const w = Number(widths && widths[i]);
    if (Number.isFinite(w)) table.set(t, w);
  });
  const space = table.has(' ') ? table.get(' ') : fallbackPx / 3;
  const word = (w) => {
    if (table.has(w)) return table.get(w);
    let sum = 0;
    for (const ch of Array.from(w)) sum += table.has(ch) ? table.get(ch) : fallbackPx;
    return sum;
  };
  return (s) => {
    const str = String(s == null ? '' : s);
    if (table.has(str)) return table.get(str);
    let sum = 0;
    for (const part of str.split(/(\s+)/)) {
      if (!part) continue;
      sum += /^\s+$/.test(part) ? space * part.length : word(part);
    }
    return sum;
  };
}

// ── 2. the recording canvas ─────────────────────────────────────────────────
// The calls the page will replay. Anything else is refused at record time, so a
// change to the composer that needs a new call fails here (in the tests), not
// silently on a phone.
export const REPLAY_METHODS = ['fillRect', 'drawImage', 'beginPath', 'arc', 'stroke', 'moveTo', 'lineTo', 'fillText'];
export const REPLAY_PROPS = ['fillStyle', 'strokeStyle', 'lineWidth', 'font', 'textBaseline'];

export function recordingCanvasFactory(measure) {
  const made = [];
  const createCanvas = (width, height) => {
    const ops = [];
    const ctx = {};
    REPLAY_METHODS.forEach((m) => {
      ctx[m] = (...args) => {
        if (m === 'drawImage') {
          const img = args[0];
          if (!img || typeof img.ref !== 'string') throw new Error('drawImage needs an image reference');
          ops.push([m, img.ref, ...args.slice(1)]);
        } else ops.push([m, ...args]);
      };
    });
    ctx.measureText = (s) => ({ width: measure(s) });
    const state = {};
    REPLAY_PROPS.forEach((p) => {
      Object.defineProperty(ctx, p, {
        get: () => state[p],
        set: (v) => { state[p] = v; ops.push(['set', p, v]); },
        enumerable: true,
      });
    });
    const canvas = { width, height, ops, getContext: () => ctx };
    made.push(canvas);
    return canvas;
  };
  return { createCanvas, made };
}

// The image as composeShareImage sees it: a size and a name the page knows.
const imageRef = (ref, size) => (size && size.width > 0 && size.height > 0
  ? { ref, naturalWidth: size.width, naturalHeight: size.height }
  : null);

export function composeOps({ planSize = null, photoSize = null, context = '', projectName = '', sheetLabel = '', date = '', measure }) {
  const { createCanvas } = recordingCanvasFactory(measure);
  const out = composeShareImage({
    planImage: imageRef('plan', planSize),
    photo: imageRef('photo', photoSize),
    // The server-made crop already carries the marker ring at the note's spot
    // (the web viewer passes no marker either).
    marker: null,
    context, projectName, sheetLabel, date, createCanvas,
  });
  return {
    width: out.width, height: out.height, ops: out.canvas.ops,
    captionLines: out.captionLines, hasPlan: out.hasPlan, hasPhoto: out.hasPhoto,
  };
}

// ── 3. the page ─────────────────────────────────────────────────────────────
// Kept as plain ES5 in a string: Hermes does not keep function source, so the
// page cannot be built from a function's toString().
export const COMPOSER_PAGE_SCRIPT = [
  '(function(){',
  '  var imgs = { plan: null, photo: null };',
  `  var METHODS = ${JSON.stringify(REPLAY_METHODS.reduce((o, k) => { o[k] = 1; return o; }, {}))};`,
  `  var PROPS = ${JSON.stringify(REPLAY_PROPS.reduce((o, k) => { o[k] = 1; return o; }, {}))};`,
  '  function post(o){ try { window.ReactNativeWebView.postMessage(JSON.stringify(o)); } catch (e) {} }',
  '  function load(src){',
  '    return new Promise(function(done){',
  '      if (typeof src !== "string" || src.indexOf("data:image/") !== 0) { done(null); return; }',
  '      var i = new Image();',
  '      i.onload = function(){ done(i.naturalWidth > 0 && i.naturalHeight > 0 ? i : null); };',
  '      i.onerror = function(){ done(null); };',
  '      i.src = src;',
  '    });',
  '  }',
  '  function size(i){ return i ? { width: i.naturalWidth, height: i.naturalHeight } : null; }',
  '  function prepare(m){',
  '    var srcs = m.images || {};',
  '    Promise.all([load(srcs.plan), load(srcs.photo)]).then(function(r){',
  '      imgs = { plan: r[0], photo: r[1] };',
  '      var c = document.createElement("canvas").getContext("2d");',
  '      c.font = m.font;',
  '      var widths = (m.texts || []).map(function(t){ return c.measureText(String(t)).width; });',
  '      post({ type: "prepared", id: m.id, widths: widths, sizes: { plan: size(r[0]), photo: size(r[1]) } });',
  '    }, function(e){ post({ type: "compose-failed", id: m.id, detail: String(e && e.message || e) }); });',
  '  }',
  '  function draw(m){',
  '    try {',
  '      var cv = document.createElement("canvas");',
  '      cv.width = m.width; cv.height = m.height;',
  '      var ctx = cv.getContext("2d");',
  '      (m.ops || []).forEach(function(op){',
  '        var k = op[0];',
  '        if (k === "set") { if (PROPS[op[1]]) ctx[op[1]] = op[2]; return; }',
  '        if (!METHODS[k]) return;',
  '        if (k === "drawImage") {',
  '          var im = imgs[op[1]];',
  '          if (im) ctx.drawImage(im, op[2], op[3], op[4], op[5]);',
  '          return;',
  '        }',
  '        ctx[k].apply(ctx, op.slice(1));',
  '      });',
  `      var url = cv.toDataURL("${SHARE_MIME}", 0.9);`,
  '      var b64 = url.slice(url.indexOf(",") + 1);',
  '      if (url.indexOf("data:image/") !== 0 || !b64) throw new Error("empty image");',
  '      post({ type: "drawn", id: m.id, base64: b64, width: cv.width, height: cv.height });',
  '    } catch (e) { post({ type: "compose-failed", id: m.id, detail: String(e && e.message || e) }); }',
  '  }',
  '  window.__planNoteCompose = function(m){',
  '    if (!m || !m.type) return;',
  '    if (m.type === "prepare") prepare(m);',
  '    else if (m.type === "draw") draw(m);',
  '  };',
  '  post({ type: "composer-ready" });',
  '})();',
].join('\n');

// default-src 'none' covers connect-src: no fetch, no XHR, no beacon, no socket.
// 'unsafe-eval' is there only so the host's injectJavaScript is never refused
// on a WebView that treats it as eval.
export const COMPOSER_CSP = "default-src 'none'; img-src data:; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'";

export const COMPOSER_HTML = [
  '<!doctype html><html><head><meta charset="utf-8">',
  `<meta http-equiv="Content-Security-Policy" content="${COMPOSER_CSP}">`,
  '</head><body style="margin:0;background:#fff">',
  `<script>${COMPOSER_PAGE_SCRIPT}</script>`,
  '</body></html>',
].join('');

// The JS the host injects to hand the page one message. JSON is a JS
// expression; U+2028/U+2029 are escaped for engines older than ES2019.
export function composerInjection(msg) {
  const LS = String.fromCharCode(0x2028);
  const PS = String.fromCharCode(0x2029);
  const json = JSON.stringify(msg).split(LS).join('\\u2028').split(PS).join('\\u2029');
  return `window.__planNoteCompose && window.__planNoteCompose(${json});true;`;
}

// ── 4. the bridge between the component and the page ───────────────────────
// `inject(js)` runs js in the page (the component passes the WebView's
// injectJavaScript). `onMessage(raw)` is wired to the WebView's onMessage.
export function createComposerBridge({ inject, timeoutMs = COMPOSE_TIMEOUT_MS, setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  let ready = false;
  let seq = 0;
  let readyWaiters = [];
  const pending = new Map();

  const settleReady = () => { const w = readyWaiters; readyWaiters = []; w.forEach((r) => r.resolve()); };

  function whenReady() {
    if (ready) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const entry = { resolve: () => { clearTimer(entry.timer); resolve(); }, reject };
      entry.timer = setTimer(() => {
        readyWaiters = readyWaiters.filter((x) => x !== entry);
        reject(new Error('composer did not start'));
      }, timeoutMs);
      readyWaiters.push(entry);
    });
  }

  function request(msg) {
    seq += 1;
    const id = `c${seq}`;
    return new Promise((resolve, reject) => {
      const timer = setTimer(() => { pending.delete(id); reject(new Error('composer timed out')); }, timeoutMs);
      pending.set(id, { resolve, reject, timer });
      try { inject(composerInjection({ ...msg, id })); } catch (e) {
        clearTimer(timer); pending.delete(id); reject(e);
      }
    });
  }

  function onMessage(raw) {
    let m = null;
    try { m = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (_) { return; }
    if (!m || typeof m.type !== 'string') return;
    if (m.type === 'composer-ready') { ready = true; settleReady(); return; }
    const p = m.id && pending.get(m.id);
    if (!p) return;
    pending.delete(m.id);
    clearTimer(p.timer);
    if (m.type === 'compose-failed') p.reject(new Error(m.detail || 'compose failed'));
    else p.resolve(m);
  }

  // The page went away (panel closed, WebView unmounted or crashed).
  function reset() {
    ready = false;
    pending.forEach((p) => { clearTimer(p.timer); p.reject(new Error('composer closed')); });
    pending.clear();
  }

  return { whenReady, request, onMessage, reset, isReady: () => ready };
}

export async function composeInPage({ bridge, planDataUri = null, photoDataUri = null, context = '', projectName = '', sheetLabel = '', date = '' }) {
  await bridge.whenReady();
  const texts = measureRequest({ context, projectName, sheetLabel, date });
  const prepared = await bridge.request({
    type: 'prepare', font: CAPTION_FONT, texts,
    images: { plan: isImageDataUri(planDataUri) ? planDataUri : null, photo: isImageDataUri(photoDataUri) ? photoDataUri : null },
  });
  const sizes = prepared.sizes || {};
  const job = composeOps({
    planSize: sizes.plan, photoSize: sizes.photo,
    context, projectName, sheetLabel, date,
    measure: tableMeasure(texts, prepared.widths),
  });
  const drawn = await bridge.request({ type: 'draw', width: job.width, height: job.height, ops: job.ops });
  if (!drawn || typeof drawn.base64 !== 'string' || !drawn.base64) throw new Error('empty image');
  return { base64: drawn.base64, width: job.width, height: job.height, hasPlan: job.hasPlan, hasPhoto: job.hasPhoto, captionLines: job.captionLines };
}

// ── 5. the photo, scaled to the share width, as a data: URI ─────────────────
// A camera frame is ~12 MP; the image is 1080 wide, so it is scaled on the
// device first (expo-image-manipulator) and only that crosses into the page.
export async function photoDataUri(photo, ImageManipulator, width = IMAGE_WIDTH) {
  if (!photo || !photo.uri) return null;
  const actions = Number(photo.width) > width ? [{ resize: { width } }] : [];
  const format = (ImageManipulator.SaveFormat && ImageManipulator.SaveFormat.JPEG) || 'jpeg';
  const out = await ImageManipulator.manipulateAsync(photo.uri, actions, { compress: PHOTO_JPEG_QUALITY, format, base64: true });
  return out && out.base64 ? `data:${SHARE_MIME};base64,${out.base64}` : null;
}

// ── 6. the file, to the OS share sheet ──────────────────────────────────────
const isCancel = (e) => !!e && (/cancel/i.test(String(e.code || '')) || /cancel/i.test(String(e.message || '')));

// Result status:
//  shared       the share sheet opened and closed (the OS does not say whether
//               an app was picked, so this is NOT a claim that it was sent)
//  cancelled    the share sheet reported a cancel: quiet, nothing to show
//  unavailable  this device has no share sheet for files
//  failed       the file could not be written or the sheet could not open
export async function shareImageFile({ base64, filename, FileSystem, Sharing }) {
  const dir = FileSystem.cacheDirectory;
  if (!dir) return { status: 'failed' };
  const uri = `${dir}${filename}`;
  try {
    await FileSystem.writeAsStringAsync(uri, base64, { encoding: (FileSystem.EncodingType && FileSystem.EncodingType.Base64) || 'base64' });
  } catch (_) { return { status: 'failed' }; }
  try {
    // ONLY the file and its type. No dialogTitle, message, text or url, so
    // nothing is prefilled in the app the user picks.
    await Sharing.shareAsync(uri, { mimeType: SHARE_MIME, UTI: SHARE_UTI });
    return { status: 'shared', uri };
  } catch (e) {
    if (isCancel(e)) return { status: 'cancelled' };
    return { status: 'failed' };
  }
}

// The whole share path, start to finish. Never throws: the component maps the
// status to a line of copy (or to nothing).
//  + compose-failed  the image could not be built
//
// `onComposed` fires once the image exists, BEFORE the share sheet opens. The
// component ends its busy state there and not on the share promise: on iOS
// expo-sharing resolves only on "shared" or "dismissed", and a user who picks
// an app and then backs out of it leaves that promise pending for good.
export async function sharePlanNoteImage({
  bridge, planDataUri = null, photo = null, context = '', projectName = '', sheetLabel = '', date = '', filename,
  ImageManipulator, FileSystem, Sharing, onComposed,
}) {
  try {
    if (!(await Sharing.isAvailableAsync())) return { status: 'unavailable' };
  } catch (_) { return { status: 'unavailable' }; }
  let image;
  try {
    let photoUri = null;
    if (photo) {
      try { photoUri = await photoDataUri(photo, ImageManipulator); } catch (_) { photoUri = null; }
    }
    image = await composeInPage({ bridge, planDataUri, photoDataUri: photoUri, context, projectName, sheetLabel, date });
  } catch (_) {
    return { status: 'compose-failed' };
  }
  try { if (onComposed) onComposed(image); } catch (_) { /* the share still goes */ }
  const res = await shareImageFile({ base64: image.base64, filename, FileSystem, Sharing });
  return { ...res, hasPlan: image.hasPlan, hasPhoto: image.hasPhoto };
}

// The i18n key (planNoteShare namespace) for a status, or null for nothing to
// show. Shared and cancelled are both quiet.
export function shareStatusKey(status) {
  if (status === 'unavailable') return 'unavailable';
  if (status === 'failed') return 'failed';
  if (status === 'compose-failed') return 'composeFailed';
  return null;
}
