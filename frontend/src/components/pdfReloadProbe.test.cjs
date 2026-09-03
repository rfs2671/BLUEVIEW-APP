/**
 * THE PINCH-RELOAD PROBE — PHASE 1 INSTRUMENTATION, NOT A FIX.
 *
 * THE SYMPTOM. A 25-31 MB plan opens on the CP files screen in 20-30 s, and
 * then every pinch-zoom reloads the WebView and drops the operator back to
 * page 1. Daily. The slow open is settled (pdf.js rasterising at
 * MAX_CANVAS_PX over a four-viewport window, deliberate, out of scope). What
 * is NOT settled is what reloads the WebView.
 *
 * THE READING SO FAR. `loadPdf` is a useCallback keyed on the WHOLE `file`
 * object; the effect that calls it is keyed on `loadPdf`; `loadPdf` opens with
 * setUrl(null) and closes with setUrl(uri). So a new `file` REFERENCE — same
 * fields, different object — tears the url down, rebuilds `webViewSource`, and
 * reloads. `webViewSource` is memoised on [url, localViewerUri], which stops
 * unrelated state INSIDE the component from doing this and does nothing about
 * a new prop from the parent.
 *
 * WHAT THE STATIC TRACE COULD NOT PRODUCE was the thing that hands the
 * component a new `file` during a pinch. `selectedPdfFile` is parent state set
 * only on tap. A pinch lands INSIDE the WebView and delivers no touch to React
 * at all. So the identity story may not be the pinch story, and the probe has
 * to be able to say so — which is why it instruments BOTH sides:
 *
 *   React side — did a render happen at all, and did `file` / `loadPdf` /
 *                `webViewSource` change identity across it?
 *   WebView side — did the page start loading again, and did Android kill the
 *                renderer process out from under it?
 *
 * A reload with NO preceding React render, or one preceded by
 * onRenderProcessGone, is not a dependency-array defect and must not be
 * "fixed" as one. That is the whole reason both halves are required here.
 *
 * WHAT THIS TEST HOLDS
 *   1. Identity is tracked by a WeakMap, and JSON.stringify appears nowhere in
 *      the viewer. A value comparison reports two distinct objects with equal
 *      fields as "unchanged" — it would hide the exact event being hunted.
 *   2. One clearly-named, boolean-literal module flag per file, so the probe
 *      can ship switched off.
 *   3. No console.log escapes that flag. The probe logs once per render of a
 *      screen the operator uses all day.
 *   4. onRenderProcessGone is wired. Without it the log cannot separate "React
 *      rebuilt the source" from "Android killed the renderer", and the trip to
 *      the tablet has to be made twice.
 *   5. The WebView's `source` is still the memoised `webViewSource` binding.
 *      A probe that introduced a fresh object here would cause the reload it
 *      is measuring.
 *   6. Both setSelectedPdfFile call sites in the parent announce themselves,
 *      so "the parent minted a new file object" is distinguishable from "the
 *      parent re-rendered and did not".
 *   7. PHASE 1 ONLY: loadPdf's dependency array is still [projectId, file].
 *      This branch measures; it does not fix. If a fix lands, this assertion
 *      is meant to fail and be updated deliberately.
 *
 * Run:  node src/components/pdfReloadProbe.test.cjs
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

const FLAG = 'PDF_RELOAD_PROBE';

const VIEWER = path.join(__dirname, 'PDFViewer.native.jsx');
const SCREEN = path.join(__dirname, '..', '..', 'app', 'projects', '[id]', 'files.jsx');

function read(p) { return fs.readFileSync(p, 'utf8'); }
function parse(src) {
  return parser.parse(src, { sourceType: 'module', plugins: ['jsx'] });
}

/** Walk with a parent chain, so a node can ask what encloses it. */
function walk(node, fn, stack = [], seen = new Set()) {
  if (!node || typeof node !== 'object' || seen.has(node)) return;
  seen.add(node);
  if (typeof node.type === 'string') fn(node, stack);
  const next = typeof node.type === 'string' ? stack.concat([node]) : stack;
  for (const k of Object.keys(node)) {
    if (k === 'loc' || k === 'leadingComments' || k === 'trailingComments') continue;
    const v = node[k];
    if (Array.isArray(v)) v.forEach((c) => walk(c, fn, next, seen));
    else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v, fn, next, seen);
  }
}

function mentions(node, name) {
  let hit = false;
  walk(node, (n) => { if (n.type === 'Identifier' && n.name === name) hit = true; });
  return hit;
}

function isConsole(node, method) {
  return node.type === 'CallExpression'
    && node.callee.type === 'MemberExpression'
    && node.callee.object.type === 'Identifier'
    && node.callee.object.name === 'console'
    && node.callee.property.type === 'Identifier'
    && node.callee.property.name === method;
}

/**
 * Is this call gated by the flag? Two accepted shapes, because both read
 * clearly at the call site:
 *   if (FLAG) { ... }                       — an enclosing conditional
 *   if (!FLAG) return;  ... later ...       — an early return at the top of
 *                                             the nearest enclosing function
 */
function isFlagGated(stack) {
  for (const anc of stack) {
    if ((anc.type === 'IfStatement' || anc.type === 'ConditionalExpression') && mentions(anc.test, FLAG)) {
      return true;
    }
    if (anc.type === 'LogicalExpression' && mentions(anc.left, FLAG)) return true;
  }
  // Early-return guard in the nearest enclosing function body.
  for (let i = stack.length - 1; i >= 0; i -= 1) {
    const anc = stack[i];
    const isFn = anc.type === 'FunctionDeclaration' || anc.type === 'FunctionExpression'
      || anc.type === 'ArrowFunctionExpression';
    if (!isFn) continue;
    const body = anc.body && anc.body.type === 'BlockStatement' ? anc.body.body : [];
    const first = body[0];
    if (first && first.type === 'IfStatement' && mentions(first.test, FLAG)) {
      const cons = first.consequent;
      const stmts = cons.type === 'BlockStatement' ? cons.body : [cons];
      if (stmts.some((s) => s.type === 'ReturnStatement')) return true;
    }
    return false; // nearest function has no guard — stop, don't credit an outer one
  }
  return false;
}

/** A module-level `const NAME = <boolean literal>;` */
function hasModuleBooleanFlag(tree, name) {
  return tree.program.body.some((stmt) => {
    if (stmt.type !== 'VariableDeclaration' || stmt.kind !== 'const') return false;
    return stmt.declarations.some((d) =>
      d.id.type === 'Identifier' && d.id.name === name
      && d.init && d.init.type === 'BooleanLiteral');
  });
}

// ─────────────────────────────────────────────────────────────────────────
console.log('\nPDFViewer.native.jsx — the probe on the viewer');

const viewerSrc = read(VIEWER);
const viewerTree = parse(viewerSrc);

ok(hasModuleBooleanFlag(viewerTree, FLAG),
   `${FLAG} is a module-level const initialised to a boolean literal`);

let viewerHasWeakMap = false;
let viewerStringify = 0;
let viewerLogs = 0;
let viewerUngatedLogs = 0;
let hasRenderProcessGone = false;
let sourceIsMemoBinding = false;
let loadPdfDeps = null;

walk(viewerTree, (n, stack) => {
  if (n.type === 'NewExpression' && n.callee.type === 'Identifier' && n.callee.name === 'WeakMap') {
    viewerHasWeakMap = true;
  }
  if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
      && n.callee.object.type === 'Identifier' && n.callee.object.name === 'JSON'
      && n.callee.property.type === 'Identifier' && n.callee.property.name === 'stringify') {
    viewerStringify += 1;
  }
  if (isConsole(n, 'log')) {
    viewerLogs += 1;
    if (!isFlagGated(stack)) viewerUngatedLogs += 1;
  }
  if (n.type === 'ObjectProperty' && n.key.type === 'Identifier'
      && n.key.name === 'onRenderProcessGone') {
    hasRenderProcessGone = true;
  }
  // { source: webViewSource, ... } on the WebView props object.
  if (n.type === 'ObjectProperty' && n.key.type === 'Identifier' && n.key.name === 'source'
      && n.value.type === 'Identifier' && n.value.name === 'webViewSource') {
    sourceIsMemoBinding = true;
  }
  // const loadPdf = useCallback(async () => {...}, [ ... ])
  if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && n.id.name === 'loadPdf'
      && n.init && n.init.type === 'CallExpression'
      && n.init.callee.type === 'Identifier' && n.init.callee.name === 'useCallback') {
    const deps = n.init.arguments[1];
    if (deps && deps.type === 'ArrayExpression') {
      loadPdfDeps = deps.elements.map((e) => (e && e.type === 'Identifier' ? e.name : '<expr>'));
    }
  }
});

ok(viewerHasWeakMap,
   'identity is stamped through a WeakMap (a new object with equal fields is a NEW id)');
ok(viewerStringify === 0,
   `no JSON.stringify in the viewer — a value compare would hide the identity change (found ${viewerStringify})`);
ok(viewerLogs > 0, `the probe actually logs (${viewerLogs} console.log calls)`);
ok(viewerUngatedLogs === 0,
   `every console.log sits behind ${FLAG} (${viewerUngatedLogs} ungated)`);
ok(hasRenderProcessGone,
   'onRenderProcessGone is wired — separates "React rebuilt the source" from "Android killed the renderer"');
ok(sourceIsMemoBinding,
   'the WebView source prop is still the memoised `webViewSource` binding, not a fresh object');

// The per-render snapshot must carry every field the operator was told to
// watch. Read the object literal itself rather than grepping for words that
// occur all over a 760-line component.
let probeKeys = null;
walk(viewerTree, (n) => {
  if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && n.id.name === 'probeNow'
      && n.init && n.init.type === 'ObjectExpression') {
    probeKeys = n.init.properties
      .filter((p) => p.type === 'ObjectProperty' && p.key.type === 'Identifier')
      .map((p) => p.key.name);
  }
});
ok(probeKeys !== null, 'the per-render snapshot is a readable object literal named `probeNow`');
for (const needle of ['file', 'loadPdf', 'webViewSource', 'url', 'localViewerUri']) {
  ok(probeKeys !== null && probeKeys.includes(needle),
     `the per-render snapshot reports \`${needle}\``);
}
// Identity fields must go through the WeakMap stamper, not be interpolated raw
// — printing the object would compare by value in the reader's eye.
let stampedFields = [];
walk(viewerTree, (n) => {
  if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && n.id.name === 'probeNow'
      && n.init && n.init.type === 'ObjectExpression') {
    stampedFields = n.init.properties
      .filter((p) => p.type === 'ObjectProperty' && p.key.type === 'Identifier'
        && p.value.type === 'CallExpression' && p.value.callee.type === 'Identifier'
        && p.value.callee.name === 'probeIdOf')
      .map((p) => p.key.name);
  }
});
for (const needle of ['file', 'loadPdf', 'webViewSource']) {
  ok(stampedFields.includes(needle),
     `\`${needle}\` is reported by WeakMap identity, not by value`);
}

ok(loadPdfDeps !== null && loadPdfDeps.join(',') === 'projectId,file',
   `PHASE 1: loadPdf deps are still [projectId, file] (found [${loadPdfDeps ? loadPdfDeps.join(', ') : 'none'}]) — this branch measures, it does not fix`);

// ─────────────────────────────────────────────────────────────────────────
console.log('\nfiles.jsx — the probe on the parent');

const screenSrc = read(SCREEN);
const screenTree = parse(screenSrc);

ok(hasModuleBooleanFlag(screenTree, FLAG),
   `${FLAG} is a module-level const initialised to a boolean literal`);

let screenLogs = 0;
let screenUngatedLogs = 0;
let setCalls = 0;

walk(screenTree, (n, stack) => {
  if (isConsole(n, 'log')) {
    screenLogs += 1;
    if (!isFlagGated(stack)) screenUngatedLogs += 1;
  }
  // Every call that hands the child a document, i.e. everything but the
  // `setSelectedPdfFile(null)` teardown in onClose. NOTE the two shapes:
  // one mints `{ ...file, directUrl: local }`; the other is a conditional
  // that on its else-branch passes the ROW OBJECT ITSELF. Counting only
  // object literals would miss the second and understate the call sites.
  if (n.type === 'CallExpression' && n.callee.type === 'Identifier'
      && n.callee.name === 'setSelectedPdfFile'
      && n.arguments.length
      && !(n.arguments[0].type === 'NullLiteral')) {
    setCalls += 1;
  }
});

ok(screenLogs > 0, `the parent probe logs (${screenLogs} console.log calls)`);
ok(screenUngatedLogs === 0,
   `every console.log sits behind ${FLAG} (${screenUngatedLogs} ungated)`);

// Both object-minting call sites must announce themselves; a mint that is not
// logged is exactly the one that would be blamed on the child.
ok(setCalls === 2,
   `both setSelectedPdfFile object-mint call sites are present (found ${setCalls})`);
const announced = (screenSrc.match(/setSelectedPdfFile\(#/g) || []).length;
ok(announced >= 2,
   `each mint announces itself in the log (found ${announced} announcements)`);

// And a render that did NOT mint must be reported as such, or the log cannot
// answer "did the parent hand the child a new object, or just re-render?".
ok(/no new selectedPdfFile|WITHOUT/.test(screenSrc),
   'a parent re-render that minted nothing is reported as such');

done();
