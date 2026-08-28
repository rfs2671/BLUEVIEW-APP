/**
 * ONE ROLE PREDICATE ON THE FILES SCREEN.
 *
 * `app/projects/[id]/files.jsx` carried three, and they disagreed in the worst
 * direction available:
 *
 *   canDelete            ['owner','admin']   — the DESTRUCTIVE control, wide
 *   per-row delete       ['owner','admin']   — wide
 *   Upload / Sync bar    role === 'admin'    — the SAFE controls, narrow
 *
 * So an `owner` could delete a file and could not upload one. The narrow guard
 * sat on the harmless controls and the wide guard on the irreversible one.
 *
 * WHICH ONE IS RIGHT IS NOT A STYLE QUESTION — it is set by the server:
 *
 *     async def get_admin_user(current_user = Depends(get_current_user)):
 *         if current_user.get("role") not in ["admin", "owner"]:
 *             raise HTTPException(status_code=403, ...)
 *
 * `owner` is a role, admitted wherever a company admin is admitted, and
 * `is_platform_operator` is documented as "never inferred from role" — so this
 * is not a superuser flag leaking into the UI. The narrow predicate hides
 * controls the server would have served.
 *
 * This test exists because the split PREDATED the one-screen redesign and was
 * carried, unnoticed, into a renamed file. A grep-shaped guard is what stops
 * the next edit reintroducing it.
 *
 * Run:  node src/utils/filesScreenOnePredicate.test.cjs
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

const REL = 'app/projects/[id]/files.jsx';
const FILE = path.join(__dirname, '..', '..', REL);
const raw = fs.readFileSync(FILE, 'utf8');

// Comments explain the predicate and name the rejected form, so every check
// below runs against code with comments blanked out.
const code = raw
  .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
  .replace(/^\s*\/\/.*$/gm, '');

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

// ═══════════════════════════════════════════════════════════════════════════
// 1. The role list appears exactly once — at the single definition.
// ═══════════════════════════════════════════════════════════════════════════
const roleListHits = (code.match(/\['owner',\s*'admin'\]/g) || []).length;
ok(roleListHits === 1,
  `the ['owner','admin'] list appears once, at the definition (found ${roleListHits})`);

// ═══════════════════════════════════════════════════════════════════════════
// 2. The NARROW form appears nowhere. This is the actual regression.
// ═══════════════════════════════════════════════════════════════════════════
const narrow = (code.match(/role\s*===\s*'admin'/g) || []).length;
ok(narrow === 0,
  `no \`role === 'admin'\` survives — it locks an owner out of controls the `
  + `server serves (found ${narrow})`);

// A role read of any other shape is equally a second predicate.
const otherRoleReads = [];
walk(tree, (n) => {
  // `user?.role` parses as OptionalMemberExpression, not MemberExpression —
  // checking only the latter found zero reads and passed for the wrong reason.
  if (!['MemberExpression', 'OptionalMemberExpression'].includes(n.type)) return;
  if (!n.property || n.property.name !== 'role') return;
  const start = raw.lastIndexOf('\n', n.start) + 1;
  const line = raw.slice(start, raw.indexOf('\n', n.start));
  if (line.trimStart().startsWith(('*')) || line.trimStart().startsWith('//')) return;
  otherRoleReads.push(line.trim().slice(0, 80));
});
ok(otherRoleReads.length === 1,
  `\`user.role\` is read exactly once, inside isAdmin (found ${otherRoleReads.length}`
  + `${otherRoleReads.length > 1 ? ': ' + otherRoleReads.join(' | ') : ''})`);

// ═══════════════════════════════════════════════════════════════════════════
// 3. isAdmin is defined, and it is the wide form.
// ═══════════════════════════════════════════════════════════════════════════
let isAdminIsWide = false;
walk(tree, (n) => {
  if (n.type !== 'VariableDeclarator') return;
  if (!n.id || n.id.name !== 'isAdmin' || !n.init) return;
  const seen = [];
  walk(n.init, (c) => { if (c.type === 'StringLiteral') seen.push(c.value); });
  isAdminIsWide = seen.includes('owner') && seen.includes('admin');
});
ok(isAdminIsWide, 'isAdmin admits both owner and admin, matching get_admin_user');

// ═══════════════════════════════════════════════════════════════════════════
// 4. THE ASYMMETRY THAT MADE THIS DANGEROUS. Whatever gates the destructive
//    control must also gate the safe ones — never the reverse.
// ═══════════════════════════════════════════════════════════════════════════
let canDeleteIsIsAdmin = false;
walk(tree, (n) => {
  if (n.type !== 'VariableDeclarator') return;
  if (!n.id || n.id.name !== 'canDelete' || !n.init) return;
  canDeleteIsIsAdmin = n.init.type === 'Identifier' && n.init.name === 'isAdmin';
});
ok(canDeleteIsIsAdmin,
  'canDelete is isAdmin — delete cannot be reachable by a role that cannot upload');

// The Upload control and the delete control must be behind the same test.
function guardsOf(text) {
  const out = new Set();
  walk(tree, (n) => {
    if (n.type !== 'LogicalExpression' || n.operator !== '&&') return;
    let hit = false;
    walk(n.right, (c) => {
      if (c.type === 'JSXText' && text.test(c.value)) hit = true;
      if (c.type === 'StringLiteral' && text.test(c.value)) hit = true;
    });
    if (!hit) return;
    walk(n.left, (c) => { if (c.type === 'Identifier') out.add(c.name); });
  });
  return out;
}
const uploadGuard = guardsOf(/Upload PDF|Uploading/);
ok(uploadGuard.has('isAdmin'),
  'the Upload/Sync action bar is behind isAdmin');

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
