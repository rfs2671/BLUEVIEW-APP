/**
 * THE PAGES SIDEBAR IS pdf.js's, AND IT MUST START CLOSED.
 *
 * On Android every PDF goes through a pdf.js viewer.html -- and now always the
 * copy STAGED ON THE DEVICE. There used to be a second builder pointing at
 * Mozilla's hosted viewer for the online case; it was removed because it
 * url-encoded a token-bearing document url into a third party's page (see
 * pdfTokenOrigin.test.cjs). One builder, one place the hash can be dropped.
 *
 * pdf.js's thumbnail sidebar is the library's default; we ship no sidebar code
 * at all. On a 6" phone it takes half the screen, and pdf.js PERSISTS sidebar
 * state in its ViewHistory, so once it is open it reopens for every later
 * document. That is why it read as undismissable.
 *
 * `#pagemode=none` in the URL hash is the whole fix, and it now matters on
 * every Android open rather than only the offline ones: a cellar is where the
 * screen is smallest and the drawing matters most.
 *
 * iOS never reaches the builder -- WKWebView/PDFKit renders the PDF directly
 * and has no sidebar.
 *
 * READ AS CODE. The files carry comments explaining #pagemode=none, so a
 * substring search would match the explanation rather than the URL. These
 * assertions read the template literal that is actually returned.
 *
 * Run:  node src/utils/pdfjsSidebar.test.cjs
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

function ast(rel) {
  return parser.parse(fs.readFileSync(path.join(__dirname, '..', '..', rel), 'utf8'), {
    sourceType: 'module',
    plugins: ['jsx'],
  });
}

function walk(node, fn, seen = new Set()) {
  if (!node || typeof node !== 'object' || seen.has(node)) return;
  seen.add(node);
  if (typeof node.type === 'string') fn(node);
  for (const k of Object.keys(node)) {
    const v = node[k];
    if (Array.isArray(v)) v.forEach((c) => walk(c, fn, seen));
    else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v, fn, seen);
  }
}

function findFn(tree, name) {
  let hit = null;
  walk(tree, (n) => {
    if (hit) return;
    if (n.type === 'FunctionDeclaration' && n.id && n.id.name === name) hit = n;
    if (n.type === 'VariableDeclarator' && n.id && n.id.name === name) hit = n.init;
  });
  if (!hit) throw new Error(`${name} not found`);
  return hit;
}

/** The literal text of every template returned by this function, comments
 *  excluded by construction -- a comment is not a quasi. */
function returnedTemplates(fnNode) {
  const out = [];
  walk(fnNode, (n) => {
    if (n.type !== 'ReturnStatement' || !n.argument) return;
    walk(n.argument, (t) => {
      if (t.type === 'TemplateLiteral') {
        out.push(t.quasis.map((q) => q.value.cooked).join(' '));
      }
    });
  });
  return out;
}

// ═══════════════════════════════════════════════════════════════════════════
// 1. The staged viewer -- the only Android path there is.
// ═══════════════════════════════════════════════════════════════════════════
const stagedTree = ast('src/utils/pdfjsViewer.js');
const staged = returnedTemplates(findFn(stagedTree, 'localViewerUrlFor'));

ok(staged.length === 1, 'localViewerUrlFor returns exactly one template literal');
ok(staged.every((t) => t.endsWith('#pagemode=none')),
  'staged viewer URL ends with #pagemode=none');
ok(staged.every((t) => t.includes('?file=')),
  'staged viewer URL still hands the document over as ?file=');

// ═══════════════════════════════════════════════════════════════════════════
// 2. THE CLASS: the hash must be LAST. A later `?`/`&` appended after the hash
//    would land inside the fragment and pdf.js would stop parsing pagemode.
// ═══════════════════════════════════════════════════════════════════════════
ok(staged.every((t) => t.indexOf('#') === t.lastIndexOf('#')),
  "staged: exactly one '#' in the URL");
ok(staged.every((t) => !t.slice(t.indexOf('#')).includes('?')),
  'staged: no query appended after the fragment');

// ═══════════════════════════════════════════════════════════════════════════
// 3. The staged builder is the one the viewer actually calls, and it is the
//    ONLY viewer builder in the component.
// ═══════════════════════════════════════════════════════════════════════════
const viewerTree = ast('src/components/PDFViewer.native.jsx');
let callsStaged = false;
walk(viewerTree, (n) => {
  if (n.type !== 'CallExpression') return;
  if (n.callee.type === 'Identifier' && n.callee.name === 'localViewerUrlFor') callsStaged = true;
});
ok(callsStaged, 'the component builds its Android source with localViewerUrlFor');

// A second builder would be a second place to forget the hash -- and, as the
// hosted one proved, a second place for a url to go somewhere it should not.
let otherBuilder = null;
walk(viewerTree, (n) => {
  if (otherBuilder) return;
  const named = (n.type === 'FunctionDeclaration' && n.id && n.id.name)
    || (n.type === 'VariableDeclarator' && n.id && n.id.type === 'Identifier' && n.id.name);
  if (!named || named === 'localViewerUrlFor') return;
  for (const t of returnedTemplates(n)) {
    if (t.includes('viewer.html')) { otherBuilder = named; return; }
  }
});
ok(!otherBuilder, `no second viewer-url builder in the component (found: ${otherBuilder || 'none'})`);

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
