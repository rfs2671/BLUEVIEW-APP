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
ok(M.whereLine({ floor: '3', area: 'Apt 3D', room: 'bedroom', trade: 'electrical' })
  === 'Floor 3 · Apt 3D · bedroom · electrical', 'a room in the unit (11:03 PM)');
ok(M.whoLine(it) === 'Ana Ortiz (Pro Paint) · due Fri', 'who and due');
ok(M.whoLine({}) === 'Not assigned', 'nobody yet');
ok(M.itemWords(it) === '🎤 “piso 6 falta pintura”', 'voice words marked 🎤, verbatim');
ok(M.itemWords({ text: 'outlet cover missing' }) === '“outlet cover missing”', 'typed words verbatim');

ok(M.historyLine({ action: 'closed', at: 'x', quote: 'P-588-4 ok' }, () => 'Oct 13') === 'Oct 13 — Closed: “P-588-4 ok”',
  'closed with the words');
ok(M.historyLine({ action: 'ready_to_check', quote: 'done P-588-4' }) === 'Marked done (ready to check): “done P-588-4”',
  'a sub\'s done is ready to check');
ok(M.historyLine({ action: 'sent', mode: 'live', quote: 'x' }) === 'Sent', 'sent has no quote');
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
ok(/canAct && \(/.test(screen) && !/isAdmin/.test(screen), 'edits are for admins and PMs (the server says: can_act)');
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

// Oct 11 11:06 PM: the default due was a fixed "Fri"; now a setting (ASAP).
ok(M.punchDueMode(null) === 'asap' && M.punchDueMode({ punch_due_default: 'none' }) === 'none'
  && M.punchDueMode({ punch_due_default: 'someday' }) === 'asap', 'Punch items due: ASAP unless set');
ok(M.PUNCH_DUE_OPTIONS.map((o) => o.mode).join() === 'asap,tomorrow,fri,none', 'the four choices');
ok(/Never chased/.test(M.PUNCH_DUE_OPTIONS.find((o) => o.mode === 'none').line), 'no due date: never chased');
ok(/patch\('punch_due_default', \{ punch_due_default: o\.mode \}\)/.test(card), 'the card sets it');
ok(/by DM/.test(M.PUNCH_TO_OPTIONS.find((o) => o.mode === 'one_person').line), 'one person: by DM');

// ── Live 588, Mon Oct 12: the Punch list screen ──────────────────────────
// 5. Layout: AnimatedBackground (flex: 1) holds the screen. As a sibling of
// the SafeAreaView it took the top half and the header sat mid-screen.
ok(!/<AnimatedBackground\s*\/>/.test(screen) && /<AnimatedBackground>\s*<SafeAreaView/.test(screen),
  'the screen is inside AnimatedBackground, not beside it (no empty top half)');

// 6. Status chips with counts, the assignee filter.
ok(M.statusChips(['open', 'ready_to_check', 'closed'], { open: 3, ready_to_check: 0, closed: 2 })
  .map((c) => c.label).join('|') === 'All 5|Open 3|Ready to check 0|Closed 2', 'chips: "Open 3", "Ready to check 0"');
ok(M.statusChips(['open'], null)[1].label === 'Open 0', 'no counts yet: 0');
const ac = M.assigneeChips([{ key: 'user:u1', name: 'Chris' }, { key: 'none', name: 'Not assigned' }]);
ok(ac[0].value === '' && ac[0].label === 'Everyone' && ac[1].value === 'user:u1' && ac[2].label === 'Not assigned',
  'assignee filter: Everyone, then each person');
ok(/chipRow\('assignee', assigneeChips\(data\.assignees\)\)/.test(screen)
  && /statusChips\(data\.statuses, data\.counts\)/.test(screen), 'the screen shows both rows');

// 8. The statuses, explained under the chips.
ok(M.STATUS_EXPLAINER === 'Open = assigned · Ready to check = assignee says fixed · Closed = admin/PM verified',
  'one line explains the statuses');
ok(/\{STATUS_EXPLAINER\}/.test(screen), 'shown on the screen');

// 7. Tap an item: its detail -- every photo, history, admin / PM actions.
ok(M.itemActions({ status: 'open' }, true).map((a) => a.key).join() === 'close,reassign,due',
  'open: close, reassign, change due');
ok(M.itemActions({ status: 'ready_to_check' }, true).map((a) => a.key).join() === 'close,reopen,reassign,due',
  'ready to check: close or reopen');
ok(M.itemActions({ status: 'closed' }, true).map((a) => a.key).join() === 'reopen,reassign,due', 'closed: reopen');
ok(M.itemActions({ status: 'open' }, false).length === 0, 'not an admin or PM: no actions (only they close)');
ok(M.itemActions({ status: 'open' }, true)[0].patch.status === 'closed', 'close sets closed');
// Live 588, Oct 12 10:47 #11: a reopen carries the admin's note to the assignee's page.
ok(!M.itemActions({ status: 'closed' }, true)[0].patch, 'reopen asks for a note first');
ok(JSON.stringify(M.reopenPatch('  Still chipped at the corner ')) === '{"status":"open","note":"Still chipped at the corner"}',
  'reopen with the note');
ok(JSON.stringify(M.reopenPatch('')) === '{"status":"open"}', 'reopen without a note');
ok(M.reopenLine({ status: 'open', reopen_note: 'Still chipped at the corner' }) === 'Reopened: “Still chipped at the corner”',
  'the reopen note shows');
ok(M.reopenLine({ status: 'ready_to_check', reopen_note: 'x' }) === '', 'only while open');
ok(M.photoList({ photos: 2, completion: { has_photo: true } }).map((p) => p.which).join() === 'item,item:2,done',
  'every photo, then the done photo');
ok(M.photoList({ has_photo: true }).map((p) => p.label).join() === 'Photo', 'one photo');
ok(M.photoList({}).length === 0, 'no photo');
ok(M.DUE_CHOICES.map((d) => d.words).join() === 'ASAP,tomorrow,Mon,Wed,Fri,no due date', 'due choices');
ok(M.historyLine({ action: 'reassigned', quote: 'Chris Lopez' }) === 'Reassigned to Chris Lopez'
  && M.historyLine({ action: 'due', quote: 'due Fri' }) === 'Due changed due Fri', 'history: reassigned, due');
ok(/onPress=\{\(\) => setDetail\(it\)\}/.test(screen) && /<PunchDetail/.test(screen)
  && /resizeMode="contain"/.test(screen) && /data\.can_act/.test(screen),
  'tap opens the detail; photos full screen; actions only when the server says so');

// ── Live 588, Mon Oct 12, 10:42–10:47 AM ─────────────────────────────────
// 6. A shadow send read "Sent".
ok(M.historyLine({ action: 'sent', mode: 'shadow', dest: 'DM to Chris Weiss (GC team)' })
  === 'Would send (shadow) · DM to Chris Weiss (GC team)', 'shadow DM send');
ok(M.historyLine({ action: 'sent', mode: 'shadow', dest: 'post in 588 Thomas St' })
  === 'Would send (shadow) · post in 588 Thomas St', 'shadow group post');
ok(M.historyLine({ action: 'sent', mode: 'live', dest: 'DM to Chris Weiss (GC team)' })
  === 'Sent · DM to Chris Weiss (GC team)', 'a live send says Sent');
// 7. The assignee row was missing with one assignee.
ok(M.showAssigneeRow([{ key: 'user:u_chris', name: 'Chris Weiss' }]) && !M.showAssigneeRow([])
  && !M.showAssigneeRow(null), 'the assignee row shows with one or more');
ok(/showAssigneeRow\(data\.assignees\)/.test(screen) && !/assignees\.length > 1/.test(screen),
  'the screen uses it');
// 8. Item cards: one inset, not GlassCard's 32px plus the card's own.
ok((screen.match(/contentStyle=\{styles\.cardContent\}/g) || []).length >= 2
  && /cardContent: \{ padding: spacing\.md \}/.test(screen)
  && !/card: \{ padding:/.test(screen), 'cards are padded once');
// 1. A photo that is only the preview says so.
ok(M.photoNote({ photo_quality: 'preview' }, 'item') === 'Original unavailable — preview only'
  && M.photoNote({ photo_quality: 'original' }, 'item') === null
  && M.photoNote({ completion: { photo_quality: 'preview' } }, 'done') === M.PREVIEW_ONLY,
  'preview only, labelled');
ok(/photoNote\(item, p\.which\)/.test(screen), 'under the photo in the detail');

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
