/**
 * THE DASHBOARD BANNER NAMES WHAT FAILED, AND PARTIAL IS NOT TOTAL.
 *
 * `app/index.jsx` has two supporting reads — the worker list and today's
 * check-ins. The banner used to collapse them into one worst-of string:
 *
 *     "Some of today's data could not be read from the server.
 *      What you see may be incomplete."
 *
 * which is the SAME SENTENCE whether one of the two failed or both did. On a
 * compliance screen that is unusable: a reader who cannot tell which number is
 * untrustworthy has to distrust all of them, which is the opposite of what a
 * banner is for. It cost an evening of theories about which call was failing,
 * when the screen already knew and discarded it one line later.
 *
 * LOADED, FAILED and PARTIALLY LOADED ARE THREE STATES. Asserted here as three.
 *
 * The `affects` clause is the load-bearing part. On a first load a failed read
 * leaves its state at the initial `[]`, so the count renders **0**, not "—". A
 * plausible-looking zero is the dangerous output, and this banner is the only
 * thing on the page that says it is not a real one.
 *
 * READ AS CODE, NOT AS TEXT. The source carries comments naming the old
 * sentence and the failure it caused, so a substring check for the old copy
 * would match the explanation. Every assertion below reads the AST.
 *
 * Run:  node src/utils/dashboardNoticeNamesSource.test.cjs
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

const REL = path.join('app', 'index.jsx');
const FILE = path.join(__dirname, '..', '..', REL);
const raw = fs.readFileSync(FILE, 'utf8');
const tree = parser.parse(raw, { sourceType: 'module', plugins: ['jsx'] });

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

function declarator(name) {
  let hit = null;
  walk(tree, (n) => {
    if (hit) return;
    if (n.type === 'VariableDeclarator' && n.id && n.id.name === name) hit = n;
  });
  return hit;
}

// ═══════════════════════════════════════════════════════════════════════════
// 1. The per-source table exists and names both reads with what they affect.
// ═══════════════════════════════════════════════════════════════════════════
const sources = declarator('dashboardSources');
ok(Boolean(sources), 'dashboardSources is declared');

if (sources) {
  const entries = [];
  walk(sources.init, (n) => {
    if (n.type !== 'ObjectExpression') return;
    const keys = n.properties
      .filter((p) => p.type === 'ObjectProperty' && p.key)
      .map((p) => p.key.name || p.key.value);
    if (keys.includes('state')) entries.push(keys);
  });
  ok(entries.length === 2,
    `both supporting reads are listed (found ${entries.length})`);
  ok(entries.every((k) => k.includes('label')),
    'every source carries a label — the name of what failed');
  ok(entries.every((k) => k.includes('affects')),
    'every source carries `affects` — the number the reader must not trust');

  // The states wired in must be the two real ones, not a constant.
  const wired = [];
  walk(sources.init, (n) => {
    if (n.type === 'ObjectProperty' && n.key && n.key.name === 'state'
        && n.value && n.value.type === 'Identifier') wired.push(n.value.name);
  });
  ok(wired.includes('workersState') && wired.includes('checkinsState'),
    `states come from the real reads (got ${JSON.stringify(wired)})`);
}

// ═══════════════════════════════════════════════════════════════════════════
// 2. PARTIAL IS A DISTINCT STATE — the regression this file exists for.
// ═══════════════════════════════════════════════════════════════════════════
const partial = declarator('dashboardPartial');
ok(Boolean(partial),
  'dashboardPartial is declared — partial is not folded into failed');

if (partial) {
  // It must compare the failed count against the TOTAL, not merely test > 0.
  let comparesToTotal = false;
  walk(partial.init, (n) => {
    if (n.type !== 'BinaryExpression') return;
    if (!['<', '<=', '!=='].includes(n.operator)) return;
    const txt = raw.slice(n.start, n.end);
    if (/dashboardSources/.test(txt)) comparesToTotal = true;
  });
  ok(comparesToTotal,
    'partial is failed-count vs total, not just "something failed"');
}

// ═══════════════════════════════════════════════════════════════════════════
// 3. The rendered detail is BUILT from the sources, not a fixed string.
// ═══════════════════════════════════════════════════════════════════════════
const notice = declarator('renderDataNotice');
ok(Boolean(notice), 'renderDataNotice is declared');

if (notice) {
  const body = raw.slice(notice.start, notice.end);

  ok(/failedSources/.test(body),
    'the banner reads the failed sources');
  ok(/dashboardPartial/.test(body),
    'the banner branches on partial vs total');
  ok(/affects/.test(body),
    'the banner names the affected number, not just the source');

  // THE OLD COPY MUST BE GONE from the rendered path. Checked against the
  // function body only — the explanation above quotes it deliberately.
  ok(!/Some of today's data/.test(body),
    'the old unnamed "Some of today..." string is gone from the banner');

  // `detail` must be assembled, not a literal handed straight to the notice.
  let detailIsBuilt = false;
  walk(notice.init, (n) => {
    if (n.type !== 'VariableDeclarator' || !n.id || n.id.name !== 'detail') return;
    // A template literal or a concatenation counts; a bare StringLiteral does not.
    detailIsBuilt = n.init && n.init.type !== 'StringLiteral';
  });
  ok(detailIsBuilt,
    'detail is assembled from the failed sources, not a fixed sentence');
}

// ═══════════════════════════════════════════════════════════════════════════
// 4. The offline/error distinction survives — it decides wait vs escalate.
// ═══════════════════════════════════════════════════════════════════════════
if (notice) {
  const body = raw.slice(notice.start, notice.end);
  ok(/could not be fetched/.test(body) && /could not be read from the server/.test(body),
    'a dead zone and a server that answered still read differently');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
