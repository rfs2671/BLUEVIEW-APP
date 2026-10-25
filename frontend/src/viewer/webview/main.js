/**
 * The page a phone's WebView loads (bundled into webview/sheetWebViewHtml.js by
 * scripts/build-sheet-webview.cjs). It is the same engine and canvas viewer as the web
 * app, so a phone without the native Skia build gets the tile viewer over the air.
 *
 * Pan, pinch, zoom, inertia, search and painting all happen HERE, in the page: nothing
 * crosses to the app per frame. Pins and highlights are drawn onto the same canvas as
 * the tiles, so they cannot trail the drawing. Only taps and a throttled status message
 * go to the app (window.ReactNativeWebView.postMessage); the app talks back by calling
 * window.__sheetRecv(message). The login token arrives in the `init` message and is
 * held in memory: it is never put in a URL.
 *
 * messages in:  init, manifest, pins, search, step, clearSearch, fit, zoom, goToPage
 * messages out: ready, tap, state, error
 */
import { createSheetApi } from '../sheetApi';
import { createSheetController } from '../sheetController';
import { mountCanvasViewer } from '../canvasViewer';
import { keepPortalFramed } from '../portalFrame';

const MAX_BYTES = 96 * 1024 * 1024;
const STATE_EVERY_MS = 200;

let ctl = null;
let view = null;
let offPortal = null;
let stateTimer = null;

function post(message) {
  try {
    if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(JSON.stringify(message));
  } catch (_e) { /* the app is gone */ }
}

function report(e) {
  post({ type: 'error', message: String((e && e.message) || e).slice(0, 300) });
}

function sendState() {
  stateTimer = null;
  if (!ctl) return;
  const s = ctl.searchState;
  post({ type: 'state', total: s.matches.length, current: s.current, query: s.query, progress: ctl.indexProgress, zoom: ctl.camera.zoom });
}
function queueState() {
  if (!stateTimer) stateTimer = setTimeout(sendState, STATE_EVERY_MS);
}

/** A tap result the app can use: plain data, nothing that points back into the page. */
function slim(hit) {
  if (!hit) return null;
  if (hit.type === 'pin') return { type: 'pin', id: hit.pin.id };
  if (hit.type === 'callout') return { type: 'callout', page: hit.page, callout: hit.callout };
  return { type: 'page', page: hit.page, x: hit.x, y: hit.y };
}

function teardown() {
  if (offPortal) { offPortal(); offPortal = null; }
  if (view) { view.destroy(); view = null; }
  if (ctl) { ctl.destroy(); ctl = null; }
}

async function decode(bytes) {
  const bmp = await window.createImageBitmap(new Blob([bytes], { type: 'image/webp' }));
  return { image: bmp, bytes: bmp.width * bmp.height * 4 };
}

function init(cfg) {
  teardown();
  const api = createSheetApi({ apiBase: cfg.apiBase, getToken: async () => cfg.token });
  ctl = createSheetController({
    api, projectId: cfg.projectId, fileId: cfg.fileId, manifest: cfg.manifest,
    decode, dispose: (img) => { try { img.close(); } catch (_e) { /* already closed */ } },
    disk: null, dpr: Math.min(2, cfg.dpr || window.devicePixelRatio || 1), maxBytes: MAX_BYTES,   // 3x canvases cost 2x the fill for no visible gain
  });
  const root = document.getElementById('root');
  view = mountCanvasViewer(root, ctl, {
    interactive: cfg.interactive !== false,
    showCallouts: cfg.showCallouts !== false,
    background: cfg.background,
    onTap: (hit) => post({ type: 'tap', hit: slim(hit) }),
  });
  if (cfg.portal) offPortal = keepPortalFramed(ctl, cfg.portal);
  ctl.on('change', queueState);
  post({ type: 'ready' });
}

const handlers = {
  init,
  manifest: (m) => { if (ctl) ctl.refreshManifest(m.manifest); },
  pins: (m) => { if (ctl) ctl.setPins(m.pins); },
  search: async (m) => { if (ctl) { await ctl.search(m.q); sendState(); } },
  step: (m) => { if (ctl) { ctl.stepMatch(m.dir); sendState(); } },
  clearSearch: () => { if (ctl) { ctl.clearSearch(); sendState(); } },
  fit: () => { if (ctl) ctl.fit(); },
  zoom: (m) => { if (ctl) ctl.zoomBy(m.factor); },
  goToPage: (m) => { if (ctl) ctl.goToPage(m.page); },
};

window.__sheetRecv = (message) => {
  try {
    const h = message && handlers[message.type];
    if (!h) return;
    const r = h(message);
    if (r && r.catch) r.catch(report);
  } catch (e) {
    report(e);
  }
};
window.addEventListener('error', (e) => report(e.error || e.message));
window.addEventListener('unhandledrejection', (e) => report(e.reason));
post({ type: 'loaded' });
