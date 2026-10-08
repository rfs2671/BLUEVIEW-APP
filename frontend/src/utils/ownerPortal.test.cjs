/**
 * OWNER PORTAL: its own nav (no app sidebar or tab bar), the company users
 * screen's rules, and what the Deleted items tab says.
 *
 * Run:  node src/utils/ownerPortal.test.cjs
 */

const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

let passed = 0;
let failed = 0;
const ok = (cond, label) => {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
};
const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');

const O = loadEsm('src/utils/ownerPortal.js');

console.log('\nnav');
ok(O.OWNER_NAV.map((n) => n.label).join('|') === 'Companies|Deleted items|Pending deletion',
  'own nav: Companies · Deleted items · Pending deletion');
ok(O.ownerNavActive('/owner') === 'companies', '/owner is Companies');
ok(O.ownerNavActive('/owner/company/abc') === 'companies', 'a company page is under Companies');
ok(O.ownerNavActive('/owner/deleted') === 'deleted', '/owner/deleted is Deleted items');
ok(O.ownerNavActive('/owner/pending-deletion') === 'pending', 'pending deletion tab');
ok(O.ownerNavActive('/projects') === null, 'outside the portal nothing is active');

console.log('\nlayout: no app nav on owner screens');
const SHELL = read('src/components/DesktopShell.jsx');
ok(/BARE_ROUTES = \[[\s\S]*'\/owner',[\s\S]*\];/.test(SHELL),
  'DesktopShell leaves /owner bare (no Dashboard/Projects/Workers rail)');
for (const f of ['app/owner/index.jsx', 'app/owner/pending-deletion.jsx',
  'app/owner/deleted.jsx', 'app/owner/company/[id].jsx']) {
  const src = read(f);
  ok(!/FloatingNav/.test(src), `${f}: no FloatingNav`);
  ok(/<OwnerNav\b/.test(src), `${f}: renders OwnerNav`);
}
const NAV = read('src/components/OwnerNav.jsx');
ok(/Back to app/.test(NAV) && /router\.replace\('\/'\)/.test(NAV),
  'OwnerNav: Back to app returns to the normal app');

console.log('\ncompany card');
const INDEX = read('app/owner/index.jsx');
ok(/style=\{styles\.companyName\}\s*numberOfLines=\{2\}/.test(INDEX),
  'company name wraps to 2 lines');
ok(!/maxWidth: 200/.test(INDEX.slice(INDEX.indexOf('  companyName: {'))),
  'and is not capped at 200px');
ok(/router\.push\(`\/owner\/company\/\$\{company\.id\}`\)/.test(INDEX),
  'the card opens the company page');

console.log('\ncompany users');
const users = [
  { id: 'a', role: 'admin' }, { id: 'p', role: 'pm' },
];
ok(O.userActions(users[0], users).canRemove === false, 'only admin cannot be removed');
ok(O.userActions(users[0], users).canChangeRole === false, 'only admin cannot change role');
ok(/Only admin/.test(O.userActions(users[0], users).lockedReason), 'and says why');
ok(O.userActions(users[1], users).canRemove === true, 'a PM can be removed');
const two = [...users, { id: 'b', role: 'admin' }];
ok(O.userActions(two[0], two).canRemove === true, 'with a second admin, either can go');
ok(O.addAdminRequest({ email: '' }).error, 'add admin: email required');
ok(JSON.stringify(O.addAdminRequest({ email: ' x@y.co ', name: '', password: '' }).body)
  === JSON.stringify({ email: 'x@y.co' }), 'existing user: email only');
ok(O.addAdminRequest({ email: 'x@y.co', name: 'X', password: 'pw' }).body.password === 'pw',
  'new account: name and password go along');
ok(O.roleLabel('cp') === 'Competent person' && O.roleLabel('') === 'No role', 'role labels');

console.log('\ndeleted items');
const row = {
  kind: 'project', id: 'p1', name: 'Job — 1 Main St', company_name: 'ACME',
  deleted_by_name: 'Ann', deleted_at: '2026-10-01T12:00:00Z', state: 'marked',
  hard_delete: { enabled: false, reason: 'Pending delete-service fix' },
};
const v = O.deletedRowView(row);
ok(v.kind === 'Project' && v.name === 'Job — 1 Main St', 'type and name/address');
ok(v.company === 'ACME' && v.by === 'Ann', 'company and deleted by');
ok(v.at === '2026-10-01 12:00 UTC', 'deleted at');
ok(v.badge === 'Marked for deletion', 'a marked project says so');
ok(v.hardDeleteEnabled === false && v.hardDeleteReason === 'Pending delete-service fix',
  'hard delete disabled, with the reason');
ok(O.deletedRowView({ kind: 'user', id: 'u', hard_delete: {} }).hardDeleteReason
  === 'Pending delete-service fix', 'missing reason still reads as pending');
ok(O.deletedRowView({ kind: 'company', id: 'c' }).company === null, 'a company row has no company column');
ok(O.deletedRowView({ kind: 'user', id: 'u' }).by === 'Unknown', 'unknown deleter is said, not blank');
ok(O.filterDeleted([{ kind: 'user' }, { kind: 'project' }], 'user').length === 1, 'filter by type');
ok(O.filterDeleted([{ kind: 'user' }, { kind: 'project' }], 'all').length === 2, 'all');

const DELETED = read('app/owner/deleted.jsx');
ok(/<Pressable disabled[\s\S]{0,200}Hard delete/.test(DELETED),
  'Hard delete button is rendered disabled');
ok(!/hardDelete\(|hard-delete/.test(DELETED), 'and wired to nothing');

console.log('\npreview and restore');
const pv = O.previewView({
  name: 'Job', counts: { dob_logs: 3, checkins: 0, logbooks: -1 },
  r2_files: { project_files: 2, indexed_pages: 0 },
  blocking: [{ kind: 'filed_logbooks', reason: 'Filed logbooks block it.' }],
});
ok(pv.counts.map((c) => `${c.label}=${c.value}`).join(',') === 'DOB records=3,Logbooks=unknown',
  'counts per collection, zeros dropped, unknowns said');
ok(pv.r2[0] === '2 stored files', 'R2 files');
ok(pv.blocking[0] === 'Filed logbooks block it.', 'what blocks it');
ok(/Nothing was deleted/.test(pv.note), 'says it is a preview');
ok(O.restoreSummary({ children: { users: 2, nfc_tags: 1 } }) === 'Also restored: 2 users, 1 NFC tag.',
  'restore summary');
ok(O.restoreSummary({}) === 'Restored.', 'restore with nothing else');
ok(O.serverMessage({ response: { data: { detail: { message: 'Only admin.' } } } }) === 'Only admin.',
  'server refusal in its own words');

console.log('\nsettings entry');
const SETTINGS = read('app/settings.jsx');
ok(/isPlatformOperator\(user\) \?[\s\S]{0,400}router\.push\('\/owner'\)/.test(SETTINGS),
  'Settings links to the owner portal for the operator only');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
