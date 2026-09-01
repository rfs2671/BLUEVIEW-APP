/**
 * THE THREE SCREEN-SHAPE DEFECTS THAT MADE "SAVE FOR OFFLINE" A LIE.
 *
 * A CP loads Plans on the street, taps Save for offline, walks down into a
 * cellar and taps a drawing. Every byte he needs is on the phone. Before this
 * change he got, in order:
 *
 *   1. A SPINNER, for the full socket timeout. The screens read the cached
 *      list FIRST and called setFiles(cached) — and then left `loading` true
 *      until after the network settled. The whole body is gated on `loading`,
 *      so the cache-first paint was painted behind a spinner. The cached list
 *      is real the moment it is read; the spinner has to come down there.
 *      site/logbooks.jsx already had this order right.
 *
 *   2. AND THAT TIMEOUT HAD NO CEILING. The axios instance was created with no
 *      `timeout`, so an offline request hung for the platform socket timeout —
 *      on Android that is over a minute of nothing.
 *
 *   3. THEN, ON ANDROID, THE WRONG FILE. The open path read
 *      `if (local && (Platform.OS === 'ios' || offline))`, and `offline` is
 *      `fetchState === 'offline'` — a record of how the LAST list fetch went,
 *      set only by a fetch that already failed during this mount. In the
 *      sequence above it is still 'ok', so Android fell past the correct bytes
 *      on disk and reached for a remote URL that could not resolve.
 *
 * These are three files with the same shape, which is exactly why a
 * grep-shaped guard is worth more than a fix: the next screen copied from
 * these must not copy the bug back in.
 *
 * Run:  node src/utils/offlinePlansUsable.test.cjs
 */

const fs = require('fs');
const path = require('path');
const parser = require('@babel/parser');
const generate = require('@babel/generator').default;

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const ROOT = path.join(__dirname, '..', '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

// Every check below runs against code with comments blanked out: these files
// explain the rejected form in prose, and a comment must never satisfy or
// break a guard.
const decomment = (raw) => raw
  .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
  .replace(/^\s*\/\/.*$/gm, '');

const parse = (raw) => parser.parse(raw, { sourceType: 'module', plugins: ['jsx'] });

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

const contains = (root, target) => {
  let found = false;
  walk(root, (n) => { if (n === target) found = true; });
  return found;
};

// The three screens that read a cached document list and gate their body on
// `loading`. app/site/logbooks.jsx is deliberately NOT here — it is the screen
// the others were fixed to match.
const SCREENS = [
  'app/projects/[id]/files.jsx',
  'app/documents.jsx',
  'app/site/documents.jsx',
];

// ═══════════════════════════════════════════════════════════════════════════
// 1. THE SPINNER COMES DOWN ON THE CACHED PAINT, NOT AFTER THE NETWORK.
// ═══════════════════════════════════════════════════════════════════════════
for (const rel of SCREENS) {
  const code = decomment(read(rel));
  const tree = parse(code);

  // The loader is the INNERMOST function that both reads a cached list and
  // owns the screen spinner. Innermost matters: the component function
  // contains it, and would trivially "contain" both markers.
  const candidates = [];
  walk(tree, (n) => {
    if (n.type !== 'ArrowFunctionExpression'
      && n.type !== 'FunctionExpression'
      && n.type !== 'FunctionDeclaration') return;
    if (!n.body || n.body.type !== 'BlockStatement') return;
    const src = generate(n).code;
    if (!/readCached(DocList|ProjectList)\s*\(/.test(src)) return;
    if (src.indexOf('setLoading(false)') === -1) return;
    candidates.push(n);
  });
  const loaders = candidates.filter(
    (c) => !candidates.some((o) => o !== c && contains(c, o)),
  );

  ok(loaders.length === 1,
    `${rel}: exactly one cache-first loader owns the spinner `
    + `(found ${loaders.length})`);
  if (loaders.length !== 1) continue;

  const stmts = loaders[0].body.body.map((s) => generate(s).code);
  const firstDown = stmts.findIndex((s) => s.indexOf('setLoading(false)') !== -1);
  const firstNet = stmts.findIndex((s) => /settleFetch\s*\(/.test(s));

  ok(firstDown !== -1 && firstNet !== -1,
    `${rel}: the loader both drops the spinner and hits the network`);
  ok(firstDown !== -1 && firstNet !== -1 && firstDown < firstNet,
    `${rel}: THE SPINNER COMES DOWN BEFORE THE FIRST NETWORK CALL — the `
    + `cache-first paint is visible instead of being painted behind a spinner `
    + `that resolves only when the request finally times out`);
  ok(stmts[stmts.length - 1].indexOf('setLoading(false)') !== -1,
    `${rel}: and it still comes down at the end, for the cold-cache path`);
}

// ═══════════════════════════════════════════════════════════════════════════
// 2. THE BYTES ON DISK WIN, ON EVERY PLATFORM.
// ═══════════════════════════════════════════════════════════════════════════
for (const rel of SCREENS) {
  const code = decomment(read(rel));

  ok(/\bensureCachedDocFile\s*\(/.test(code),
    `${rel}: still asks the cache for a local copy before opening`);
  ok(!/\blocal\s*&&\s*\(/.test(code),
    `${rel}: THE LOCAL HIT IS NOT CONDITIONED ON ANYTHING ELSE — `
    + `\`local && (Platform.OS === 'ios' || offline)\` sent Android past the `
    + `correct bytes, because \`offline\` is how the last fetch went, not `
    + `whether there is a network right now`);
  ok(/if\s*\(\s*local\s*\)\s*\{/.test(code),
    `${rel}: the cached copy is taken on a bare \`if (local)\``);
  ok(!/Platform\.OS\s*===\s*'ios'\s*\|\|\s*offline/.test(code),
    `${rel}: and the stale-flag platform split is gone entirely`);
}

// ═══════════════════════════════════════════════════════════════════════════
// 3. THE HTTP CLIENT GIVES UP IN HUMAN TIME.
//
//    With no `timeout` axios waits for the platform socket timeout. Offline
//    that is the difference between a screen that says "offline" and a screen
//    that appears frozen. A ceiling here is what makes the cache-first paint
//    above worth painting.
// ═══════════════════════════════════════════════════════════════════════════
{
  const code = decomment(read('src/utils/api.js'));
  const tree = parse(code);

  let created = null;
  walk(tree, (n) => {
    if (n.type !== 'CallExpression') return;
    const c = n.callee;
    if (!(c && c.type === 'MemberExpression'
      && c.object.name === 'axios' && c.property.name === 'create')) return;
    if (n.arguments[0] && n.arguments[0].type === 'ObjectExpression') {
      created = n.arguments[0];
    }
  });

  ok(created !== null, 'api.js creates the shared axios instance with options');
  const prop = created && created.properties.find(
    (p) => p.type === 'ObjectProperty' && (p.key.name || p.key.value) === 'timeout',
  );
  ok(!!prop, 'THE SHARED CLIENT SETS A TIMEOUT — without one an offline '
    + 'request hangs for the platform socket timeout and the screen just '
    + 'sits there');
  // The value may be a literal or a named module constant; resolve both, so
  // naming the number does not silently disable this check.
  const literalOf = (node) => {
    if (!node) return null;
    if (node.type === 'NumericLiteral') return node.value;
    if (node.type !== 'Identifier') return null;
    let found = null;
    walk(tree, (n) => {
      if (n.type !== 'VariableDeclarator') return;
      if (n.id.type === 'Identifier' && n.id.name === node.name
        && n.init && n.init.type === 'NumericLiteral') found = n.init.value;
    });
    return found;
  };
  const ms = prop ? literalOf(prop.value) : null;
  ok(Number.isFinite(ms) && ms >= 5000 && ms <= 60000,
    `and it is a literal in human range (got ${ms}) — long enough for a slow `
    + 'cell connection, short enough that a dead zone is reported rather than '
    + 'endured');

  // The default must not silently shorten the long jobs. An upload of a full
  // set of drawings over site LTE is minutes, not seconds; a 15s default
  // applied to it would fail every large upload.
  const uploadTimeouts = [...code.matchAll(/timeout:\s*(\d+)/g)].map((m) => Number(m[1]));
  ok(Number.isFinite(ms) && uploadTimeouts.some((t) => t > ms),
    'and at least one per-request override stays LONGER than the default — a '
    + 'global ceiling must not amputate the uploads and report builds that '
    + 'legitimately take minutes');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
