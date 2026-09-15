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
      parentNode: null, __slot: null, width: 0, height: 0,
      appendChild() {}, removeChild() {},
      getBoundingClientRect() {
        return (typeof el.__i === 'number') ? rectFor(el.__i) : { top: 0, bottom: PAGE_H };
      },
      getContext: () => ({
        fillStyle: '', fillRect() {},
        getImageData: () => ({ data: [0, 0, 0, 255] }),
      }),
      addEventListener(t, f) { listeners[`el:${t}`] = f; },
    };
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
        const rec = {
          page: n,
          order: renders.length,
          canvasW: o && o.canvasContext ? 0 : 0,
          inFlightAtStart: inFlight,
        };
        renders.push(rec);
        if (hooks.onRenderStart) hooks.onRenderStart(rec);
        let cancelled = false;
        const promise = new Promise((resolve, reject) => {
          schedule(5, () => {
            inFlight -= 1;
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

  return {
    posted, listeners, renders, canvases, sandbox, pump, deliverIO, hooks,
    setScroll(v) { scrollTop = v; },
    get scrollTop() { return scrollTop; },
    get threw() { return threw; },
    get maxInFlight() { return maxInFlight; },
    livePages() { return canvases.filter((c) => c.width > 0 && c.height > 0).length; },
    canvasBytes() {
      return canvases
        .filter((c) => c.width > 0 && c.height > 0)
        .reduce((a, c) => a + (c.width * c.height * 4), 0);
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

  // ── AND THE SAME BUDGET HOLDS WHEN THE PAGES GET BIG ───────────────────
  // A reader who has pinched in gets 12.58 MP sheets — about 50 MB each. The
  // budget must derive the page count from the ACTUAL canvas at render time,
  // not from a scale someone assumed.
  {
    const s = bootRender({ zoom: 2, pageH: REAL_PAGE_H });
    await s.pump();
    for (let i = 0; i < PAGES; i += 1) {
      s.setScroll(i * (REAL_PAGE_H + PAGE_GAP));
      s.deliverIO();
      await s.pump();
    }
    const kept = s.livePages();
    const bytes = s.canvasBytes();
    const perPage = kept ? bytes / kept : 0;
    ok(perPage > 32 * MB,
      `the zoomed sheets really are the expensive ones (${(perPage / MB).toFixed(1)} MB each)`);
    ok(kept > 0 && kept <= 3,
      `zoomed in, the same budget keeps only ${kept} sheet(s) — the count is `
      + 'derived from the canvas, not assumed');
    ok(bytes > 0 && bytes <= 128 * MB,
      `and the ceiling still holds at the expensive scale (${(bytes / MB).toFixed(1)} MB)`);
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
}

main().then(() => {
  console.log(`\n  ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}).catch((e) => {
  console.log(`  FAIL  the live harness threw — ${e && e.stack}`);
  console.log(`\n  ${passed} passed, ${failed + 1} failed`);
  process.exit(1);
});
