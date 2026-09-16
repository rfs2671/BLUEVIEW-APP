/**
 * THE VIEWER SCRIPT IS EXECUTED, NOT JUST READ.
 *
 * WHY THIS FILE EXISTS. viewer.html is assembled from an array of JS strings
 * and written to disk, and until now NOTHING ran it. The gates around it are
 * all static:
 *   pdfRenderProbe     parses it with acorn — proves it is valid ES5
 *   pdfjsViewerMemory  walks its AST — proves the eviction path is reachable
 *   pdfScaleAnchor     lifts ONE function out and runs the arithmetic
 * Every one of those passes on a script whose top level throws on the first
 * line. The mount smoke cannot help either: it renders the web bundle, and
 * this page only ever runs inside an Android WebView, from file://.
 *
 * That gap mattered the moment the page stopped being a one-shot. It used to
 * read its document out of `?file=` and run straight down the page; it now
 * boots, announces itself, and waits to be handed documents over postMessage,
 * which is a real lifecycle with real ordering — a `var` read before its
 * declaration, a listener registered after the host has already posted, a
 * function called before it is defined. Those are runtime failures on a
 * blank dark screen, and the operator would report "the plan will not open".
 *
 * WHAT THIS IS NOT. It is not a rendering test. pdf.js is stubbed, no bytes
 * are read and no canvas is rasterised. The question is narrow and is the one
 * nothing else asks: does the page come up, say it is ready, accept a
 * document, and survive a pinch — without throwing.
 *
 * Run:  node src/utils/pdfjsViewerBoot.test.cjs
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const VIEWER = path.join(__dirname, 'pdfjsViewer.js');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/** Rebuild the script exactly as viewerHtml() writes it to disk. */
function viewerScript() {
  const src = fs.readFileSync(VIEWER, 'utf8').replace(/\r\n/g, '\n');
  const start = src.indexOf('const VIEWER_SCRIPT = [');
  if (start < 0) throw new Error('VIEWER_SCRIPT not found');
  const open = src.indexOf('[', start);
  const close = src.indexOf("].join('\\n');", open);
  if (close < 0) throw new Error('VIEWER_SCRIPT terminator not found');
  // eslint-disable-next-line no-new-func
  const arr = new Function('WORKER_NAME', `return ${src.slice(open, close + 1)};`)('pdf.worker.min.js');
  return arr.join('\n');
}

// ═══════════════════════════════════════════════════════════════════════════
// A WebView-shaped sandbox. Deliberately MEAN: no Worker, no Blob, no
// WebAssembly, no fetch — the capability probes must all fail soft, because
// on a real device some of them will.
// ═══════════════════════════════════════════════════════════════════════════
function boot({ search = '', scale = 1, visualViewport = true } = {}) {
  const posted = [];
  const listeners = {};

  const makeEl = () => ({
    style: {}, textContent: '', innerHTML: '', className: '',
    parentNode: null, __slot: null, width: 0, height: 0,
    appendChild() {}, removeChild() {},
    getBoundingClientRect: () => ({ top: 0, bottom: 100 }),
    getContext: () => ({
      fillStyle: '',
      fillRect() {},
      getImageData: () => ({ data: [0, 0, 0, 255] }),
    }),
    addEventListener(t, f) { listeners[`el:${t}`] = f; },
  });

  const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    document: {
      getElementById: () => makeEl(),
      createElement: () => makeEl(),
      documentElement: { clientWidth: 390, clientHeight: 800 },
      addEventListener(t, f) { listeners[`doc:${t}`] = f; },
    },
    screen: { width: 390, height: 844 },
    navigator: { userAgent: 'stub', deviceMemory: 4, hardwareConcurrency: 8 },
    performance: { now: () => 1, getEntriesByType: () => [] },
    XMLHttpRequest: function XHR() { this.open = () => {}; this.send = () => {}; },
    IntersectionObserver: function IO() { this.observe = () => {}; this.disconnect = () => {}; },
    pdfjsLib: {
      GlobalWorkerOptions: {},
      OPS: {},
      getDocument: () => ({ promise: new Promise(() => {}) }),
    },
    // Bounded: the script schedules work on these and this test is not
    // interested in what happens later, only in the top level coming up.
    setTimeout: () => 0,
    setInterval: () => 0,
    clearInterval: () => {},
    Promise, Math, JSON, String, Number, Date, Object, RegExp, Array, Error,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  sandbox.window.location = { search };
  sandbox.window.devicePixelRatio = 3;
  sandbox.window.innerHeight = 800;
  sandbox.window.innerWidth = 390;
  sandbox.window.scrollTo = () => {};
  sandbox.window.addEventListener = (t, f) => { listeners[`win:${t}`] = f; };
  sandbox.window.removeEventListener = () => {};
  sandbox.window.ReactNativeWebView = {
    postMessage: (s) => { try { posted.push(JSON.parse(s)); } catch (_e) {} },
  };
  if (visualViewport) {
    sandbox.window.visualViewport = {
      scale,
      addEventListener(t, f) { listeners[`vv:${t}`] = f; },
    };
  }

  let threw = null;
  try {
    vm.createContext(sandbox);
    vm.runInContext(viewerScript(), sandbox, { filename: 'viewer.html' });
  } catch (e) { threw = e; }
  return { posted, listeners, threw, sandbox };
}

console.log('\nThe staged viewer actually runs\n');

// ═══════════════════════════════════════════════════════════════════════════
// 1. IT COMES UP.
// ═══════════════════════════════════════════════════════════════════════════
const run = boot();
ok(!run.threw, `the generated viewer script executes without throwing${
  run.threw ? ` — ${String(run.threw && run.threw.stack).split('\n')[0]}` : ''}`);

// ═══════════════════════════════════════════════════════════════════════════
// 2. THE HANDSHAKE, WHICH IS THE WHOLE DELIVERY MECHANISM.
//    The host holds the first document until it hears this. No announcement
//    means no document is ever sent and the viewer sits on "Loading…" — a
//    failure with no error anywhere to explain it.
// ═══════════════════════════════════════════════════════════════════════════
ok(run.posted.some((m) => m && m.type === 'pdf-viewer-ready'),
  'it announces pdf-viewer-ready so the host knows it can send a document');
ok(!!run.listeners['doc:message'] && !!run.listeners['win:message'],
  'and is already listening on BOTH document and window — react-native-webview '
  + 'delivers to document on Android and window on iOS');

// Ordering, not just presence: a listener registered after the announcement
// races the host's first post, and the loser is a document that is dropped
// silently. Re-run with the announcement intercepted to prove the listeners
// exist by the time it fires.
{
  const seen = { atAnnounce: false };
  const probe = boot();
  // The listeners are registered synchronously during the same run, so if the
  // announcement is in `posted` and the handlers are in `listeners`, the only
  // way to order them is to check that delivering immediately works.
  seen.atAnnounce = !!probe.listeners['doc:message'];
  ok(seen.atAnnounce,
    'the inbound handler exists by the end of boot, not on a later turn');
}

// ═══════════════════════════════════════════════════════════════════════════
// 3. NOTHING FAILS BEFORE A DOCUMENT ARRIVES.
//    The page is now mounted with no document at all — the old `?file=` guard
//    would have posted pdf-error and painted "Could not render this document"
//    on an empty viewer.
// ═══════════════════════════════════════════════════════════════════════════
ok(!run.posted.some((m) => m && m.type === 'pdf-error'),
  'a viewer with no document yet reports no error');

// ═══════════════════════════════════════════════════════════════════════════
// 4. A DOCUMENT CAN BE DELIVERED, AND A SECOND ONE AFTER IT.
//    The second is the one that matters: it runs resetDocument() against real
//    state rather than the empty first-open case.
// ═══════════════════════════════════════════════════════════════════════════
{
  let err = null;
  try {
    run.listeners['doc:message']({ data: JSON.stringify({ type: 'open-document', file: 'file:///a.pdf' }) });
    run.listeners['doc:message']({ data: JSON.stringify({ type: 'open-document', file: 'file:///b.pdf' }) });
  } catch (e) { err = e; }
  ok(!err, `two documents can be opened in a row without a navigation${err ? ` — ${err.message}` : ''}`);
}

// Junk on the channel must be ignored, not thrown on. This listener sees every
// postMessage the host makes, including any future unrelated one.
{
  let err = null;
  try {
    run.listeners['doc:message']({ data: 'not json at all' });
    run.listeners['doc:message']({ data: JSON.stringify({ type: 'something-else' }) });
    run.listeners['doc:message']({});
  } catch (e) { err = e; }
  ok(!err, `unparseable or unrelated messages are ignored${err ? ` — ${err.message}` : ''}`);
}

// ═══════════════════════════════════════════════════════════════════════════
// 5. THE ZOOM PATH RUNS.
// ═══════════════════════════════════════════════════════════════════════════
ok(!!run.listeners['vv:resize'],
  'it listens for pinch-zoom on the visual viewport');
{
  let err = null;
  try {
    run.sandbox.window.visualViewport.scale = 2;
    run.listeners['vv:resize']();
    run.listeners['vv:resize']();   // idempotent: goSharp must not re-run
  } catch (e) { err = e; }
  ok(!err, `a pinch past the threshold does not throw${err ? ` — ${err.message}` : ''}`);
}

// ═══════════════════════════════════════════════════════════════════════════
// 6. THE DEVICE THAT CANNOT REPORT ITS ZOOM STILL BOOTS.
//    This is the fail-toward-legible branch, and it is the one that runs on
//    the oldest System WebView in the field — exactly the device nobody tests.
// ═══════════════════════════════════════════════════════════════════════════
{
  const blind = boot({ visualViewport: false });
  ok(!blind.threw,
    `a WebView with no visualViewport still boots${
      blind.threw ? ` — ${String(blind.threw && blind.threw.stack).split('\n')[0]}` : ''}`);
  ok(blind.posted.some((m) => m && m.type === 'pdf-viewer-ready'),
    'and still announces itself');
}

// ═══════════════════════════════════════════════════════════════════════════
// 7. CAPS MODE RUNS AND STOPS.
//    The capability screen opens this page with ?caps=1 and no document, and
//    waits for the completion marker. Without it the screen cannot tell "still
//    running" from "this WebView answered nothing".
// ═══════════════════════════════════════════════════════════════════════════
{
  const caps = boot({ search: '?caps=1' });
  ok(!caps.threw,
    `caps mode executes without throwing${
      caps.threw ? ` — ${String(caps.threw && caps.threw.stack).split('\n')[0]}` : ''}`);
  const kinds = caps.posted.filter((m) => m && m.type === 'pdf-probe').map((m) => m.probe);
  ok(kinds.indexOf('boot') === 0,
    `caps mode reports the boot cost first (got: ${kinds.join(', ') || 'nothing'})`);
  ok(kinds.includes('env') && kinds.includes('canvas-lim'),
    'and the device measurements');
  // No document is opened, so nothing may be posted about one.
  ok(!caps.posted.some((m) => m && (m.type === 'pdf-ready' || m.type === 'pdf-error')),
    'and never touches a document');
}

// ═══════════════════════════════════════════════════════════════════════════
// 8. THE A/B SUITE RUNS ITS THREE SCALES TWICE, BACK TO BACK, SAME PAGE.
//
//    WHAT IS BEING SETTLED. The suite's numbers off the operator's device say
//    the FIRST render is the slowest and the LARGEST is not:
//
//        cur     over 1.5   1.2 MP  ->  2252 ms   (run first)
//        noOver  over 1.0   0.5 MP  ->   488 ms
//        ceil    headroom  11.2 MP  ->   727 ms   (9x the pixels, a third
//                                                  of the time)
//
//    Pixels cannot explain that. Either the first rasterisation of a page pays
//    a one-off cost the ones after it reuse — the warm-up theory, on which a
//    concurrency cap and a byte-bounded canvas cache are both about to be
//    built — or the suite is measuring something other than what it thinks.
//    A SECOND IDENTICAL PASS is the only reading that separates the two, and
//    it has to be a second pass IN THE SAME SESSION: a reload re-parses the
//    document and puts back whatever the first pass warmed.
//
//    WHY IT HAD TO EXECUTE. `pdfRenderProbe` parses this script and
//    `pdfjsViewerMemory` walks its AST; neither can tell whether a second
//    pass HAPPENS, in what order, or whether the two passes overlap. A
//    sequenced suite is the entire premise of the comparison — two renders
//    contending for one thread would put each other's time into each other's
//    number, which is the very bug the cap exists to fix — so "no two A/B
//    renders are ever in flight at once" is asserted here rather than assumed
//    from the comment that claims it.
//
//    WHAT THE SANDBOX IS. `boot()` above deliberately has no clock and no
//    timers, so nothing past the top level ever runs. `bootLive()` drives the
//    page to completion instead: a fake pdf.js, an XHR that answers, a timer
//    queue pumped in due order, and a performance.now() that advances with it.
//    Still no pixels — the render stub resolves on a timer — because what is
//    under test is the SHAPE of the suite, not a rasteriser.
// ═══════════════════════════════════════════════════════════════════════════

function bootLive({
  search = '?probe=1&file=file%3A%2F%2F%2Fplan.pdf',
  pages = 3,
  // How long a rasterisation takes on the fake clock. The default of 5 is
  // what section 8 has always used; the isolation cases below set it long
  // ENOUGH TO OUTLAST THE SUITE'S OWN 2000 ms DELAY, because that is the real
  // condition — on the operator's phone the band's sheets reported 5109 ms
  // and the suite started on top of them.
  slotRenderMs = 5,
  // ── WHICH WORKER THIS WEBVIEW CAN GIVE ────────────────────────────────
  //
  // 'real'     Worker, Blob and URL.createObjectURL all present — the Pixel 10
  //            Pro XL, where the operator's probe measured a blob worker doing
  //            page 1 in 618 ms.
  // 'none'     none of the three. The old System WebView, and the branch the
  //            viewer must FALL BACK on — loudly.
  worker = 'real',
  // ── PAGE GEOMETRY THE TEST CONTROLS ───────────────────────────────────
  //
  // 886 px sheets against an 883 px viewport is the operator's device, and it
  // is the geometry that makes "two sheets are partly on screen for most of a
  // scroll" true — which is the whole reason `visible` could never be the
  // thing `trim()` protects.
  pageH = 886,
  viewportH = 883,
  // ── CAN THIS WEBVIEW ENCODE A CANVAS ──────────────────────────────────
  //
  // The preview tier stores an ENCODED blob per page and keeps the raw bitmap
  // for no page at all, which is the only reason it can be held for all N
  // sheets at once. `canvas.toBlob` is how it gets there, `toDataURL` is the
  // fallback, and a WebView with neither leaves it holding raw canvases — a
  // real branch on a real device, so the harness can turn each one off.
  //
  // 'blob'    toBlob + URL.createObjectURL. The shipping path.
  // 'dataurl' toDataURL only.
  // 'none'    neither. The raw-canvas fallback, ~1.6 MB a sheet.
  encode = 'blob',
} = {}) {
  const posted = [];
  const listeners = {};
  const renders = [];
  const timers = [];
  const observers = [];
  const workersMade = [];
  const injectedScripts = [];
  let scrollTop = 0;
  // `renderMsFor` lets a case give each variant a DIFFERENT duration, which is
  // the only way to prove a median picks the middle value rather than the last
  // one it happened to see.
  const hooks = { renderMsFor: null };
  const marks = { drainAt: null, readyAt: null };
  let now = 0;
  let nextId = 1;
  let inFlight = 0;
  let maxInFlight = 0;

  function schedule(ms, fn) {
    const id = nextId; nextId += 1;
    timers.push({ id, at: now + (Number(ms) || 0), fn });
    return id;
  }

  // ── AN ELEMENT WITH A POSITION IN A SCROLLING DOCUMENT ──────────────────
  //
  // Every placeholder used to report the same rect, which made "nearest to the
  // viewport" a question with no answer and `trim()`'s protection rule
  // untestable. A page element now reports where it really is: page n starts
  // at (n-1) * pageH and the whole column moves with `scrollTop`. Canvases and
  // #msg carry no `__slot` and keep the old inert rect.
  // EVERY ELEMENT THE PAGE EVER CREATES, so the resident bitmap can be summed
  // off the canvases that really exist rather than inferred from the log.
  // `releaseSlot` zeroes width and height — that is the step that returns the
  // megabytes — so a freed canvas drops out of this sum by itself.
  const els = [];
  // WHAT AN ENCODED PREVIEW WOULD WEIGH. A stand-in for the shape only — the
  // real figure is a `Blob.size` off the device and travels in the page's own
  // `preview` / `preview-mem` rows. What matters here is that it is a fraction
  // of `w * h * 4` and that the page reads it off the object rather than
  // computing it, which is the property the storage decision rests on.
  const ENCODED_BYTES_PER_PX = 0.06;
  const makeEl = () => {
    const el = {
      style: {}, textContent: '', innerHTML: '', className: '', alt: '',
      parentNode: null, __slot: null, width: 0, height: 0,
      src: '', onload: null, onerror: null,
      // ── THE PLACEHOLDER NOW HOLDS TWO CHILDREN, NOT ONE ────────────────
      //
      // A `.pg` carries the preview <img> (class "pv", underneath, never
      // evicted) and the sharp <canvas> (on top, evictable). `__child` is
      // still THE SHARP CANVAS and nothing else, because that is what
      // `residentPages()` asks about; the preview is reachable through
      // `__kids` for the cases that ask whether it survived.
      __kids: [],
      appendChild(child) { el.__kids.push(child); el.__adopt(child); },
      insertBefore(child, ref) {
        const i = ref ? el.__kids.indexOf(ref) : -1;
        if (i >= 0) el.__kids.splice(i, 0, child); else el.__kids.push(child);
        el.__adopt(child);
      },
      __adopt(child) {
        if (!child) return;
        child.parentNode = el;
        if (child.className !== 'pv') el.__child = child;
      },
      removeChild(child) {
        const i = el.__kids.indexOf(child);
        if (i >= 0) el.__kids.splice(i, 1);
        if (child) child.parentNode = null;
      },
      getContext: () => ({
        fillStyle: '',
        fillRect() {},
        getImageData: () => ({ data: [0, 0, 0, 255] }),
      }),
      addEventListener(t, f) { listeners[`el:${t}`] = f; },
    };
    Object.defineProperty(el, 'firstChild', { get: () => el.__kids[0] || null });
    // ASYNCHRONOUS, like the real one. A `toBlob` that called back on the same
    // turn would hide an ordering bug the device would show — the slot's
    // generation can move between the render finishing and the encode landing.
    if (encode === 'blob') {
      el.toBlob = (cb, type, quality) => {
        const size = Math.round((el.width || 0) * (el.height || 0) * ENCODED_BYTES_PER_PX);
        schedule(0, () => cb({ size, type: type || '', quality }));
      };
    }
    if (encode === 'blob' || encode === 'dataurl') {
      // base64 is four characters per three bytes, so the string is longer
      // than the payload — which is exactly why the page prefers the blob.
      el.toDataURL = () => {
        const bytes = Math.round((el.width || 0) * (el.height || 0) * ENCODED_BYTES_PER_PX);
        return `data:image/jpeg;base64,${'A'.repeat(Math.max(64, Math.round(bytes * (4 / 3))))}`;
      };
    }
    el.getBoundingClientRect = () => {
      if (!el.__slot) return { top: 0, bottom: 100, height: 100 };
      const top = ((el.__slot.n - 1) * pageH) - scrollTop;
      return { top, bottom: top + pageH, height: pageH };
    };
    els.push(el);
    return el;
  };
  const residentPixels = () => els.reduce(
    (t, el) => t + ((Number(el.width) || 0) * (Number(el.height) || 0)), 0);
  // ── THE BUDGET IS THE SHARP TIER'S, AND ONLY THE SHARP TIER'S ──────────
  //
  // `CANVAS_BUDGET_MP` bounds what `trim()` can evict. A preview is held for
  // every page, outside the budget and on purpose, so summing both would make
  // the budget look busted by the design that fixes the bug. Class "pv" is the
  // page's own marker for the preview layer and is read off the element rather
  // than inferred from a size.
  const sharpPixels = () => els.reduce(
    (t, el) => t + (el.className === 'pv' ? 0
      : ((Number(el.width) || 0) * (Number(el.height) || 0))), 0);
  const residentPages = () => els
    .filter((el) => el.__slot && el.__child && Number(el.__child.width) > 0)
    .map((el) => el.__slot.n)
    .sort((a, b) => a - b);
  // Pages whose preview layer is attached to the placeholder and carries
  // something to paint — a src, or (on the no-encoder fallback) a live bitmap.
  const previewPages = () => els
    .filter((el) => el.__slot && el.__kids.some(
      (k) => k && k.className === 'pv' && (k.src || Number(k.width) > 0)))
    .map((el) => el.__slot.n)
    .sort((a, b) => a - b);
  // Sheets a reader would be looking at with NOTHING on them: on screen, no
  // preview layer, no live sharp canvas. The whole acceptance, as an integer.
  const blankOnScreen = () => els.filter((el) => {
    if (!el.__slot) return false;
    const r = el.getBoundingClientRect();
    const top = r.top > 0 ? r.top : 0;
    const bot = r.bottom < viewportH ? r.bottom : viewportH;
    if (bot <= top) return false;
    const hasPv = el.__kids.some((k) => k && k.className === 'pv' && (k.src || Number(k.width) > 0));
    const hasSharp = !!(el.__child && Number(el.__child.width) > 0);
    return !hasPv && !hasSharp;
  }).map((el) => el.__slot.n);

  // A 36x48" sheet in PDF user units (72/inch) — the document this viewer
  // exists for, and the one every measurement above was taken on.
  const PT_W = 2592;
  const PT_H = 3456;

  function makePage(n) {
    const page = {
      _n: n,
      cleanups: 0,
      getViewport({ scale }) {
        return { width: PT_W * scale, height: PT_H * scale, scale, __scale: scale };
      },
      getOperatorList() { return Promise.resolve({ fnArray: [], argsArray: [] }); },
      objs: { get() { return null; } },
      cleanup() { page.cleanups += 1; return true; },
      render(opts) {
        const scale = (opts && opts.viewport && opts.viewport.__scale) || 0;
        inFlight += 1;
        if (inFlight > maxInFlight) maxInFlight = inFlight;
        const rec = { page: n, scale, startedAt: now, endedAt: null, inFlightAtStart: inFlight,
          mp: Math.round(((PT_W * scale) * (PT_H * scale)) / 1e5) / 10 };
        renders.push(rec);
        const ms = hooks.renderMsFor ? hooks.renderMsFor(rec) : slotRenderMs;
        let cancelled = false;
        const promise = new Promise((resolve, reject) => {
          schedule(ms, () => {
            inFlight -= 1;
            rec.endedAt = now;
            if (cancelled) {
              const e = new Error('cancelled');
              e.name = 'RenderingCancelledException';
              reject(e);
            } else resolve();
          });
        });
        return { promise, cancel() { cancelled = true; rec.cancelled = true; } };
      },
    };
    return page;
  }

  const pageCache = {};
  const pdfStub = {
    numPages: pages,
    getPage(n) {
      if (!pageCache[n]) pageCache[n] = makePage(n);
      return Promise.resolve(pageCache[n]);
    },
    destroy() { return Promise.resolve(); },
  };

  // 64 bytes is enough for readBytes to accept it and for the filter scan to
  // run; the point is that the XHR ANSWERS, not what it answers with.
  const bodyBytes = new Uint8Array(64);

  function XHR() {
    this._url = '';
    this.responseType = '';
    this.response = null;
    this.responseText = '';
    this.onload = null;
    this.onerror = null;
    this.open = (m, u) => { this._url = u; };
    this.send = () => {
      schedule(1, () => {
        if (this.responseType === 'arraybuffer') this.response = bodyBytes.buffer;
        // LONG ENOUGH TO BE BELIEVED. The viewer refuses to build a Worker out
        // of a source read that came back short, because a Worker made from
        // half a file is a Worker that never answers — and a hang is worse
        // than the main-thread path it replaced. The real bundle is ~1.1 MB.
        else this.responseText = `/*worker*/${'x'.repeat(200000)}`;
        if (this.onload) this.onload();
      });
    };
  }

  // ── THE FALLBACK'S OWN MACHINERY ───────────────────────────────────────
  //
  // The page no longer carries a `<script src="pdf.worker.min.js">` tag, so
  // `globalThis.pdfjsWorker` does NOT exist at boot. The only way it can come
  // into being now is the viewer injecting that script itself, which is
  // exactly what the fallback does — so this stub defines the global at the
  // moment the injected script "loads", and not one instant earlier. A viewer
  // that never fell back therefore never sees the global at all, which is the
  // property section 13 turns on.
  const head = {
    appendChild(el) {
      injectedScripts.push(el);
      schedule(0, () => {
        // eslint-disable-next-line no-use-before-define
        sandbox.pdfjsWorker = { WorkerMessageHandler: {} };
        if (el.onload) el.onload();
      });
    },
  };

  const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    document: {
      getElementById: () => makeEl(),
      createElement: () => makeEl(),
      documentElement: { clientWidth: 390, clientHeight: viewportH },
      head,
      addEventListener(t, f) { listeners[`doc:${t}`] = f; },
    },
    screen: { width: 390, height: 844 },
    navigator: { userAgent: 'stub', deviceMemory: 4, hardwareConcurrency: 8 },
    performance: { now: () => now, getEntriesByType: () => [] },
    XMLHttpRequest: XHR,
    // AN OBSERVER THAT RECORDS RATHER THAN SWALLOWS. It still fires nothing on
    // its own — `deliverIO()` is the only thing that delivers a batch — so
    // every case above, which never calls it, behaves exactly as it did when
    // this was a no-op stub and no slot render ever happened.
    //
    // THE OPTIONS ARE KEPT because the page's own `rootMargin` is the band,
    // and a geometric delivery that invented its own margin would be testing
    // the harness rather than the viewer.
    IntersectionObserver: function IO(cb, opts) {
      const io = this;
      io.cb = cb;
      io.opts = opts || {};
      io.els = [];
      io.live = true;
      io.observe = (el) => { io.els.push(el); };
      io.disconnect = () => { io.live = false; io.els = []; };
      observers.push(io);
    },
    pdfjsLib: {
      GlobalWorkerOptions: {},
      OPS: { paintImageXObject: 1, paintJpegXObject: 2, paintImageMaskXObject: 3 },
      // THE WORKER PATH THIS STUB REPRESENTS is the one the device really
      // runs: `pdf.worker.min.js` defines `globalThis.pdfjsWorker` before
      // pdf.js loads, so pdf.js never constructs a real Worker. The stub says
      // so, because the viewer is about to be asked to report it.
      getDocument: () => ({ promise: Promise.resolve(pdfStub), _worker: { _webWorker: null } }),
    },
    setTimeout: (fn, ms) => schedule(ms, fn),
    clearTimeout: () => {},
    // THE HEARTBEAT IS RECORDED AND NEVER FIRED, deliberately. It re-arms
    // every 16 ms for the life of the open; a pump that honoured it would
    // never reach the suite it was written to observe. hbStop() still gets a
    // truthy id to clear, so the uithread post still happens.
    setInterval: () => { const id = nextId; nextId += 1; return id; },
    clearInterval: () => {},
    Promise, Math, JSON, String, Number, Date, Object, RegExp, Array, Error,
    Uint8Array, ArrayBuffer, Boolean, isNaN, parseInt, parseFloat,
  };
  // ── WHAT THIS WEBVIEW WILL GIVE A WORKER ───────────────────────────────
  //
  // Present together or absent together, because that is how a WebView is: the
  // operator's device answered yes to all three (`blob workers ARE supported`,
  // measured), and the old builds answer no to all three. A half-capable
  // sandbox would be testing a device that does not exist.
  // ── OBJECT URLs BELONG TO BOTH FEATURES, SO THEY ARE THEIR OWN SWITCH ──
  //
  // `URL.createObjectURL` is how the worker is built from a blob AND how a
  // preview is held. Leaving it tied to `worker` alone would have made
  // `encode: 'blob'` silently untestable on the fallback WebView and, worse,
  // made the default case pass for a reason that had nothing to do with the
  // tier under test.
  const objectUrls = { made: [], revoked: [] };
  if (worker === 'real' || encode === 'blob') {
    sandbox.Blob = function BlobStub(parts, opts) {
      this.parts = parts;
      this.type = (opts && opts.type) || '';
      this.size = (parts || []).reduce((t, p) => t + String(p).length, 0);
    };
    sandbox.URL = {
      createObjectURL(b) {
        const u = `blob:stub-${(b && b.size) || 0}-${objectUrls.made.length}`;
        objectUrls.made.push(u);
        return u;
      },
      revokeObjectURL(u) { objectUrls.revoked.push(u); },
    };
  }
  if (worker === 'real') {
    sandbox.Worker = function WorkerStub(url) {
      const w = this;
      w.url = url;
      w.onerror = null;
      w.onmessage = null;
      w.terminate = () => { w.terminated = true; };
      w.postMessage = () => {};
      w.addEventListener = () => {};
      w.removeEventListener = () => {};
      workersMade.push(w);
    };
  }

  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  sandbox.window.location = { search };
  sandbox.window.devicePixelRatio = 3;
  sandbox.window.innerHeight = viewportH;
  sandbox.window.innerWidth = 390;
  // `pageYOffset` MOVES WITH IT. The page reads it to turn a placeholder's
  // rect into an absolute scroll target, and a sandbox that never defined it
  // would make every `scrollTo` land on the same place — which looks exactly
  // like a viewer that ignores the scroll.
  sandbox.pageYOffset = 0;
  sandbox.window.scrollTo = (x, y) => {
    scrollTop = Number(y) || 0;
    sandbox.pageYOffset = scrollTop;
    const onScroll = listeners['win:scroll'];
    if (onScroll) { try { onScroll(); } catch (e) { threw = threw || e; } }
  };
  sandbox.window.addEventListener = (t, f) => { listeners[`win:${t}`] = f; };
  sandbox.window.removeEventListener = () => {};
  sandbox.window.ReactNativeWebView = {
    postMessage: (s) => {
      let m = null;
      try { m = JSON.parse(s); } catch (_e) { return; }
      posted.push(m);
      // STAMPED WITH THE FAKE CLOCK, because "the queue was empty" is a claim
      // about a MOMENT and the posts themselves carry no time.
      if (m && m.type === 'pdf-ready' && marks.readyAt === null) marks.readyAt = now;
      if (m && m.type === 'pdf-probe' && m.probe === 'drain' && marks.drainAt === null) marks.drainAt = now;
    },
  };
  sandbox.window.visualViewport = {
    scale: 1,
    addEventListener(t, f) { listeners[`vv:${t}`] = f; },
  };

  let threw = null;
  try {
    vm.createContext(sandbox);
    vm.runInContext(viewerScript(), sandbox, { filename: 'viewer.html' });
  } catch (e) { threw = e; }

  // EVERYTHING INTERSECTS, which is the worst case for the ordering bug and
  // what an initial observation of a short document really looks like.
  function deliverIO() {
    const io = observers.filter((o) => o.live).pop();
    if (!io) return 0;
    const entries = io.els.map((el) => ({ target: el, isIntersecting: true }));
    io.cb(entries);
    return entries.length;
  }

  // ── THE SAME CALLBACK, BUT TOLD THE TRUTH ABOUT WHERE THE PAGES ARE ────
  //
  // An initial observation of a 26-sheet plan does NOT report 26 intersecting
  // pages: the observer honours its own rootMargin, and the page asked for one
  // built out of `band()`. Delivering with the real geometry is the only way
  // to test what the band actually admits — and the margin is read off the
  // observer the page constructed, never invented here.
  function deliverIOGeo() {
    const io = observers.filter((o) => o.live).pop();
    if (!io) return { delivered: 0, intersecting: [] };
    const m = /^(-?[\d.]+)%/.exec(String((io.opts && io.opts.rootMargin) || '0px'));
    const margin = m ? (parseFloat(m[1]) / 100) * viewportH : 0;
    const entries = io.els.map((el) => {
      const r = el.getBoundingClientRect();
      return { target: el, isIntersecting: r.bottom > -margin && r.top < viewportH + margin };
    });
    io.cb(entries);
    return {
      delivered: entries.length,
      intersecting: entries.filter((e) => e.isIntersecting)
        .map((e) => e.target.__slot && e.target.__slot.n),
    };
  }

  // ── A TELEPORT, OR A SCROLL ───────────────────────────────────────────
  //
  // `fire` is not a convenience. Without it this moves the column and tells
  // the page nothing, which is what every case written before the settle gate
  // existed assumes — and changing that silently would have altered what
  // sections 13 and 14 were measuring. With it, the page hears the event a
  // thumb would produce, which is the only way to test a gate that exists to
  // notice the scroll STOPPING.
  function scrollTo(y, fire) {
    scrollTop = Number(y) || 0;
    sandbox.pageYOffset = scrollTop;
    if (!fire) return;
    const onScroll = listeners['win:scroll'];
    if (onScroll) { try { onScroll(); } catch (e) { threw = threw || e; } }
  }

  // Drain: give the event loop a turn, settle microtasks, then fire the
  // earliest due timer, and repeat.
  //
  // THE setImmediate IS NOT DECORATION. A vm context keeps V8's own built-ins,
  // so `WebAssembly` is real in there — and `WebAssembly.instantiate` settles
  // on a FOREGROUND TASK, not a microtask. A pump that only awaited
  // `Promise.resolve()` stalled the capability chain forever on `probeWasm`
  // and never reached the suite it was written to observe.
  //
  // And it does not stop the moment the queue empties: work in flight can
  // schedule the next timer a turn later, so it takes several idle passes in
  // a row to call it done.
  async function pump(maxSteps = 5000) {
    let idle = 0;
    for (let step = 0; step < maxSteps; step += 1) {
      await new Promise((r) => setImmediate(r));
      for (let k = 0; k < 12; k += 1) await Promise.resolve();
      if (!timers.length) {
        idle += 1;
        if (idle > 4) break;
        continue;
      }
      idle = 0;
      timers.sort((a, b) => (a.at - b.at) || (a.id - b.id));
      const t = timers.shift();
      if (t.at > now) now = t.at;
      try { t.fn(); } catch (e) { threw = threw || e; }
    }
  }

  // Stop at a MOMENT rather than at exhaustion. `pump()` runs the clock to the
  // end, which is no use when the thing under test is what the page does while
  // work is still in flight.
  //
  // ⚠️ THE PREDICATE IS CHECKED AFTER THE MICROTASKS SETTLE AND BEFORE THE NEXT
  // TIMER FIRES, and the order is the whole correctness of this function. With
  // the check at the TOP of the loop instead, an iteration that satisfies the
  // predicate during its microtask drain STILL went on to fire a timer — so
  // `pumpUntil(pdf-ready)` could return with the suite's 2000 ms timer already
  // run. That is not hypothetical: it passed locally and failed on CI, where
  // the only timer left at that moment WAS the suite's, and the drain therefore
  // happened before the case had delivered a single page to the observer. The
  // rows came back `inflight: 0, pending: 6` — the queue technically empty,
  // for entirely the wrong reason.
  //
  // Checking after the drain and before the fire makes "stop the instant this
  // becomes true" mean what it says, on any machine.
  async function pumpUntil(pred, maxSteps = 5000) {
    for (let step = 0; step < maxSteps; step += 1) {
      await new Promise((r) => setImmediate(r));
      for (let k = 0; k < 12; k += 1) await Promise.resolve();
      if (pred()) return true;
      if (!timers.length) continue;
      timers.sort((a, b) => (a.at - b.at) || (a.id - b.id));
      const t = timers.shift();
      if (t.at > now) now = t.at;
      try { t.fn(); } catch (e) { threw = threw || e; }
    }
    return pred();
  }

  return { posted, listeners, renders, sandbox, pump, pumpUntil, deliverIO, deliverIOGeo,
    scrollTo, hooks, marks, workersMade, injectedScripts, residentPixels, residentPages,
    sharpPixels, previewPages, blankOnScreen, objectUrls, els,
    pageH, viewportH,
    get now() { return now; },
    get threw() { return threw; },
    get maxInFlight() { return maxInFlight; } };
}

/** Rows of one probe kind, in the order the page posted them. */
function probeData(posted, kind) {
  return posted.filter((m) => m && m.type === 'pdf-probe' && m.probe === kind).map((m) => m.data);
}

async function main() {
  console.log('\n── the A/B suite runs its three scales three times ────────────\n');

  const live = bootLive();
  await live.pump();

  ok(!live.threw, `the viewer drives a whole probe session without throwing${
    live.threw ? ` — ${String(live.threw && live.threw.stack).split('\n')[0]}` : ''}`);

  const probes = live.posted.filter((m) => m && m.type === 'pdf-probe');
  ok(probes.some((m) => m.probe === 'suite' && m.data && m.data.done === true),
    'the suite reaches its completion marker — the harness really ran it '
    + `(saw: ${probes.map((m) => m.probe).join(', ') || 'nothing'})`);

  const ab = probes.filter((m) => m.probe === 'render-ab').map((m) => m.data);
  const withPass = ab.filter((d) => d && d.pass >= 1 && d.pass <= 3);

  // THREE RUNS, NOT TWO. Two readings of the same variant have no middle: if
  // they disagree there is nothing to prefer, and a mean of two is dragged the
  // whole way by one outlier. Three is the smallest count with a median, and
  // the median is the statistic a first-run warm-up cost cannot move.
  for (const pass of [1, 2, 3]) {
    ok(withPass.filter((d) => d.pass === pass).length === 3,
      `pass ${pass} runs all three scales (got ${withPass.filter((d) => d.pass === pass).length})`);
  }

  // ORDER. The claim under test is "the first render of a page is the
  // expensive one", so each pass must come AFTER the last and repeat the same
  // three in the same sequence. A shuffled or interleaved pass would answer a
  // different question.
  ok(withPass.length === 9
    && withPass.slice(0, 3).every((d) => d.pass === 1)
    && withPass.slice(3, 6).every((d) => d.pass === 2)
    && withPass.slice(6).every((d) => d.pass === 3),
    `the nine A/B renders are pass 1 then 2 then 3, not interleaved (got: ${
      withPass.map((d) => d.pass).join(',') || 'none'})`);

  // LIKE FOR LIKE. A pass that rendered different scales would not be a repeat
  // of the first at all.
  const p1 = withPass.filter((d) => d.pass === 1).map((d) => d.scale);
  const p2 = withPass.filter((d) => d.pass === 2).map((d) => d.scale);
  const p3 = withPass.filter((d) => d.pass === 3).map((d) => d.scale);
  ok(p1.length === 3 && p2.length === 3 && p3.length === 3
    && p1.every((s, i) => s === p2[i] && s === p3[i]),
    `every pass repeats pass 1's exact scales (p1=${p1.join('/')} p2=${p2.join('/')} p3=${p3.join('/')})`);

  // ── AND THE THREE ARE ACTUALLY THREE ──────────────────────────────────
  //
  // THIS WOULD HAVE GONE SILENT. The low variant was `targetScaleInfo(vp1,
  // 1.0)` — the viewport OVERSAMPLE turned down. With the ppi floor
  // unconditional again the floor term wins on a large sheet and the edge
  // clamp binds every variant, so all three collapsed onto one scale and the
  // suite went on reporting nine rows that looked like an A/B and were three
  // identical renders repeated. The low variant now asks for the viewport
  // anchor explicitly, and this is the check that keeps it honest.
  ok(new Set(p1).size >= 2,
    `the variants really do span more than one scale — an A/B of one scale is `
    + `worse than none (${p1.join(' / ')})`);
  {
    const mps = withPass.filter((d) => d.pass === 1).map((d) => d.megapixels);
    ok(Math.max(...mps) / Math.min(...mps) >= 5,
      `spanning an order of magnitude in pixels, which is what a "does this set `
      + `scale with pixels" reading needs (${mps.join(' / ')} MP)`);
    // ── AND THE HEADROOM VARIANT NOW READS THE SAME AS THE SHIPPING ONE ──
    //
    // NOT A BUG. `cap-ceiling` was written when the shipping scale was
    // viewport-anchored and 11 of the 16 budgeted megapixels were never used —
    // it existed to put a time against that unused headroom. With the ppi
    // floor unconditional the shipping render is ALREADY on the edge clamp, so
    // there is no headroom left and the two coincide. Asserting the identity
    // records that rather than leaving a future reader to wonder why two rows
    // of a three-way comparison match.
    ok(p1[0] === p1[2],
      `and the shipping scale now sits ON the cap ceiling, so the headroom the `
      + `probe was written to measure is gone (shipping ${p1[0]}, ceiling ${p1[2]})`);
  }

  // And the same page, or it is not a repeat reading.
  ok(withPass.length === 9 && withPass.every((d) => d.page === 1),
    'all three passes render the same page');

  // DISTINGUISHABLE IN THE LOG. PDFViewer.native.jsx dumps `label` verbatim
  // into the shareable probe log; two identically-labelled rows would be
  // unreadable in exactly the artefact the operator sends back.
  const labels = withPass.map((d) => d.label);
  ok(new Set(labels).size === 9,
    `all nine rows carry a distinct label (${labels.join(' | ')})`);

  // ── AND EVERY ONE OF THEM SAYS THE QUEUE WAS EMPTY ─────────────────────
  //
  // THE ROWS BEFORE THIS CHANGE WERE WORTHLESS AND NOTHING SAID SO. The suite
  // starts 2000 ms after `pdf-ready` while the band's own sheets are still
  // rasterising — on the operator's phone they reported 5109 ms — so every
  // variant's wall clock contained the queue's wait and the three numbers were
  // being compared to each other through a shared, moving contention term.
  //
  // A FUTURE READER MUST BE ABLE TO SEE THAT IT WAS ISOLATED, not take it on
  // trust from a comment in a file they do not have open, which is why the
  // claim rides in the row itself rather than in the suite's own sequencing.
  //
  // ⚠️ THE CLAIM IS `inflight: 0` PLUS `suspended: true`, AND `pending: 0` HAS
  // BEEN DROPPED FROM IT. `pending` used to read 0 for a reason that was not
  // the reason anyone thought: the old render path started every in-band sheet
  // immediately and uncapped, so nothing was ever waiting and the field was
  // structurally 0 whatever the suite did. With a queue behind a cap of one,
  // sheets legitimately SIT in it — five of them in the case below — and they
  // are not contention, because `pumpQueue` starts nothing while `abSuspend`
  // is set. `suspended` is the field that says so, and asserting it is
  // strictly stronger than asserting a count that could only ever be zero.
  ok(withPass.length === 9
    && withPass.every((d) => d.inflight === 0 && d.suspended === true),
    `every A/B row states nothing was running, and nothing could start (got: ${
      withPass.map((d) => `${d.inflight} inflight/${d.pending} queued/susp=${d.suspended}`)
        .join(' ') || 'no field at all'})`);

  // SEQUENCED, WHICH IS THE PREMISE. Two rasterisations sharing a thread each
  // contain the other's time — the exact defect the render cap is being
  // written for — so an A/B that overlapped would be measuring contention and
  // calling it warm-up.
  ok(live.maxInFlight === 1,
    `no two renders are ever in flight at once (peak ${live.maxInFlight})`);

  console.log('\n── the median, and the three raw values it came from ──────────\n');

  // ═════════════════════════════════════════════════════════════════════════
  // 9. A MEDIAN, WITH ITS WORKING SHOWN.
  //
  //    Three runs are only worth taking if the summary is the MIDDLE one. A
  //    "median" that is really the last value, or the mean, would hide exactly
  //    the thing three runs were taken to expose — a first-run cost that lands
  //    on one reading and not the other two.
  //
  //    So the durations are made DIFFERENT PER PASS here. With every run the
  //    same length (which is what the default stub gives) `median === last ===
  //    mean` and the assertion would pass on any of the three implementations.
  // ═════════════════════════════════════════════════════════════════════════
  {
    // Per variant, in pass order: 30, 10, 20 ms. Median 20, mean 20 — no: mean
    // is 20 as well, so the durations are chosen so the three candidates
    // differ. 30/10/26: median 26, mean 22, last 26. Still ambiguous against
    // "last". 30/10/20 gives median 20 and last 20 too.
    //
    // THE ONE ORDERING THAT SEPARATES ALL THREE is largest last:
    //   runs 12, 30, 60  ->  median 30, mean 34, last 60, first 12.
    const seq = [12, 30, 60];
    const s = bootLive();
    // ⚠️ KEYED ON THE A/B'S OWN SEQUENCE, NOT ON THE SCALE.
    //
    // It used to count occurrences per scale, which worked only while the
    // three variants HAD three different scales. They no longer do on a large
    // sheet: with the PPI floor back on at first paint, `targetScaleInfo(vp1,
    // 1.5)`, `targetScaleInfo(vp1, 1.0)` and `ceilingScaleInfo(vp1)` all land
    // on the same MAX_CANVAS_EDGE clamp for a 36x48 drawing, so a per-scale
    // counter sees one bucket and hands every variant the same duration.
    //
    // (That collapse is itself worth knowing and is a REAL finding about the
    // A/B on large sheets — it is not a harness artefact. It is recorded here
    // rather than worked around silently.)
    //
    // The suite renders variants in a fixed order, three per pass, and only
    // after the drain. So the pass number is the index over three, and the
    // duration is chosen from that — which is what makes each variant's three
    // runs 12 / 30 / 60 in pass order.
    let abIndex = 0;
    s.hooks.renderMsFor = () => {
      if (s.marks.drainAt === null) return 5;     // the band's own sheets
      const pass = Math.floor(abIndex / 3);
      abIndex += 1;
      return seq[Math.min(pass, seq.length - 1)];
    };
    await s.pump();

    const med = probeData(s.posted, 'render-ab-median');
    ok(med.length === 3,
      `one median row per variant (got ${med.length}: ${med.map((d) => d && d.variant).join(', ') || 'none'})`);

    ok(med.length === 3 && med.every((d) => Array.isArray(d.runs) && d.runs.length === 3),
      'each median row carries the three raw values it was computed from');

    // THE RAW VALUES ARE IN PASS ORDER, not sorted. Sorted raws would throw
    // away the only thing that says WHICH run was the slow one — which is the
    // entire warm-up question.
    ok(med.length === 3 && med.every((d) => String(d.runs) === String(seq)),
      `the raw values are in pass order, not sorted (got ${
        med.map((d) => `[${(d.runs || []).join(',')}]`).join(' ') || 'none'})`);

    ok(med.length === 3 && med.every((d) => d.medianMs === 30),
      `the median is the middle value and not the last or the mean `
      + `(runs 12/30/60 -> wanted 30, got ${med.map((d) => d.medianMs).join(', ') || 'nothing'})`);

    ok(med.length === 3 && med.every((d) => d.minMs === 12 && d.maxMs === 60),
      'and the spread is reported beside it');

    // The variant has to be nameable, or three rows of numbers mean nothing.
    ok(med.length === 3 && new Set(med.map((d) => d.variant)).size === 3
      && med.every((d) => typeof d.scale === 'number' && typeof d.megapixels === 'number'),
      `each median row names its variant and its size (${
        med.map((d) => `${d.variant}@${d.megapixels}MP`).join(' | ')})`);
  }

  console.log('\n── layout() is timed per page, not just in total ──────────────\n');

  // ═════════════════════════════════════════════════════════════════════════
  // 10. WHAT `layout()` COSTS, PAGE BY PAGE.
  //
  //     `layout()` chains `doc.getPage(n)` for EVERY page before anything is
  //     rendered — on a 26-sheet plan that is 26 sequential page parses on the
  //     main thread, purely to read `getViewport({scale:1})` for placeholder
  //     sizing. It has been the leading suspect for the open stall, and the
  //     total alone cannot settle it: a layout that is slow because of ONE bad
  //     page and one that is slow because all 26 cost the same are different
  //     defects with different fixes.
  //
  //     `layoutMs` on its own has been emitted since the first probe round.
  //     The per-page split has not, and it is the half that says which.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const s = bootLive({ pages: 7 });
    await s.pump();
    const lay = probeData(s.posted, 'layout')[0];
    ok(!!lay, 'the layout cost is reported at all');
    ok(!!lay && lay.numPages === 7,
      `and says how many pages it walked (got ${lay && lay.numPages})`);
    ok(!!lay && Array.isArray(lay.perPageGetPageMs) && lay.perPageGetPageMs.length === 7,
      `with one getPage reading per page (got ${
        lay && Array.isArray(lay.perPageGetPageMs) ? lay.perPageGetPageMs.length : 'no array'})`);
    ok(!!lay && typeof lay.getPageMedianMs === 'number'
      && typeof lay.getPageMinMs === 'number' && typeof lay.getPageMaxMs === 'number',
      'and min / median / max beside it, so one bad page can be told from 26 equal ones');
    // The parts cannot exceed the whole, or the split is measuring something
    // other than the function it claims to be inside.
    ok(!!lay && typeof lay.getPageTotalMs === 'number' && typeof lay.sizeTotalMs === 'number'
      && (lay.getPageTotalMs + lay.sizeTotalMs) <= lay.layoutMs + 1,
      `the per-page parts add up inside the total (getPage ${lay && lay.getPageTotalMs} + `
      + `sizing ${lay && lay.sizeTotalMs} <= layout ${lay && lay.layoutMs})`);

    // AND THE ANSWER HAS TO BE READABLE IN ONE ROW. `open.totalMs` already
    // contains layout; carrying `layoutMs` beside it is what lets a reader see
    // the share without cross-referencing two posts from a phone screenshot.
    const open = probeData(s.posted, 'open')[0];
    ok(!!open && typeof open.layoutMs === 'number' && typeof open.totalMs === 'number',
      `the open row carries the layout share beside the total (got ${
        open ? `${open.layoutMs} of ${open.totalMs}` : 'no open row'})`);
    ok(!!open && open.layoutMs <= open.totalMs,
      'and layout is inside the open, which is what makes the share meaningful');
  }

  console.log('\n── which worker is actually live, said by the running code ────\n');

  // ═════════════════════════════════════════════════════════════════════════
  // 11. THE WORKER PATH, STATED RATHER THAN INFERRED.
  //
  //     The file's comment used to say the `<script src="pdf.worker.min.js">`
  //     tag defines `globalThis.pdfjsWorker` and that pdf.js therefore skips
  //     the real-Worker attempt and rasterises on the main thread. EVERY
  //     PERFORMANCE CONCLUSION IN THIS FILE RESTED ON THAT, and nothing ever
  //     checked it — until the operator's probe did, and reported
  //     `workerpath verdict: FAKE` on a device where a blob worker does page 1
  //     in 618 ms.
  //
  //     THE READING STILL HAS TO BE HONEST NOW THAT THE ANSWER IS SUPPOSED TO
  //     BE "REAL". `_initializeFromPort` — the branch pdf.js takes when it is
  //     handed a `workerPort` — never assigns `_worker._webWorker`, so the old
  //     verdict logic reads null off a genuinely off-thread document and calls
  //     it FAKE. The stub below models exactly that, which is what makes this
  //     case worth running.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const s = bootLive();
    await s.pump();
    const wp = probeData(s.posted, 'workerpath')[0];
    ok(!!wp, 'the viewer reports which worker path is live');
    // BEFORE `getDocument`, which is the only moment the answer is decided.
    // Read afterwards it proves nothing: pdf.js may have defined things itself.
    // FALSE is now the correct answer: the page carries no worker <script>.
    ok(!!wp && wp.globalWorkerDefinedBeforeGetDocument === false,
      `and says whether globalThis.pdfjsWorker existed BEFORE getDocument (got ${
        wp && wp.globalWorkerDefinedBeforeGetDocument})`);
    ok(!!wp && wp.mode === 'real',
      `and which worker the page itself set up (got ${JSON.stringify(wp && wp.mode)})`);
    ok(!!wp && typeof wp.verdict === 'string' && /^REAL/.test(wp.verdict),
      `and names the path in words a reader can act on (got ${JSON.stringify(wp && wp.verdict)})`);
    // THE TRAP, ASSERTED. `_webWorker` is null on the port path; a verdict
    // that still read it would report FAKE on a working real worker, and the
    // whole acceptance criterion would be scored against the wrong field.
    ok(!!wp && wp.taskWebWorker === 'null' && /^REAL/.test(wp.verdict),
      `the verdict does not come from task._worker._webWorker, which is null on `
      + `the workerPort path (got webWorker=${wp && wp.taskWebWorker}, verdict=${
        JSON.stringify(wp && wp.verdict)})`);
  }

  console.log('\n── the suite waits for the queue to empty ─────────────────────\n');

  // ═════════════════════════════════════════════════════════════════════════
  // 12. THE ISOLATION ITSELF, WITH REAL CONTENTION TO ISOLATE FROM.
  //
  //     Asserting `inflight: 0` on a harness where no slot render ever happens
  //     asserts nothing — the field would read 0 on a viewer that never
  //     drained anything. So this case puts a slot render in flight that
  //     outlasts the suite's own 2000 ms delay, which is the condition on the
  //     operator's phone: the suite started on top of the band and every
  //     variant's number contained the wait.
  //
  //     ⚠️ IT USED TO PUT SIX IN FLIGHT AT ONCE, AND IT CANNOT ANY MORE. That
  //     was the defect: the band handed over six pages and six rasterisations
  //     started on one thread. `MAX_CONCURRENT_RENDERS = 1` makes six
  //     concurrent slot renders unreachable BY CONSTRUCTION, so the count this
  //     case can assert is 1 — and the six still being QUEUED is what the
  //     `deferred` field says instead.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const s = bootLive({ pages: 6, slotRenderMs: 5000 });
    // Run only as far as the document being open. The suite's timer is armed
    // at this moment and is 2000 ms away.
    await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-ready'));
    const delivered = s.deliverIO();
    ok(delivered === 6,
      `the band really does hand over a crowd (${delivered} pages in one callback)`);

    // ⚠️ THE RENDER MUST ACTUALLY BE RUNNING BEFORE THE SUITE IS LET NEAR IT.
    // `renderSlot` starts on a microtask (it waits for `doc.getPage`), so
    // immediately after `deliverIO()` nothing is in flight yet. Handing
    // straight to `pump()` from here lets the clock jump to the suite's 2000 ms
    // timer with the queue still empty — which is precisely the CI failure the
    // note on `pumpUntil` describes, and it makes the whole case pass for the
    // wrong reason. This settles the microtasks WITHOUT advancing the clock,
    // and says so out loud rather than assuming it worked.
    await s.pumpUntil(() => s.renders.length >= 1);
    ok(s.renders.length >= 1,
      `and a sheet is really in flight before the suite is due (${s.renders.length} started, `
      + `clock at ${s.now} ms of the 2000 the suite waits)`);
    ok(s.renders.length === 1,
      `and only ONE — six pages arrived, one rasterisation started (${s.renders.length})`);
    ok(s.now < 2000,
      `with the suite's timer still ahead of us, not behind (clock ${s.now} ms)`);

    await s.pump();

    ok(!s.threw, `the viewer survives a suite that had to wait${
      s.threw ? ` — ${String(s.threw && s.threw.stack).split('\n')[0]}` : ''}`);

    const drain = probeData(s.posted, 'drain')[0];
    ok(!!drain, 'the suite says out loud that it drained the queue first');
    // THERE WAS SOMETHING TO DRAIN. Without this the case would pass on a
    // viewer that drained nothing because nothing was running.
    // ONE IS THE MOST THERE CAN BE now that the cap is 1, and the QUEUE
    // behind it is the other half of "there was something to drain" — six
    // pages arrived, one was running and the rest were waiting.
    ok(!!drain && drain.inflightAtStart >= 1,
      `and there really was contention to drain (${drain && drain.inflightAtStart} renders in flight)`);
    ok(!!drain && typeof drain.deferred === 'number',
      `and says how many sheets were left waiting behind it (${drain && drain.deferred})`);
    ok(!!drain && drain.drained === true && drain.waitedMs > 0,
      `and it waited for them rather than measuring through them (waited ${drain && drain.waitedMs} ms)`);

    // THE STRUCTURAL PROOF, independent of the field the page emits about
    // itself: from the moment the drain completed, no rasterisation ever
    // started while another was running.
    // `drainAt` NULL IS A FAILURE, not a permissive filter. Compared with
    // null every render is "after the drain" and this case would go green on a
    // viewer that never drained at all.
    const after = s.marks.drainAt === null
      ? [] : s.renders.filter((r) => r.startedAt >= s.marks.drainAt);
    ok(s.marks.drainAt !== null && after.length >= 9,
      `the suite's own renders all fall after the drain (${after.length} of ${s.renders.length}${
        s.marks.drainAt === null ? '; no drain was ever posted' : ''})`);
    ok(after.length > 0 && after.every((r) => r.inFlightAtStart === 1),
      `and each one started alone (peaks: ${[...new Set(after.map((r) => r.inFlightAtStart))].join(',')})`);

    // AND THE ROWS SAY SO. Same claim, from the page's own mouth, which is
    // what a reader of the shared log actually has.
    const rows = probeData(s.posted, 'render-ab').filter((d) => d && d.pass);
    ok(rows.length === 9 && rows.every((d) => d.inflight === 0 && d.suspended === true),
      `all nine rows report nothing running and the path suspended (got ${
        rows.map((d) => `${d.inflight}/susp=${d.suspended}`).join(' ') || 'nothing'})`);
    // AND THE QUEUE REALLY DID HAVE SHEETS IN IT while they ran, which is what
    // makes `suspended` load-bearing rather than decorative.
    ok(rows.length === 9 && rows.every((d) => d.pending > 0),
      `with sheets genuinely waiting behind the suspension (queued: ${
        [...new Set(rows.map((d) => d.pending))].join(',')})`);

    // THE VIEWER IS HANDED BACK. A suspension that is never lifted is a viewer
    // that stops drawing pages for the rest of the session — a far worse bug
    // than the measurement error being fixed.
    const resumed = probeData(s.posted, 'resume')[0];
    ok(!!resumed && resumed.suspended === false,
      `the normal render path is switched back on afterwards (${JSON.stringify(resumed)})`);
  }

  // ── AND NONE OF IT HAPPENS WITH THE FLAG OFF ───────────────────────────
  // The probe is inert unless `probe=1`. Three passes is half again the
  // suite's old cost, and a drain that suspended the render path for a reader
  // who is not being measured would be a defect and not a measurement, so
  // this is the assertion that keeps all of it off everybody else.
  {
    const off = bootLive({ search: '?file=file%3A%2F%2F%2Fplan.pdf' });
    await off.pump();
    ok(!off.threw, `a normal open still runs clean${
      off.threw ? ` — ${String(off.threw && off.threw.stack).split('\n')[0]}` : ''}`);
    ok(!off.posted.some((m) => m && m.type === 'pdf-probe'),
      'with the flag off the viewer posts no probe readings at all');
    ok(off.posted.some((m) => m && m.type === 'pdf-ready'),
      'and still opens the document');
  }

  // AND THE SHIPPING RENDER PATH IS NEVER SUSPENDED FOR A READER WHO IS NOT
  // BEING MEASURED. With the flag off the band must rasterise exactly as it
  // always did — this is the one that would catch a drain gate left ungated.
  {
    const off = bootLive({ search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 6, slotRenderMs: 5000 });
    await off.pumpUntil(() => off.posted.some((m) => m && m.type === 'pdf-ready'));
    off.deliverIO();
    await off.pumpUntil(() => off.renders.length >= 6);
    await off.pump();
    const drawn = new Set(off.renders.map((r) => r.page));
    ok(drawn.size === 6,
      `with the probe off every in-band sheet is still rasterised (got ${drawn.size} of 6)`);
    ok(off.maxInFlight === 1,
      `and one at a time, probe or no probe — the cap is not a probe branch `
      + `(peak ${off.maxInFlight})`);
  }

  await renderQueue();
  await memoryBudget();
  await workerPath();
  await previewTier();
  await tierFairness();
  await scrollProbe();
}

// ═══════════════════════════════════════════════════════════════════════════
// 13. ONE RENDER AT A TIME, AND IT IS THE READER'S.
//
//     `renderSlot` guarded per slot (`if (slot.busy) return;`) and NOTHING
//     capped the global in-flight count. The observer's first callback arrives
//     with the whole band and called `renderSlot` on each entry as it walked
//     them, so the sheet on screen finished last, behind every sheet the
//     reader could not see. On the operator's phone that was a monotonic climb
//     from 4585 ms to 9490 ms across twenty sheets — the signature of
//     contention, not of size.
//
//     A CAP ALONE FIXES NOTHING. A queue of one that still starts with sheet
//     12 because sheet 12 came first out of the callback leaves the reader
//     watching the same white screen. The order is half the fix and is
//     asserted here as its own property.
//
//     GEOMETRY: 1200 px sheets against an 883 px viewport, so exactly ONE page
//     is on screen and "nearest" has an unambiguous answer. The device's own
//     886/883 is used by section 14, where two-partly-visible is the point.
// ═══════════════════════════════════════════════════════════════════════════
async function renderQueue() {
  console.log('\n── one sheet at a time, and it is the reader\'s ────────────────\n');

  {
    const s = bootLive({
      search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 12, slotRenderMs: 700, pageH: 1200,
    });
    await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-ready'));
    // The reader opened at sheet 7. Page 7 spans -100..1100 against an 883 px
    // viewport: the only page on screen, and the only one at distance 0.
    s.scrollTo((7 - 1) * 1200 + 100);
    const delivered = s.deliverIO();
    ok(delivered === 12,
      `the band really does hand over a crowd — ${delivered} pages in one callback`);

    await s.pumpUntil(() => s.renders.length >= 1);
    ok(s.renders.length === 1,
      `only one rasterisation starts, not twelve (got ${s.renders.length})`);
    ok(s.renders.length >= 1 && s.renders[0].page === 7,
      `and it is the sheet ON SCREEN, not the first one out of the loop `
      + `(got page ${s.renders.length ? s.renders[0].page : 'none'}, wanted 7)`);

    await s.pump();
    ok(s.maxInFlight === 1,
      `never more than one rasterisation in flight across the whole run (peak ${s.maxInFlight})`);
    // The cap must not become a leak: everything the band asked for still gets
    // drawn, just one at a time.
    const drawn = [...new Set(s.renders.map((r) => r.page))];
    ok(drawn.length === 12,
      `and all twelve are eventually drawn, just not at once (got ${drawn.length})`);
  }

  // ── THE SECOND CHOICE IS RE-MADE AGAINST WHERE THE READER IS NOW ───────
  //
  // A priority queue sorted once when the pages were enqueued would be a FIFO
  // with extra steps: a page that was nearest ten seconds ago is not nearest
  // now, and the key is the READER'S POSITION, not a property of the page.
  {
    const s = bootLive({
      search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 12, slotRenderMs: 700, pageH: 1200,
    });
    await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-ready'));
    s.scrollTo((7 - 1) * 1200 + 100);
    s.deliverIO();
    await s.pumpUntil(() => s.renders.length >= 1);
    // He flicks to the end of the set while sheet 7 is still rasterising.
    s.scrollTo((12 - 1) * 1200 + 100);
    await s.pumpUntil(() => s.renders.length >= 2);
    ok(s.renders.length >= 2 && s.renders[1].page === 12,
      `the second pick is made against where the reader is NOW (got 7 -> ${
        s.renders.length >= 2 ? s.renders[1].page : 'nothing'}; a FIFO answers 7 -> 1)`);
    await s.pump();
  }

  // ── A SHEET THE READER HAS LEFT IS DROPPED, AND THE ONE RUNNING FOR IT
  //    IS STOPPED ───────────────────────────────────────────────────────
  //
  // With one thread, a render still running for a page nobody is looking at
  // IS the page they are looking at, waiting behind it. `dequeue` only takes a
  // sheet out of the LINE; stopping the work needs `RenderTask.cancel()`, and
  // only pdf.js can do that.
  {
    const s = bootLive({
      search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 12, slotRenderMs: 5000, pageH: 1200,
    });
    await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-ready'));
    s.scrollTo((7 - 1) * 1200 + 100);
    s.deliverIO();
    await s.pumpUntil(() => s.renders.length >= 1);
    const first = s.renders[0];
    ok(first && first.page === 7, `sheet 7 is the one in flight (got ${first && first.page})`);

    // He has gone; the observer reports page 7 no longer intersecting.
    s.scrollTo((12 - 1) * 1200 + 100);
    s.deliverIOGeo();
    await s.pumpUntil(() => !!first.cancelled);
    ok(!!first.cancelled,
      'the rasterisation already running for the abandoned sheet is CANCELLED, '
      + 'not merely dequeued');
    await s.pump();
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// 14. THE RESIDENT SET IS BOUNDED BY MEGAPIXELS, AND THE BAND CANNOT VETO IT.
//
//     `KEEP_RENDERED = 7` NEVER BOUND ANYTHING. `trim()` skips any page still
//     marked `visible`, and `visible` was set by an IntersectionObserver whose
//     rootMargin is the BAND — so the band marked several pages unfreeable and
//     a "window of 7" could sit at any size the band happened to be.
//
//     A page count was the wrong unit regardless. The same seven sheets are
//     27.4 MB un-zoomed and 336 MB zoomed in, and 336 MB is the figure a
//     Chromium renderer gets killed at. The unit that runs out is pixels.
//
//     THE FIX HAS TWO HALVES AND BOTH ARE ASSERTED: the budget is in
//     megapixels read off the canvas that was ACTUALLY allocated, and the only
//     thing `trim()` may not free is a sheet that is ON SCREEN — not a sheet
//     the band merely called near.
//
//     GEOMETRY: 500 px sheets against an 883 px viewport puts THREE pages in
//     the band and only TWO on screen, which is the condition that separates
//     the two rules. A viewer that protected the band would hold all three and
//     bust the budget.
// ═══════════════════════════════════════════════════════════════════════════
const BUDGET_MP = (() => {
  const m = /var CANVAS_BUDGET_MP = ([\d.]+);/.exec(viewerScript());
  return m ? Number(m[1]) : null;
})();

async function memoryBudget() {
  console.log('\n── the resident set is bounded by megapixels, not by pages ────\n');

  ok(typeof BUDGET_MP === 'number' && BUDGET_MP > 0,
    `the page declares a megapixel budget for resident canvases (got ${BUDGET_MP})`);
  ok(!/var KEEP_RENDERED/.test(viewerScript()),
    'and the page-count window it replaces is gone, not left beside it');

  const s = bootLive({
    search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 26, slotRenderMs: 700,
    pageH: 500, viewportH: 883,
  });
  await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-ready'));
  s.scrollTo(0);
  const geo = s.deliverIOGeo();

  // THE PREMISE, MEASURED RATHER THAN ASSUMED. If the band did not hold more
  // pages than the screen does, this case would prove nothing.
  ok(geo.intersecting.length >= 3,
    `the band really does mark more sheets than are on screen (${
      geo.intersecting.join(',')} near, 2 on screen)`);

  let peak = 0;
  await s.pumpUntil(() => {
    const r = s.residentPixels();
    if (r > peak) peak = r;
    return false;
  }, 400);
  await s.pump();
  peak = Math.max(peak, s.residentPixels());

  const sheetMp = s.renders.length ? s.renders[0].mp : 0;
  ok(sheetMp > 1,
    `a sheet really is expensive at this scale (${sheetMp} MP each)`);
  // ── SETTLED, AND TRANSIENT, ASSERTED SEPARATELY ────────────────────────
  //
  // A canvas has to be ALLOCATED before it can be priced, so the instant a
  // render attaches, the resident set is over by exactly one sheet until
  // `trim()` runs on the next line. That overshoot is inherent to measuring
  // the bitmap that was really created rather than a scale — which is the
  // property the budget rests on — and it is bounded at one sheet. Asserting
  // one number for both would either ignore the overshoot or forbid the
  // design.
  ok(s.residentPixels() <= (BUDGET_MP * 1e6) + 1,
    `once settled, the resident bitmap is under the budget (${
      (s.residentPixels() / 1e6).toFixed(1)} MP of ${BUDGET_MP} MP)`);
  ok(peak <= (BUDGET_MP * 1e6) + (sheetMp * 1e6) + 1,
    `and never overshoots by more than the one sheet being attached (peak ${
      (peak / 1e6).toFixed(1)} MP, budget ${BUDGET_MP} + one ${sheetMp} MP sheet)`);

  // AND THE ONE THAT WAS FREED WAS IN THE BAND. This is the assertion
  // `KEEP_RENDERED` could never have made: the band marked it, and it went
  // anyway, because it was not on screen.
  const resident = s.residentPages();
  ok(resident.length >= 1 && resident.length < geo.intersecting.length,
    `a sheet the band still calls near was freed on merit (band ${
      geo.intersecting.join(',')}, resident ${resident.join(',') || 'none'})`);
  ok(resident.includes(1),
    `and the sheet ON SCREEN is the one that was kept (resident ${resident.join(',')})`);

  // Every sheet the band asked for was still DRAWN — the budget bounds what is
  // kept, not what is shown.
  const drawn = [...new Set(s.renders.map((r) => r.page))].sort((a, b) => a - b);
  ok(geo.intersecting.every((n) => drawn.includes(n)),
    `every sheet in the band was drawn (drawn ${drawn.join(',')})`);
}

// ═══════════════════════════════════════════════════════════════════════════
// 15. A REAL WORKER, AND A FALLBACK THAT SAYS SO OUT LOUD.
//
//     THE FAKE WORKER WAS DELIBERATE AND THE REASON FOR IT IS FALSE. The page
//     loaded `pdf.worker.min.js` as a page <script>, which defines
//     `globalThis.pdfjsWorker` and makes pdf.js short-circuit to the
//     main-thread handler — parse AND rasterise on the UI thread — with a
//     comment claiming a real Worker is "blocked from a file:// origin". True
//     of `new Worker("pdf.worker.min.js")`. FALSE of a Worker built from a
//     blob: URL, which the operator's device proved: blob workers supported,
//     page 1 through one in 618 ms.
//
//     AND THE FALLBACK HAS TO BE LOUD. A silent fallback is how this survived:
//     the viewer would go on rasterising on the UI thread and every reading
//     taken afterwards would be interpreted against the wrong model.
// ═══════════════════════════════════════════════════════════════════════════
async function workerPath() {
  console.log('\n── a real worker, and a fallback that says so ─────────────────\n');

  // THE PAGE MUST NOT CARRY THE WORKER <script> ANY MORE. Left in place it
  // defines the global before pdf.js loads and pdf.js short-circuits whatever
  // else the page does — and it costs 1.1 MB of main-thread compile at every
  // boot for a file that is now only read as text.
  {
    const raw = fs.readFileSync(VIEWER, 'utf8');
    const html = raw.slice(raw.indexOf('function viewerHtml()'), raw.indexOf('const VIEWER_SCRIPT'));
    ok(!/<script src="' \+ WORKER_NAME/.test(html),
      'the page no longer loads pdf.worker.min.js as a <script> — that tag is what '
      + 'defined globalThis.pdfjsWorker and made pdf.js skip the real Worker');
    ok(/<script src="' \+ LIB_NAME/.test(html),
      'and pdf.min.js itself is still loaded as a page script');
  }

  // ── THE DEVICE THAT CAN ──────────────────────────────────────────────
  {
    const s = bootLive({ search: '?file=file%3A%2F%2F%2Fplan.pdf', worker: 'real' });
    await s.pump();
    ok(!s.threw, `the viewer boots with a real worker without throwing${
      s.threw ? ` — ${String(s.threw && s.threw.stack).split('\n')[0]}` : ''}`);

    const wm = s.posted.filter((m) => m && m.type === 'pdf-worker');
    ok(wm.length === 1 && wm[0].mode === 'real',
      `it reports the worker it set up, once (got ${JSON.stringify(wm.map((m) => m.mode))})`);
    // NOT A PROBE ROW. This has to reach the log of a reader who is not being
    // measured, because the whole failure mode is nobody noticing.
    ok(wm.length === 1 && !s.posted.some((m) => m && m.type === 'pdf-probe'),
      'and says it on the ordinary channel, with the probe flag off');

    ok(s.workersMade.length === 1 && /^blob:/.test(s.workersMade[0].url),
      `a Worker really was constructed, from a blob: URL (got ${
        s.workersMade.map((w) => w.url).join(', ') || 'none'})`);
    ok(s.workersMade.length === 1
      && s.sandbox.pdfjsLib.GlobalWorkerOptions.workerPort === s.workersMade[0],
      'and handed to pdf.js as GlobalWorkerOptions.workerPort');
    ok(typeof s.sandbox.pdfjsWorker === 'undefined',
      `and globalThis.pdfjsWorker is never defined, so pdf.js cannot short-circuit `
      + `to the main-thread handler (got ${typeof s.sandbox.pdfjsWorker})`);
    ok(s.injectedScripts.length === 0,
      `and the fallback <script> was never injected (got ${s.injectedScripts.length})`);
    ok(s.posted.some((m) => m && m.type === 'pdf-ready'),
      'and the document still opens');
  }

  // ── THE DEVICE THAT CANNOT, AND IS NOT ALLOWED TO BE QUIET ABOUT IT ──
  {
    const s = bootLive({ search: '?file=file%3A%2F%2F%2Fplan.pdf', worker: 'none' });
    await s.pump();
    ok(!s.threw, `a WebView with no Worker or Blob still boots${
      s.threw ? ` — ${String(s.threw && s.threw.stack).split('\n')[0]}` : ''}`);

    const wm = s.posted.filter((m) => m && m.type === 'pdf-worker');
    ok(wm.length === 1 && wm[0].mode === 'main-thread',
      `it falls back to the main-thread worker (got ${JSON.stringify(wm.map((m) => m.mode))})`);
    ok(wm.length === 1 && typeof wm[0].reason === 'string' && wm[0].reason.length > 0,
      `AND SAYS WHY — a silent fallback is how this survived (got ${
        JSON.stringify(wm.length ? wm[0].reason : null)})`);
    ok(s.injectedScripts.length === 1 && s.injectedScripts[0].src === 'pdf.worker.min.js',
      `and loads the worker bundle the old way, on purpose (got ${
        s.injectedScripts.map((e) => e.src).join(', ') || 'nothing'})`);
    ok(s.sandbox.pdfjsLib.GlobalWorkerOptions.workerSrc === 'pdf.worker.min.js',
      'with workerSrc pointed at it, exactly as the viewer has always done');
    ok(s.posted.some((m) => m && m.type === 'pdf-ready'),
      'and the document STILL opens — the fallback is a slower viewer, never no viewer');
  }

  // ── THE WORKER THAT STARTS AND THEN DIES ────────────────────────────
  //
  // THE ONE FAILURE MODE WORSE THAN THE BUG. A Worker whose script throws on
  // load reports it ASYNCHRONOUSLY, possibly after `getDocument` has already
  // been handed the port — and at that point the document simply never
  // resolves. The reader gets "Loading…" for ever, with no error anywhere,
  // which is strictly worse than the slow main-thread viewer this replaces.
  //
  // So `onerror` does not merely log. It tears the port down, falls back, and
  // re-opens the document that was in flight.
  {
    const s = bootLive({ search: '?file=file%3A%2F%2F%2Fplan.pdf', worker: 'real' });
    await s.pump();
    ok(s.workersMade.length === 1 && typeof s.workersMade[0].onerror === 'function',
      'the page watches its own worker for a load failure');

    const readyBefore = s.posted.filter((m) => m && m.type === 'pdf-ready').length;
    s.workersMade[0].onerror({ message: 'boom' });
    await s.pump();

    const wm = s.posted.filter((m) => m && m.type === 'pdf-worker');
    ok(wm.length === 2 && wm[1].mode === 'main-thread',
      `a worker that dies falls back (modes: ${wm.map((m) => m.mode).join(' -> ')})`);
    ok(wm.length === 2 && /worker-error/.test(String(wm[1].reason)),
      `and says it was the worker that died, not a missing capability (${
        wm.length === 2 ? wm[1].reason : 'no second row'})`);
    ok(s.workersMade[0].terminated === true,
      'the dead worker is terminated rather than left holding a thread');
    ok(s.injectedScripts.length === 1,
      'the main-thread bundle is loaded the old way');
    ok(s.posted.filter((m) => m && m.type === 'pdf-ready').length === readyBefore + 1,
      'and the document the reader was waiting for is RE-OPENED, not abandoned');

    // ONCE. A Worker can report more than one error, and the fallback settles a
    // turn later — so a second onerror in that window must not start a second
    // re-open on top of the first.
    s.workersMade[0].onerror({ message: 'boom again' });
    await s.pump();
    ok(s.posted.filter((m) => m && m.type === 'pdf-worker').length === 2,
      'and a second onerror in the same window changes nothing');
    ok(s.posted.filter((m) => m && m.type === 'pdf-ready').length === readyBefore + 1,
      'the document is not re-opened twice');
    ok(!s.threw, `without throwing${s.threw ? ` — ${String(s.threw.stack).split('\n')[0]}` : ''}`);
  }

  // ── AND THE SUPERSEDED OPEN DOES NOT PUBLISH ITSELF ─────────────────
  //
  // Two opens can be in flight at once — the host posts a second document
  // while the first is parsing, and the fallback above re-opens one on
  // purpose. `resetDocument` cannot reach into the pending promise of the open
  // it superseded, so the generation stamp is what stops it assigning `doc`
  // and posting a `pdf-ready` for a document nobody is looking at.
  {
    const s = bootLive({ search: '', worker: 'real' });
    await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-viewer-ready'));
    s.listeners['doc:message']({ data: JSON.stringify({ type: 'open-document', file: 'file:///a.pdf' }) });
    s.listeners['doc:message']({ data: JSON.stringify({ type: 'open-document', file: 'file:///b.pdf' }) });
    await s.pump();
    const readies = s.posted.filter((m) => m && m.type === 'pdf-ready');
    ok(readies.length === 1,
      `two documents opened back to back publish exactly one (got ${readies.length})`);
    ok(!s.threw, `and nothing throws${s.threw ? ` — ${String(s.threw.stack).split('\n')[0]}` : ''}`);
  }

  // ── ITEM 5: THE EXPENSIVE PROBES CANNOT RUN IN THE SHIPPING VIEWER ───
  //
  // `probeCanvasLimits` walks a ladder to 16384x16384 — a gigabyte of
  // allocation — and `probeImageFilters` scans every operator of page 1.
  // Both are behind `MEASURE = PROBE || CAPS`, both from URL params, so
  // neither can run for a reader who did not ask. ASSERTED BY RUNNING, not by
  // reading the guard: a normal open is driven to completion and the rows it
  // would have emitted are counted.
  {
    const s = bootLive({ search: '?file=file%3A%2F%2F%2Fplan.pdf' });
    await s.pump();
    const kinds = s.posted.filter((m) => m && m.type === 'pdf-probe').map((m) => m.probe);
    ok(kinds.length === 0,
      `a shipping open emits no probe rows at all (got ${kinds.join(', ') || 'none'})`);
    ok(!kinds.includes('canvas-lim') && !kinds.includes('imgfilters'),
      'and in particular neither the canvas ladder nor the image-filter scan');
    // AND THE LADDER'S OWN ALLOCATIONS NEVER HAPPENED. A guard that returned
    // after allocating would pass the row check and still cost the reader a
    // gigabyte.
    const big = s.residentPixels();
    ok(big <= (BUDGET_MP || 0) * 1e6 + 1,
      `and no canvas outside the render path was ever allocated (${
        (big / 1e6).toFixed(1)} MP resident)`);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// 16. THE PREVIEW TIER, AND THE BLANK SHEET IT ABOLISHES.
//
//     WHAT #544 LEFT BEHIND. It fixed the open — 633 ms, real worker, one
//     rasterisation at a time — and broke the scroll, and its acceptance could
//     not see that because it measured the OPEN ONLY. Two things it did are
//     both correct and together are the defect:
//
//       CANVAS_BUDGET_MP = 32 holds about two sharp sheets. Everything else
//         is evicted, which is right: the alternative is a killed renderer.
//       the low-resolution pass was DELETED, on open-time medians (11.2 MP
//         701 ms beating 0.5 MP 800 ms) that are uncontended, single-page and
//         about FIRST PAINT. They say nothing about a sheet whose bitmap was
//         thrown away three scrolls ago, because that sheet is not being
//         rendered at all.
//
//     So an evicted page had NOTHING to show. Scroll down and back up and the
//     pages reloaded — blank, then re-render.
//
//     WHAT IS ASSERTED HERE, and none of it is visible to a parse or an AST
//     walk: a preview exists for EVERY page and not merely the near ones; the
//     megapixel budget still binds because previews are outside it; an
//     eviction takes the sharp canvas and LEAVES the preview; and a reader
//     scrolled back to an evicted sheet is looking at something.
// ═══════════════════════════════════════════════════════════════════════════
const PREVIEW_TARGET_PX = (() => {
  const m = /var PREVIEW_TARGET_PX = ([\d.]+);/.exec(viewerScript());
  return m ? Number(m[1]) : null;
})();
const SETTLE_MS = (() => {
  const m = /var SETTLE_MS = ([\d.]+);/.exec(viewerScript());
  return m ? Number(m[1]) : null;
})();
// WHICH TIER A RECORDED RENDER BELONGS TO, derived from the page's own target
// and not from a number written here. On the 36x48 geometry the two are 0.4 MP
// and ~12.6 MP, and every case below asserts that gap is real before relying
// on it — a classifier that silently collapsed would make each of these pass
// for the wrong reason.
const isPreviewRender = (r) => PREVIEW_TARGET_PX !== null
  && r.mp <= ((PREVIEW_TARGET_PX / 1e6) * 1.25);

async function previewTier() {
  console.log('\n── a preview for every page, and it outlives the budget ───────\n');

  ok(typeof PREVIEW_TARGET_PX === 'number' && PREVIEW_TARGET_PX > 0,
    `the page declares a preview pixel target (got ${PREVIEW_TARGET_PX})`);
  ok(typeof SETTLE_MS === 'number' && SETTLE_MS > 0,
    `and a settle interval for the sharp tier (got ${SETTLE_MS} ms)`);
  // THE DELETED TIER IS BACK AS A KEPT ONE, NOT AS A FASTER RENDER. If the
  // page ever stops holding the preview for every sheet this is the assertion
  // that has to be argued with.
  ok(/function renderPreview\(slot\)\{/.test(viewerScript()),
    'and a render path of its own for it');

  const s = bootLive({
    search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 26, slotRenderMs: 40,
    pageH: 886, viewportH: 883,
  });
  await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-ready'));
  s.scrollTo(0);
  s.deliverIOGeo();
  await s.pump();

  // (a) EVERY PAGE, NOT THE BAND. This is the whole difference between a
  //     preview tier and a wider prefetch window: the reader can land
  //     anywhere, and a tier that only covers the band cannot answer the
  //     "3-4 SECONDS BLANK" report at all.
  const previews = s.previewPages();
  ok(previews.length === 26,
    `every sheet in the set has a preview, not just the band (${previews.length} of 26)`);

  // (b) AND THE TWO TIERS REALLY ARE DIFFERENT SIZES. Without this the rest
  //     of the section could pass on a viewer that drew 26 sharp sheets and
  //     called them previews.
  const pv = s.renders.filter(isPreviewRender);
  const sh = s.renders.filter((r) => !isPreviewRender(r));
  ok(pv.length >= 26 && sh.length >= 1,
    `both tiers really ran (${pv.length} preview renders, ${sh.length} sharp)`);
  ok(pv.length && sh.length && pv[0].mp < sh[0].mp,
    `and a preview is far cheaper in pixels than a sheet (${
      pv.length ? pv[0].mp : '?'} MP vs ${sh.length ? sh[0].mp : '?'} MP)`);

  // (c) THE BUDGET STILL BINDS. Previews are outside it by design; if they
  //     were inside it, 26 of them would evict the sheet the reader is on.
  ok(s.sharpPixels() <= (BUDGET_MP * 1e6) + 1,
    `the SHARP tier is still under its budget with 26 previews resident (${
      (s.sharpPixels() / 1e6).toFixed(1)} MP of ${BUDGET_MP} MP)`);
  const resident = s.residentPages();
  ok(resident.length >= 1 && resident.length <= 3,
    `and only a couple of sharp sheets survive it (resident ${resident.join(',') || 'none'})`);

  // (d) THE EVICTION TAKES THE CANVAS AND LEAVES THE PREVIEW.
  //     `releaseSlot` used to empty the placeholder with `innerHTML = ""`,
  //     which would have deleted the preview along with the canvas — the
  //     original defect, reintroduced by the evictor itself.
  const evicted = previews.filter((n) => !resident.includes(n));
  ok(evicted.length > 0,
    `sheets really were evicted (${evicted.length} of 26 have no sharp canvas)`);
  ok(evicted.every((n) => previews.includes(n)),
    'and every one of them still has its preview — the evictor takes the canvas, not the layer under it');

  // (e) SO NOTHING THE READER CAN SEE IS BLANK. Measured off the DOM, not
  //     off the log: a placeholder on screen with neither layer in it.
  ok(s.blankOnScreen().length === 0,
    `no sheet on screen is blank (blank: ${s.blankOnScreen().join(',') || 'none'})`);

  // ── AND A SCROLL BACK TO AN EVICTED SHEET IS INSTANT, BECAUSE NOTHING
  //    HAS TO HAPPEN ───────────────────────────────────────────────────
  //
  // THE ACCEPTANCE IS "PREVIEW INSTANT", and the only way to be instant is to
  // already be there. A design that re-rendered a preview on the way back
  // would be a faster version of the bug. So the assertion is not a time: it
  // is that the reader arrives at a sheet that is already showing something,
  // with ZERO renders started to make it so.
  {
    const target = evicted.length ? evicted[evicted.length - 1] : 26;
    const before = s.renders.length;
    s.scrollTo((target - 1) * s.pageH, true);
    const pvNow = s.previewPages();
    ok(pvNow.includes(target),
      `sheet ${target} was evicted and is STILL showing a preview the instant the reader lands on it`);
    ok(s.renders.length === before,
      `and not one rasterisation was needed to put it there (${
        s.renders.length - before} started)`);
    ok(s.blankOnScreen().length === 0,
      `nothing on screen is blank on arrival (blank: ${s.blankOnScreen().join(',') || 'none'})`);
    // The observer is what tells the page the band moved; in a browser it
    // fires on its own, and here it has to be delivered. Without this the
    // sheet stays on its preview for ever, which would be a viewer that never
    // sharpens — and the assertion below would not be able to tell.
    s.deliverIOGeo();
    await s.pump();
    // The sharp render still lands afterwards — the preview is what fills the
    // gap, not what replaces the tier.
    ok(s.residentPages().includes(target),
      `and the sharp render lands on it once the scroll settles (resident ${
        s.residentPages().join(',')})`);
  }

  // ── THE STORAGE DECISION, ASSERTED RATHER THAN DESCRIBED ──────────────
  //
  // 26 x 0.4 MP x 4 B is ~42 MB of raw bitmap, which is affordable at 26
  // sheets and 320 MB at the 200-sheet sets this viewer's own header
  // documents — straight through the 250-350 MB renderer kill. The tier holds
  // ENCODED bytes instead. The gate is that the page KEEPS NO RAW PREVIEW
  // BITMAP: every preview canvas it allocates is zeroed on the same turn it
  // is encoded, so the raw cost is one scratch sheet whatever N is.
  {
    const pvEls = s.els.filter((el) => el.className === 'pv');
    ok(pvEls.length === 26, `there are 26 preview layers (got ${pvEls.length})`);
    const rawHeld = pvEls.reduce((t, el) => t + ((Number(el.width) || 0) * (Number(el.height) || 0)), 0);
    ok(rawHeld === 0,
      `and not one of them is a live bitmap — the tier holds encoded bytes (${
        (rawHeld * 4 / 1e6).toFixed(1)} MB of raw preview resident, raw design would be ${
        ((26 * PREVIEW_TARGET_PX * 4) / 1e6).toFixed(0)} MB)`);
    ok(pvEls.every((el) => typeof el.src === 'string' && el.src.indexOf('blob:') === 0),
      'each is an <img> against an object URL, which is what lets Chromium '
      + 'decide for itself which of them to keep decoded');
  }

  // ── AND THEY ARE HANDED BACK WHEN THE DOCUMENT GOES ───────────────────
  //
  // This page outlives every document the reader opens. A blob: URL that is
  // never revoked keeps its bytes for the life of the PAGE, so a missed revoke
  // accumulates one whole set of previews per open — the same shape of leak
  // `releaseSlot` was written for, one layer down.
  {
    const madeBefore = s.objectUrls.made.length;
    s.listeners['doc:message']({ data: JSON.stringify({ type: 'open-document', file: 'file:///b.pdf' }) });
    await s.pump();
    ok(madeBefore >= 26, `26 object URLs were taken out for the first document (${madeBefore})`);
    ok(s.objectUrls.revoked.length >= 26,
      `and opening a second document gives them back (${s.objectUrls.revoked.length} revoked)`);
  }

  // ── THE WEBVIEW THAT CANNOT ENCODE STILL GETS PREVIEWS ────────────────
  //
  // FAIL TOWARD HAVING SOMETHING TO SHOW. A device with no `toBlob` and no
  // `createObjectURL` falls to `toDataURL`, and one with neither keeps the raw
  // canvas at ~1.6 MB a sheet. Both are worse than the shipping path and both
  // are enormously better than a blank sheet, which is what a tier that
  // required an encoder would hand that device.
  {
    const d = bootLive({
      search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 6, slotRenderMs: 40,
      pageH: 886, viewportH: 883, encode: 'dataurl',
    });
    await d.pumpUntil(() => d.posted.some((m) => m && m.type === 'pdf-ready'));
    d.deliverIOGeo();
    await d.pump();
    ok(d.previewPages().length === 6,
      `a WebView with only toDataURL still previews every sheet (${d.previewPages().length} of 6)`);
    ok(!d.threw, `without throwing${d.threw ? ` — ${String(d.threw.stack).split('\n')[0]}` : ''}`);

    const n = bootLive({
      search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 6, slotRenderMs: 40,
      pageH: 886, viewportH: 883, encode: 'none',
    });
    await n.pumpUntil(() => n.posted.some((m) => m && m.type === 'pdf-ready'));
    n.deliverIOGeo();
    await n.pump();
    ok(n.previewPages().length === 6,
      `and one with no encoder at all keeps the raw canvas rather than going blank (${
        n.previewPages().length} of 6)`);
    ok(n.blankOnScreen().length === 0,
      `nothing is blank on that device either (blank: ${n.blankOnScreen().join(',') || 'none'})`);
    ok(!n.threw, `and it does not throw${n.threw ? ` — ${String(n.threw.stack).split('\n')[0]}` : ''}`);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// 17. NEITHER TIER STARVES THE OTHER, AND NEITHER MOVES THE OPEN.
//
//     ONE THREAD, TWO TIERS, AND A 26-JOB BACKGROUND FILL. Every way this can
//     go wrong is a real design someone would write:
//
//       the fill starts at `pdf-ready`   -> 26 rasterisations land in front of
//                                           the reader's first sheet and the
//                                           open number #544 bought is gone.
//       the fill runs at equal priority  -> the reader stops on a sheet and
//                                           waits behind sheets 21 to 26.
//       sharp renders start mid-flick    -> ~700 ms of the one thread spent on
//                                           a sheet that is off screen before
//                                           it lands, and the sheet he stops
//                                           on queues behind it. THAT IS THE
//                                           "3-4 SECONDS BLANK" REPORT.
//
//     All three are ORDERING properties of a running queue. No parse and no
//     AST walk can see any of them, which is why they are asserted by driving
//     the page rather than by reading it.
// ═══════════════════════════════════════════════════════════════════════════
async function tierFairness() {
  console.log('\n── the fill waits, then yields, and never blocks the reader ───\n');

  // ── (a) NOT ONE PREVIEW BEFORE THE FIRST SHARP SHEET IS ON SCREEN ─────
  //
  // The acceptance that must not move is the open: 633 ms, longest stall under
  // 200 ms. A single background preview landing ahead of the reader's first
  // sheet is ~700 ms of the only thread there is.
  {
    const s = bootLive({
      search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 26, slotRenderMs: 700,
      pageH: 886, viewportH: 883,
    });
    await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-ready'));
    s.scrollTo(0);
    s.deliverIOGeo();
    // Stop the instant the first rasterisation of any kind begins.
    await s.pumpUntil(() => s.renders.length >= 1);
    ok(s.renders.length >= 1 && !isPreviewRender(s.renders[0]),
      `the first rasterisation after the open is a SHARP sheet, not a preview (${
        s.renders.length ? `${s.renders[0].mp} MP` : 'nothing ran'})`);
    ok(s.renders.length >= 1 && s.renders[0].page === 1,
      `and it is the sheet the reader is looking at (page ${
        s.renders.length ? s.renders[0].page : 'none'})`);

    // Now let the first one land and the fill arm itself.
    await s.pumpUntil(() => s.renders.some((r) => !isPreviewRender(r) && r.endedAt !== null));
    await s.pumpUntil(() => s.renders.some(isPreviewRender));
    const firstPv = s.renders.findIndex(isPreviewRender);
    const firstSharpDone = s.renders.find((r) => !isPreviewRender(r) && r.endedAt !== null);
    ok(firstPv > 0 && firstSharpDone
      && s.renders[firstPv].startedAt >= firstSharpDone.endedAt,
      `the background fill starts only AFTER the first sharp sheet is on screen `
      + `(sharp done at ${firstSharpDone && firstSharpDone.endedAt}, first preview at ${
        firstPv >= 0 ? s.renders[firstPv].startedAt : 'never'})`);
    await s.pump();
    ok(s.maxInFlight === 1,
      `and two tiers still means one rasterisation at a time (peak ${s.maxInFlight})`);
  }

  // ── (b) A SHARP RENDER DOES NOT START WHILE THE SCROLL IS MOVING ──────
  //
  // The gate is the scroll STOPPING, so a viewer that ignored it would start a
  // 12.6 MP render on a sheet the reader is flying past. Previews keep running
  // throughout, which is what makes the wait affordable.
  {
    const s = bootLive({
      search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 26, slotRenderMs: 700,
      pageH: 886, viewportH: 883,
    });
    await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-ready'));
    s.deliverIOGeo();
    await s.pump();                       // open, fill, everything settles

    // ⚠️ THE THREAD IS IDLE AT THE MOMENT OF THE FLICK, AND THAT IS THE
    //    CONTROL. `await s.pump()` above ran the fill to the end, so nothing
    //    is occupying the one render slot. With the settle gate removed, the
    //    sharp render for the sheet under the thumb would start on the SAME
    //    tick as the scroll event — there is nothing else for it to wait for.
    //    So a reading of "started at or after flick + SETTLE_MS" can only come
    //    from the gate, and the case can fail.
    //
    //    MEASURED ON THE CLOCK, NOT IN PUMP STEPS. An earlier draft asserted
    //    "nothing started in the next few turns of the loop", and a turn of the
    //    loop fires the earliest DUE timer — which was the settle timer itself.
    //    It reported the gate broken on a viewer whose gate worked.
    const sharpBefore = s.renders.filter((r) => !isPreviewRender(r)).length;
    // A flick: three scroll events inside one settle interval.
    s.scrollTo(4 * s.pageH, true);
    s.scrollTo(9 * s.pageH, true);
    s.scrollTo(14 * s.pageH, true);
    s.deliverIOGeo();
    const flickAt = s.now;
    await s.pump();
    const sharpAfter = s.renders.filter((r) => !isPreviewRender(r)).slice(sharpBefore);
    const early = sharpAfter.filter((r) => r.startedAt < flickAt + SETTLE_MS);
    ok(early.length === 0,
      `no sharp render starts inside the ${SETTLE_MS} ms the scroll is still `
      + `moving (${early.length} started at ${
        early.map((r) => `p${r.page}@${r.startedAt - flickAt}ms`).join(',') || 'none'})`);

    const drawnAfter = s.renders.filter((r) => !isPreviewRender(r)).length - sharpBefore;
    ok(drawnAfter >= 1,
      `and once it settles the sheet he stopped on IS drawn sharp (${drawnAfter} started)`);
    const resident = s.residentPages();
    ok(resident.some((n) => n >= 14 && n <= 17),
      `on the sheet he actually stopped at, not the ones he flew past (resident ${
        resident.join(',')})`);
  }

  // ── (c) THE VISIBLE SHEET'S SHARP RENDER JUMPS THE FILL QUEUE ─────────
  //
  // The fill is 26 jobs long. A queue that took them in order would put the
  // reader behind every one of them. The rank is re-derived at the instant a
  // slot comes free, so "the sheet he is on" wins whatever was queued first.
  {
    const s = bootLive({
      search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 26, slotRenderMs: 300,
      pageH: 886, viewportH: 883,
    });
    await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-ready'));
    s.deliverIOGeo();
    // Let the fill get going but nowhere near finished.
    await s.pumpUntil(() => s.renders.filter(isPreviewRender).length >= 3);
    const pending = 26 - s.previewPages().length;
    ok(pending > 5, `the fill really is still mostly outstanding (${pending} previews to go)`);

    const mark = s.renders.length;
    s.scrollTo((12 - 1) * s.pageH, true);
    s.deliverIOGeo();
    await s.pumpUntil(() => s.renders.slice(mark).some((r) => !isPreviewRender(r)));
    const after = s.renders.slice(mark);
    const firstSharp = after.findIndex((r) => !isPreviewRender(r));
    const previewsAhead = after.slice(0, firstSharp < 0 ? after.length : firstSharp).length;
    ok(firstSharp >= 0,
      'the sheet he stopped on gets a sharp render while the fill is outstanding');
    // AT MOST ONE. The preview for the sheet he landed on is allowed in front
    // of it — it is the cheapest thing that can end a blank sheet — but no
    // BACKGROUND preview may be.
    ok(previewsAhead <= 1,
      `and at most its own preview goes in front of it, never the fill (${
        previewsAhead} preview renders ahead of it)`);
    ok(previewsAhead === 0 || after[0].page === 12,
      `and if one did, it was for the sheet he is looking at (page ${
        after.length ? after[0].page : 'none'})`);
    await s.pump();
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// 18. THE PROBE MEASURES SCROLLING, WHICH IS WHY THIS REGRESSED.
//
//     ⚠️ THE ACCEPTANCE FOR #544 MEASURED THE OPEN ONLY AND PASSED WHILE
//     SCROLLING WAS BROKEN. `boot`, `open`, `parse`, `layout`, `render-ab`,
//     `uithread` — every row the probe emits is about the first paint of the
//     first sheet, and the suite never scrolls, so not one of them could have
//     gone red on a viewer that reloads every page on the way back up. An
//     instrument that cannot fail the thing that is broken is not one.
//
//     WHAT IS ASSERTED HERE IS THE INSTRUMENT, not the device's numbers: that
//     the rows EXIST, that they are emitted the way `render-ab` and `boot`
//     are, and that they carry the four quantities the acceptance is written
//     in — preview time, sharp time, whether the sheet re-rendered, and how
//     many sheets were blank. A row that reported `previewMs` and omitted
//     `maxBlankOnScreen` would pass an acceptance about blank sheets without
//     ever looking at one.
// ═══════════════════════════════════════════════════════════════════════════
async function scrollProbe() {
  console.log('\n── the probe scrolls, and says what it saw ───────────────────\n');

  // ── THE GEOMETRY IS CHOSEN SO THE BUDGET REALLY EVICTS ────────────────
  //
  // 500 px sheets against an 883 px viewport puts TWO on screen, which is
  // 25.2 MP; the jump to sheet 20 makes it four and `trim()` frees the two
  // behind. Sheet 1 is therefore genuinely gone by the time the reader comes
  // back, which is the condition the whole acceptance is about — "scroll down
  // then back up -> pages RELOAD".
  //
  // ⚠️ THE DEVICE'S OWN 886/883 DOES NOT PRODUCE IT ANY MORE, and that is
  // worth knowing rather than working around: with one sheet on screen at a
  // time and no off-screen sharp prefetch, the reader's sheet plus the one he
  // came from is 25.2 MP of a 32 MP budget and nothing is evicted at all. A
  // probe case left on that geometry would report `reRendered:false` and
  // measure the scroll-back path without ever taking it.
  const s = bootLive({
    search: '?probe=1&file=file%3A%2F%2F%2Fplan.pdf', pages: 26, slotRenderMs: 20,
    pageH: 500, viewportH: 883,
  });
  await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-ready'));
  s.deliverIOGeo();
  await s.pump();

  const rows = probeData(s.posted, 'scroll');
  const setup = probeData(s.posted, 'scroll-setup');
  const census = probeData(s.posted, 'render-census');
  const mem = probeData(s.posted, 'preview-mem');

  ok(rows.length === 2,
    `the probe emits a row per scroll leg, its own kind, like render-ab does (got ${rows.length})`);
  ok(setup.length === 1 && setup[0].filled === true,
    `and says first whether the fill had finished — a leg run mid-fill reports a `
    + `blank that is a schedule, not a defect (built ${
      setup.length ? setup[0].previewsBuilt : '?'} of ${setup.length ? setup[0].pages : '?'})`);

  const jump = rows.find((r) => /^jump-to-p/.test(r.phase));
  const back = rows.find((r) => r.phase === 'back-to-p1');
  ok(!!jump, `there is a fast-jump leg (${rows.map((r) => r.phase).join(', ') || 'none'})`);
  ok(!!back, 'and a scroll-back leg');
  ok(jump && jump.page === 20,
    `the jump goes to sheet 20, the operator's own number (got ${jump && jump.page})`);

  // THE FOUR QUANTITIES THE ACCEPTANCE IS WRITTEN IN. Named individually
  // because a row that carried three of them would read as an answer.
  for (const r of rows) {
    ok(r && typeof r.previewMs === 'number',
      `${r && r.phase}: ms until the sheet shows a PREVIEW (${r && r.previewMs})`);
    ok(r && typeof r.sharpMs === 'number',
      `${r && r.phase}: ms until it shows SHARP (${r && r.sharpMs})`);
    ok(r && typeof r.reRendered === 'boolean',
      `${r && r.phase}: whether it had to re-render (${r && r.reRendered})`);
    ok(r && typeof r.maxBlankOnScreen === 'number',
      `${r && r.phase}: how many sheets were blank at any tick (${r && r.maxBlankOnScreen})`);
    ok(r && r.timedOut === false,
      `${r && r.phase}: and the leg completed rather than running out the clock`);
  }

  // THE ACCEPTANCE ITSELF, on the fake clock. Not the device's milliseconds —
  // those come off the operator's phone — but the PROPERTY the device numbers
  // are supposed to demonstrate, which a harness can hold to.
  ok(rows.every((r) => r.maxBlankOnScreen === 0),
    `no sheet is blank at any point in either leg (${
      rows.map((r) => `${r.phase}:${r.maxBlankOnScreen}`).join(' ')})`);
  ok(rows.every((r) => r.previewPrebuilt === true && r.previewMs === 0),
    `and the preview is already there on arrival, both legs — instant because `
    + `nothing has to happen (${rows.map((r) => `${r.phase}:${r.previewMs}ms`).join(' ')})`);
  ok(back && back.reRendered === true,
    'the scroll-back leg really did find sheet 1 evicted, so "it re-renders" is '
    + 'being measured rather than assumed');
  ok(rows.every((r) => typeof r.sharpMs === 'number' && r.sharpMs >= SETTLE_MS),
    `and the sharp render waits out the settle before it starts (${
      rows.map((r) => `${r.phase}:${r.sharpMs}ms`).join(' ')}, settle ${SETTLE_MS} ms)`);

  // ── STARTED vs CANCELLED vs COMPLETED ─────────────────────────────────
  //
  // A viewer that starts nine renders to finish one reports the same
  // COMPLETED count as one that starts one. The gap is the measurement.
  ok(census.length === 1, `the census is emitted once (got ${census.length})`);
  const c = census[0] || {};
  for (const k of ['sharpStarted', 'sharpCancelled', 'sharpCompleted',
    'previewStarted', 'previewCompleted', 'previewFailed']) {
    ok(typeof c[k] === 'number', `the census carries ${k} (${c[k]})`);
  }
  ok(c.previewCompleted === 26,
    `and it agrees with the document: 26 previews built (${c.previewCompleted})`);
  ok(c.sharpStarted >= c.sharpCompleted,
    `started is never below completed (${c.sharpStarted} started, ${
      c.sharpCompleted} completed, ${c.sharpCancelled} cancelled)`);

  // ── THE MEMORY ROW, WHICH IS WHAT THE STORAGE DECISION IS AUDITED ON ──
  //
  // `previewStoredBytes` is a sum of real `Blob.size` values and
  // `previewRawEquivalentMB` is what the rejected design would have been
  // holding, from the dimensions actually allocated. A report that stated only
  // the winner's figure would leave nobody able to check the choice.
  ok(mem.length === 1, `the preview memory row is emitted once (got ${mem.length})`);
  const m = mem[0] || {};
  ok(m.storage === 'blob',
    `and names the storage that was actually used (got ${m.storage})`);
  ok(typeof m.previewStoredMB === 'number' && m.previewStoredMB > 0,
    `with the measured total (${m.previewStoredMB} MB for ${m.previewsBuilt} previews)`);
  ok(typeof m.previewRawEquivalentMB === 'number'
    && m.previewRawEquivalentMB > m.previewStoredMB,
    `beside what the raw-bitmap design would have cost (${
      m.previewRawEquivalentMB} MB raw vs ${m.previewStoredMB} MB stored)`);
  ok(typeof m.totalResidentMB === 'number' && typeof m.sharpResidentMB === 'number',
    `and the total resident across both tiers (${m.totalResidentMB} MB, sharp ${
      m.sharpResidentMB} MB)`);

  ok(!s.threw, `the scroll probe runs without throwing${
    s.threw ? ` — ${String(s.threw.stack).split('\n')[0]}` : ''}`);

  // ── AND NONE OF IT RUNS FOR A READER WHO DID NOT ASK ──────────────────
  //
  // The scroll test drives the page somewhere the reader did not put it. A
  // shipping open must not emit a single one of these rows, and must not be
  // scrolled by them.
  {
    const off = bootLive({
      search: '?file=file%3A%2F%2F%2Fplan.pdf', pages: 26, slotRenderMs: 20,
      pageH: 886, viewportH: 883,
    });
    await off.pumpUntil(() => off.posted.some((m2) => m2 && m2.type === 'pdf-ready'));
    off.deliverIOGeo();
    await off.pump();
    const kinds = off.posted.filter((m2) => m2 && m2.type === 'pdf-probe').map((m2) => m2.probe);
    ok(kinds.length === 0,
      `a shipping open emits no scroll rows at all (got ${kinds.join(', ') || 'none'})`);
    ok(off.sandbox.pageYOffset === 0,
      `and the probe never moved the reader's page (scrollTop ${off.sandbox.pageYOffset})`);
    ok(off.previewPages().length === 26,
      `while still building every preview (${off.previewPages().length} of 26)`);
  }
}

main().then(() => {
  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}).catch((e) => {
  console.log(`  FAIL  the live harness threw — ${e && e.stack}`);
  console.log(`\n  ${passed} passed, ${failed + 1} failed`);
  process.exit(1);
});
