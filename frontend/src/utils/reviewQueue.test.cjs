/**
 * OWNER PORTAL → REVIEW QUEUE (L6.4): what the list shows, that a decision
 * needs an explanation, that the Notify and "Include my explanation"
 * checkboxes are what is sent, that a decided item can be decided again with
 * a new explanation, and that Approve / Deny sit in a pinned footer.
 *
 * Run:  node src/utils/reviewQueue.test.cjs
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

const R = loadEsm('src/utils/reviewQueue.js');

// What GET /api/owner/review-queue returns (shape of server.owner_review_queue).
const LIST = {
  items: [
    { source: 'dispute', id: 'd1', kind: 'dispute', reason: 'dispute', priority: 'normal',
      status: 'pending', company: { id: 'c1', name: 'ACME BUILDERS' },
      project: { id: 'p1', name: '12 Main St' }, created_at: '2026-10-28T09:10:00+00:00',
      summary: "that's wrong, it's 3'-6\"", asker: { user_id: 'u1', name: 'Pat PM' },
      answer: { question: 'door 101 width?', final_text: "3'-0\" (A-101)",
        records: [{ id: 'r1', sheet: 'A-101', text: 'DOOR 101' }], records_total: 3,
        gates: [{ gate: 'plan_answer_gate', outcome: 'grounded' }],
        model: 'm', code_sha: 'abc1234' },
      decision: null },
    { source: 'queue', id: 'q1', kind: 'set_health', reason: 'set_health_info',
      priority: 'low', status: 'pending', company: { id: 'c2', name: 'OTHER CO' },
      project: null, created_at: '2026-10-28T09:05:00+00:00', summary: 'info',
      answer: null, decision: null },
    { source: 'dispute', id: 'd2', kind: 'dispute', reason: 'dispute', status: 'denied',
      company: { id: 'c2', name: 'OTHER CO' }, asker: { user_id: null, name: null },
      decision: { decision: 'deny', explanation: 'checked S-201', notify: false,
        decided_at: '2026-10-28T10:00:00+00:00' },
      decisions: [
        { decision: 'approve', explanation: 'first look', notify: true,
          include_explanation: true, decided_at: '2026-10-28T09:30:00+00:00' },
        { decision: 'deny', explanation: 'checked S-201', notify: false,
          decided_at: '2026-10-28T10:00:00+00:00' }] },
  ],
};

console.log('\nthe list renders each item');
const [d, q, g] = LIST.items.map(R.itemView);
ok(d.label === 'Dispute' && q.label === 'Set health: info', 'reason is the label');
ok(d.company === 'ACME BUILDERS' && d.project === '12 Main St', 'company and project');
ok(d.when === '2026-10-28 09:10 UTC', 'when, in UTC');
ok(d.question === 'door 101 width?' && d.answer === "3'-0\" (A-101)", 'question and answer');
ok(d.records.length === 1 && d.records[0].sheet === 'A-101' && d.recordsMore === 2,
  'records, and how many more');
ok(d.gates[0] === 'plan_answer_gate: grounded', 'gates as a line each');
ok(d.build === 'm · abc1234', 'model and code sha');
ok(q.low === true && d.low === false, 'low priority is marked');
ok(q.question === null, 'a non-answer item has no question block');
ok(d.canNotify === true && g.canNotify === false && q.canNotify === false,
  'Notify only for a dispute with a known person');
ok(g.decision && g.decision.text === 'Denied' && g.decision.explanation === 'checked S-201',
  'a decided item shows its decision');
ok(g.history.length === 2 && g.history[0].text === 'Denied'
  && g.history[1].text === 'Approved' && g.history[1].withExplanation === true,
  'every decision, newest first');
ok(d.history.length === 0, 'a pending item has no history');
ok(R.reasonLabel('set_ambiguity') === 'Set ambiguity'
  && R.REASON_FILTERS.some((f) => f.key === 'set_ambiguity'), 'set_ambiguity is a reason');
ok(R.itemView(undefined).key === 'item:' && R.itemView({}).records.length === 0,
  'any shape renders (never throws)');

console.log('\nthe default view is "Needs decision"');
const p0 = R.listParams({});
ok(p0.status === 'pending' && p0.priority === 'normal', 'pending, normal priority');
ok(R.listParams({ showLow: true }).priority === 'all', 'Show low priority widens it');
ok(R.listParams({ reason: 'set_health_info' }).priority === 'all',
  'picking the low reason shows it');
const p1 = R.listParams({ reason: 'conflict', company: 'c1', offset: 25, limit: 25 });
ok(p1.reason === 'conflict' && p1.company_id === 'c1' && p1.offset === 25,
  'reason, company and paging');
ok(R.STATUS_FILTERS[0].label === 'Needs decision', 'the first filter is Needs decision');

console.log('\na decision needs an explanation');
ok(!!R.decideRequest('approve', '').error, 'empty: refused');
ok(!!R.decideRequest('deny', '   too short ').error, 'under 10 characters: refused');
ok(!!R.decideRequest('maybe', 'a long enough reason').error, 'approve or deny only');
const good = R.decideRequest('approve', '  Sheet A-101 says 3\'-6"  ', true);
ok(good.body && good.body.decision === 'approve'
  && good.body.explanation === 'Sheet A-101 says 3\'-6"', 'trimmed explanation is sent');

console.log('\nthe Notify checkbox is what is sent');
ok(R.decideRequest('deny', 'checked it twice', true).body.notify === true, 'ticked: notify true');
ok(R.decideRequest('deny', 'checked it twice', false).body.notify === false, 'unticked: false');
ok(R.decideRequest('deny', 'checked it twice', 'yes').body.notify === false, 'only true is true');

console.log('\n"Include my explanation" only with Notify');
ok(R.decideRequest('deny', 'checked it twice', true, true).body.include_explanation === true,
  'Notify + Include: true');
ok(R.decideRequest('deny', 'checked it twice', true, false).body.include_explanation === false,
  'Notify only: false');
ok(R.decideRequest('deny', 'checked it twice', false, true).body.include_explanation === false,
  'Include without Notify: false');
ok(R.decideRequest('deny', 'checked it twice').body.include_explanation === false,
  'default off');

console.log('\na decided item can be decided again, with a new explanation');
ok(!!R.decideRequest('approve', ' Checked  S-201 ', false, false, 'checked S-201').error,
  'the same explanation: refused');
ok(R.decideRequest('approve', 'rechecked S-201 rev 2', false, false, 'checked S-201').body
  .decision === 'approve', 'a new one: sent');
ok(/no direct chat/.test(R.decideResult({ notify: { sent: false, reason: 'no_asker' } })),
  'a group dispute says why nobody was told');
ok(/sent the note/.test(R.decideResult({ notify: { sent: true, reason: 'sent' } })), 'sent');

console.log('\nthe screen');
const SCREEN = read('app/owner/review.jsx');
ok(/isPlatformOperator\(user\)/.test(SCREEN) && /if \(!isOperator\) return;/.test(SCREEN),
  'fetches nothing for a non-operator');
ok(/Platform operator access required\./.test(SCREEN), 'and shows the denial panel');
ok(/const req = decideRequest\(decision, explanation, notify && iv\.canNotify,\s*includeExplanation, iv\.decision \? iv\.decision\.explanation : null\);\s*if \(req\.error\) \{ setFormError\(req\.error\); return; \}/.test(SCREEN),
  'decide checks the explanation before any request');
ok(/ownerAPI\.reviewDecide\(it\.source, it\.id, req\.body\)/.test(SCREEN),
  'and sends the checked body (notify included)');
ok(/ownerAPI\.reviewQueue\(\s*listParams\(/.test(SCREEN), 'the list asks with listParams');
ok(/accessibilityRole="checkbox"[\s\S]*Notify the person/.test(SCREEN), 'a Notify checkbox');
ok(/Show low priority/.test(SCREEN), 'a Show low priority toggle');
const notifyAt = SCREEN.lastIndexOf('Notify the person');
const includeAt = SCREEN.lastIndexOf('Include my explanation');
ok(notifyAt > 0 && includeAt > notifyAt, '"Include my explanation" sits under Notify');
ok(/disabled=\{!notify\} accessibilityRole="checkbox"/.test(SCREEN.slice(notifyAt, includeAt)),
  'and is enabled only when Notify is ticked');
ok(/useState\(false\);/.test(SCREEN) && /const \[includeExplanation, setIncludeExplanation\] = useState\(false\);/.test(SCREEN),
  'off by default');
ok(/if \(notify\) setIncludeExplanation\(false\);/.test(SCREEN), 'unticking Notify clears it');
const scrollEnd = SCREEN.indexOf('</ScrollView>\n              ) : null}');
const footerAt = SCREEN.indexOf('<View style={s.footer}>');
ok(scrollEnd > 0 && footerAt > scrollEnd
  && SCREEN.indexOf("decide('approve')", footerAt) > footerAt
  && SCREEN.indexOf("decide('deny')", footerAt) > footerAt,
  'Approve / Deny are in the footer, outside the scroll (pinned)');
ok(/detailScroll: \{ flexGrow: 0, flexShrink: 1/.test(SCREEN) && /footer: \{\s*flexShrink: 0/.test(SCREEN),
  'the detail shrinks, the footer does not');
ok(/\{ov\.decision \|\| ov\.pending \? \(/.test(SCREEN) && /NEW EXPLANATION \(REQUIRED\)/.test(SCREEN),
  'a decided item shows the form again, asking for a new explanation');

const API = read('src/utils/api.js');
ok(/reviewQueue: async \(params\) => \{\s*const r = await apiClient\.get\('\/api\/owner\/review-queue', \{ params \}\);/.test(API),
  'api: GET /api/owner/review-queue');
ok(/\/decide`,\s*body\);/.test(API), 'api: POST .../decide with the body');

const O = loadEsm('src/utils/ownerPortal.js');
ok(O.OWNER_NAV.some((n) => n.path === '/owner/review'), 'in the owner portal nav');
const SMOKE = read('scripts/smoke-mount.cjs');
const routes = SMOKE.slice(SMOKE.indexOf('const ROUTES = ['), SMOKE.indexOf('const MIME'));
ok(/'\/owner\/review',/.test(routes), 'mounted by smoke-mount');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
