/**
 * PROJECT → WHATSAPP → WOULD CHASE (BETA): admins review the nudges sub
 * chasing would have sent (shadow mode — nothing was sent), Correct / Wrong,
 * with precision overall and per slot.
 *
 * Run:  node src/utils/whatsappChase.test.cjs
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

const C = loadEsm('src/utils/whatsappChase.js');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');

console.log('copy');
ok(C.CHASE_TITLE === 'Would chase (beta)', 'title');
ok(/Nothing here was sent/.test(C.CHASE_NOTE), 'says nothing was sent');
ok(C.CHASE_VERDICTS.map((v) => v.verdict).join('|') === 'correct|wrong', 'Correct / Wrong');

console.log('\nentry lines');
{
  const g = { slot: 'morning', kind: 'group', day: '2026-10-08', at: null,
              group_name: 'Main St Project', owner: 'Mike Rivera',
              items: [{ id: 'a' }, { id: 'b' }], reason: 'Due today; no update.' };
  ok(C.headLine(g) === 'Morning · 2026-10-08 · Main St Project', 'slot, day and group');
  ok(C.ownerLine(g) === 'Owner: Mike Rivera · 2 items', 'owner and batch size');
  ok(C.ownerLine({ ...g, items: [{ id: 'a' }] }) === 'Owner: Mike Rivera', 'one item');
  ok(C.reasonLine(g) === 'Why: Due today; no update.', 'the reason it fired');
  const dm = { slot: 'admin_dm', kind: 'admin_dm', day: '2026-10-08', to: ['Ana Admin'],
               group_name: 'Main St Project' };
  ok(C.headLine(dm) === 'DM to admin · 2026-10-08 · to Ana Admin', 'admin DM names who');
  ok(C.headLine({ ...g, at: '2026-10-08T12:35:00Z' })
     === 'Morning · 2026-10-08 8:35 AM · Main St Project', 'the time, in New York');
  ok(C.clock('2026-10-08T20:35:00Z') === '4:35 PM', 'New York time on any device');
  ok(C.clock('nope') === '' && C.clock(null) === '', 'no time, no text');
}

console.log('\nprecision');
{
  const lines = C.precisionLines({
    correct: 3, wrong: 1, unreviewed: 2,
    by_slot: { midday: { correct: 0, wrong: 0, unreviewed: 2 },
               morning: { correct: 3, wrong: 1, unreviewed: 0 } },
  });
  ok(lines[0] === 'All: 3 of 4 correct (75%)', 'overall');
  ok(lines[1] === 'Morning: 3 of 4 correct (75%)', 'per slot, in slot order');
  ok(lines[2] === 'Midday: not reviewed yet', 'no verdict yet');
  ok(C.precisionLines({ correct: 0, wrong: 0, unreviewed: 0 }).length === 0, 'nothing yet');
  ok(C.precisionLines(null).length === 0, 'no data');
}
ok(/Nothing yet/.test(C.emptyText(0)) && C.emptyText(3) === 'Nothing more to show.', 'empty states');

console.log('\nscreen wiring');
{
  const card = read('src/components/whatsapp/ChaseCard.jsx');
  ok(/whatsappAPI\.getChase\(projectId\)/.test(card), 'loads the list');
  ok(/whatsappAPI\.reviewChase\(projectId, entryId, verdict\)/.test(card), 'sends a verdict');
  ok(/bodyText\(e\)/.test(card) && /reasonLine\(e\)/.test(card), 'shows the message text and why');
  ok(/channelTag\(e\)/.test(card), 'each entry says Group or DM');
  ok(!/sendWhatsApp|send-message|sendMessage/.test(card), 'the card sends nothing to anyone');
  const api = read('src/utils/api.js');
  ok(api.includes('`/api/projects/${projectId}/whatsapp/chase`'), 'GET path');
  ok(api.includes('/whatsapp/chase/${encodeURIComponent(entryId)}/review'), 'review path');
  const screen = read('app/projects/[id]/whatsapp-groups.jsx');
  ok(/isAdmin && !readOnly && groups\.length > 0 \? \(\s*<ChaseCard projectId=\{projectId\} \/>/.test(screen),
     'admins only, on the project WhatsApp screen');
}

{
  // GC staff: privately by DM; not opted in is listed, not chased.
  ok(C.channelTag({ channel: 'dm', kind: 'dm' }) === 'DM', 'GC staff: DM');
  ok(C.channelTag({ channel: 'group', kind: 'group' }) === 'Group', 'a sub: Group');
  ok(C.channelTag({ kind: 'admin_dm' }) === 'DM', 'the admin DM: DM');
  ok(C.channelTag({ kind: 'group' }) === 'Group', 'an entry from before channels: Group');
  ok(C.bodyText({ not_chased: 'not opted in', text: '' }) === 'Not chased: not opted in',
     'not opted in: says so');
  ok(C.bodyText({ text: 'Following up: you said “x” in 588 Thomas – any update?' })
     .startsWith('Following up'), 'the DM text');
  ok(C.SLOT_LABELS.not_chased === 'Not chased', 'the not-chased slot has a label');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
