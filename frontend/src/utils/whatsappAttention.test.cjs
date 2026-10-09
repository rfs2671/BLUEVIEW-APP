/**
 * PROJECT → WHATSAPP → ATTENTION (BETA): admins review what the assistant
 * would flag (shadow mode — nothing was posted), Correct / Wrong / Dismiss,
 * with precision per type.
 *
 * Run:  node src/utils/whatsappAttention.test.cjs
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

const A = loadEsm('src/utils/whatsappAttention.js');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', '..', p), 'utf8');

console.log('copy');
ok(A.ATTENTION_TITLE === 'Attention (beta)', 'title');
ok(/Nothing here was posted/.test(A.ATTENTION_NOTE), 'says nothing was posted');
ok(A.VERDICTS.map((v) => v.label).join('|') === 'Correct|Wrong|Dismiss', 'three buttons');
ok(A.VERDICTS.map((v) => v.verdict).join('|') === 'correct|wrong|dismissed', 'verdicts the server takes');
ok(A.typeLabel('question') === 'Question' && A.typeLabel('x') === 'Item', 'type labels');
ok(A.typeLabel('update_review') === 'Unclear update', 'one entry for an unclear update');

console.log('\nitem lines');
ok(A.ownerLine({ owner: 'Mike', owner_status: 'resolved' }) === 'Owner: Mike', 'resolved owner');
ok(A.ownerLine({ owner: '…4321', owner_status: 'unresolved' })
   === 'Owner: …4321 (not matched to a person)', 'unresolved owner says so');
ok(A.ownerLine({ owner: null }) === null, 'no owner, no line');
ok(A.ownerLine({ owner: 'Patricia', owner_status: 'resolved', owner_possibly: true })
   === 'Owner: possibly Patricia (check)', 'a possible owner says so');
ok(/Possibly theirs/.test(A.eventLine({ kind: 'flag', note: 'possible_owner' })), 'possible-owner flag');
ok(/possibly that ask/.test(A.eventLine({ kind: 'flag', note: 'possible_subject' })),
   'a commitment whose subject is only the ask before it');
ok(A.dueLine({ due_text: 'by Friday', due_at: '2026-10-09' }) === 'Due: by Friday (2026-10-09)', 'due with a date');
ok(A.dueLine({ due_text: 'next week', due_at: null }) === 'Due: next week', 'due as said, no date');
ok(A.statusLine({ status: 'possibly_resolved' }) === 'Possibly answered (someone replied)', 'possibly answered');
ok(A.statusLine({ status: 'open' }) === null, 'open says nothing extra');

console.log('\nprecision');
{
  const lines = A.precisionLines({
    issue: { correct: 1, wrong: 0, dismissed: 0, unreviewed: 2 },
    question: { correct: 3, wrong: 1, dismissed: 2, unreviewed: 0 },
    decision: { correct: 0, wrong: 0, dismissed: 1, unreviewed: 4 },
  });
  ok(lines[0] === 'Question: 3 of 4 correct (75%)', 'question precision, dismissed not counted');
  ok(lines[1] === 'Issue: 1 of 1 correct (100%)', 'fixed type order');
  ok(lines[2] === 'Decision: not reviewed yet', 'no verdict yet');
  ok(A.precisionLines(null).length === 0, 'nothing yet, no lines');
}
ok(/Nothing flagged yet/.test(A.emptyText(0)) && A.emptyText(5) === 'Nothing left to review.', 'empty states');

console.log('\ntimeline');
ok(A.statusLine({ status: 'rescheduled' }) === 'Rescheduled', 'rescheduled');
ok(A.statusLine({ status: 'possibly_done' }) === 'Possibly done: check which item it was', 'possibly done');
ok(A.statusLine({ status: 'open', parts_done: 1 }) === '1 person has done their part', 'a part done');
ok(A.eventLine({ kind: 'created', due_to: 'tomorrow morning' }) === 'Recorded · due tomorrow morning', 'created');
ok(A.eventLine({ kind: 'state', to: 'rescheduled', due_from: 'tomorrow morning', due_to: 'Monday' })
   === 'Rescheduled: tomorrow morning → Monday', 'reschedule shows old and new date');
ok(A.eventLine({ kind: 'state', to: 'done', evidence_kind: 'file' }) === 'Done (file sent)', 'done by file');
ok(A.eventLine({ kind: 'state', to: 'cancelled' }) === 'Cancelled by who asked', 'cancelled');
ok(A.eventLine({ kind: 'flag', note: 'not_owner' }) === 'Someone else gave a new date. Not applied.', 'flag');
ok(A.eventLine({ kind: 'part_done', sender_last4: '1003' }) === 'One part done (…1003)', 'part done');
ok(A.eventLine({ kind: 'handover', owner_from: 'Patricia Lee', owner_to: 'Jose Zarate', due_to: 'Friday' })
  === 'Handed over: Patricia Lee → Jose Zarate · due Friday', 'handover');
ok(/not chased/.test(A.eventLine({ kind: 'flag', note: 'possible_handover' })), 'possible handover');
ok(A.eventLine({ kind: 'state', to: 'done', by: 'gc_staff' }) === 'Done (closed by GC staff)', 'done by GC');
ok(A.eventLine({ kind: 'state', to: 'done', by: 'requester' }) === 'Done (closed by who asked)', 'done by asker');
ok(A.eventLine({ kind: 'state', to: 'done', by: 'owner' }) === 'Done', 'done by owner');
ok(A.eventLine({ kind: 'state', to: 'cancelled', by: 'gc_staff' }) === 'Cancelled by GC staff', 'cancel by GC');
ok(A.linkLine({ link: 'reply' }) === 'Linked: a reply to it' && A.linkLine({}) === null, 'link');
ok(A.reviewable({ id: 'x', kind: 'state' }) && !A.reviewable({ id: 'x', kind: 'created' })
   && !A.reviewable({ id: 'x', kind: 'follow_up' }), 'changes are reviewable, the record is not');
ok(A.STATE_VERDICTS.map((v) => v.label).join('|') === 'Correct|Wrong', 'two buttons per change');
ok(A.LISTS.map((l) => l.status).join('|') === 'open|closed', 'open and closed lists');
{
  const lines = A.statePrecisionLines({ done: { correct: 3, wrong: 1 }, rescheduled: { correct: 0, wrong: 0 } });
  ok(lines[0] === 'Rescheduled: not reviewed yet' && lines[1] === 'Done: 3 of 4 correct (75%)',
     'precision per kind of change');
}

console.log('\nscreen wiring');
{
  const tab = read('app/projects/[id]/whatsapp-groups.jsx');
  ok(/isAdmin && !readOnly && groups\.length > 0 \? \(\s*<AttentionCard projectId=\{projectId\} \/>/.test(tab),
     'card is admin only, on the WhatsApp tab');
  const card = read('src/components/whatsapp/AttentionCard.jsx');
  ok(/whatsappAPI\.getAttention\(projectId, list\)/.test(card), 'loads the open or closed list');
  ok(/whatsappAPI\.reviewAttentionChange\(projectId, itemId, changeId, verdict\)/.test(card),
     'sends a verdict per change');
  ok(/reviewable\(e\)/.test(card) && /eventLine\(e\)/.test(card), 'renders the timeline');
  ok(/whatsappAPI\.reviewAttention\(projectId, itemId, verdict\)/.test(card), 'sends the verdict');
  const api = read('src/utils/api.js');
  ok(api.includes('`/api/projects/${projectId}/attention`'), 'GET path');
  ok(api.includes('/attention/${encodeURIComponent(itemId)}/review'), 'review path');
  ok(api.includes('/history/${encodeURIComponent(changeId)}/review'), 'change review path');
  ok(!/sendWhatsApp|send-message|sendMessage/.test(card), 'the card sends nothing to anyone');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
