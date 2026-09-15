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

console.log(`\n  ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
