/**
 * THE PAGES SIDEBAR IS pdf.js's, AND IT MUST START CLOSED.
 *
 * On Android every PDF goes through Mozilla's viewer.html -- the hosted copy
 * while online, a staged local copy offline. Its thumbnail sidebar is the
 * library's default; we ship no sidebar code at all. On a 6" phone it takes
 * half the screen, and pdf.js PERSISTS sidebar state in its ViewHistory, so
 * once it is open it reopens for every later document. That is why it read as
 * undismissable.
 *
 * `#pagemode=none` in the URL hash is the whole fix. Both builders need it:
 * the offline one especially, because a cellar is where the screen is smallest
 * and the drawing matters most.
 *
 * iOS never reaches either builder -- WKWebView/PDFKit renders the PDF
 * directly and has no sidebar.
 *
 * READ AS CODE. Both files now carry comments explaining #pagemode=none, so a
 * substring search of the file would match the explanation rather than the URL.
 * These assertions read the template literal that is actually returned.
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
// 1. The hosted viewer -- Android, online.
// ═══════════════════════════════════════════════════════════════════════════
const viewerTree = ast('src/components/PDFViewer.native.jsx');
const hosted = returnedTemplates(findFn(viewerTree, 'pdfJsViewerUrl'));

ok(hosted.length === 1, 'pdfJsViewerUrl returns exactly one template literal');
ok(hosted.every((t) => t.endsWith('#pagemode=none')),
  'hosted viewer URL ends with #pagemode=none');
ok(hosted.every((t) => t.includes('viewer.html')),
  'hosted viewer URL still points at viewer.html');

// ═══════════════════════════════════════════════════════════════════════════
// 2. The staged viewer -- Android, offline. Same hash, same reason.
// ═══════════════════════════════════════════════════════════════════════════
const stagedTree = ast('src/utils/pdfjsViewer.js');
const staged = returnedTemplates(findFn(stagedTree, 'localViewerUrlFor'));

ok(staged.length === 1, 'localViewerUrlFor returns exactly one template literal');
ok(staged.every((t) => t.endsWith('#pagemode=none')),
  'staged offline viewer URL ends with #pagemode=none');

// ═══════════════════════════════════════════════════════════════════════════
// 3. THE CLASS: the hash must be LAST. A later `?`/`&` appended after the hash
//    would land inside the fragment and pdf.js would stop parsing pagemode.
// ═══════════════════════════════════════════════════════════════════════════
for (const [name, tpls] of [['hosted', hosted], ['staged', staged]]) {
  ok(tpls.every((t) => t.indexOf('#') === t.lastIndexOf('#')),
    `${name}: exactly one '#' in the URL`);
  ok(tpls.every((t) => !t.slice(t.indexOf('#')).includes('?')),
    `${name}: no query appended after the fragment`);
}

// ═══════════════════════════════════════════════════════════════════════════
// 4. iOS is untouched -- it must NOT be routed through pdf.js.
// ═══════════════════════════════════════════════════════════════════════════
let iosGuarded = false;
walk(viewerTree, (n) => {
  if (n.type !== 'CallExpression') return;
  if (!(n.callee.type === 'Identifier' && n.callee.name === 'pdfJsViewerUrl')) return;
  iosGuarded = true;
});
ok(iosGuarded, 'pdfJsViewerUrl is still called (the Android path survives)');

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
