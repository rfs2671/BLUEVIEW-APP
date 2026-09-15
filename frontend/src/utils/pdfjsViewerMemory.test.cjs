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

// THE CENSUS IS DERIVED, NOT LISTED. Naming `renderSlot` and only
// `renderSlot` made this check answerable by renaming: move the call behind a
// one-line helper and the loop looks innocent while rasterising just the same.
// So: every function from which renderSlot is REACHABLE is a function that can
// begin a rasterisation, and a call to any of them inside a slots loop is the
// defect regardless of what it is called.
const renderStarters = new Set(['renderSlot']);
for (let grew = true; grew;) {
  grew = false;
  for (const [name, node] of fns) {
    if (renderStarters.has(name)) continue;
    const calls = callsIn(node.body);
    if ([...renderStarters].some((s) => calls.has(s))) { renderStarters.add(name); grew = true; }
  }
}
ok(renderStarters.size >= 1, `the call graph finds ${renderStarters.size} way(s) into a render`);

const unguardedBulkRenders = [];
walk(script, (loop) => {
  if (!loopsOverSlots(loop)) return;
  walk(loop.body, (n) => {
    if (n.type !== 'CallExpression') return;
    if (!(n.callee.type === 'Identifier' && renderStarters.has(n.callee.name))) return;
    let guarded = false;
    walk(loop.body, (g) => {
      if (g.type !== 'IfStatement') return;
      walk(g, (inner) => { if (inner === n) guarded = true; });
    });
    if (!guarded) unguardedBulkRenders.push(n);
  });
});
ok(unguardedBulkRenders.length === 0,
  'no loop over every slot rasterises unconditionally');

// ── AND THE STRONGER FORM, WHICH IS WHAT ACTUALLY BOUNDS IT NOW ──────────
//
// The loop check above is a check on ONE SHAPE of the bug. The class is
// "nothing bounds how many rasterisations are in flight", and a guarded loop
// that starts twelve of them one at a time down a scroll is the same defect
// with better manners. What bounds it is that renderSlot has exactly ONE
// caller and that caller is governed by a numeric cap.
{
  const FN_TYPES = new Set(['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression']);

  /** Calls made by THIS function body, not by functions nested inside it.
   *  `callsIn` descends through nested functions, which makes the top-level
   *  IIFE — and every scope enclosing pumpQueue — look like a caller. */
  function directCallsIn(root) {
    const out = new Set();
    (function rec(n) {
      if (!n || typeof n !== 'object') return;
      if (n !== root && typeof n.type === 'string' && FN_TYPES.has(n.type)) return;
      if (n.type === 'CallExpression' && n.callee && n.callee.type === 'Identifier') {
        out.add(n.callee.name);
      }
      for (const k of Object.keys(n)) {
        if (k === 'loc' || k === 'leadingComments' || k === 'trailingComments') continue;
        const v = n[k];
        if (Array.isArray(v)) v.forEach(rec);
        else if (v && typeof v === 'object' && typeof v.type === 'string') rec(v);
      }
    }(root));
    return out;
  }

  const callers = [];
  for (const [name, node] of fns) {
    if (name === 'renderSlot') continue;
    if (directCallsIn(node.body).has('renderSlot')) callers.push(name);
  }
  // Calls from anonymous function expressions — observer callbacks, promise
  // handlers — count too. That is exactly where the twelve came from.
  let anonCalls = 0;
  walk(script, (n) => {
    if (n.type !== 'FunctionExpression' && n.type !== 'ArrowFunctionExpression') return;
    if (directCallsIn(n.body).has('renderSlot')) anonCalls += 1;
  });
  ok(callers.length === 1 && anonCalls === 0,
    `renderSlot has exactly one door into it (named: ${callers.join(', ') || 'none'}; `
    + `anonymous: ${anonCalls})`);

  // The cap governs the LOOP that starts the work, so read it off the loop's
  // own test — not off any `<` that happens to appear in the body, which is
  // how a scan for "the last comparison" picks up the nearest-first search.
  const pump = callers.length === 1 ? fns.get(callers[0]) : null;
  let capName = null;
  if (pump) {
    walk(pump.body, (n) => {
      if (n.type !== 'WhileStatement' && n.type !== 'ForStatement') return;
      walk(n.test || {}, (t) => {
        if (t.type !== 'BinaryExpression') return;
        if (t.operator !== '<' && t.operator !== '<=') return;
        if (t.right.type === 'Identifier' && !capName) capName = t.right.name;
      });
    });
  }
  ok(!!capName, `and it starts work only while under a named cap (${capName || 'none found'})`);

  let capValue = null;
  walk(script, (n) => {
    if (n.type !== 'VariableDeclarator' || !n.id || n.id.type !== 'Identifier') return;
    if (n.id.name !== capName) return;
    if (n.init && n.init.type === 'NumericLiteral') capValue = n.init.value;
  });
  ok(typeof capValue === 'number' && capValue >= 1 && capValue <= 2,
    `and the cap is a small number (${capName} = ${capValue})`);
}

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
// 5. THE BUDGET IS IN BYTES, AND IT IS READ OFF THE REAL CANVAS.
//
//    WAS: `KEEP_RENDERED`, a page count. It never bound anything — trim()
//    skips any page still marked visible and the band marks several — and a
//    count is the wrong unit besides: the same seven sheets are 31 MB at the
//    viewport scale and 336 MB once the reader has pinched in, which is the
//    figure a renderer gets killed at. The unit that runs out is megabytes.
//
//    AND IT HAS TO BE DERIVED, NOT ASSUMED. A budget computed from a constant
//    "MB per sheet" is a page count wearing a different name and would be
//    wrong by an order of magnitude the moment someone zooms. The cost of a
//    slot must be read from the width and height the canvas actually got.
// ═══════════════════════════════════════════════════════════════════════════
let budget = null;
walk(script, (n) => {
  if (n.type !== 'VariableDeclarator' || !n.id || n.id.type !== 'Identifier') return;
  if (n.id.name !== 'CANVAS_BUDGET_BYTES') return;
  if (n.init && n.init.type === 'NumericLiteral') budget = n.init.value;
  // `96 * 1048576` reads better than the literal, so fold it.
  if (n.init && n.init.type === 'BinaryExpression' && n.init.operator === '*'
    && n.init.left.type === 'NumericLiteral' && n.init.right.type === 'NumericLiteral') {
    budget = n.init.left.value * n.init.right.value;
  }
});
ok(typeof budget === 'number', 'the page declares a byte budget for resident canvases');
// Lower bound: the band is unfreeable, so a budget below it would ask trim()
// for something it can never deliver. Upper bound: the crash reports were at
// 250-350 MB.
ok(typeof budget === 'number' && budget >= 48 * 1048576 && budget <= 192 * 1048576,
  `the budget (${budget ? (budget / 1048576).toFixed(0) : '?'} MB) covers the near band `
  + 'without approaching the ceiling a renderer dies at');

// The cost function must reach for a canvas dimension, not a constant.
{
  const sizers = [...fns.entries()].filter(([, node]) => {
    let readsW = false;
    let readsH = false;
    walk(node.body, (n) => {
      if (n.type !== 'MemberExpression' || n.computed) return;
      if (n.property.type !== 'Identifier') return;
      if (n.property.name === 'width') readsW = true;
      if (n.property.name === 'height') readsH = true;
    });
    return readsW && readsH;
  }).map(([name]) => name);

  let trimFn = null;
  for (const [name, node] of fns) {
    if (!callsIn(node.body).has('releaseSlot')) continue;
    // trim() is the one that both frees AND compares against the budget.
    let usesBudget = false;
    walk(node.body, (n) => {
      if (n.type === 'Identifier' && n.name === 'CANVAS_BUDGET_BYTES') usesBudget = true;
    });
    if (usesBudget) trimFn = name;
  }
  ok(!!trimFn, `the evictor compares against the byte budget (${trimFn || 'nothing does'})`);

  const fromTrim = trimFn ? reachable(fns.get(trimFn)) : new Set();
  ok(sizers.some((n) => fromTrim.has(n)),
    'and sizes each slot from the canvas it actually allocated, not from an assumed scale');
}

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
