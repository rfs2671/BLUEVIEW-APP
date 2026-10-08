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

console.log('\nitem lines');
ok(A.ownerLine({ owner: 'Mike', owner_status: 'resolved' }) === 'Owner: Mike', 'resolved owner');
ok(A.ownerLine({ owner: '…4321', owner_status: 'unresolved' })
   === 'Owner: …4321 (not matched to a person)', 'unresolved owner says so');
ok(A.ownerLine({ owner: null }) === null, 'no owner, no line');
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

console.log('\nscreen wiring');
{
  const tab = read('app/projects/[id]/whatsapp-groups.jsx');
  ok(/isAdmin && !readOnly && groups\.length > 0 \? \(\s*<AttentionCard projectId=\{projectId\} \/>/.test(tab),
     'card is admin only, on the WhatsApp tab');
  const card = read('src/components/whatsapp/AttentionCard.jsx');
  ok(/whatsappAPI\.getAttention\(projectId\)/.test(card), 'loads the list');
  ok(/whatsappAPI\.reviewAttention\(projectId, itemId, verdict\)/.test(card), 'sends the verdict');
  const api = read('src/utils/api.js');
  ok(api.includes('`/api/projects/${projectId}/attention`'), 'GET path');
  ok(api.includes('/attention/${encodeURIComponent(itemId)}/review'), 'review path');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
