/**
 * PLAN NOTE SHARE AS ONE IMAGE -- composition + share decision.
 * Run: node src/utils/planNoteShare.test.cjs
 * (SHARE_MODULE=<file in this dir> points it at another module: the control run.)
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0; const failed = [];
function ok(c, m) { if (c) passed++; else { failed.push(m); console.error('FAIL: ' + m); } }

function load(file) {
  const full = path.join(__dirname, file);
  const code = babel.transformSync(fs.readFileSync(full, 'utf8'), {
    filename: full, plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false, babelrc: false,
  }).code;
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', code)(mod, mod.exports, require);
  return mod.exports;
}
const SRC = process.env.SHARE_MODULE || 'planNoteShare.js';
const S = load(SRC);
const viewerSrc = fs.readFileSync(process.env.VIEWER_FILE || path.join(__dirname, '..', 'components', 'PDFViewerWeb.jsx'), 'utf8');
const moduleSrc = fs.readFileSync(path.join(__dirname, SRC), 'utf8');

// ---- fakes -----------------------------------------------------------------
function fakeCanvasFactory() {
  const made = [];
  const createCanvas = (w, h) => {
    const calls = [];
    const ctx = new Proxy({ calls }, {
      get(t, k) {
        if (k === 'calls') return calls;
        if (k === 'measureText') return (s) => ({ width: String(s).length * 20 });
        if (k in t) return t[k];
        return (...a) => { calls.push([k, ...a]); };
      },
      set(t, k, v) { t[k] = v; if (k !== 'font') calls.push(['set:' + k, v]); return true; },
    });
    const c = {
      width: w, height: h, calls, ctx,
      getContext: () => ctx,
      toBlob(cb, type) { cb(new Blob([JSON.stringify(calls)], { type: type || 'image/jpeg' })); },
    };
    made.push(c);
    return c;
  };
  return { createCanvas, made };
}
const img = (w, h) => ({ naturalWidth: w, naturalHeight: h, tag: `img${w}x${h}` });
const textsOf = (c) => c.calls.filter((x) => x[0] === 'fillText').map((x) => x[1]);

(async () => {
  ok(typeof S.composeShareImage === 'function', 'module exports composeShareImage');
  ok(typeof S.shareComposedImage === 'function', 'module exports shareComposedImage');
  // ---- (a) no provider, no prefill, no gating ------------------------------
  const PROVIDER = /wa\.me|api\.whatsapp\.com|whatsapp:\/\/|web\.whatsapp\.com|graph\.facebook\.com/i;
  ok(!PROVIDER.test(moduleSrc), 'share module names no messaging provider host');
  ok(!PROVIDER.test(viewerSrc), 'web viewer names no messaging provider host');
  ok(!/\bfetch\s*\(|XMLHttpRequest|sendBeacon|window\.open|location\.(href|assign|replace)/.test(moduleSrc), 'share module has no fetch/XHR/beacon/window.open/navigation');
  ok(!/text\s*[:=]\s*(msg|message|text)|buildShareText|buildWaMeUrl/.test(moduleSrc + viewerSrc), 'no prefilled message builder remains');
  const shareBlock = viewerSrc.slice(viewerSrc.indexOf('SHARE A PLAN NOTE AS ONE IMAGE'), viewerSrc.indexOf('const getMarkerColor'));
  ok(shareBlock.length > 500, 'found the viewer share block');
  const code = shareBlock.replace(/\/\/.*$/gm, '');
  ok(!/\brole\b|isAdmin|isCp|canShare|user\?\.|currentUser/.test(code), 'share block has no role gating');
  const btn = viewerSrc.slice(viewerSrc.indexOf('Share as image') - 200, viewerSrc.indexOf('Share as image') + 50);
  ok(!/canDelete|role|isAdmin/.test(btn), 'share button is not behind a role/permission check');

  if (typeof S.composeShareImage !== 'function' || typeof S.shareComposedImage !== 'function') {
    // control run against the old module: the behaviour tests cannot execute
    ok(false, 'the share module has no image composer / no file share path');
    console.log(`${passed} passed, ${failed.length} failed`);
    process.exit(1);
  }

  // network + navigation spy over the whole share path
  const net = [];
  const realFetch = global.fetch;
  global.fetch = (...a) => { net.push(['fetch', a[0]]); return Promise.reject(new Error('no network in test')); };
  global.window = { open: (...a) => { net.push(['window.open', a[0]]); return null; } };

  const { createCanvas, made } = fakeCanvasFactory();
  const base = { projectName: 'Boyland St', sheetLabel: 'A-101', date: '2026-11-04', createCanvas };

  // ---- (b) with photo / without photo --------------------------------------
  const plan = img(400, 400);
  const photo = img(3000, 4000);
  const withPhoto = S.composeShareImage({ ...base, planImage: plan, marker: { x: 0.5, y: 0.5 }, photo, context: 'Lintel is cracked at the east wall' });
  const noPhoto = S.composeShareImage({ ...base, planImage: plan, marker: { x: 0.5, y: 0.5 }, context: 'Lintel is cracked at the east wall' });
  ok(withPhoto.width === S.IMAGE_WIDTH && noPhoto.width === S.IMAGE_WIDTH, 'output is the fixed share width');
  ok(withPhoto.hasPhoto && !noPhoto.hasPhoto, 'hasPhoto reflects the input');
  ok(withPhoto.height > noPhoto.height, 'photo adds a section (taller image)');
  ok(withPhoto.canvas.height === withPhoto.height && noPhoto.canvas.height === noPhoto.height, 'canvas is sized to the computed height');
  const planH = Math.round(400 * S.IMAGE_WIDTH / 400);
  ok(noPhoto.height > Math.min(planH, S.MAX_SECTION_HEIGHT), 'no-photo image = plan section + caption bar');
  const drawn = (r) => r.canvas.calls.filter((x) => x[0] === 'drawImage').map((x) => x[1].tag);
  ok(drawn(withPhoto).join() === 'img400x400,img3000x4000', 'with photo: plan crop then photo drawn');
  ok(drawn(noPhoto).join() === 'img400x400', 'without photo: only the plan crop drawn');
  ok(withPhoto.canvas.calls.some((x) => x[0] === 'arc') && withPhoto.canvas.calls.some((x) => x[0] === 'stroke'), 'marker is drawn on the plan crop');
  const arc = withPhoto.canvas.calls.find((x) => x[0] === 'arc');
  ok(arc[1] === S.IMAGE_WIDTH / 2, 'marker at x=0.5 lands at the centre of the plan section');
  const noMarker = S.composeShareImage({ ...base, planImage: plan, context: 'x' });
  ok(!noMarker.canvas.calls.some((x) => x[0] === 'arc'), 'no marker input -> composer draws none (crop already carries it)');
  const t1 = textsOf(withPhoto.canvas).join(' | ');
  ok(/Lintel is cracked/.test(t1), 'caption draws the context');
  ok(t1.includes('Boyland St') && t1.includes('Sheet A-101') && t1.includes('2026-11-04'), 'caption draws project, sheet id, date');
  const blobA = await S.canvasToBlob(withPhoto.canvas);
  const blobB = await S.canvasToBlob(noPhoto.canvas);
  ok(blobA.size > 0 && blobB.size > 0 && /image\//.test(blobA.type), 'both compose to a non-empty image blob');
  let emptyRejects = false;
  try { await S.canvasToBlob({ toBlob: (cb) => cb(null) }); } catch (_) { emptyRejects = true; }
  ok(emptyRejects, 'a null/empty blob is rejected, not shared');
  const longCtx = S.composeShareImage({ ...base, planImage: plan, context: 'word '.repeat(400) });
  ok(longCtx.captionLines.length <= S.CAPTION_MAX_CONTEXT_LINES + 2, 'a very long context is capped');
  ok(longCtx.captionLines.every((l) => l.length > 0), 'no empty caption line from a long context');
  ok(S.sheetLabelFor({ name: 'A-101.pdf' }, 1) === 'A-101' && S.sheetLabelFor({ name: 'A-101.pdf' }, 3) === 'A-101 (p. 3)', 'sheet id label');
  ok(S.formatShareDate(new Date(2026, 10, 4)) === '2026-11-04', 'date format');

  // ---- (c) empty context ---------------------------------------------------
  let threw = false; let empty;
  try { empty = S.composeShareImage({ ...base, planImage: plan, context: '   \n  ' }); } catch (_) { threw = true; }
  ok(!threw, 'empty context composes without throwing');
  ok(empty.captionLines.length === 1 && empty.captionLines.every((l) => l.trim().length > 0), 'empty context leaves no blank caption line');
  ok(empty.captionLines[0].includes('Sheet A-101'), 'the meta line still carries project/sheet/date');
  const nul = S.composeShareImage({ createCanvas, planImage: plan, context: null, projectName: undefined, sheetLabel: '', date: '2026-11-04' });
  ok(nul.captionLines.join('') === '2026-11-04', 'null context + missing project/sheet: caption is just the date');
  const lines = S.captionFields({ context: '', projectName: '', sheetLabel: '', date: '' });
  ok(lines.context === '' && lines.meta.length === 0, 'all-empty fields produce no lines');
  let none = false;
  try { S.composeShareImage({ createCanvas }); } catch (_) { none = true; }
  ok(none, 'nothing at all to compose is an error, not a blank image');
  const eb = await S.canvasToBlob(empty.canvas);
  const shared0 = [];
  const r0 = await S.shareComposedImage({ blob: eb, filename: 'x.jpg', nav: { canShare: () => true, share: async (d) => { shared0.push(d); } } });
  ok(r0.status === 'shared' && shared0.length === 1, 'empty-context image shares');

  // ---- share path: only a file, nothing prefilled -------------------------
  const sharedArgs = [];
  const navOk = { canShare: (d) => !!(d && d.files && d.files.length), share: async (d) => { sharedArgs.push(d); } };
  const rs = await S.shareComposedImage({ blob: blobA, filename: 'plan-note.jpg', nav: navOk, download: () => { throw new Error('should not download'); } });
  ok(rs.status === 'shared', 'canShare({files}) true -> OS share sheet');
  ok(Object.keys(sharedArgs[0]).join() === 'files' && sharedArgs[0].files[0].name === 'plan-note.jpg', 'navigator.share gets ONLY the file (no text/title/url prefilled)');

  // ---- (d) cancel / failure / fallback ------------------------------------
  const saved = [];
  const download = (b, f) => saved.push([b, f]);
  const abort = Object.assign(new Error('cancelled'), { name: 'AbortError' });
  let cancelRes; let cancelThrew = false;
  try { cancelRes = await S.shareComposedImage({ blob: blobA, filename: 'a.jpg', nav: { canShare: () => true, share: async () => { throw abort; } }, download }); } catch (_) { cancelThrew = true; }
  ok(!cancelThrew && cancelRes.status === 'cancelled', 'AbortError -> cancelled, does not throw');
  ok(saved.length === 0, 'cancel does not download (no error UX, no surprise file)');
  ok(!('error' in cancelRes) && !('message' in cancelRes), 'cancel carries no error to show');
  const rf = await S.shareComposedImage({ blob: blobA, filename: 'b.jpg', nav: { canShare: () => true, share: async () => { throw new Error('NotAllowedError-ish'); } }, download });
  ok(rf.status === 'downloaded' && saved.length === 1 && saved[0][1] === 'b.jpg', 'non-Abort failure falls back to download');
  const rd1 = await S.shareComposedImage({ blob: blobA, filename: 'c.jpg', nav: { canShare: () => false, share: async () => { throw new Error('must not call'); } }, download });
  ok(rd1.status === 'downloaded' && saved.length === 2, 'canShare({files}) false -> download');
  const rd2 = await S.shareComposedImage({ blob: blobA, filename: 'd.jpg', nav: { share: async () => { throw new Error('must not call'); } }, download });
  ok(rd2.status === 'downloaded' && saved.length === 3, 'no canShare -> download');
  const rd3 = await S.shareComposedImage({ blob: blobA, filename: 'e.jpg', nav: null, download });
  ok(rd3.status === 'downloaded' && saved.length === 4, 'no navigator (desktop/old) -> download');
  const rd4 = await S.shareComposedImage({ blob: blobA, filename: 'f.jpg', nav: { canShare: () => { throw new Error('boom'); }, share: async () => {} }, download });
  ok(rd4.status === 'downloaded', 'canShare throwing -> download');

  // ---- download helper: blob link, no provider -----------------------------
  const anchors = [];
  const doc = { createElement: () => { const a = { style: {}, click() { anchors.push(a); } }; return a; }, body: { appendChild() {}, removeChild() {} } };
  const urlApi = { createObjectURL: () => 'blob:abc', revokeObjectURL() {} };
  S.downloadBlob(blobA, 'z.jpg', doc, urlApi);
  ok(anchors[0].href === 'blob:abc' && anchors[0].download === 'z.jpg' && /noopener/.test(anchors[0].rel) && /noreferrer/.test(anchors[0].rel), 'download is a blob: link with rel noopener noreferrer');

  // ---- (a) closing: nothing touched the network or navigated --------------
  ok(net.length === 0, `no fetch/XHR/window.open during compose + share (saw ${JSON.stringify(net)})`);
  global.fetch = realFetch;

  console.log(`${passed} passed, ${failed.length} failed`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
