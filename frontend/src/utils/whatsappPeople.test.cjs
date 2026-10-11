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
// New York's day, whatever the phone's zone: 00:30 New York on Oct 9 is
// 04:30Z (and Oct 8 on a phone in California).
ok(P.detailLine({ ...row, last_message_at: '2026-10-09T04:30:00+00:00' }, NOW)
  .endsWith('last Oct 9'), 'last message day is New York\'s');
ok(P.detailLine({ groups: ['a', 'b'], message_count: 1 }, NOW) === '2 groups · 1 message',
  'several groups counted, singular message');

console.log('\nno raw ids');
ok(P.safeLabel('Carlos B') === 'Carlos B', 'a name passes');
ok(P.safeLabel('123456789012345@lid') === 'Unnamed sender', 'an @lid never shows');
ok(P.safeLabel('123456789012345') === 'Unnamed sender', 'nor its digits');
ok(P.safeLabel('Unnamed sender …0101') === 'Unnamed sender …0101', 'phone last 4 allowed');
ok(P.safeLabel('+1 (718) 555-0101') === 'Unnamed sender', 'a formatted phone number never shows');
ok(P.safeName('Carlos B') === 'Carlos B' && P.safeName('718-555-0101') === ''
  && P.safeName('123456789012345@lid') === '', 'the form is never pre-filled with an id');
ok(/safeName\(row\.push_name\)/.test(read('src/components/whatsapp/PeopleCard.jsx')),
  'the card pre-fills through safeName');

console.log('\nthe form');
const cos = ['Bright Electric', 'GC team'];
ok(P.assignRequest({ name: '', company: 'GC team' }, cos).error, 'name required');
ok(P.assignRequest({ name: 'Carlos', company: null }, cos).error, 'company required');
ok(P.assignRequest({ name: 'Carlos', company: 'Other' }, cos).error, 'company must be offered');
ok(JSON.stringify(P.assignRequest({ name: '  Carlos   Baez ', company: 'GC team' }, cos).body)
  === JSON.stringify({ personName: 'Carlos Baez', subCompany: 'GC team' }), 'name tidied');
ok(P.savedText({ open_items_updated: 0 }) === 'Saved for every group of your company.', 'saved, no items');
ok(P.savedText({ open_items_updated: 2 }) === 'Saved. 2 open items now name them.', 'saved, items');

console.log('\nthe optional WhatsApp number (real @mentions)');
ok(P.cleanPhone('(718) 555-0144') === '17185550144', 'a 10-digit US number gets the 1');
ok(P.cleanPhone('+972 52 123 4567') === '972521234567', 'an international number kept');
ok(P.cleanPhone('') === '' && P.cleanPhone('  ') === '', 'none is fine');
ok(P.cleanPhone('12') === null, 'not a number');
ok(P.assignRequest({ name: 'Chris', company: 'GC team', phone: '12' }, cos).error, 'a bad number refused');
ok(P.assignRequest({ name: 'Chris', company: 'GC team', phone: '718 555 0144' }, cos).body.phone
  === '17185550144', 'the number sent as digits');
ok(!('phone' in P.assignRequest({ name: 'Chris', company: 'GC team', phone: '' }, cos).body),
  'no number typed: none sent (the one on file is kept)');
ok(P.assignRequest({ name: 'Chris', company: 'GC team', phone: '', removePhone: true }, cos).body.phone === '',
  'removing the number on file sends an explicit empty phone');
ok(P.assignmentLine({ assigned: { person_name: 'Chris', sub_company: 'GC team', phone: '+1 718-555-0144' } })
  === 'Chris · GC team · +1 718-555-0144', 'an admin sees the full number');
ok(P.assignmentLine({ assigned: { person_name: 'Chris', sub_company: 'GC team', phone: '…0144' } })
  === 'Chris · GC team · …0144', 'a PM the last 4');
ok(P.assignmentLine({ phone: '…0333', assigned: { person_name: 'Chris', sub_company: 'GC team', phone: null } })
  === 'Chris · GC team · …0333', 'a number found by lookup shows too');
ok(/@mention/.test(P.PHONE_NOTE) && /won’t notify/.test(P.PHONE_NOTE), 'says what the number is for');
const card = read('src/components/whatsapp/PeopleCard.jsx');
ok(/keyboardType="phone-pad"/.test(card) && /PHONE_NOTE/.test(card), 'the form asks for it');
ok(/req\.body\.phone/.test(card), 'and sends it');
ok(/Remove the number on file/.test(card) && /removePhone/.test(card), 'and can remove a wrong one');
const api = read('src/utils/api.js');
ok(/phone !== null && phone !== undefined/.test(api), "the API keeps '' (remove) apart from left out (keep)");

console.log('\nvoice note language');
ok(P.LANGUAGES.map((l) => l.value).join(',') === 'auto,en,es,yi', 'Auto, English, Español, Yiddish');
ok(P.languageLabel('es') === 'Spanish' && P.languageLabel('yi') === 'Yiddish'
   && P.languageLabel('auto') === null && P.languageLabel(undefined) === null, 'labels');
ok(/voice: Spanish$/.test(P.detailLine({ groups: ['588'], message_count: 3, language: 'es' })),
   'a set language shows on the row');
ok(!/voice:/.test(P.detailLine({ groups: ['588'], message_count: 3, language: 'auto' })),
   'auto says nothing');
ok(api.includes('/language`') && /setWhatsAppPersonLanguage/.test(api), 'its own endpoint');
const langCard = read('src/components/whatsapp/PeopleCard.jsx');
ok(/setWhatsAppPersonLanguage\(projectId, editing\.key, language\)/.test(langCard),
   'saves on tap, with no name needed');
ok(/accessibilityRole="radio"/.test(read('src/components/whatsapp/VoiceLanguagePicker.jsx'))
   && /VoiceLanguagePicker/.test(langCard), 'one choice of four (the shared picker)');

console.log('\nthe same picker on every person who can send a voice note');
const picker = read('src/components/whatsapp/VoiceLanguagePicker.jsx');
ok(/export function VoiceLanguagePicker/.test(picker) && /export function VoiceLanguageSetting/.test(picker),
   'one picker, and a self-loading setting');
ok(/LANGUAGES\.map/.test(picker) && /NO_PHONE_LANGUAGE_NOTE/.test(picker), 'four choices; no phone: says so');
ok(/VoiceLanguagePicker value=\{editing && editing\.language\}/.test(langCard), 'People (unknown senders)');
const users = read('app/admin/users.jsx');
ok(/<VoiceLanguageSetting key=\{selectedUser\.id\}/.test(users)
   && /adminUsersAPI\.getVoiceLanguage\(selectedUser\.id\)/.test(users)
   && /adminUsersAPI\.setVoiceLanguage\(selectedUser\.id, language\)/.test(users), 'users: the edit sheet');
const worker = read('app/workers/[id].jsx');
ok(/<VoiceLanguageSetting key=\{workerId\}/.test(worker)
   && /workersAPI\.getVoiceLanguage\(workerId\)/.test(worker)
   && /workersAPI\.setVoiceLanguage\(workerId, language\)/.test(worker), 'workers: their screen');
ok(api.includes('/api/admin/users/${encodeURIComponent(userId)}/voice-language')
   && api.includes('/api/workers/${encodeURIComponent(workerId)}/voice-language'), 'their endpoints');
ok(/Add their phone number first/.test(P.NO_PHONE_LANGUAGE_NOTE), 'the no-phone note');

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
