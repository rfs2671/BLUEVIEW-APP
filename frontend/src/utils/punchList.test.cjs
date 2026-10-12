// Run: node src/utils/punchList.test.cjs
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');
const M = loadEsm('src/utils/punchList.js');

let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log(`  PASS  ${label}`); } else { fail++; console.log(`  FAIL  ${label}`); }
}

ok(M.canSeePunch({ role: 'admin' }) && M.canSeePunch({ role: 'pm' }), 'admins and PMs see it');
ok(!M.canSeePunch({ role: 'cp' }) && !M.canSeePunch(null), 'not others');

ok(M.statusLabel('ready_to_check') === 'Ready to check' && M.statusLabel('closed') === 'Closed', 'status labels');
ok(M.floorLabel('6') === 'Floor 6' && M.floorLabel('lobby') === 'Lobby' && M.floorLabel('?') === 'Floor ?',
  'floor labels');
const chips = M.filterChips(['3', '6'], M.floorLabel);
ok(chips[0].value === '' && chips[0].label === 'All' && chips[2].label === 'Floor 6', 'filter chips start with All');

const it = { pid: 'P-588-4', text: 'piso 6 falta pintura', voice: true, floor: '6', area: 'hallway',
  trade: 'paint', assignee: { name: 'Ana Ortiz', company: 'Pro Paint' }, due: 'Fri' };
ok(M.whereLine(it) === 'Floor 6 · hallway · paint', 'where: floor, area, trade');
ok(M.whereLine({ floor: '?', area: '?', trade: '?' }) === 'trade ?', 'unknowns are not shown as places');
ok(M.whoLine(it) === 'Ana Ortiz (Pro Paint) · due Fri', 'who and due');
ok(M.whoLine({}) === 'Not assigned', 'nobody yet');
ok(M.itemWords(it) === '🎤 “piso 6 falta pintura”', 'voice words marked 🎤, verbatim');
ok(M.itemWords({ text: 'outlet cover missing' }) === '“outlet cover missing”', 'typed words verbatim');

ok(M.historyLine({ action: 'closed', at: 'x', quote: 'P-588-4 ok' }, () => 'Oct 13') === 'Oct 13 — Closed: “P-588-4 ok”',
  'closed with the words');
ok(M.historyLine({ action: 'ready_to_check', quote: 'done P-588-4' }) === 'Marked done (ready to check): “done P-588-4”',
  'a sub\'s done is ready to check');
ok(M.historyLine({ action: 'sent', quote: 'x' }) === 'Sent', 'sent has no quote');
ok(/walkthrough/.test(M.emptyText(false)) && /filters/.test(M.emptyText(true)), 'empty text');
ok(M.ADMIN_STATUSES.join() === 'open,ready_to_check,closed', 'admin statuses');

ok(M.punchSendsMode(null) === 'shadow' && M.punchSendsMode({ punch_sends: 'bogus' }) === 'shadow',
  'shadow by default');
ok(M.punchSendsMode({ punch_sends: 'live' }) === 'live', 'live when set');
ok(M.PUNCH_SENDS_OPTIONS.map((o) => o.mode).join() === 'shadow,live', 'two choices');

const root = path.join(__dirname, '../..');
const screen = fs.readFileSync(path.join(root, 'app/projects/[id]/punch.jsx'), 'utf8');
ok(/punchAPI\.list\(/.test(screen) && /punchAPI\.photo\(/.test(screen) && /punchAPI\.edit\(/.test(screen),
  'the screen lists, shows photos and edits');
ok(/isAdmin && \(/.test(screen), 'status edits are admins only');
const api = fs.readFileSync(path.join(root, 'src/utils/api.js'), 'utf8');
ok(/export const punchAPI/.test(api) && /\/punch\/\$\{encodeURIComponent\(pid\)\}\/photo/.test(api), 'punchAPI');
const project = fs.readFileSync(path.join(root, 'app/project/[id].jsx'), 'utf8');
ok(/canSeePunch\(user\) \? \[\{ title: 'Punch list'/.test(project) && /\/projects\/\$\{projectId\}\/punch`/.test(project),
  'Punch list tile for admins and PMs');
const card = fs.readFileSync(path.join(root, 'src/components/whatsapp/LevelogAssistantCard.jsx'), 'utf8');
ok(/patch\('punch_sends', \{ punch_sends: o\.mode \}\)/.test(card), 'Punch sends shadow / live in Levelog Assistant');

ok(M.mentionLine({ assignee: { name: 'Luis Ortega' }, mention_note: "mention won't notify (no number)" })
  === "Luis Ortega: mention won't notify (no number)", 'punch: no number flagged');
ok(M.mentionLine({ assignee: { name: 'Ana' } }) === null, 'punch: a real mention says nothing');
ok(/mentionLine\(it\)/.test(screen), 'the punch screen shows it');

ok(/timeZone: 'America\/New_York'/.test(screen), 'the punch screen shows New York time');
// Oct 11 8:31 PM: who a punch list may go to.
ok(M.punchToMode({ punch_to: 'one_person' }) === 'one_person' && M.punchToMode(null) === 'per_trade',
  'Punch list goes to: per trade unless one person');
ok(M.punchContactLine({ trade: 'Electrical', company: 'Power Direct', contact_name: 'Dov Klein' }).title
  === 'Electrical · Power Direct', 'a sub row');
ok(/Dov Klein/.test(M.punchContactLine({ contact_name: 'Dov Klein' }).line)
  && /asks/.test(M.punchContactLine({ options: [{ id: 'm' }] }).line)
  && /No one from this sub/.test(M.punchContactLine({}).line), 'its contact, none, or no People');
ok(/never messaged/.test(M.PUNCH_CONTACTS_NOTE), 'check-ins are never messaged, said');
ok(/patch\('punch_to', \{ punch_to: o\.mode \}\)/.test(card)
  && /punch_to_user: u\.id/.test(card) && /punch_contacts: \{ \[r\.row_id\]/.test(card),
  'the card sets who the list goes to and each punch contact');

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
