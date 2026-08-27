/**
 * DISCONNECT MUST NOT LINK THE PROJECT TO THE WHOLE DROPBOX.
 *
 * link_dropbox_to_project reads its body as:
 *     folder_path: None      -> unlink
 *     folder_path: "" or "/" -> LINK TO ROOT of the Dropbox scope
 *
 * project/[id].jsx's Disconnect sent ''. That stored "/" instead of clearing
 * the field, and _sync_project_to_r2 lists with recursive=True -- so the next
 * sync would have copied every file the company owns into ONE project's
 * project_files rows and onto R2 under that project's prefix.
 *
 * It never fired: the button renders behind `dropbox_enabled && dropbox_folder`,
 * two fields nothing has written since create_project. Correcting those names
 * is what arms it. This is held shut first so that correction is safe.
 *
 * The picker had the same hole reachable by hand: "Select This Folder" at depth
 * 0 sent `currentPath || '/'`.
 *
 * READ AS CODE, NOT AS TEXT. Both files now carry comments that name '' , '/'
 * and null and explain the trap, so every substring check here would be
 * satisfied by the explanation rather than the behaviour.
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

function ast(rel) {
  const file = path.join(__dirname, '..', '..', rel);
  return parser.parse(fs.readFileSync(file, 'utf8'), {
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
    if ((n.type === 'FunctionDeclaration') && n.id && n.id.name === name) hit = n;
  });
  if (!hit) throw new Error(`${name} not found`);
  return hit;
}

// ═══════════════════════════════════════════════════════════════════════════
// 1. Disconnect sends null.
// ═══════════════════════════════════════════════════════════════════════════
const projTree = ast('app/project/[id].jsx');
const disconnect = findFn(projTree, 'handleDisconnectDropbox');

const linkArgs = [];
walk(disconnect, (n) => {
  if (n.type === 'CallExpression'
      && n.callee.type === 'MemberExpression'
      && n.callee.property.name === 'linkFolder') {
    linkArgs.push(n.arguments[1]);
  }
});

ok(linkArgs.length === 1, 'Disconnect calls linkFolder exactly once');
ok(linkArgs.length === 1 && linkArgs[0] && linkArgs[0].type === 'NullLiteral',
  'Disconnect passes null (the unlink value), as a literal');
ok(!linkArgs.some((a) => a && a.type === 'StringLiteral'),
  'Disconnect passes NO string -- \'\' and \'/\' both link to root');

// ═══════════════════════════════════════════════════════════════════════════
// 2. The picker cannot select root -- guarded at the handler, which is the
//    class. A new call site cannot reintroduce it.
// ═══════════════════════════════════════════════════════════════════════════
const settingsTree = ast('app/projects/[id]/dropbox-settings.jsx');
const select = findFn(settingsTree, 'handleSelectFolder');

// The guard must RETURN before any link call, not merely exist.
let guardReturnsEarly = false;
walk(select, (n) => {
  if (n.type !== 'IfStatement') return;
  const body = n.consequent;
  const stmts = body.type === 'BlockStatement' ? body.body : [body];
  const returns = stmts.some((st) => st.type === 'ReturnStatement');
  if (!returns) return;
  // and its test must mention a '/' comparison or a falsy check
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
walk(settingsTree, (n) => {
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
walk(settingsTree, (n) => {
  if (n.type !== 'ConditionalExpression') return;
  if (!(n.test && n.test.name === 'currentPath')) return;
  let hasSelectText = false;
  walk(n.consequent, (c) => {
    if (c.type === 'JSXText' && /Select This Folder/.test(c.value)) hasSelectText = true;
  });
  if (hasSelectText) selectIsConditional = true;
});
ok(selectIsConditional,
  '"Select This Folder" renders only when currentPath is non-empty');

// And the depth-0 branch states a reason rather than rendering nothing.
let rootBranchExplains = false;
walk(settingsTree, (n) => {
  if (n.type !== 'ConditionalExpression') return;
  if (!(n.test && n.test.name === 'currentPath')) return;
  walk(n.alternate, (c) => {
    if (c.type === 'JSXText' && /cannot be linked to/i.test(c.value)) {
      rootBranchExplains = true;
    }
  });
});
ok(rootBranchExplains, 'the root branch tells the admin WHY, on screen');

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
