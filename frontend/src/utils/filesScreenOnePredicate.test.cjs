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
 * So one principal could delete a file and could not upload one. The narrow
 * guard sat on the harmless controls and the wide guard on the irreversible
 * one.
 *
 * WHICH ONE IS RIGHT IS NOT A STYLE QUESTION — it is set by the server, and
 * the screen has to ask the same question `get_admin_user` asks.
 *
 * ── WHAT CHANGED, AND WHY THE PROPERTY DID NOT ──────────────────────────
 *
 * The wide form used to be spelled `['owner', 'admin']`, and the role "owner"
 * is retired — it was what every self-serve signup received, never a rank.
 * The screen now calls `isCompanyAdmin(user)`, which is the client half of
 * the server's `is_company_admin`: role 'admin', or the platform operator by
 * his flag.
 *
 * So this file no longer looks for a role LIST. It asserts something stronger
 * and simpler: THIS SCREEN READS NO ROLE AT ALL. One shared predicate, called
 * once, gating both the destructive and the safe controls. A second predicate
 * of any shape — a role list, a role comparison, an inline `user?.role` — is
 * the regression this file exists to catch.
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
// THE SHARED PREDICATE IS IMPORTED. Without this the two checks below could
// both pass on a screen that had simply deleted its role gate entirely.
ok(/import \{[^}]*\bisCompanyAdmin\b[^}]*\} from ['"][^'"]*AuthContext['"]/.test(code),
  'isCompanyAdmin is imported from AuthContext — the same rule the server asks');

// NO ROLE LIST OF ANY KIND, including the retired one this used to require.
const retiredRole = (code.match(/'owner'/g) || []).length;
ok(retiredRole === 0,
  `the retired role 'owner' appears nowhere in the code (found ${retiredRole})`);

// ═══════════════════════════════════════════════════════════════════════════
// 2. The NARROW form appears nowhere. This is the actual regression.
// ═══════════════════════════════════════════════════════════════════════════
const narrow = (code.match(/role\s*[=!]==\s*'/g) || []).length;
ok(narrow === 0,
  `no inline role comparison survives — a second predicate is how the three `
  + `disagreed in the first place (found ${narrow})`);

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
ok(otherRoleReads.length === 0,
  `\`user.role\` is never read on this screen — the shared predicate reads it `
  + `(found ${otherRoleReads.length}`
  + `${otherRoleReads.length ? ': ' + otherRoleReads.join(' | ') : ''})`);

// ═══════════════════════════════════════════════════════════════════════════
// 3. isAdmin is defined, and it is the SHARED predicate — not a local
//    re-derivation that happens to agree with it today.
// ═══════════════════════════════════════════════════════════════════════════
let isAdminIsShared = false;
walk(tree, (n) => {
  if (n.type !== 'VariableDeclarator') return;
  if (!n.id || n.id.name !== 'isAdmin' || !n.init) return;
  isAdminIsShared = n.init.type === 'CallExpression'
    && n.init.callee.type === 'Identifier'
    && n.init.callee.name === 'isCompanyAdmin';
});
ok(isAdminIsShared,
  'isAdmin is isCompanyAdmin(user) — the same rule the server enforces');

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
