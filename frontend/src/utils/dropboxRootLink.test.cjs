/**
 * LINKING MUST NOT LINK THE PROJECT TO THE WHOLE DROPBOX.
 *
 * link_dropbox_to_project reads its body as:
 *     folder_path: None      -> unlink
 *     folder_path: "" or "/" -> LINK TO ROOT of the Dropbox scope
 *
 * and _sync_project_to_r2 lists RECURSIVELY -- so a root link copies every file
 * the company owns into ONE project's project_files rows and onto R2 under that
 * project's prefix. The value that looks most like "clear this field" is the
 * one that does the most damage.
 *
 * ── WHAT CHANGED, AND WHY THIS FILE LOOKS DIFFERENT NOW ───────────────────
 *
 * The original of this test held two things shut:
 *
 *   1. project/[id].jsx's Disconnect, which sent ''. It never fired, because
 *      the button rendered behind `dropbox_enabled && dropbox_folder` -- two
 *      fields nothing has written since create_project. A dead control in
 *      front of a live trap. The redesign DELETED that whole block: the modal,
 *      the free-text path field, the file list and the Disconnect. So the
 *      assertion is no longer "Disconnect passes null" but "there is no
 *      Disconnect, and no second linker, on that screen at all" -- which is
 *      the stronger statement, and the one that cannot rot.
 *
 *   2. The picker in dropbox-settings.jsx. That screen is gone too; plans and
 *      documents were never two subjects, and the folder they come from is not
 *      a third. Its guards moved to projects/[id]/files.jsx and are asserted
 *      there, unchanged in substance.
 *
 * READ AS CODE, NOT AS TEXT. Both files carry comments that name '', '/' and
 * null and explain the trap, so every substring check here would be satisfied
 * by the explanation rather than by the behaviour.
 *
 * Run:  node src/utils/dropboxRootLink.test.cjs
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

function src(rel) {
  return fs.readFileSync(path.join(__dirname, '..', '..', rel), 'utf8');
}

function ast(rel) {
  return parser.parse(src(rel), { sourceType: 'module', plugins: ['jsx'] });
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
    if ((n.type === 'FunctionDeclaration') && n.id && n.id.name === name) hit = n;
  });
  if (!hit) throw new Error(`${name} not found`);
  return hit;
}

function maybeFn(tree, name) {
  try { return findFn(tree, name); } catch (_e) { return null; }
}

const FILES = 'app/projects/[id]/files.jsx';
const PROJECT = 'app/project/[id].jsx';

// ═══════════════════════════════════════════════════════════════════════════
// 1. project/[id].jsx is not a Dropbox writer any more.
//
//    One row that states the folder or "Not linked" and taps through. No
//    modal, no typed path, no Disconnect, no second copy of the API client.
// ═══════════════════════════════════════════════════════════════════════════
const projTree = ast(PROJECT);

ok(maybeFn(projTree, 'handleDisconnectDropbox') === null,
  'project screen: handleDisconnectDropbox is gone');
ok(maybeFn(projTree, 'handleLinkDropbox') === null,
  'project screen: handleLinkDropbox is gone');
ok(maybeFn(projTree, 'fetchDropboxFiles') === null,
  'project screen: the second file list is gone');

// No local dropboxAPI shim -- the one that called link-dropbox directly.
let hasShim = false;
walk(projTree, (n) => {
  if (n.type === 'VariableDeclarator' && n.id && n.id.name === 'dropboxAPI') hasShim = true;
});
ok(!hasShim, 'project screen: the local dropboxAPI shim is gone');

// Nothing on this screen calls the linking endpoint, under any name.
let linkCalls = 0;
walk(projTree, (n) => {
  if (n.type === 'CallExpression'
      && n.callee.type === 'MemberExpression'
      && ['linkFolder', 'linkToProject'].includes(n.callee.property.name)) {
    linkCalls += 1;
  }
});
ok(linkCalls === 0, 'project screen: nothing calls the link endpoint');

let mentionsLinkDropboxPath = /link-dropbox/.test(
  // strip comments: the deletion is explained in one, and the explanation
  // names the endpoint.
  src(PROJECT).replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, ''),
);
ok(!mentionsLinkDropboxPath,
  'project screen: the /link-dropbox path is not referenced in code');

// THE DEAD-FIELD PREDICATE IS GONE. It is what kept the trap unreachable and
// therefore unnoticed; correcting the field names would have armed it.
const projCode = src(PROJECT)
  .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
ok(!/dropbox_enabled/.test(projCode),
  'project screen: no code reads dropbox_enabled');
ok(!/dropbox_folder(?![_a-zA-Z])/.test(projCode),
  'project screen: no code reads dropbox_folder');
ok(/dropbox_folder_path/.test(projCode),
  'project screen: the row reads dropbox_folder_path, the live field');

// ═══════════════════════════════════════════════════════════════════════════
// 2. The picker cannot select root -- guarded at the handler, which is the
//    class. A new call site cannot reintroduce it.
// ═══════════════════════════════════════════════════════════════════════════
const filesTree = ast(FILES);
const select = findFn(filesTree, 'handleSelectFolder');

// The guard must RETURN before any link call, not merely exist.
let guardReturnsEarly = false;
walk(select, (n) => {
  if (n.type !== 'IfStatement') return;
  const body = n.consequent;
  const stmts = body.type === 'BlockStatement' ? body.body : [body];
  const returns = stmts.some((st) => st.type === 'ReturnStatement');
  if (!returns) return;
  let mentionsRoot = false;
  walk(n.test, (t) => {
    if (t.type === 'StringLiteral' && t.value === '/') mentionsRoot = true;
    if (t.type === 'UnaryExpression' && t.operator === '!') mentionsRoot = true;
  });
  if (mentionsRoot) guardReturnsEarly = true;
});
ok(guardReturnsEarly,
  'handleSelectFolder returns early for a falsy path or \'/\'');

// No call site inside the picker may pass `currentPath || '/'` any more.
let rootFallback = false;
walk(filesTree, (n) => {
  if (n.type === 'LogicalExpression' && n.operator === '||'
      && n.right && n.right.type === 'StringLiteral' && n.right.value === '/'
      && n.left && n.left.name === 'currentPath') {
    rootFallback = true;
  }
});
ok(!rootFallback, 'no `currentPath || \'/\'` fallback survives anywhere');

// The Select control is behind a conditional on currentPath, so depth 0 has
// no selectable control at all.
let selectIsConditional = false;
walk(filesTree, (n) => {
  if (n.type !== 'ConditionalExpression') return;
  if (!(n.test && n.test.name === 'currentPath')) return;
  let hasSelectText = false;
  walk(n.consequent, (c) => {
    if (c.type === 'JSXText' && /Link this folder/.test(c.value)) hasSelectText = true;
    if (c.type === 'StringLiteral' && /Link this folder/.test(c.value)) hasSelectText = true;
  });
  if (hasSelectText) selectIsConditional = true;
});
ok(selectIsConditional,
  'the link control renders only when currentPath is non-empty');

// And the depth-0 branch states a reason rather than rendering nothing.
let rootBranchExplains = false;
walk(filesTree, (n) => {
  if (n.type !== 'ConditionalExpression') return;
  if (!(n.test && n.test.name === 'currentPath')) return;
  walk(n.alternate, (c) => {
    if (c.type === 'JSXText' && /cannot be linked to/i.test(c.value)) {
      rootBranchExplains = true;
    }
  });
});
ok(rootBranchExplains, 'the root branch tells the admin WHY, on screen');

// ═══════════════════════════════════════════════════════════════════════════
// 3. PICKER ONLY. There is no way to type a path.
//
//    The deleted modal had a GlassInput bound to a folder-path state. Nobody
//    types a Dropbox path, and the one who tries types it wrong -- then reads
//    the server's rejection as his own mistake.
// ═══════════════════════════════════════════════════════════════════════════
let typedPathInput = false;
walk(filesTree, (n) => {
  if (n.type !== 'JSXOpeningElement') return;
  const tag = n.name && n.name.name;
  if (!['TextInput', 'GlassInput'].includes(tag)) return;
  for (const attr of n.attributes || []) {
    if (attr.type !== 'JSXAttribute') continue;
    if (attr.name.name !== 'value' && attr.name.name !== 'onChangeText') continue;
    walk(attr, (c) => {
      if (c.type === 'Identifier' && /folder|path/i.test(c.name)) typedPathInput = true;
    });
  }
});
ok(!typedPathInput, 'no text input is bound to a folder path');

// ═══════════════════════════════════════════════════════════════════════════
// 4. UNLINK IS ITS OWN LABELLED CONTROL, AND IT SENDS null.
//
//    It used to be the off-position of a Switch labelled "Enable Dropbox",
//    which is not a label for removing a link -- and which made linked-ness a
//    thing the UI remembered as well as a thing the server stored.
// ═══════════════════════════════════════════════════════════════════════════
const unlink = findFn(filesTree, 'handleUnlink');

const unlinkArgs = [];
walk(unlink, (n) => {
  if (n.type === 'CallExpression'
      && n.callee.type === 'MemberExpression'
      && ['linkToProject', 'linkFolder'].includes(n.callee.property.name)) {
    unlinkArgs.push(n.arguments[1]);
  }
});
ok(unlinkArgs.length === 1, 'unlink calls the link endpoint exactly once');
ok(unlinkArgs.length === 1 && unlinkArgs[0] && unlinkArgs[0].type === 'NullLiteral',
  'unlink passes null (the unlink value), as a literal');
ok(!unlinkArgs.some((a) => a && a.type === 'StringLiteral'),
  'unlink passes NO string -- \'\' and \'/\' both link to root');

// No Switch decides linked-ness. The field does.
let hasSwitch = false;
walk(filesTree, (n) => {
  if (n.type === 'JSXOpeningElement' && n.name && n.name.name === 'Switch') hasSwitch = true;
});
ok(!hasSwitch, 'no Switch stands in for bool(dropbox_folder_path)');

let hasEnabledState = false;
walk(filesTree, (n) => {
  if (n.type === 'Identifier' && n.name === 'setDropboxEnabled') hasEnabledState = true;
});
ok(!hasEnabledState, 'no local dropboxEnabled state shadows the server field');

// The control says what it does AND what it does not delete. A person who
// thinks it deletes his drawings will not press it; one who thinks it tidies
// up is surprised later.
const filesText = src(FILES);
ok(/Nothing in your Dropbox is changed or deleted/i.test(filesText),
  'the unlink dialog says Dropbox itself is untouched');
ok(/Files already synced into this project stay/i.test(filesText),
  'the unlink dialog says the synced files are kept');
ok(/no longer arrive here/i.test(filesText),
  'the unlink dialog says what stops happening');

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
