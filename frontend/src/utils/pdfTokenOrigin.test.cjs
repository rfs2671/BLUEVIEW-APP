/**
 * THE BEARER TOKEN DOES NOT LEAVE OUR ORIGIN, AND TRY AGAIN CAN ACTUALLY TRY.
 *
 * THE DEFECT. `resolvePdfSrc` appended the user's 30-day JWT to the document
 * url as `?token=`. On Android the viewer then url-ENCODED that whole
 * token-bearing url into a page hosted by someone else:
 *
 *     https://mozilla.github.io/pdf.js/web/viewer.html?file=<encoded url>
 *
 * so every ONLINE Android plan open handed a live Levelog credential to a third
 * party's request log and referrer surface. Not an edge case — the default
 * Android path.
 *
 * THE SECOND DEFECT. Both "Try Again" buttons called `setUrl(r.url)` with the
 * RAW response url — no absolutising, no auth — so a retry pointed the viewer
 * at a bare relative `/api/...` path and failed deterministically. The button
 * could not work.
 *
 * WHAT IS ASSERTED, AND HOW.
 *   Part 1 runs utils/pdfSrc.js for real: which urls get a token, and what a
 *          platform without a native PDF renderer is allowed to be handed.
 *   Part 2 reads the two viewer components as SOURCE, because their rendering
 *          cannot be executed here. It asserts the property that matters and
 *          not a spelling: every absolute origin that appears anywhere in
 *          either file must be our own. That catches mozilla.github.io and any
 *          replacement for it.
 *   Part 3 asserts the retry handlers reference the shared loader, and that
 *          `setUrl` is never called with a raw `.url` off a response again.
 *
 * Run:  node src/utils/pdfTokenOrigin.test.cjs
 */

const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');
const parser = require('@babel/parser');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const FRONTEND = path.join(__dirname, '..', '..');

function load(rel) {
  const file = path.join(FRONTEND, rel);
  if (!fs.existsSync(file)) {
    ok(false, `${rel} exists`);
    console.log(`\n  ${passed} passed, ${failed} failed`);
    process.exit(1);
  }
  const { code } = babel.transformSync(fs.readFileSync(file, 'utf8'), {
    filename: file,
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    configFile: false,
    babelrc: false,
  });
  const m = {};
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(m, { exports: m }, require);
  return m;
}

function ast(rel) {
  return parser.parse(fs.readFileSync(path.join(FRONTEND, rel), 'utf8'), {
    sourceType: 'module',
    plugins: ['jsx'],
  });
}

function walk(node, fn, seen = new Set()) {
  if (!node || typeof node !== 'object' || seen.has(node)) return;
  seen.add(node);
  if (typeof node.type === 'string') fn(node);
  for (const k of Object.keys(node)) {
    if (k === 'loc' || k === 'leadingComments' || k === 'trailingComments' || k === 'innerComments') continue;
    const v = node[k];
    if (Array.isArray(v)) v.forEach((c) => walk(c, fn, seen));
    else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v, fn, seen);
  }
}

const NATIVE = 'src/components/PDFViewer.native.jsx';
const WEB = 'src/components/PDFViewerWeb.jsx';
const API_BASE = 'https://api.levelog.com';
const TOKEN = 'eyJhbGciOiJIUzI1NiJ9.PRETEND.PAYLOAD';
const PROXY = '/api/projects/p1/files/f1/content';

// ═══════════════════════════════════════════════════════════════════════════
// 1. BEHAVIOUR — utils/pdfSrc.js, executed.
// ═══════════════════════════════════════════════════════════════════════════
const M = load('src/utils/pdfSrc.js');
const {
  authorizedPdfUrl, pdfSourcePlan, pdfCacheKey,
  isFirstPartyProxyUrl, toAbsolutePdfUrl, isLocalFileUri,
} = M;

console.log('\n-- 1. which urls may carry the token --');

const ours = authorizedPdfUrl(PROXY, { apiBase: API_BASE, token: TOKEN });
ok(ours === `${API_BASE}${PROXY}?token=${encodeURIComponent(TOKEN)}`,
  'our own proxy url is absolutised and gets the token');

// THE LEAK, stated as a rule: a token may only ever ride on OUR origin.
const foreignShapes = [
  `https://mozilla.github.io${PROXY}`,
  `https://evil.example.com${PROXY}`,
  'https://mozilla.github.io/pdf.js/web/viewer.html?file=x',
  'https://dl.dropboxusercontent.com/scl/plan.pdf',
  'https://levelog-r2.example.com/co/proj/plan.pdf?X-Amz-Signature=abc',
];
for (const u of foreignShapes) {
  const got = authorizedPdfUrl(u, { apiBase: API_BASE, token: TOKEN });
  ok(!String(got).includes('token=') && !String(got).includes(TOKEN),
    `no token on a foreign origin: ${u.slice(0, 46)}`);
}

ok(authorizedPdfUrl('file:///data/user/0/doc.pdf', { apiBase: API_BASE, token: TOKEN })
  === 'file:///data/user/0/doc.pdf',
  'a local file:// is returned untouched — never decorated with a token');

ok(!String(authorizedPdfUrl(PROXY, { apiBase: API_BASE, token: null })).includes('token='),
  'no token stored -> no token param');

ok(isFirstPartyProxyUrl(`${API_BASE}${PROXY}`, API_BASE),
  'first-party check accepts our proxy path on our origin');
ok(!isFirstPartyProxyUrl(`https://mozilla.github.io${PROXY}`, API_BASE),
  'first-party check is by ORIGIN, not by path shape');
ok(!isFirstPartyProxyUrl(`${API_BASE}/api/projects/p1/files/f1/content/../../x`, API_BASE),
  'first-party check anchors the proxy path at both ends');
ok(toAbsolutePdfUrl('https://other.example/x.pdf', API_BASE) === 'https://other.example/x.pdf',
  'an already-absolute url is not rewritten onto our base');

console.log('\n-- 2. a platform with no PDF renderer is never handed a remote url --');

const remotes = [`${API_BASE}${PROXY}`, PROXY, 'https://dl.dropboxusercontent.com/scl/plan.pdf'];
for (const u of remotes) {
  ok(pdfSourcePlan(u, 'android').kind === 'download',
    `android must fetch the bytes itself: ${u.slice(0, 46)}`);
  ok(pdfSourcePlan(u, 'ios').kind === 'direct',
    `ios renders the remote url itself (PDFKit): ${u.slice(0, 46)}`);
}
// An unknown platform must fail SAFE, not fall through to "hand it a url".
ok(pdfSourcePlan(remotes[0], undefined).kind === 'download',
  'an unknown platform downloads rather than being handed a remote url');
ok(pdfSourcePlan('file:///x/doc.pdf', 'android').kind === 'local',
  'a cached file:// is already local on android');
ok(pdfSourcePlan(null, 'android').kind === 'none', 'no url -> nothing to show');
ok(isLocalFileUri('file:///x') && !isLocalFileUri(`${API_BASE}/x`), 'isLocalFileUri');

// The download key becomes a FILENAME, so it has to stay bounded.
const longPath = '/Construction Plans/' + 'x'.repeat(300) + '/Sheet A-101.pdf';
ok(pdfCacheKey({ id: 'abc123' }, PROXY) === 'abc123', 'cache key prefers the record id');
ok(pdfCacheKey({ path: longPath }, PROXY).length <= 48, 'cache key stays filename-sized');
ok(/^[A-Za-z0-9_-]+$/.test(pdfCacheKey({ path: longPath }, PROXY)), 'cache key is filename-safe');
ok(pdfCacheKey({ path: longPath }, PROXY) === pdfCacheKey({ path: longPath }, PROXY),
  'cache key is stable for the same document');
ok(pdfCacheKey({ path: longPath + 'a' }, PROXY) !== pdfCacheKey({ path: longPath + 'b' }, PROXY),
  'two documents that differ only past the cap still get different keys');

// ═══════════════════════════════════════════════════════════════════════════
// 3. SOURCE — no absolute origin in either viewer that is not ours.
//    Read as a PROPERTY: any third-party host trips this, not just the one
//    that was there.
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- 3. no third-party origin appears in either viewer --');

const ALLOWED_HOSTS = new Set(['api.levelog.com']);

/** Every host in every string/template the file actually EVALUATES. Comments
 *  are excluded by construction — a comment is neither a literal nor a quasi,
 *  which matters here because both files now explain the defect in prose. */
function evaluatedHosts(rel) {
  const hosts = new Set();
  const collect = (text) => {
    const re = /https?:\/\/([A-Za-z0-9._-]+)/g;
    let m;
    while ((m = re.exec(String(text))) !== null) hosts.add(m[1].toLowerCase());
  };
  walk(ast(rel), (n) => {
    if (n.type === 'StringLiteral') collect(n.value);
    if (n.type === 'TemplateElement') collect(n.value.cooked || '');
  });
  return hosts;
}

for (const rel of [NATIVE, WEB]) {
  const hosts = [...evaluatedHosts(rel)];
  const foreign = hosts.filter((h) => !ALLOWED_HOSTS.has(h));
  ok(foreign.length === 0,
    `${rel}: no foreign origin in evaluated source (found: ${foreign.join(', ') || 'none'})`);
}

// The mechanism, named: nothing may url-encode a url INTO another url. That is
// the exact shape that carried the token off-origin.
for (const rel of [NATIVE, WEB]) {
  let wraps = false;
  walk(ast(rel), (n) => {
    if (n.type !== 'TemplateLiteral') return;
    const text = n.quasis.map((q) => q.value.cooked || '').join(' ');
    if (!/https?:\/\//.test(text)) return;
    // A template that BOTH names an absolute origin AND interpolates an
    // encodeURIComponent(...) is a url being nested inside a url.
    const encodes = n.expressions.some((e) =>
      e.type === 'CallExpression' && e.callee.type === 'Identifier'
      && e.callee.name === 'encodeURIComponent');
    if (encodes) wraps = true;
  });
  ok(!wraps, `${rel}: no url is url-encoded into another absolute url`);
}

// ═══════════════════════════════════════════════════════════════════════════
// 4. SOURCE — Try Again reaches the same loader the first open reached.
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- 4. Try Again runs the real loader --');

/** The onPress JSX attribute of the Pressable whose subtree renders `label`. */
function onPressForLabel(rel, label) {
  let hit = null;
  walk(ast(rel), (n) => {
    if (hit || n.type !== 'JSXElement') return;
    const name = n.openingElement.name;
    if (!(name.type === 'JSXIdentifier' && name.name === 'Pressable')) return;
    let labelled = false;
    walk(n, (c) => { if (c.type === 'JSXText' && c.value.trim() === label) labelled = true; });
    if (!labelled) return;
    hit = n.openingElement.attributes.find(
      (a) => a.type === 'JSXAttribute' && a.name.name === 'onPress');
  });
  return hit;
}

/** Identifiers referenced anywhere inside a node. */
function identsIn(node) {
  const out = new Set();
  walk(node, (n) => { if (n.type === 'Identifier') out.add(n.name); });
  return out;
}

for (const rel of [NATIVE, WEB]) {
  const attr = onPressForLabel(rel, 'Try Again');
  ok(!!attr, `${rel}: a Try Again button exists`);
  const idents = attr ? identsIn(attr) : new Set();
  ok(idents.has('loadPdf'), `${rel}: Try Again invokes the shared loader`);
  // The old handler's tell: it re-fetched a url and shoved it straight in.
  ok(!idents.has('setUrl'),
    `${rel}: Try Again does not set the url itself, so it cannot skip resolution`);
}

// THE CLASS: a raw `<response>.url` must never reach setUrl anywhere. That is
// what made the retry load a bare relative path with no token.
for (const rel of [NATIVE, WEB]) {
  const bad = [];
  walk(ast(rel), (n) => {
    if (n.type !== 'CallExpression') return;
    if (!(n.callee.type === 'Identifier' && n.callee.name === 'setUrl')) return;
    const a = n.arguments[0];
    if (!a) return;
    if ((a.type === 'MemberExpression' || a.type === 'OptionalMemberExpression')
      && a.property && a.property.name === 'url') bad.push(rel);
  });
  ok(bad.length === 0, `${rel}: setUrl is never handed a raw response .url`);
}

// And the loader itself must be a single definition both callers share.
for (const rel of [NATIVE, WEB]) {
  let defs = 0;
  walk(ast(rel), (n) => {
    if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && n.id.name === 'loadPdf') defs += 1;
  });
  ok(defs === 1, `${rel}: exactly one loadPdf definition`);
}

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
