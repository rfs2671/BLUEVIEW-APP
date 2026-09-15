/**
 * THE OFFLINE VIEWER GIVES PAGES BACK.
 *
 * The admin PDF viewer froze and then died AFTER the document had loaded, over
 * and over, with no correlation to file size — the tell that it was the number
 * of sheets SCROLLED PAST, not the bytes read. The staged pdf.js page in
 * pdfjsViewer.js built a fresh <canvas> per page, appended it, and never took
 * one back: the IntersectionObserver had a branch for a page arriving and none
 * for a page leaving, no canvas was ever removed or zeroed, the observer was
 * never disconnected, and if IntersectionObserver was missing the fallback
 * rasterised the entire set in one loop. At roughly 4–8 MB of backing bitmap a
 * sheet, a 200-page plan set walked the WebView into the OOM killer.
 *
 * WHAT IS HELD HERE
 *   1. A page that leaves the band is actually FREED — removed from the DOM
 *      AND zeroed, because removal alone does not drop the backing store.
 *   2. The observer callback has a not-intersecting branch. Add-only is the
 *      defect.
 *   3. Both the eviction path and the disconnect are REACHABLE from the code
 *      that runs — a helper nothing calls would satisfy a grep and leak just
 *      the same.
 *   4. The no-IntersectionObserver fallback is bounded: no loop over every
 *      slot may rasterise unconditionally.
 *
 * READ AS THE GENERATED PAGE, NOT AS THE MODULE. viewer.html is assembled from
 * an array of JS strings, so the source file's own syntax says nothing about
 * what the WebView runs, and its comments would match a substring search for
 * exactly the words this test is looking for. So: rebuild the script the way
 * viewerHtml() does, parse THAT, and assert on its AST. Comments are gone by
 * construction.
 *
 * Run:  node src/utils/pdfjsViewerMemory.test.cjs
 */

const fs = require('fs');
const path = require('path');
const parser = require('@babel/parser');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
function done() {
  console.log(`\n  ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
}

function walk(node, fn, seen = new Set()) {
  if (!node || typeof node !== 'object' || seen.has(node)) return;
  seen.add(node);
  if (typeof node.type === 'string') fn(node);
  for (const k of Object.keys(node)) {
    if (k === 'loc' || k === 'leadingComments' || k === 'trailingComments') continue;
    const v = node[k];
    if (Array.isArray(v)) v.forEach((c) => walk(c, fn, seen));
    else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v, fn, seen);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Rebuild the script exactly as viewerHtml() writes it to disk.
// ═══════════════════════════════════════════════════════════════════════════
const modulePath = path.join(__dirname, 'pdfjsViewer.js');
const moduleTree = parser.parse(fs.readFileSync(modulePath, 'utf8'), {
  sourceType: 'module',
  plugins: ['jsx'],
});

/** Top-level `const X = 'literal'`, so the script's `'…' + WORKER_NAME + '…'`
 *  concatenations resolve the same way they do at staging time. */
const stringConsts = new Map();
let scriptArray = null;
for (const stmt of moduleTree.program.body) {
  const decl = stmt.type === 'VariableDeclaration' ? stmt
    : (stmt.type === 'ExportNamedDeclaration' && stmt.declaration
      && stmt.declaration.type === 'VariableDeclaration' ? stmt.declaration : null);
  if (!decl) continue;
  for (const d of decl.declarations) {
    if (!d.id || d.id.type !== 'Identifier') continue;
    if (d.id.name === 'VIEWER_SCRIPT') scriptArray = d.init;
    else if (d.init && d.init.type === 'StringLiteral') stringConsts.set(d.id.name, d.init.value);
  }
}

if (!scriptArray) {
  ok(false, 'pdfjsViewer.js declares VIEWER_SCRIPT');
  done();
}

function literalOf(node) {
  if (node.type === 'StringLiteral') return node.value;
  if (node.type === 'Identifier' && stringConsts.has(node.name)) return stringConsts.get(node.name);
  if (node.type === 'BinaryExpression' && node.operator === '+') {
    return literalOf(node.left) + literalOf(node.right);
  }
  throw new Error(`VIEWER_SCRIPT line is not a static string (${node.type})`);
}

// `[ … ].join('\n')`
const elements = scriptArray.type === 'CallExpression'
  ? scriptArray.callee.object.elements
  : scriptArray.elements;

let scriptText = null;
try {
  scriptText = elements.map(literalOf).join('\n');
} catch (e) {
  ok(false, `VIEWER_SCRIPT is a joined array of string literals — ${e.message}`);
  done();
}
ok(elements.length > 0 && typeof scriptText === 'string',
  'VIEWER_SCRIPT rebuilds into the page script');

let script = null;
try {
  script = parser.parse(scriptText, { sourceType: 'script' });
} catch (e) {
  ok(false, `the generated viewer script parses — ${e.message}`);
  done();
}
ok(!!script, 'the generated viewer script parses as a plain script');

// ═══════════════════════════════════════════════════════════════════════════
// A call graph over the script's named functions, so "is this reachable"
// is a question the test can actually answer.
// ═══════════════════════════════════════════════════════════════════════════
const fns = new Map();   // name -> FunctionDeclaration node
walk(script, (n) => {
  if (n.type === 'FunctionDeclaration' && n.id) fns.set(n.id.name, n);
});

/** Every name invoked inside `node`: plain calls by identifier, method calls by
 *  property name, and `new X(...)`. */
function callsIn(node) {
  const out = new Set();
  walk(node, (n) => {
    if (n.type !== 'CallExpression' && n.type !== 'NewExpression') return;
    const c = n.callee;
    if (!c) return;
    if (c.type === 'Identifier') out.add(c.name);
    else if (c.type === 'MemberExpression' && !c.computed && c.property.type === 'Identifier') {
      out.add(c.property.name);
    } else if (c.type === 'MemberExpression' && c.computed && c.property.type === 'StringLiteral') {
      out.add(c.property.value);
    }
  });
  return out;
}

/** Names reachable from `node`, following the script's own function
 *  declarations. A helper nothing calls is not reachable. */
function reachable(node) {
  const seen = new Set();
  const queue = [...callsIn(node)];
  while (queue.length) {
    const name = queue.shift();
    if (seen.has(name)) continue;
    seen.add(name);
    const fn = fns.get(name);
    if (fn) queue.push(...callsIn(fn.body));
  }
  return seen;
}

for (const required of ['renderSlot', 'watch', 'layout']) {
  ok(fns.has(required), `the viewer script still declares ${required}()`);
}

// ═══════════════════════════════════════════════════════════════════════════
// 1. THE EVICTION PATH EXISTS AND ACTUALLY FREES THE BITMAP.
//    Removal detaches the element; only width/height = 0 returns the memory.
// ═══════════════════════════════════════════════════════════════════════════
function zeroesADimension(fnNode, prop) {
  let hit = false;
  walk(fnNode, (n) => {
    if (n.type !== 'AssignmentExpression' || n.operator !== '=') return;
    const t = n.left;
    if (t.type !== 'MemberExpression' || t.computed) return;
    if (t.property.type !== 'Identifier' || t.property.name !== prop) return;
    if (n.right.type === 'NumericLiteral' && n.right.value === 0) hit = true;
  });
  return hit;
}

const evictors = [...fns.entries()].filter(([, node]) => (
  zeroesADimension(node, 'width')
  && zeroesADimension(node, 'height')
  && callsIn(node).has('removeChild')
));

ok(evictors.length > 0,
  'a function removes a canvas AND zeroes its width and height');

const evictorNames = new Set(evictors.map(([name]) => name));

// It must also let the slot be drawn again, or a page scrolled back to stays
// blank forever.
let resetsDone = false;
for (const [, node] of evictors) {
  walk(node, (n) => {
    if (n.type !== 'AssignmentExpression' || n.operator !== '=') return;
    if (n.left.type !== 'MemberExpression' || n.left.computed) return;
    if (n.left.property.type !== 'Identifier' || n.left.property.name !== 'done') return;
    if (n.right.type === 'BooleanLiteral' && n.right.value === false) resetsDone = true;
  });
}
ok(resetsDone, 'the eviction path clears slot.done so the page can be redrawn');

// ═══════════════════════════════════════════════════════════════════════════
// 2. THE OBSERVER HAS A NOT-INTERSECTING BRANCH.
//    Add-only is the defect: the page was told what arrived and never what
//    left, so nothing could ever be freed.
// ═══════════════════════════════════════════════════════════════════════════
let observerCallback = null;
walk(script, (n) => {
  if (n.type !== 'NewExpression') return;
  if (!(n.callee.type === 'Identifier' && n.callee.name === 'IntersectionObserver')) return;
  const arg = n.arguments[0];
  if (arg && (arg.type === 'FunctionExpression' || arg.type === 'ArrowFunctionExpression')) {
    observerCallback = arg;
  }
});
ok(!!observerCallback, 'the page constructs an IntersectionObserver with a callback');

const intersectingTests = [];
if (observerCallback) {
  walk(observerCallback, (n) => {
    if (n.type !== 'IfStatement') return;
    let mentions = false;
    walk(n.test, (t) => {
      if (t.type === 'Identifier' && t.name === 'isIntersecting') mentions = true;
    });
    if (mentions) intersectingTests.push(n);
  });
}
ok(intersectingTests.length > 0, 'the callback branches on isIntersecting');
ok(intersectingTests.length > 0 && intersectingTests.every((n) => !!n.alternate),
  'every isIntersecting branch has an else — the page learns what LEFT');

// The eviction has to be reachable from the callback, not merely declared.
const fromCallback = observerCallback ? reachable(observerCallback) : new Set();
ok([...evictorNames].some((n) => fromCallback.has(n)),
  'the observer callback reaches the eviction path');

// ═══════════════════════════════════════════════════════════════════════════
// 3. THE OBSERVER IS DISCONNECTED.
//    The WebView outlives the document — PDFViewer.native.jsx repoints its
//    source rather than unmounting — so a live observer holds every slot.
// ═══════════════════════════════════════════════════════════════════════════
let disconnectCalls = 0;
walk(script, (n) => {
  if (n.type !== 'CallExpression') return;
  const c = n.callee;
  if (c.type === 'MemberExpression' && !c.computed
    && c.property.type === 'Identifier' && c.property.name === 'disconnect') disconnectCalls += 1;
});
ok(disconnectCalls > 0, 'disconnect() is called on the observer');

// Reachable from something that runs: an event listener or the top-level IIFE.
const listenerHandlers = [];
walk(script, (n) => {
  if (n.type !== 'CallExpression') return;
  const c = n.callee;
  if (!(c.type === 'MemberExpression' && !c.computed
    && c.property.type === 'Identifier' && c.property.name === 'addEventListener')) return;
  const h = n.arguments[1];
  if (!h) return;
  if (h.type === 'Identifier') listenerHandlers.push(h.name);
  else listenerHandlers.push(h);
});

let teardownReached = false;
for (const h of listenerHandlers) {
  const node = typeof h === 'string' ? fns.get(h) : h;
  if (!node) continue;
  const names = reachable(node.body || node);
  if (names.has('disconnect') && [...evictorNames].some((n) => names.has(n))) teardownReached = true;
}
ok(teardownReached,
  'a registered listener tears the page down — disconnect() plus eviction of every slot');

// ═══════════════════════════════════════════════════════════════════════════
// 4. THE NO-INTERSECTIONOBSERVER FALLBACK IS BOUNDED.
//    THE CLASS: no loop that walks every slot may rasterise unconditionally.
//    The defect was literally `for (…slots.length…) renderSlot(slots[i]);`.
// ═══════════════════════════════════════════════════════════════════════════
function loopsOverSlots(n) {
  if (n.type !== 'ForStatement' && n.type !== 'WhileStatement') return false;
  let hit = false;
  walk(n.test || {}, (t) => {
    if (t.type !== 'MemberExpression' || t.computed) return;
    if (t.object.type === 'Identifier' && t.object.name === 'slots'
      && t.property.type === 'Identifier' && t.property.name === 'length') hit = true;
  });
  return hit;
}

// ⚠️ THE CENSUS IS DERIVED, NOT A NAME. This used to look for `renderSlot`
// BY NAME inside a slots loop. The render path now routes through `enqueue`,
// so that check would have passed on an empty set and said nothing, for ever —
// a gate that goes quiet the moment the thing it guards is renamed is not a
// gate. Every function from which `renderSlot` is reachable IS a function that
// can begin a rasterisation, whatever it is called, and a call to any of them
// inside a slots loop is the defect.
const rasterisers = new Set(['renderSlot']);
for (let grew = true; grew;) {
  grew = false;
  for (const [name, node] of fns) {
    if (rasterisers.has(name)) continue;
    for (const called of callsIn(node.body)) {
      if (rasterisers.has(called)) { rasterisers.add(name); grew = true; break; }
    }
  }
}
ok(rasterisers.size >= 2,
  `the call graph finds the functions that can begin a rasterisation (${
    [...rasterisers].join(', ')})`);

const unguardedBulkRenders = [];
walk(script, (loop) => {
  if (!loopsOverSlots(loop)) return;
  walk(loop.body, (n) => {
    if (n.type !== 'CallExpression') return;
    if (!(n.callee.type === 'Identifier' && rasterisers.has(n.callee.name))) return;
    let guarded = false;
    walk(loop.body, (g) => {
      if (g.type !== 'IfStatement') return;
      walk(g, (inner) => { if (inner === n) guarded = true; });
    });
    if (!guarded) unguardedBulkRenders.push(n.callee.name);
  });
});
ok(unguardedBulkRenders.length === 0,
  `no loop over every slot starts work unconditionally (found: ${
    unguardedBulkRenders.join(', ') || 'none'})`);

// ═══════════════════════════════════════════════════════════════════════════
// 4b. THE INVARIANT THE CAP ACTUALLY RESTS ON.
//
//     A guarded loop that starts twelve rasterisations one at a time down a
//     scroll is the same defect with better manners, and the loop check above
//     cannot see it. What rules it out is narrower and is the thing to assert:
//     `renderSlot` HAS EXACTLY ONE CALLER, and that caller starts work only
//     while under a named numeric cap.
// ═══════════════════════════════════════════════════════════════════════════
const renderSlotCallers = [];
for (const [name, node] of fns) {
  if (name === 'renderSlot') continue;
  if (callsIn(node.body).has('renderSlot')) renderSlotCallers.push(name);
}
ok(renderSlotCallers.length === 1,
  `renderSlot has exactly one door into it (callers: ${
    renderSlotCallers.join(', ') || 'none'})`);

// AND THAT CALLER IS CAPPED. The loop it lives in must test a NAMED constant,
// not a literal buried in a condition — a cap nobody can find is a cap nobody
// will keep.
let capName = null;
let capValue = null;
if (renderSlotCallers.length === 1) {
  const pump = fns.get(renderSlotCallers[0]);
  walk(pump.body, (n) => {
    if (n.type !== 'WhileStatement' && n.type !== 'ForStatement') return;
    let startsWork = false;
    walk(n.body, (c) => {
      if (c.type === 'CallExpression' && c.callee.type === 'Identifier'
        && c.callee.name === 'renderSlot') startsWork = true;
    });
    if (!startsWork || !n.test) return;
    walk(n.test, (t) => {
      if (t.type !== 'BinaryExpression') return;
      for (const side of [t.left, t.right]) {
        if (side && side.type === 'Identifier' && /^[A-Z][A-Z0-9_]+$/.test(side.name)) {
          capName = side.name;
        }
      }
    });
  });
}
ok(!!capName, `and it starts work only while under a named cap (found ${capName})`);
if (capName) {
  walk(script, (n) => {
    if (n.type !== 'VariableDeclarator' || !n.id || n.id.type !== 'Identifier') return;
    if (n.id.name !== capName) return;
    if (n.init && n.init.type === 'NumericLiteral') capValue = n.init.value;
  });
}
ok(capValue === 1,
  `and the cap is 1 — the thread is the resource (${capName} = ${capValue})`);

// The fallback branch itself: `if (typeof IntersectionObserver === "undefined")`.
let fallbackBranch = null;
walk(script, (n) => {
  if (n.type !== 'IfStatement') return;
  let mentions = false;
  walk(n.test, (t) => {
    if (t.type === 'Identifier' && t.name === 'IntersectionObserver') mentions = true;
  });
  if (mentions) fallbackBranch = n.consequent;
});
ok(!!fallbackBranch, 'the page still guards on IntersectionObserver being absent');

const fromFallback = fallbackBranch ? reachable(fallbackBranch) : new Set();
ok([...evictorNames].some((n) => fromFallback.has(n)),
  'the fallback reaches the eviction path too — it is bounded, not all-at-once');
ok(fromFallback.has('addEventListener') || fromFallback.has('setTimeout')
  || fromFallback.has('requestAnimationFrame'),
  'the fallback re-evaluates on scroll rather than drawing the set once');

// ═══════════════════════════════════════════════════════════════════════════
// 5. THE BUDGET IS IN MEGAPIXELS, PRICED OFF THE CANVAS, AND CAN BE REACHED.
//
//    ⚠️ IT USED TO BE `KEEP_RENDERED = 7` AND IT NEVER BOUND ANYTHING.
//    `trim()` skipped any page marked `visible`, and `visible` was set by an
//    observer whose rootMargin IS THE BAND — so the band marked several sheets
//    unfreeable at once and the "window of 7" could sit at any size the band
//    happened to be. Measured: the same seven sheets, 27.4 MB un-zoomed and
//    336 MB zoomed in.
//
//    THREE THINGS HAVE TO HOLD and none of them implies the others:
//      a. the budget is in pixels, not pages;
//      b. each slot is priced from the canvas it ACTUALLY allocated, so the
//         number survives any change of scale;
//      c. the only thing that may not be freed is what is ON SCREEN — if the
//         evictor still protected the band, (a) and (b) would both be true and
//         the budget would still be unreachable.
// ═══════════════════════════════════════════════════════════════════════════
ok(!fns.has('KEEP_RENDERED') && !/KEEP_RENDERED/.test(scriptText),
  'the page-count window is gone, not left beside the new one');

let budgetMp = null;
walk(script, (n) => {
  if (n.type !== 'VariableDeclarator' || !n.id || n.id.type !== 'Identifier') return;
  if (n.id.name !== 'CANVAS_BUDGET_MP') return;
  if (n.init && n.init.type === 'NumericLiteral') budgetMp = n.init.value;
});
ok(typeof budgetMp === 'number', 'the page declares a megapixel budget for resident canvases');
// Lower bound: two sheets can be partly on screen at once and neither may be
// freed, so a budget under that floor is one trim() can never reach. Upper
// bound: renderer kills were reported at 250-350 MB and pdf.js holds the file
// buffer on top of this.
ok(typeof budgetMp === 'number' && budgetMp >= 32 && budgetMp <= 64,
  `CANVAS_BUDGET_MP (${budgetMp} MP = ${budgetMp * 4} MB) clears the on-screen `
  + 'floor without approaching the kill threshold');

// (b) PRICED OFF THE CANVAS. A cost derived from a scale would be a page count
// wearing a different name and wrong the moment the scale moved.
const pricer = fns.get('canvasPixels');
ok(!!pricer, 'a function prices a slot');
let readsCanvasDims = false;
if (pricer) {
  let w = false;
  let h = false;
  walk(pricer.body, (n) => {
    if (n.type !== 'MemberExpression' || n.computed) return;
    if (n.property.type !== 'Identifier') return;
    if (n.property.name === 'width') w = true;
    if (n.property.name === 'height') h = true;
  });
  readsCanvasDims = w && h;
}
ok(readsCanvasDims,
  'and it does so from the canvas\'s own width and height, not from an assumed scale');

// (c) THE PROTECTION RULE. The evictor must consult something that means "on
// screen" and must NOT be gated on band membership.
const trimFn = fns.get('trim');
ok(!!trimFn, 'the evictor still exists');
const fromTrim = trimFn ? reachable(trimFn.body) : new Set();
ok(fromTrim.has('onScreen'),
  'the evictor asks whether a sheet is ON SCREEN before sparing it');
ok(fromTrim.has('canvasPixels'),
  'and prices every resident slot through the canvas pricer');
let comparesBudget = false;
if (trimFn) {
  walk(trimFn.body, (n) => {
    if (n.type === 'Identifier' && n.name === 'CANVAS_BUDGET_MP') comparesBudget = true;
  });
}
ok(comparesBudget, 'reading the budget constant rather than a literal');
let mentionsNear = false;
if (trimFn) {
  walk(trimFn.body, (n) => {
    if (n.type === 'MemberExpression' && !n.computed
      && n.property.type === 'Identifier' && n.property.name === 'near') mentionsNear = true;
  });
}
ok(!mentionsNear,
  'and band membership does NOT veto an eviction — that is the bug KEEP_RENDERED had');

// ═══════════════════════════════════════════════════════════════════════════
// 6. THE PAGE NOW OUTLIVES THE DOCUMENT, AND MUST NOT ACCUMULATE THEM.
//
//    WHY THE PAGE OUTLIVES THE DOCUMENT AT ALL. The viewer used to take its
//    file from `?file=`, so every open was a different url — and a different
//    url in a WebView is a NAVIGATION. 1.5 MB of pdf.js, 1.1 MB of it the
//    worker bundle that a file:// origin forces onto the MAIN THREAD, was
//    read off storage and recompiled before anything could be drawn. Staging
//    was memoised; the parse never was, and the parse is the half that is
//    identical for a 16 KB logbook and a 30 MB plan set.
//
//    THE TRADE THIS MUST NOT MAKE. A navigation was, incidentally, a complete
//    reset: the old document's canvases died with the page. Keeping the page
//    means that reset has to be done deliberately, and a viewer that holds two
//    plan sets' bitmaps has swapped a slow open for the OOM this whole file
//    exists to prevent.
// ═══════════════════════════════════════════════════════════════════════════
ok(fns.has('openDocument'),
  'a document can be opened into the live page, without a navigation');

// It has to be reachable from a listener, or the host can never deliver one.
let openFromListener = false;
for (const h of listenerHandlers) {
  const node = typeof h === 'string' ? fns.get(h) : h;
  if (!node) continue;
  if (reachable(node.body || node).has('openDocument')) openFromListener = true;
}
ok(openFromListener,
  'and it is reachable from a registered message listener — a handler nothing '
  + 'dispatches to is a viewer that never opens anything');

const fromOpen = fns.has('openDocument') ? reachable(fns.get('openDocument').body) : new Set();
ok([...evictorNames].some((n) => fromOpen.has(n)),
  'opening a document reaches the eviction path — the previous document\'s '
  + 'canvases are zeroed, not merely dropped on the floor');
ok(fromOpen.has('disconnect'),
  'and disconnects the previous document\'s observer, which would otherwise '
  + 'keep every one of its slots alive');
ok(fromOpen.has('destroy'),
  'and destroys the previous pdf.js document, which is what frees the file '
  + 'bytes the parser holds for the life of the document');

// The arrays are the other half: releaseSlot frees the bitmap but leaves the
// slot object, and a second document appends to `slots` rather than replacing
// it unless something empties it.
function zeroesLengthOf(node, arrName) {
  let hit = false;
  walk(node, (n) => {
    if (n.type !== 'AssignmentExpression' || n.operator !== '=') return;
    const t = n.left;
    if (t.type !== 'MemberExpression' || t.computed) return;
    if (t.object.type !== 'Identifier' || t.object.name !== arrName) return;
    if (t.property.type !== 'Identifier' || t.property.name !== 'length') return;
    if (n.right.type === 'NumericLiteral' && n.right.value === 0) hit = true;
  });
  return hit;
}
// Look across every function the open path reaches, so it does not matter
// which one of them does the emptying.
const openPathNodes = [...fromOpen].map((n) => fns.get(n)).filter(Boolean);
if (fns.has('openDocument')) openPathNodes.push(fns.get('openDocument'));
ok(openPathNodes.some((n) => zeroesLengthOf(n, 'slots')),
  'the slot list is emptied between documents — otherwise the second document '
  + 'is appended to the first and the page grows without bound');
ok(openPathNodes.some((n) => zeroesLengthOf(n, 'rendered')),
  'and so is the rasterised-page list that trim() bounds against');

// The DOM placeholders too: `slots` is the model, `pagesEl` is the view.
let clearsPages = false;
for (const n of openPathNodes) {
  walk(n, (a) => {
    if (a.type !== 'AssignmentExpression' || a.operator !== '=') return;
    const t = a.left;
    if (t.type !== 'MemberExpression' || t.computed) return;
    if (t.object.type !== 'Identifier' || t.object.name !== 'pagesEl') return;
    if (t.property.type !== 'Identifier' || t.property.name !== 'innerHTML') return;
    if (a.right.type === 'StringLiteral' && a.right.value === '') clearsPages = true;
  });
}
ok(clearsPages,
  'and the previous document\'s page elements are removed from the DOM');

// The staged copy on an installed device is only replaced when the stamp
// changes, so the fix does not reach anyone unless VIEWER_VERSION moved.
let viewerVersion = null;
for (const stmt of moduleTree.program.body) {
  if (stmt.type !== 'VariableDeclaration') continue;
  for (const d of stmt.declarations) {
    if (d.id && d.id.name === 'VIEWER_VERSION' && d.init && d.init.type === 'StringLiteral') {
      viewerVersion = d.init.value;
    }
  }
}
ok(viewerVersion !== null && viewerVersion !== '1',
  `VIEWER_VERSION moved off '1' so installed apps re-stage (is '${viewerVersion}')`);

done();
