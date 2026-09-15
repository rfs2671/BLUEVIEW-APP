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
  const makeEl = () => {
    const el = {
      style: {}, textContent: '', innerHTML: '', className: '',
      parentNode: null, __slot: null, width: 0, height: 0,
      src: '', onload: null, onerror: null,
      // THE CANVAS IS REMEMBERED so the test can ask which PAGE is still
      // resident, not merely how many bitmaps are. `releaseSlot` zeroes the
      // canvas it drops, so a page whose `__child` has width 0 has been freed.
      appendChild(child) { el.__child = child; if (child) child.parentNode = el; },
      removeChild() {},
      getContext: () => ({
        fillStyle: '',
        fillRect() {},
        getImageData: () => ({ data: [0, 0, 0, 255] }),
      }),
      addEventListener(t, f) { listeners[`el:${t}`] = f; },
    };
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
  const residentPages = () => els
    .filter((el) => el.__slot && el.__child && Number(el.__child.width) > 0)
    .map((el) => el.__slot.n)
    .sort((a, b) => a - b);

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
  if (worker === 'real') {
    sandbox.Blob = function BlobStub(parts, opts) {
      this.parts = parts;
      this.type = (opts && opts.type) || '';
      this.size = (parts || []).reduce((t, p) => t + String(p).length, 0);
    };
    sandbox.URL = {
      createObjectURL(b) { return `blob:stub-${(b && b.size) || 0}`; },
      revokeObjectURL() {},
    };
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
  sandbox.window.scrollTo = (x, y) => { scrollTop = Number(y) || 0; };
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

  function scrollTo(y) { scrollTop = Number(y) || 0; }

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

main().then(() => {
  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}).catch((e) => {
  console.log(`  FAIL  the live harness threw — ${e && e.stack}`);
  console.log(`\n  ${passed} passed, ${failed + 1} failed`);
  process.exit(1);
});
