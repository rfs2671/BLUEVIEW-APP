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
// 8. THE RENDER QUEUE, AND THE BYTE BUDGET.
//
//    THE DEFECT, MEASURED. `renderSlot` guards per slot (`if (slot.busy)
//    return;`) and NOTHING caps the global in-flight count. The observer's
//    callback arrives with every in-band page at once and calls `renderSlot`
//    on each, so a dozen rasterisations start on one thread and each one's
//    wall clock contains all the others. On the operator's phone, 26-page
//    plan, 1.2 MP a sheet, that is a monotonic climb:
//
//        4585 4591 4749 4912 5323 5465 5886 6304 6310 6668
//        6935 7529 7601 7933 8214 8790 8970 9004 9281 9490
//
//    Uncontended, the same 1.2 MP page renders in 2252 ms — and 11.2 MP in
//    727 ms. Total work is unchanged by a cap; what changes is that the page
//    the reader is looking at finishes in its own time instead of last behind
//    eleven others.
//
//    AND ORDER MATTERS AS MUCH AS THE CAP. A queue of one that still starts
//    with page 12 because page 12 was first in the loop fixes nothing, which
//    is why "the first page rasterised is the one nearest the viewport" and
//    "the choice is re-made as the reader scrolls" are asserted here and not
//    left to the comment that claims them.
//
//    WHY IT HAD TO EXECUTE. An AST walk can see that a cap constant exists.
//    It cannot see that two renders never overlap — that is a property of the
//    running page, and this sandbox is the only thing in the repo that runs it.
// ═══════════════════════════════════════════════════════════════════════════

// The operator's document: 26 sheets, and on his device a rendered page is
// 886 px tall against an 883 px viewport — a band of 1.5 is a prefetch depth
// of about 3.6 sheets.
//
// TWO GEOMETRIES, ON PURPOSE.
//   pageH 886 (REAL_PAGE_H) is his device, and it is what the byte-budget
//     cases use: `trim()` may never free a page still in the band, so a
//     budget can only be measured against a band of a realistic width.
//   pageH 150 packs a crowd into the same band with no scrolling, which is
//     the condition the concurrency defect needs — a dozen pages handed to
//     the observer in one callback.
const PAGES = 26;
const PAGE_GAP = 10;
const VIEW_H = 800;
const REAL_PAGE_H = 886;
const CROWD_PAGE_H = 150;

function bootRender(opts = {}) {
  const {
    search = '?file=file%3A%2F%2F%2Fplan.pdf',
    // 48x36" landscape — a plan sheet, which is what this viewer exists for.
    ptW = 3456,
    ptH = 2592,
    clientWidth = 390,
    dpr = 2,
    zoom = 1,
    pageH = 150,
    // THE DEVICE'S REAL CANVAS DIMENSION LIMIT. The operator's Pixel 10 Pro XL
    // passes a 16384 edge — the probe's ladder measured it — and the viewer is
    // no longer allowed to assume that of every device. A canvas asked for
    // more than this refuses the assignment, which is the signal the real
    // thing gives and the one `measureCanvasEdge()` reads.
    deviceMaxEdge = 16384,
  } = opts;
  const PAGE_H = pageH;

  const posted = [];
  const listeners = {};
  const renders = [];
  const canvases = [];
  const timers = [];
  const observers = [];
  let now = 0;
  let nextId = 1;
  let inFlight = 0;
  let maxInFlight = 0;
  let scrollTop = 0;
  let divs = 0;
  const hooks = { onRenderStart: null };

  function schedule(ms, fn) {
    const id = nextId; nextId += 1;
    timers.push({ id, at: now + (Number(ms) || 0), fn });
    return id;
  }

  function rectFor(i) {
    const top = (i * (PAGE_H + PAGE_GAP)) - scrollTop;
    return { top, bottom: top + PAGE_H };
  }

  function makeEl(tag) {
    const el = {
      tag,
      style: {}, textContent: '', innerHTML: '', className: '',
      parentNode: null, __slot: null,
      appendChild() {}, removeChild() {},
      getBoundingClientRect() {
        return (typeof el.__i === 'number') ? rectFor(el.__i) : { top: 0, bottom: PAGE_H };
      },
      getContext: () => (el.__w > 0 && el.__h > 0 ? {
        fillStyle: '', fillRect() {},
        getImageData: () => ({ data: [0, 0, 0, 255] }),
      } : null),
      addEventListener(t, f) { listeners[`el:${t}`] = f; },
    };
    // A CANVAS THAT CAN REFUSE. A real one does not throw when asked for an
    // edge past the device limit — it silently keeps the old value, which is
    // exactly why `measureCanvasEdge()` has to read the property BACK rather
    // than trust the assignment. Modelling the refusal is the only way the
    // unknown-capability branch can be exercised at all.
    el.__w = 0;
    el.__h = 0;
    Object.defineProperty(el, 'width', {
      get() { return el.__w; },
      set(v) { if (tag !== 'canvas' || v <= deviceMaxEdge) el.__w = v; },
    });
    Object.defineProperty(el, 'height', {
      get() { return el.__h; },
      set(v) { if (tag !== 'canvas' || v <= deviceMaxEdge) el.__h = v; },
    });
    if (tag === 'div') { el.__i = divs; divs += 1; }
    if (tag === 'canvas') canvases.push(el);
    return el;
  }

  function makePage(n) {
    const page = {
      _n: n,
      getViewport({ scale }) {
        return { width: ptW * scale, height: ptH * scale, scale, __scale: scale };
      },
      getOperatorList() { return Promise.resolve({ fnArray: [], argsArray: [] }); },
      objs: { get() { return null; } },
      cleanup() { return true; },
      render(o) {
        inFlight += 1;
        if (inFlight > maxInFlight) maxInFlight = inFlight;
        const scale = (o && o.viewport && o.viewport.__scale) || 0;
        const rec = {
          page: n,
          order: renders.length,
          scale,
          // THE TIER, DERIVED FROM THE CANVAS RATHER THAN ANNOUNCED. The page
          // could tell the harness which tier it thinks it is rendering; the
          // pixel count is what the reader and the byte budget actually get.
          mp: (ptW * scale * ptH * scale) / 1e6,
          inFlightAtStart: inFlight,
          cancelled: false,
        };
        renders.push(rec);
        if (hooks.onRenderStart) hooks.onRenderStart(rec);
        const promise = new Promise((resolve, reject) => {
          schedule(5, () => {
            inFlight -= 1;
            if (rec.cancelled) {
              const e = new Error('cancelled');
              e.name = 'RenderingCancelledException';
              reject(e);
            } else resolve();
          });
        });
        return { promise, cancel() { rec.cancelled = true; } };
      },
    };
    return page;
  }

  const pageCache = {};
  const pdfStub = {
    numPages: PAGES,
    getPage(n) {
      if (!pageCache[n]) pageCache[n] = makePage(n);
      return Promise.resolve(pageCache[n]);
    },
    destroy() { return Promise.resolve(); },
  };

  const bodyBytes = new Uint8Array(64);
  function XHR() {
    this.responseType = '';
    this.response = null;
    this.responseText = '';
    this.onload = null;
    this.onerror = null;
    this.open = () => {};
    this.send = () => {
      schedule(1, () => {
        if (this.responseType === 'arraybuffer') this.response = bodyBytes.buffer;
        else this.responseText = 'stub';
        if (this.onload) this.onload();
      });
    };
  }

  // A REAL OBSERVER, not a no-op. It honours the rootMargin the page asked
  // for, and it delivers every observed element in PAGE ORDER — the worst
  // case for the ordering bug, and what a real initial observation does.
  function IO(cb, o) {
    const self = this;
    self.cb = cb;
    self.margin = (() => {
      const m = /(-?\d+(?:\.\d+)?)%/.exec((o && o.rootMargin) || '0%');
      return m ? Number(m[1]) / 100 : 0;
    })();
    self.els = [];
    self.live = true;
    self.observe = (el) => { self.els.push(el); };
    self.disconnect = () => { self.live = false; self.els = []; };
    observers.push(self);
  }

  function deliverIO() {
    const io = observers.filter((o) => o.live).pop();
    if (!io) return 0;
    const entries = io.els.map((el) => {
      const r = el.getBoundingClientRect();
      const pad = io.margin * VIEW_H;
      return { target: el, isIntersecting: r.bottom > -pad && r.top < VIEW_H + pad };
    });
    io.cb(entries);
    return entries.filter((e) => e.isIntersecting).length;
  }

  const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    document: {
      getElementById: () => makeEl('span'),
      createElement: (tag) => makeEl(tag),
      documentElement: { clientWidth, clientHeight: VIEW_H },
      addEventListener(t, f) { listeners[`doc:${t}`] = f; },
    },
    screen: { width: clientWidth, height: VIEW_H },
    navigator: { userAgent: 'stub', deviceMemory: 8, hardwareConcurrency: 8 },
    performance: { now: () => now, getEntriesByType: () => [] },
    XMLHttpRequest: XHR,
    IntersectionObserver: IO,
    pdfjsLib: {
      GlobalWorkerOptions: {},
      OPS: {},
      getDocument: () => ({ promise: Promise.resolve(pdfStub) }),
    },
    setTimeout: (fn, ms) => schedule(ms, fn),
    clearTimeout: () => {},
    setInterval: () => { const id = nextId; nextId += 1; return id; },
    clearInterval: () => {},
    Promise, Math, JSON, String, Number, Date, Object, RegExp, Array, Error,
    Uint8Array, ArrayBuffer, Boolean, isNaN, parseInt, parseFloat,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  sandbox.window.location = { search };
  sandbox.window.devicePixelRatio = dpr;
  sandbox.window.innerHeight = VIEW_H;
  sandbox.window.innerWidth = clientWidth;
  sandbox.window.scrollTo = () => {};
  sandbox.window.addEventListener = (t, f) => { listeners[`win:${t}`] = f; };
  sandbox.window.removeEventListener = () => {};
  sandbox.window.ReactNativeWebView = {
    postMessage: (s) => { try { posted.push(JSON.parse(s)); } catch (_e) {} },
  };
  sandbox.window.visualViewport = {
    scale: zoom,
    addEventListener(t, f) { listeners[`vv:${t}`] = f; },
  };

  let threw = null;
  try {
    vm.createContext(sandbox);
    vm.runInContext(viewerScript(), sandbox, { filename: 'viewer.html' });
  } catch (e) { threw = e; }

  // A vm context keeps V8's own built-ins, so `WebAssembly` is real in there
  // and settles on a FOREGROUND task, not a microtask — hence the setImmediate.
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

  // A LIVE canvas is one that still holds its backing store. `releaseSlot`
  // zeroes width and height, which is the only step that actually returns the
  // megabytes, so a zeroed element is a freed one.
  const live = () => canvases.filter((c) => c.width > 0 && c.height > 0);
  // SHARP vs DRAFT, told apart by size and not by a label. A draft is ~0.5 MP
  // (2 MB) and a sharp sheet ~16 MP (64 MB); anything over 8 MP is
  // unambiguously the expensive tier whatever the sheet's aspect.
  const SHARP_MIN_PX = 8e6;
  const sharpLive = () => live().filter((c) => c.width * c.height >= SHARP_MIN_PX);

  return {
    posted, listeners, renders, canvases, sandbox, pump, deliverIO, hooks,
    setScroll(v) { scrollTop = v; },
    get scrollTop() { return scrollTop; },
    get threw() { return threw; },
    get maxInFlight() { return maxInFlight; },
    livePages() { return live().length; },
    sharpPages() { return sharpLive().length; },
    largestEdge() { return live().reduce((a, c) => Math.max(a, c.width, c.height), 0); },
    largestCanvas() {
      return live().reduce((a, c) => ((c.width * c.height) > (a.width * a.height) ? c : a),
        { width: 0, height: 0 });
    },
    canvasBytes() {
      return live().reduce((a, c) => a + (c.width * c.height * 4), 0);
    },
  };
}

const MB = 1048576;

async function main() {
  console.log('\n── one render at a time, nearest first ───────────────────────\n');

  // The reader is looking at page 7 (index 6). Every page from 1 to 18 is in
  // the band, and the observer hands them over in PAGE ORDER — so page 1 is
  // first in the loop and page 7 is the one on screen.
  const live = bootRender();
  live.setScroll(6 * (CROWD_PAGE_H + PAGE_GAP));
  await live.pump();
  const visible = live.deliverIO();
  await live.pump();

  ok(!live.threw, `the viewer opens and lays out without throwing${
    live.threw ? ` — ${String(live.threw && live.threw.stack).split('\n')[0]}` : ''}`);
  ok(visible >= 10,
    `the band really does hold a crowd — ${visible} pages reported visible at once`);

  // THE CAP. This is the fix.
  ok(live.maxInFlight === 1,
    `never more than one rasterisation in flight (peak ${live.maxInFlight} of ${visible} visible)`);

  // THE ORDER. A cap that still starts with page 1 leaves the reader watching
  // a white screen while six sheets he cannot see are drawn ahead of his.
  ok(live.renders.length > 0 && live.renders[0].page === 7,
    `the first page rasterised is the one on screen, not the first in the loop `
    + `(got page ${live.renders.length ? live.renders[0].page : 'none'}, wanted 7)`);

  // EVERY in-band page still gets drawn. A cap must reorder work, not drop it.
  {
    const drawn = new Set(live.renders.map((r) => r.page));
    ok(drawn.size >= visible,
      `all ${visible} visible pages are eventually drawn, just not at once (got ${drawn.size})`);
  }

  // ── THE QUEUE IS RE-SORTED, NOT FIFO ───────────────────────────────────
  // A page that was nearest when it was queued is not nearest ten seconds
  // later. The reader starts on page 7 and flicks to page 19 while the first
  // render is still in flight; the NEXT page chosen must be 19, not 8.
  //
  // 19 AND NOT 20, DELIBERATELY. The queue holds what the observer has
  // reported — at the starting scroll that is pages 1 to 19 — so 19 is the
  // nearest AVAILABLE page and the honest answer. A FIFO answers 8.
  {
    const s = bootRender();
    s.setScroll(6 * (CROWD_PAGE_H + PAGE_GAP));
    await s.pump();
    s.hooks.onRenderStart = (rec) => {
      if (rec.order === 0) s.setScroll(18 * (CROWD_PAGE_H + PAGE_GAP));
    };
    s.deliverIO();
    await s.pump();
    const got = s.renders.slice(0, 3).map((r) => r.page);
    ok(s.renders.length >= 2 && s.renders[0].page === 7 && s.renders[1].page === 19,
      'the second choice is re-made against where the reader is NOW '
      + `(got ${got.join(' -> ') || 'none'}, wanted 7 -> 19; a FIFO answers 7 -> 8)`);
    ok(s.maxInFlight === 1, `and still one at a time while scrolling (peak ${s.maxInFlight})`);
  }

  // ── A PAGE THAT LEAVES THE BAND WHILE QUEUED IS NOT DRAWN ──────────────
  // Queued work for a page the reader has scrolled away from is work stolen
  // from the page he is actually looking at.
  {
    const s = bootRender();
    await s.pump();
    s.hooks.onRenderStart = (rec) => {
      if (rec.order !== 0) return;
      // Jump far down the document and tell the observer about it, which is
      // what a real scroll does.
      s.setScroll(22 * (CROWD_PAGE_H + PAGE_GAP));
      s.deliverIO();
    };
    s.deliverIO();
    await s.pump();
    const drawn = new Set(s.renders.map((r) => r.page));
    ok(!drawn.has(5) && !drawn.has(6),
      `pages abandoned mid-queue are never rasterised (drawn: ${[...drawn].sort((a, b) => a - b).join(',')})`);
    ok(drawn.has(23),
      'and the pages the reader scrolled TO are');
  }

  console.log('\n── the resident set is bounded by bytes, not by page count ────\n');

  // ── THE BUDGET IS BYTES ────────────────────────────────────────────────
  // `KEEP_RENDERED = 7` never bound anything: `trim()` skips any page marked
  // `visible` and the band marks several. And a page count is the wrong unit
  // anyway — the same 7 pages are 31 MB at the viewport scale and 350 MB
  // zoomed in. Evicting is not free either: every eviction is a re-decode
  // costing seconds, which is the operator's 5–6 second scroll-back.
  {
    const s = bootRender({ pageH: REAL_PAGE_H });
    await s.pump();
    // Walk the whole document so every page is rendered and then leaves the
    // band, which is the only state in which trim() may free anything.
    for (let i = 0; i < PAGES; i += 1) {
      s.setScroll(i * (REAL_PAGE_H + PAGE_GAP));
      s.deliverIO();
      await s.pump();
    }
    const kept = s.livePages();
    const bytes = s.canvasBytes();
    const perPage = kept ? bytes / kept : 0;

    // STOP EVICTING. With the band only four or five sheets wide, a count of
    // 7 leaves barely two pages of scroll-back — and every one thrown away is
    // ~857 decode operations to recreate, which is the operator's 5-6 second
    // reload. The budget should be FULL, not nearly empty.
    ok(kept >= 16,
      `scroll-back is cached, not thrown away — ${kept} of ${PAGES} pages at `
      + `${(perPage / MB).toFixed(2)} MB still resident after a full scroll`);
    ok(bytes > 48 * MB && bytes <= 128 * MB,
      `and the resident bitmap fills a byte budget rather than a page count `
      + `(${(bytes / MB).toFixed(1)} MB)`);
    ok(s.maxInFlight === 1,
      `one at a time across the whole document (peak ${s.maxInFlight})`);
  }

  // ── AND THE SAME BUDGET HOLDS WHEN THE READER PINCHES IN ───────────────
  //
  // WHAT THIS CASE USED TO ASSERT, AND WHY IT NO LONGER CAN. Under the single
  // tier, a pinch was the RESOLUTION switch: every in-band sheet jumped to
  // 12.58 MP / ~50 MB, and the case checked that the budget then kept only two
  // or three of them. With the progressive tiers the pinch no longer changes
  // any sheet's scale — the one in front of the reader was already sharp the
  // moment it became primary, and the rest are drafts whatever the zoom is.
  // Asserting the old shape here would be asserting a design that is gone.
  //
  // WHAT IS STILL TRUE, AND IS THE PART THAT MATTERED: the budget is priced
  // off the canvas that was really allocated, so the expensive sheet is
  // counted at its real 64 MB and the ceiling holds. And the pinch still does
  // the one thing it is now for — BAND_SHARP narrows the prefetch, so a reader
  // examining one sheet is not also holding four he is not looking at.
  {
    const s = bootRender({ ptW: 2592, ptH: 1728, zoom: 2, pageH: REAL_PAGE_H });
    await s.pump();
    for (let i = 0; i < PAGES; i += 1) {
      s.setScroll(i * (REAL_PAGE_H + PAGE_GAP));
      s.deliverIO();
      await s.pump();
    }
    const kept = s.livePages();
    const bytes = s.canvasBytes();
    ok(s.sharpPages() === 1,
      `pinched in, exactly one sheet is at the expensive tier (${s.sharpPages()})`);
    const big = s.largestCanvas();
    ok(big.width * big.height * 4 > 32 * MB,
      `and it really is the expensive one (${((big.width * big.height * 4) / MB).toFixed(1)} MB, `
      + `${big.width}x${big.height})`);
    ok(kept > 0 && bytes > 0 && bytes <= 128 * MB,
      `the ceiling still holds with an expensive sheet resident (${
        (bytes / MB).toFixed(1)} MB over ${kept} sheets)`);
  }

  // ── THE BAND IS NOT TIGHTENED ──────────────────────────────────────────
  // Tightening the band evicts more, and every eviction is a five-second
  // debt. 1.5 is a prefetch depth of about 3.6 sheets on the operator's
  // device and is defensible; this is here so a later memory scare cannot
  // quietly pay for itself out of the reader's scroll-back.
  {
    const src = fs.readFileSync(VIEWER, 'utf8');
    ok(/var BAND = 1\.5;/.test(src), 'BAND is still 1.5');
    ok(/var BAND_SHARP = 0\.25;/.test(src), 'and BAND_SHARP is still 0.25');
  }

  // ── THE CAP IS ONE EDIT ────────────────────────────────────────────────
  // If 1 leaves prefetch too slow, 2 is a tuning question — and must be a
  // one-line answer, not a re-read of the render path.
  {
    const src = fs.readFileSync(VIEWER, 'utf8');
    const m = /var MAX_CONCURRENT_RENDERS = (\d+);/.exec(src);
    ok(!!m, 'the cap is a named constant');
    ok(!!m && Number(m[1]) === 1,
      `and it is 1 — the thread is the resource (found ${m ? m[1] : 'nothing'})`);
  }

  console.log('\n── the sheet in front of the reader arrives in two passes ─────\n');

  // ═════════════════════════════════════════════════════════════════════════
  // 9. PROGRESSIVE RENDER, AND WHY A CAP ALONE IS NOT ENOUGH.
  //
  //    The queue cap above fixes the ORDER — the reader's sheet is drawn
  //    first instead of twelfth. It does not change what that first draw
  //    COSTS, and the operator's isolated numbers say the cost is mostly
  //    fixed: 0.5 MP renders in ~465 ms and 11.2 MP in 732 ms, so roughly
  //    450 ms is per-page decode and only ~25 ms is per megapixel.
  //
  //    THAT SPLIT IS THE WHOLE DESIGN. It means a cheap first pass is barely
  //    cheaper than an expensive one, so there is no point drafting anything
  //    the reader is not looking at — but it also means the reader can have
  //    SOMETHING at 465 ms instead of nothing at 1400, and the sharp pass can
  //    follow it on the same page without ever having been in the way.
  //
  //    SO: every in-band sheet gets a draft, and ONLY the sheet actually on
  //    screen is ever promoted. An off-screen sheet that got a sharp pass
  //    would be 64 MB spent on something nobody is reading.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const s = bootRender({ pageH: REAL_PAGE_H });
    await s.pump();
    s.deliverIO();
    await s.pump();

    ok(!s.threw, `the viewer opens progressively without throwing${
      s.threw ? ` — ${String(s.threw && s.threw.stack).split('\n')[0]}` : ''}`);

    const first = s.renders[0];
    const second = s.renders[1];
    ok(!!first && first.page === 1 && first.mp < 1,
      `the first thing drawn is a DRAFT of the sheet on screen (page ${
        first && first.page}, ${first && first.mp.toFixed(2)} MP — wanted page 1 under 1 MP)`);
    ok(!!second && second.page === 1 && second.mp > 8,
      `and the very next thing is the SHARP pass for that same sheet (page ${
        second && second.page}, ${second && second.mp.toFixed(1)} MP — wanted page 1 over 8 MP)`);

    // NOT AFTER THE NEIGHBOURS. Two drafts of pages the reader cannot fully
    // see are ~930 ms, which is the difference between a sharp sheet at 1.4 s
    // and one at 2.4 s — and 1.5 s is the acceptance.
    ok(s.renders.length > 1 && s.renders[1].page === 1,
      'the sharp pass jumps ahead of the neighbours\' drafts, because nearness '
      + 'orders the queue and the sheet on screen is the only one at distance 0');

    // ONLY THE SHEET ON SCREEN. Every other page must stay a draft forever.
    const sharpPages = new Set(s.renders.filter((r) => r.mp > 8).map((r) => r.page));
    ok(sharpPages.size === 1 && sharpPages.has(1),
      `no off-screen sheet is ever promoted (sharp pages: ${[...sharpPages].join(',') || 'none'})`);

    // AND EVERY IN-BAND SHEET STILL GETS SOMETHING. A progressive render that
    // only ever drew one page would have replaced a slow viewer with an empty
    // one.
    const drafted = new Set(s.renders.filter((r) => r.mp < 1).map((r) => r.page));
    ok(drafted.size >= 3,
      `the rest of the band is still drafted behind it (${drafted.size} pages drafted)`);
    ok(s.maxInFlight === 1, `and still one rasterisation at a time (peak ${s.maxInFlight})`);
  }

  // ── THE PROMOTION FOLLOWS THE READER ───────────────────────────────────
  // A sharp pass pinned to page 1 for the life of the document would be the
  // same defect in a different place. Scroll, and the sheet now on screen is
  // the one that gets promoted.
  {
    const s = bootRender({ pageH: REAL_PAGE_H });
    await s.pump();
    s.deliverIO();
    await s.pump();
    s.setScroll(5 * (REAL_PAGE_H + PAGE_GAP));
    s.deliverIO();
    await s.pump();
    const sharpPages = s.renders.filter((r) => r.mp > 8).map((r) => r.page);
    ok(sharpPages.includes(6),
      `the sheet scrolled to is promoted in its turn (sharp: ${sharpPages.join(',') || 'none'})`);

    // ── AND NEVER TWO SHARP SHEETS AT ONCE ───────────────────────────────
    // This is the invariant the byte budget is priced on. A sharp sheet is
    // 64 MB; two would be 128 MB of bitmap before a single draft is counted,
    // and the budget below would be a number with no relationship to what the
    // page actually holds.
    ok(s.sharpPages() <= 1,
      `only one sharp sheet is ever resident (${s.sharpPages()} live)`);
  }

  console.log('\n── work for a sheet the reader left is stopped, not finished ──\n');

  // ═════════════════════════════════════════════════════════════════════════
  // 10. CANCEL ON LEAVING THE BAND.
  //
  //     `dequeue` already takes an abandoned sheet out of the LINE. It does
  //     nothing about one that has already started, and with one render at a
  //     time that in-flight sheet is holding the only thread there is — so
  //     the page the reader just scrolled to waits behind a page he has left.
  //
  //     Two mechanisms, and they are NOT interchangeable:
  //       RenderTask.cancel()  stops the WORK. Only pdf.js can stop
  //                            rasterising, and this is the only thing that
  //                            asks it to.
  //       slot.gen             stops the RESULT being used. cancel() is a
  //                            request, not a guarantee, and a render can
  //                            still complete in the window after it.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const s = bootRender({ pageH: REAL_PAGE_H });
    await s.pump();
    s.hooks.onRenderStart = (rec) => {
      if (rec.order !== 0) return;
      // ONE TURN LATER, NOT INSIDE page.render(). The stub calls this hook
      // from within `page.render(...)`, which is BEFORE the viewer has
      // assigned the returned task to `slot.task` — there is nothing to cancel
      // yet at that instant, and a real scroll never lands there. Scheduling
      // it puts the scroll where a reader's would be: after the render has
      // started and while it is still running.
      s.sandbox.setTimeout(() => {
        s.setScroll(20 * (REAL_PAGE_H + PAGE_GAP));
        s.deliverIO();
      }, 1);
    };
    s.deliverIO();
    await s.pump();
    ok(!s.threw, `leaving the band mid-render does not throw${
      s.threw ? ` — ${String(s.threw && s.threw.stack).split('\n')[0]}` : ''}`);
    ok(s.renders[0] && s.renders[0].cancelled === true,
      'the rasterisation already running for the abandoned sheet is CANCELLED, '
      + 'not left to finish — with one thread, finishing it is the reader waiting');
    const drawn = new Set(s.renders.map((r) => r.page));
    ok(drawn.has(21),
      `and the sheet the reader went to is drawn (drawn: ${[...drawn].sort((a, b) => a - b).join(',')})`);
  }

  console.log('\n── the edge cap is measured, not assumed ─────────────────────\n');

  // ═════════════════════════════════════════════════════════════════════════
  // 11. FIT TO MAX_CANVAS_PX, NOT TO A 4096 EDGE.
  //
  //     `MAX_CANVAS_EDGE = 4096` was the binding clamp on every large sheet,
  //     which is why a 36x48 drawing landed at 85 ppi and why the file's own
  //     comment says lowering TARGET_PPI would change nothing. The operator's
  //     device passes a 16384 edge — the probe's ladder measured it — so the
  //     cap was leaving resolution unused for no reason anyone had checked.
  //
  //     MEASURED, NOT ASSUMED. 16384 is this device. A cheap read at boot says
  //     what THIS device does, an absolute guard bounds what any device may be
  //     asked for, and an unknown answer falls back to the 4096 the viewer has
  //     always shipped rather than to the optimistic number.
  // ═════════════════════════════════════════════════════════════════════════
  {
    // 36x24" landscape: 2592x1728 pt. Fitting 16 MP gives 4899 x 3266, which
    // is 136 ppi across the 36" — against 85 ppi at a 4096 edge.
    const s = bootRender({ ptW: 2592, ptH: 1728, pageH: REAL_PAGE_H });
    await s.pump();
    s.deliverIO();
    await s.pump();
    const big = s.largestCanvas();
    const px = big.width * big.height;
    ok(px > 14e6 && px <= 16e6 + 1,
      `the sharp sheet fills the 16 MP budget (${big.width}x${big.height} = ${
        (px / 1e6).toFixed(1)} MP)`);
    ok(big.width > 4096,
      `and is no longer held at a 4096 edge (${big.width} px across)`);
    const ppi = big.width / 36;
    ok(ppi > 130 && ppi < 142,
      `which is ~136 ppi on a 36" sheet rather than 85 (got ${ppi.toFixed(0)})`);
  }

  // ── AND A DEVICE THAT IS NOT HIS ───────────────────────────────────────
  // The whole point of measuring is that the answer differs. A WebView that
  // refuses anything past 4096 must be held there, not handed a canvas it
  // cannot allocate — a silent refusal is a blank sheet, which is worse than
  // a soft one.
  {
    const s = bootRender({ ptW: 2592, ptH: 1728, pageH: REAL_PAGE_H, deviceMaxEdge: 4096 });
    await s.pump();
    s.deliverIO();
    await s.pump();
    ok(!s.threw, `a 4096-limited device still opens${
      s.threw ? ` — ${String(s.threw && s.threw.stack).split('\n')[0]}` : ''}`);
    ok(s.largestEdge() > 0 && s.largestEdge() <= 4096,
      `and every canvas it allocates fits inside what it will give (largest edge ${
        s.largestEdge()})`);
    ok(s.renders.length > 0,
      'and it still draws — the fallback is a smaller sheet, never no sheet');
  }

  // ── THE ABSOLUTE GUARD IS STILL THERE ──────────────────────────────────
  // A measured capability is a reading off one WebView, and a WebView that
  // over-reports would be handed an allocation that takes the renderer down.
  // The guard is what nothing may exceed regardless of what the device claims.
  {
    const src = fs.readFileSync(VIEWER, 'utf8');
    const guard = /var MAX_CANVAS_EDGE = (\d+);/.exec(src);
    ok(!!guard, 'there is still an absolute edge guard');
    ok(!!guard && Number(guard[1]) >= 4096 && Number(guard[1]) <= 32768,
      `and it is a sane ceiling rather than removed (${guard ? guard[1] : 'gone'})`);
    ok(/var CANVAS_EDGE_FALLBACK = 4096;/.test(src),
      'and an unknown capability falls back to the 4096 this viewer has always '
      + 'shipped, not to the optimistic number');
    ok(/function measureCanvasEdge\(\)/.test(src),
      'the capability is read off the device rather than assumed');
  }

  console.log('\n── the byte budget re-derived against a 64 MB sheet ───────────\n');

  // ═════════════════════════════════════════════════════════════════════════
  // 12. THE BUDGET SURVIVES THE BIGGER SHEET.
  //
  //     96 MB was derived when the expensive sheet was 12.58 MP / 50 MB. A
  //     sharp sheet is now 16 MP — 64 MB of RGBA — and the budget has to be
  //     re-derived against that or it is a number inherited from arithmetic
  //     that no longer applies.
  //
  //     WHAT HAS TO FIT: one sharp sheet (64 MB, and never two — see 9) plus
  //     the whole 26-sheet plan cached as 0.5 MP drafts (52 MB) = 116 MB.
  //     128 MB is that with slack.
  //
  //     AND IT IS PRICED OFF THE CANVAS, which is why it survived the change
  //     at all: `canvasBytes()` reads width and height off the bitmap that was
  //     really allocated, so it prices a 2 MB draft and a 64 MB sharp sheet
  //     correctly with no knowledge of tiers whatsoever.
  // ═════════════════════════════════════════════════════════════════════════
  {
    const s = bootRender({ ptW: 2592, ptH: 1728, pageH: REAL_PAGE_H });
    await s.pump();
    let peakBytes = 0;
    let peakSharp = 0;
    for (let i = 0; i < PAGES; i += 1) {
      s.setScroll(i * (REAL_PAGE_H + PAGE_GAP));
      s.deliverIO();
      await s.pump();
      peakBytes = Math.max(peakBytes, s.canvasBytes());
      peakSharp = Math.max(peakSharp, s.sharpPages());
    }
    ok(peakSharp === 1,
      `never more than one sharp sheet across a whole document (peak ${peakSharp})`);
    ok(peakBytes <= 128 * MB,
      `and the resident bitmap never passes the budget (peak ${(peakBytes / MB).toFixed(1)} MB)`);
    // NOT NEARLY EMPTY EITHER. Every eviction is a ~465 ms re-decode, and a
    // budget that threw the plan away to stay small would be paying for
    // memory with the reader's scroll-back.
    ok(s.livePages() >= 16,
      `while still caching the scroll-back (${s.livePages()} of ${PAGES} sheets resident)`);
    ok(s.maxInFlight === 1, `one at a time throughout (peak ${s.maxInFlight})`);
  }

  {
    const src = fs.readFileSync(VIEWER, 'utf8');
    const b = /var CANVAS_BUDGET_BYTES = (\d+) \* 1048576;/.exec(src);
    ok(!!b, 'the budget is a named constant in megabytes');
    ok(!!b && Number(b[1]) === 128,
      `re-derived against the 64 MB sharp sheet: 64 + 26 drafts at 2 MB = 116, `
      + `so 128 (found ${b ? b[1] : 'nothing'})`);
    ok(/function canvasBytes\(slot\)\{/.test(src)
      && /\(c\.width \|\| 0\) \* \(c\.height \|\| 0\) \* 4/.test(src),
      'and the cost is still read off the canvas that was really allocated, '
      + 'never inferred from a scale — which is why it survived the tier change');
    ok(/var DRAFT_CANVAS_PX = 500000;/.test(src),
      'the draft tier is a named pixel budget, so raising it is one edit');
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
