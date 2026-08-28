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

const FILES = 'app/projects/[id]/files.jsx';
const PLANS = FILES;

// ═══════════════════════════════════════════════════════════════════════════
// 1. THE HEADLINE TAKES BOTH ITS NUMBERS FROM THE LIST, NOT FROM THE SYNC.
//
//    dropbox-settings.jsx is gone -- it was a second screen for one field, and
//    its `setFileCount(res.file_count)` is gone with it. What replaced it is a
//    sentence: "412 files in 9 folders · last synced 3:04 PM".
//
//    `POST /sync-dropbox` returns a file_count taken from a RECURSIVE Dropbox
//    listing while the background copy into project_files is still running. It
//    is correct about Dropbox and wrong about the tree on screen. Taking the
//    file count from it and the folder count from the rows would produce a
//    sentence true of neither -- so the headline is derived, in one call, from
//    the one array being rendered.
// ═══════════════════════════════════════════════════════════════════════════
const filesTree = ast(FILES);

// The headline is computed by the shared helper over the rendered list.
let headlineFromList = false;
walk(filesTree, (n) => {
  if (n.type !== 'VariableDeclarator') return;
  if (!n.id || n.id.name !== 'headline' || !n.init) return;
  if (n.init.type === 'CallExpression'
      && n.init.callee.type === 'Identifier'
      && n.init.callee.name === 'treeHeadline') {
    headlineFromList = true;
  }
});
ok(headlineFromList, 'files: the headline is treeHeadline() over the file list');

// And nothing anywhere on this screen feeds file_count into a rendered count.
let countFromSync = false;
walk(filesTree, (n) => {
  if (n.type !== 'VariableDeclarator' || !n.init) return;
  const name = n.id && n.id.name;
  if (!name || !/count|headline|total/i.test(name)) return;
  walk(n.init, (c) => {
    if (c.type === 'MemberExpression' && c.property && c.property.name === 'file_count') {
      countFromSync = true;
    }
  });
});
ok(!countFromSync,
  'files: no rendered count is derived from the sync response file_count');

// There is no setFileCount state left to go stale between mounts.
let hasFileCountState = false;
walk(filesTree, (n) => {
  if (n.type === 'Identifier' && n.name === 'setFileCount') hasFileCountState = true;
});
ok(!hasFileCountState,
  'files: the standalone fileCount state is gone -- the count is derived');

// ═══════════════════════════════════════════════════════════════════════════
// 2. The label still never claims the copy is complete.
// ═══════════════════════════════════════════════════════════════════════════
let claimsSynced = false;
walk(filesTree, (n) => {
  if (n.type !== 'JSXText') return;
  if (/files\s+synced/i.test(n.value)) claimsSynced = true;
});
ok(!claimsSynced, 'files: no "N files synced" label survives');

// ═══════════════════════════════════════════════════════════════════════════
// 3. handleSync: the response's file_count is still used for the TOAST --
//    "Copying 412 files from Dropbox" is a statement about the TARGET, not
//    about the tree, and it is the honest thing to say while the copy runs.
//    The screen still re-reads the LIST, because it renders rows.
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
