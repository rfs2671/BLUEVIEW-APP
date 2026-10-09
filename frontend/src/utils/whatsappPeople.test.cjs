/**
 * Project → WhatsApp → People: copy, the form, who sees the card, and that no
 * raw WhatsApp id can reach the screen.
 *
 * Run:  node src/utils/whatsappPeople.test.cjs
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

const P = loadEsm('src/utils/whatsappPeople.js');
const NOW = new Date('2026-10-09T12:00:00Z');

console.log('\nrows');
const row = {
  key: 'k1', label: 'Carlos B', groups: ['Main St Project'], message_count: 12,
  last_message_at: '2026-10-08T14:00:00Z', assigned: null,
};
ok(P.assignmentLine(row) === 'Not assigned', 'unassigned says so');
ok(P.assignmentLine({ assigned: { person_name: 'Carlos Baez', sub_company: 'Bright Electric' } })
  === 'Carlos Baez · Bright Electric', 'assigned: name · company');
ok(P.detailLine(row, NOW) === 'Main St Project · 12 messages · last Oct 8', 'group, count, last');
ok(P.detailLine({ groups: ['a', 'b'], message_count: 1 }, NOW) === '2 groups · 1 message',
  'several groups counted, singular message');

console.log('\nno raw ids');
ok(P.safeLabel('Carlos B') === 'Carlos B', 'a name passes');
ok(P.safeLabel('123456789012345@lid') === 'Unnamed sender', 'an @lid never shows');
ok(P.safeLabel('123456789012345') === 'Unnamed sender', 'nor its digits');
ok(P.safeLabel('Unnamed sender …0101') === 'Unnamed sender …0101', 'phone last 4 allowed');

console.log('\nthe form');
const cos = ['Bright Electric', 'GC team'];
ok(P.assignRequest({ name: '', company: 'GC team' }, cos).error, 'name required');
ok(P.assignRequest({ name: 'Carlos', company: null }, cos).error, 'company required');
ok(P.assignRequest({ name: 'Carlos', company: 'Other' }, cos).error, 'company must be offered');
ok(JSON.stringify(P.assignRequest({ name: '  Carlos   Baez ', company: 'GC team' }, cos).body)
  === JSON.stringify({ personName: 'Carlos Baez', subCompany: 'GC team' }), 'name tidied');
ok(P.savedText({ open_items_updated: 0 }) === 'Saved for every group of your company.', 'saved, no items');
ok(P.savedText({ open_items_updated: 2 }) === 'Saved. 2 open items now name them.', 'saved, items');

console.log('\nwho sees it');
ok(P.canManagePeople({ role: 'admin' }) && P.canManagePeople({ role: ' PM ' }), 'admin and PM');
ok(!P.canManagePeople({ role: 'cp' }) && !P.canManagePeople({ role: 'owner' }), 'not CP, not retired owner');
ok(P.canManagePeople({ role: 'demo', is_platform_operator: true }), 'the operator');

const TAB = read('app/projects/[id]/whatsapp-groups.jsx');
ok(/canManagePeople\(user\) && !readOnly && groups\.length > 0 \? \(\s*<PeopleCard/.test(TAB),
  'the WhatsApp tab shows People to admins and PMs');
const CARD = read('src/components/whatsapp/PeopleCard.jsx');
ok(/safeLabel\(row\.label\)/.test(CARD) && !/\.jid\b|sender_jid/.test(CARD),
  'the card renders labels through safeLabel and never touches a jid');
const apiCalls = CARD.match(/whatsappAPI\.(\w+)/g) || [];
ok(apiCalls.length > 0 && apiCalls.every((c) => /People|Person/.test(c)),
  'the card calls only the People endpoints (it sends nothing to anyone)');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
