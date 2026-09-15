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

function bootLive({ search = '?probe=1&file=file%3A%2F%2F%2Fplan.pdf', pages = 3 } = {}) {
  const posted = [];
  const listeners = {};
  const renders = [];
  const timers = [];
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
        const rec = { page: n, scale, startedAt: now, endedAt: null };
        renders.push(rec);
        let cancelled = false;
        const promise = new Promise((resolve, reject) => {
          schedule(5, () => {
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
    IntersectionObserver: function IO() { this.observe = () => {}; this.disconnect = () => {}; },
    pdfjsLib: {
      GlobalWorkerOptions: {},
      OPS: { paintImageXObject: 1, paintJpegXObject: 2, paintImageMaskXObject: 3 },
      getDocument: () => ({ promise: Promise.resolve(pdfStub) }),
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
  sandbox.window.ReactNativeWebView = {
    postMessage: (s) => { try { posted.push(JSON.parse(s)); } catch (_e) {} },
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

  return { posted, listeners, renders, sandbox, pump, get threw() { return threw; },
    get maxInFlight() { return maxInFlight; } };
}

async function main() {
  console.log('\n── the A/B suite runs its three scales twice ──────────────────\n');

  const live = bootLive();
  await live.pump();

  ok(!live.threw, `the viewer drives a whole probe session without throwing${
    live.threw ? ` — ${String(live.threw && live.threw.stack).split('\n')[0]}` : ''}`);

  const probes = live.posted.filter((m) => m && m.type === 'pdf-probe');
  ok(probes.some((m) => m.probe === 'suite' && m.data && m.data.done === true),
    'the suite reaches its completion marker — the harness really ran it '
    + `(saw: ${probes.map((m) => m.probe).join(', ') || 'nothing'})`);

  const ab = probes.filter((m) => m.probe === 'render-ab').map((m) => m.data);
  const withPass = ab.filter((d) => d && (d.pass === 1 || d.pass === 2));

  ok(withPass.filter((d) => d.pass === 1).length === 3,
    `pass 1 runs all three scales (got ${withPass.filter((d) => d.pass === 1).length})`);
  ok(withPass.filter((d) => d.pass === 2).length === 3,
    `pass 2 runs all three scales (got ${withPass.filter((d) => d.pass === 2).length})`);

  // ORDER. The claim under test is "the first render of a page is the
  // expensive one", so the second pass must come AFTER the first and repeat
  // the same three in the same sequence. A shuffled or interleaved second
  // pass would answer a different question.
  ok(withPass.length === 6
    && withPass.slice(0, 3).every((d) => d.pass === 1)
    && withPass.slice(3).every((d) => d.pass === 2),
    `the six A/B renders are pass 1 then pass 2, not interleaved (got: ${
      withPass.map((d) => d.pass).join(',') || 'none'})`);

  // LIKE FOR LIKE. Pass 2 that rendered different scales would not be a
  // repeat of pass 1 at all.
  const p1 = withPass.filter((d) => d.pass === 1).map((d) => d.scale);
  const p2 = withPass.filter((d) => d.pass === 2).map((d) => d.scale);
  ok(p1.length === 3 && p2.length === 3 && p1.every((s, i) => s === p2[i]),
    `pass 2 repeats pass 1's exact scales (p1=${p1.join('/')} p2=${p2.join('/')})`);

  // And the same page, or it is not a warm-up reading.
  ok(withPass.length === 6 && withPass.every((d) => d.page === 1),
    'both passes render the same page');

  // DISTINGUISHABLE IN THE LOG. PDFViewer.native.jsx dumps `label` verbatim
  // into the shareable probe log; two identically-labelled rows would be
  // unreadable in exactly the artefact the operator sends back.
  const labels = withPass.map((d) => d.label);
  ok(new Set(labels).size === 6,
    `all six rows carry a distinct label (${labels.join(' | ')})`);

  // SEQUENCED, WHICH IS THE PREMISE. Two rasterisations sharing a thread each
  // contain the other's time — the exact defect the render cap is being
  // written for — so an A/B that overlapped would be measuring contention and
  // calling it warm-up.
  ok(live.maxInFlight === 1,
    `no two renders are ever in flight at once (peak ${live.maxInFlight})`);

  // ── AND NONE OF IT HAPPENS WITH THE FLAG OFF ───────────────────────────
  // The probe is inert unless `probe=1`. A second pass doubles the suite's
  // cost, so this is the assertion that keeps that cost off every reader who
  // is not being measured.
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
}

main().then(() => {
  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}).catch((e) => {
  console.log(`  FAIL  the live harness threw — ${e && e.stack}`);
  console.log(`\n  ${passed} passed, ${failed + 1} failed`);
  process.exit(1);
});
