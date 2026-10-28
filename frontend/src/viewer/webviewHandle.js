/**
 * The app's handle on a viewer that lives inside a WebView page (webview/main.js). It has
 * the same surface SheetViewerPane uses on a controller (setPins, search, stepMatch,
 * clearSearch, fit, zoomBy, goToPage, searchState, indexProgress, on), so the search bar,
 * zoom buttons and pins work the same whether the viewer is a web canvas or a WebView page.
 *
 * State that must survive the page loading late (the pins, the latest manifest) is
 * replayed when the page reports `ready`; everything else is sent as it happens.
 */
export function createWebViewHandle() {
  let send = null;                 // (message) => void, set while a WebView is mounted
  let ready = false;
  let pins = [];
  let manifest = null;
  let tapCb = null;
  let errorCb = null;
  let state = { total: 0, current: 0, query: '', progress: { loaded: 0, total: 0, failed: 0 }, zoom: 1 };
  const listeners = new Set();

  const emit = () => { for (const f of listeners) { try { f(); } catch (_e) { /* a bad listener must not stop the rest */ } } };
  const post = (m) => { if (send && ready) send(m); };

  const h = {
    isWebView: true,

    /** Called by the pane: `fn` posts a message into the page; null when it unmounts. Only an
     *  unmount detaches (callback changes must not: see SheetWebViewPane), and a page that
     *  loads again announces `loaded` first, which clears `ready` until it says so again. */
    attach(fn) { send = fn; if (!fn) ready = false; },
    onTap(cb) { tapCb = cb; },
    onError(cb) { errorCb = cb; },

    /** A message from the page. */
    receive(m) {
      if (!m || typeof m !== 'object') return;
      if (m.type === 'loaded') {
        ready = false;                       // the page (re)loaded: it will say `ready` again after init
      } else if (m.type === 'ready') {
        ready = true;
        post({ type: 'pins', pins });
        if (manifest) post({ type: 'manifest', manifest });
        emit();
      } else if (m.type === 'state') {
        state = { total: m.total || 0, current: m.current || 0, query: m.query || '', progress: m.progress || state.progress, zoom: m.zoom || state.zoom };
        emit();
      } else if (m.type === 'tap') {
        const hit = m.hit || null;
        if (hit && hit.type === 'pin') hit.pin = { id: hit.id };      // the shape SheetViewerPane reads
        if (tapCb) tapCb(hit);
      } else if (m.type === 'error') {
        if (errorCb) errorCb(m.message);
      }
    },

    // ── the controller surface ──
    setPins(next) { pins = next || []; post({ type: 'pins', pins }); },
    setManifest(next) { manifest = next; post({ type: 'manifest', manifest: next }); },
    search(q) { state = { ...state, query: q }; post({ type: 'search', q }); return Promise.resolve(h.searchState); },
    stepMatch(dir) { post({ type: 'step', dir }); },
    clearSearch() { state = { ...state, total: 0, current: 0, query: '' }; post({ type: 'clearSearch' }); emit(); },
    fit() { post({ type: 'fit' }); },
    zoomBy(factor) { post({ type: 'zoom', factor }); },
    goToPage(page) { post({ type: 'goToPage', page }); },

    get searchState() { return { matches: { length: state.total }, total: state.total, current: state.current, query: state.query }; },
    get indexProgress() { return state.progress; },
    get ready() { return ready; },
    on(name, fn) { if (name === 'change') { listeners.add(fn); return () => listeners.delete(fn); } return () => {}; },
  };
  return h;
}
