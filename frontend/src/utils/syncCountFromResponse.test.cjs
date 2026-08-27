/**
 * THE COUNT COMES FROM THE RESPONSE, NOT FROM A MID-SYNC RE-READ.
 *
 * POST /sync-dropbox says it in its own docstring -- "returns immediately, runs
 * sync in background" -- and hands back a recursive Dropbox count it gathered
 * for exactly this purpose ("Quick count from Dropbox for immediate response").
 *
 * Both callers discarded it and then counted project_files rows that the
 * background task had not finished inserting. That is where "3 files synced"
 * came from on a folder holding 15, and it stuck: nothing refreshes the number
 * until the screen remounts.
 *
 * The label went with it. While the task is running the number is a TARGET, so
 * "synced" is a claim we cannot make yet. The Last Synced stat carries that
 * claim on its own, from a timestamp the background task stamps when it
 * actually finishes.
 *
 * READ AS CODE. Both files now carry comments naming file_count, "synced" and
 * the mid-sync read, so every substring check would be satisfied by the
 * explanation instead of the behaviour.
 *
 * Run:  node src/utils/syncCountFromResponse.test.cjs
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
    if (n.type === 'VariableDeclarator' && n.id && n.id.name === name) hit = n.init;
    if (n.type === 'FunctionDeclaration' && n.id && n.id.name === name) hit = n;
  });
  if (!hit) throw new Error(`${name} not found`);
  return hit;
}

function callsTo(node, prop) {
  const out = [];
  walk(node, (n) => {
    if (n.type === 'CallExpression'
        && n.callee.type === 'MemberExpression'
        && n.callee.property.name === prop) out.push(n);
  });
  return out;
}

/** Every JSX text and string/template literal in a subtree. */
function textsIn(node) {
  const out = [];
  walk(node, (n) => {
    if (n.type === 'JSXText') out.push(n.value);
    if (n.type === 'StringLiteral') out.push(n.value);
    if (n.type === 'TemplateLiteral') out.push(n.quasis.map((q) => q.value.cooked).join(' '));
  });
  return out;
}

const SETTINGS = 'app/projects/[id]/dropbox-settings.jsx';
const PLANS = 'app/projects/[id]/construction-plans.jsx';

// ═══════════════════════════════════════════════════════════════════════════
// 1. The settings screen: the response is captured and used, and the
//    mid-sync re-read is GONE.
// ═══════════════════════════════════════════════════════════════════════════
const settingsTree = ast(SETTINGS);
const dsSync = findFn(settingsTree, 'handleSync');

// syncProject's result is assigned, not awaited-and-dropped.
let captured = false;
walk(dsSync, (n) => {
  if (n.type !== 'VariableDeclarator' || !n.init) return;
  walk(n.init, (c) => {
    if (c.type === 'CallExpression'
        && c.callee.type === 'MemberExpression'
        && c.callee.property.name === 'syncProject') captured = true;
  });
});
ok(captured, 'settings: syncProject result is captured, not discarded');

ok(callsTo(dsSync, 'getProjectFiles').length === 0,
  'settings: NO getProjectFiles re-read inside handleSync');

// setFileCount's argument must mention file_count and must NOT use .length
let usesFileCount = false;
let usesLength = false;
for (const call of callsTo(dsSync, 'setFileCount').concat(
  (() => { const o = []; walk(dsSync, (n) => {
    if (n.type === 'CallExpression' && n.callee.type === 'Identifier'
        && n.callee.name === 'setFileCount') o.push(n); }); return o; })())) {
  walk(call, (n) => {
    if (n.type === 'MemberExpression' && n.property && n.property.name === 'file_count') usesFileCount = true;
    if (n.type === 'MemberExpression' && n.property && n.property.name === 'length') usesLength = true;
  });
}
ok(usesFileCount, 'settings: the count comes from response.file_count');
ok(!usesLength, 'settings: the count is NOT a .length of a mid-sync row read');

// ═══════════════════════════════════════════════════════════════════════════
// 2. The label no longer claims the copy is complete.
// ═══════════════════════════════════════════════════════════════════════════
let claimsSynced = false;
walk(settingsTree, (n) => {
  if (n.type !== 'JSXText') return;
  if (/files\s+synced/i.test(n.value)) claimsSynced = true;
});
ok(!claimsSynced, 'settings: no "N files synced" label survives');

const dsToasts = textsIn(dsSync);
ok(!dsToasts.some((t) => /synchronized/i.test(t)),
  'settings: the toast does not claim files are synchronized');

// "Last Synced" stays -- it is the one honest completed-sync claim, stamped by
// the background task when it finishes.
ok(textsIn(settingsTree).some((t) => /Last Synced/.test(t)),
  'settings: the Last Synced stat is kept');

// ═══════════════════════════════════════════════════════════════════════════
// 3. The plans screen: same response used, same claim withdrawn. It still
//    re-reads the LIST, because it renders rows -- that is not a count.
// ═══════════════════════════════════════════════════════════════════════════
const plansTree = ast(PLANS);
const cpSync = findFn(plansTree, 'handleSync');

let cpCaptured = false;
walk(cpSync, (n) => {
  if (n.type !== 'VariableDeclarator' || !n.init) return;
  walk(n.init, (c) => {
    if (c.type === 'CallExpression'
        && c.callee.type === 'MemberExpression'
        && c.callee.property.name === 'syncProject') cpCaptured = true;
  });
});
ok(cpCaptured, 'plans: syncProject result is captured');

let cpUsesFileCount = false;
walk(cpSync, (n) => {
  if (n.type === 'MemberExpression' && n.property && n.property.name === 'file_count') {
    cpUsesFileCount = true;
  }
});
ok(cpUsesFileCount, 'plans: the sync message uses file_count');

ok(callsTo(cpSync, 'getProjectFiles').length === 1,
  'plans: still reads the list once -- it renders rows, not a count');

const cpToasts = textsIn(cpSync);
ok(!cpToasts.some((t) => /synchronized/i.test(t)),
  'plans: the toast does not claim files are synchronized');
ok(!cpToasts.some((t) => /^Synced$/.test(t.trim())),
  'plans: the toast title is not the bare claim "Synced"');

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
