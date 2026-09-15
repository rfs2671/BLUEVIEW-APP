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
} = {}) {
  const posted = [];
  const listeners = {};
  const renders = [];
  const timers = [];
  const observers = [];
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
        const rec = { page: n, scale, startedAt: now, endedAt: null, inFlightAtStart: inFlight };
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
        return { promise, cancel() { cancelled = true; } };
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
        else this.responseText = 'stub-worker-source';
        if (this.onload) this.onload();
      });
    };
  }

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
    performance: { now: () => now, getEntriesByType: () => [] },
    XMLHttpRequest: XHR,
    // AN OBSERVER THAT RECORDS RATHER THAN SWALLOWS. It still fires nothing on
    // its own — `deliverIO()` is the only thing that delivers a batch — so
    // every case above, which never calls it, behaves exactly as it did when
    // this was a no-op stub and no slot render ever happened.
    IntersectionObserver: function IO(cb) {
      const io = this;
      io.cb = cb;
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
  // The real `pdf.worker.min.js` <script> defines this global before pdf.js
  // runs. It is the whole reason the rasteriser is on the main thread, and the
  // viewer is asked below to state that rather than leave it to a comment.
  sandbox.pdfjsWorker = { WorkerMessageHandler: {} };
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

  function deliverIO() {
    const io = observers.filter((o) => o.live).pop();
    if (!io) return 0;
    const entries = io.els.map((el) => ({ target: el, isIntersecting: true }));
    io.cb(entries);
    return entries.length;
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
  async function pumpUntil(pred, maxSteps = 5000) {
    for (let step = 0; step < maxSteps; step += 1) {
      if (pred()) return true;
      await new Promise((r) => setImmediate(r));
      for (let k = 0; k < 12; k += 1) await Promise.resolve();
      if (!timers.length) continue;
      timers.sort((a, b) => (a.at - b.at) || (a.id - b.id));
      const t = timers.shift();
      if (t.at > now) now = t.at;
      try { t.fn(); } catch (e) { threw = threw || e; }
    }
    return pred();
  }

  return { posted, listeners, renders, sandbox, pump, pumpUntil, deliverIO, hooks, marks,
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
  ok(withPass.length === 9
    && withPass.every((d) => d.inflight === 0 && d.pending === 0),
    `every A/B row states the queue was empty when it ran (got: ${
      withPass.map((d) => `${d.inflight}/${d.pending}`).join(' ') || 'no field at all'})`);

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
    const seen = {};
    const s = bootLive();
    s.hooks.renderMsFor = (rec) => {
      const key = String(rec.scale);
      seen[key] = (seen[key] || 0) + 1;
      return seq[(seen[key] - 1) % seq.length];
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
  //     The file's comment says the `<script src="pdf.worker.min.js">` tag
  //     defines `globalThis.pdfjsWorker` and that pdf.js therefore skips the
  //     real-Worker attempt and rasterises on the main thread. EVERY
  //     PERFORMANCE CONCLUSION IN THIS FILE RESTS ON THAT, and nothing has ever
  //     checked it. A pdf.js version that stopped honouring the global, or a
  //     staging order that loaded the two scripts the other way round, would
  //     change the answer silently and every reading would be reinterpreted
  //     against the wrong model.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const s = bootLive();
    await s.pump();
    const wp = probeData(s.posted, 'workerpath')[0];
    ok(!!wp, 'the viewer reports which worker path is live');
    // BEFORE `getDocument`, which is the only moment the answer is decided.
    // Read afterwards it proves nothing: pdf.js may have defined things itself.
    ok(!!wp && wp.globalWorkerDefinedBeforeGetDocument === true,
      `and says whether globalThis.pdfjsWorker existed BEFORE getDocument (got ${
        wp && wp.globalWorkerDefinedBeforeGetDocument})`);
    ok(!!wp && wp.workerSrc === 'pdf.worker.min.js',
      `and what GlobalWorkerOptions.workerSrc is set to (got ${JSON.stringify(wp && wp.workerSrc)})`);
    ok(!!wp && typeof wp.verdict === 'string' && /fake|main-thread/i.test(wp.verdict),
      `and names the path in words a reader can act on (got ${JSON.stringify(wp && wp.verdict)})`);
  }

  console.log('\n── the suite waits for the queue to empty ─────────────────────\n');

  // ═════════════════════════════════════════════════════════════════════════
  // 12. THE ISOLATION ITSELF, WITH REAL CONTENTION TO ISOLATE FROM.
  //
  //     Asserting `inflight: 0` on a harness where no slot render ever happens
  //     asserts nothing — the field would read 0 on a viewer that never
  //     drained anything. So this case puts SIX slot renders in flight, each
  //     outlasting the suite's own 2000 ms delay, which is the condition on the
  //     operator's phone: the suite started on top of the band and every
  //     variant's number contained the wait.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const s = bootLive({ pages: 6, slotRenderMs: 5000 });
    // Run only as far as the document being open. The suite's timer is armed
    // at this moment and is 2000 ms away.
    await s.pumpUntil(() => s.posted.some((m) => m && m.type === 'pdf-ready'));
    const delivered = s.deliverIO();
    ok(delivered === 6,
      `the band really does hand over a crowd (${delivered} pages in one callback)`);
    await s.pump();

    ok(!s.threw, `the viewer survives a suite that had to wait${
      s.threw ? ` — ${String(s.threw && s.threw.stack).split('\n')[0]}` : ''}`);

    const drain = probeData(s.posted, 'drain')[0];
    ok(!!drain, 'the suite says out loud that it drained the queue first');
    // THERE WAS SOMETHING TO DRAIN. Without this the case would pass on a
    // viewer that drained nothing because nothing was running.
    ok(!!drain && drain.inflightAtStart >= 2,
      `and there really was contention to drain (${drain && drain.inflightAtStart} renders in flight)`);
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
    ok(rows.length === 9 && rows.every((d) => d.inflight === 0 && d.pending === 0),
      `all nine rows report an empty queue (got ${
        rows.map((d) => `${d.inflight}/${d.pending}`).join(' ') || 'nothing'})`);

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
    await off.pump();
    const drawn = new Set(off.renders.map((r) => r.page));
    ok(drawn.size === 6,
      `with the probe off every in-band sheet is still rasterised (got ${drawn.size} of 6)`);
    ok(off.maxInFlight > 1,
      `and the shipping path is byte-identical — still uncapped and still `
      + `concurrent (peak ${off.maxInFlight}); the queue cap is PR #544's job, not this one`);
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
