/**
 * A HAND-ADDED CREW CAN BE REMOVED. A CREW OF REAL MEN CANNOT.
 *
 * #244's reconcile deliberately appends a second row when the CP hand-added a
 * company the gate later reports, and justified it as "visible on the screen
 * and correctable". It was visible and it was not correctable: there was no
 * delete. This is what makes the second half true.
 *
 * THE PREDICATE IS ABSENT WORKER IDENTITIES, NOT gate_sourced. A row carrying
 * worker_ids or worker_names represents named men who tapped a turnstile, and
 * removing it takes them off a filed 3301.2 record with no trace. A hand-added
 * row is the CP's own assertion with nobody behind it. Reading identities
 * rather than the flag means a row whose gate_sourced was lost is still
 * protected, and a hand-added row that somehow acquired the flag is still
 * removable -- the flag is provenance, this question is about people.
 *
 * AND THE CONFIRM STATES A CONSEQUENCE. In the duplicate, the description sits
 * on one row and the men on the other; deleting the described one destroys the
 * only record of that company's work while the requirement to describe it
 * stands, so he has to retype it onto the other card.
 *
 * MEASURED, NOT ASSUMED: Next is ALREADY disabled in that state -- the gate row
 * arrived with six men and no description, so it was in crewsWithoutWork before
 * he touched anything. The delete does not newly disable it; it takes away the
 * work he had already done. The copy is right either way, and the assertions
 * below pin what actually changes rather than what it looked like it would.
 *
 * The model is EXECUTED. The duplicate is produced by the real reconcile rather
 * than hand-written, so if #244's append rule changes these stop describing it.
 *
 * Run:  node src/utils/crewDelete.test.cjs
 */

const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');
const parser = require('@babel/parser');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const MODEL = path.join(__dirname, 'dailyJobsiteModel.js');
const { code } = babel.transformSync(fs.readFileSync(MODEL, 'utf8'), {
  filename: MODEL,
  plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
  configFile: false,
  babelrc: false,
});
const mod = {};
// eslint-disable-next-line no-new-func
new Function('exports', 'module', 'require', code)(mod, { exports: mod }, require);

const {
  isDeletableCrew, crewDeleteImpact, crewWorkerIdentities,
  reconcileCrewsWithRoster, crewsWithoutWork, workRows,
} = mod;

{
  const required = { isDeletableCrew, crewDeleteImpact, crewWorkerIdentities };
  let missing = 0;
  for (const [name, fn] of Object.entries(required)) {
    const present = typeof fn === 'function';
    ok(present, `dailyJobsiteModel exports ${name}`);
    if (!present) missing += 1;
  }
  if (missing > 0) {
    console.log(`\n  ${passed} passed, ${failed} failed`);
    console.log('  (stopping: the model does not carry the delete rule)');
    process.exit(1);
  }
}

const HAND = {
  crew_id: 'C1', company: 'Arkon Builders', trade: '', num_workers: '4',
  gate_sourced: false, worker_ids: [], worker_names: [],
  work_description: 'Poured slab', work_locations: 'cellar',
};
const GATE = {
  crew_id: 'C2', company: 'Arkon Builders', trade: 'concrete', num_workers: '6',
  gate_num_workers: '6', gate_sourced: true,
  worker_ids: ['w1', 'w2'], worker_names: ['A', 'B'],
  check_in_time: '2026-08-27T11:00:00Z', work_description: '', work_locations: '',
};

// ═══════════════════════════════════════════════════════════════════════════
// 1. WHAT MAY BE REMOVED — identities, not the flag.
// ═══════════════════════════════════════════════════════════════════════════
ok(isDeletableCrew(HAND), 'a hand-added crew is removable');
ok(!isDeletableCrew(GATE), 'a crew of named men is NOT removable');

ok(!isDeletableCrew({ ...GATE, gate_sourced: false }),
  'THE FLAG IS NOT THE TEST: a row that lost gate_sourced but still carries '
  + 'worker_ids is still protected');
ok(isDeletableCrew({ ...HAND, gate_sourced: true }),
  'and a hand-added row that acquired the flag is still removable');

ok(!isDeletableCrew({ ...GATE, worker_ids: [], worker_names: ['A'] }),
  'worker_names alone is enough to protect a row');
ok(!isDeletableCrew({ ...GATE, worker_names: [], worker_ids: ['w1'] }),
  'worker_ids alone is enough to protect a row');
ok(isDeletableCrew({ ...GATE, worker_ids: [], worker_names: [] }),
  'a gate crew the roster emptied carries nobody and may be removed');

ok(!isDeletableCrew({ gate_sourced: true, company: '' }),
  'an unassigned-worker row is not a crew card and is not deletable');
ok(!isDeletableCrew(null) && !isDeletableCrew(undefined),
  'a missing row is not deletable');

ok(crewWorkerIdentities(GATE) === 4, 'identities counts ids and names');
ok(crewWorkerIdentities({}) === 0, 'a row with neither counts zero');

// ═══════════════════════════════════════════════════════════════════════════
// 2. THE DUPLICATE — NO LONGER CREATED, STILL FOUND ON FILED LOGS.
//
// This section used to build `dup` by calling the real reconcile, because the
// reconcile appended a second row for a company the CP had already typed. It
// no longer does: a gate crew confirming a typed company MERGES, and
// crewReconcileMerge.test.cjs owns that behaviour.
//
// THE DELETE RULE IS NOT DEAD CODE. Every log filed before that change carries
// the duplicate — 2026-08-31's had eight crews where four worked — and the
// ambiguous case still produces extra rows on purpose, when one company fields
// two crews in different trades and an untraded hand row cannot be assigned to
// either. So the state is constructed literally here rather than generated,
// and everything below it is unchanged.
// ═══════════════════════════════════════════════════════════════════════════
ok(reconcileCrewsWithRoster([HAND], [GATE]).length === 1,
  'THE RECONCILE NO LONGER CREATES ONE: a gate crew confirming a typed '
  + 'company merges into it');

const dup = [HAND, GATE];
ok(dup.length === 2, 'the historical duplicate state: two rows for one sub');
ok(dup.filter((r) => !r.gate_sourced).length === 1
   && dup.filter((r) => r.gate_sourced).length === 1,
  'one hand row holding the description, one gate row holding the men');

const handIdx = dup.findIndex((r) => !r.gate_sourced);
const gateIdx = dup.findIndex((r) => r.gate_sourced);

ok(isDeletableCrew(dup[handIdx]), 'the hand half of the duplicate is removable');
ok(!isDeletableCrew(dup[gateIdx]), 'the gate half is not');

// The delete is DURABLE — the reconcile cannot re-append a hand-added row,
// because the append loop reads the gate roster and a hand row is not in it.
const afterDelete = dup.filter((_, i) => i !== handIdx);
const nextLoad = reconcileCrewsWithRoster(afterDelete, [GATE]);
ok(nextLoad.length === 1,
  'THE DELETE STICKS: the reconcile does not re-append a hand-added row');
ok(nextLoad[0].gate_sourced === true, 'and the gate row is what remains');

// ═══════════════════════════════════════════════════════════════════════════
// 3. THE CONSEQUENCE, BEFORE HE TAPS.
// ═══════════════════════════════════════════════════════════════════════════
{
  const impact = crewDeleteImpact(dup, handIdx);
  ok(impact.deletable, 'the impact says it can be removed');
  ok(impact.hasDescription, 'and that this card carries a work description');
  ok(impact.stranded !== null, 'and NAMES the crew left holding men and no work');
  ok(impact.stranded.workers === 6, 'with the headcount that would be stranded');
  ok(/arkon/i.test(impact.stranded.company), 'and the company it belongs to');

  // THE CLAIM THE SENTENCE MAKES, CHECKED RATHER THAN ASSUMED.
  //
  // Next is ALREADY disabled in the duplicate state -- the gate row arrived
  // with six men and no description, so it was in crewsWithoutWork before the
  // CP touched anything. The delete does not newly disable it. What the delete
  // does is destroy the only description of that company's work while leaving
  // the requirement to describe it standing, so he must retype onto the other
  // card. That is exactly what the copy says, and it is the claim worth
  // pinning.
  ok(crewsWithoutWork(dup).length === 1,
    'the gate row is already blocking Next before any delete');
  ok(crewsWithoutWork(afterDelete).length === 1,
    'and is still blocking it afterwards — the requirement does not go away');

  const describedBefore = dup.some(
    (r) => String(r.work_description || '').trim() === 'Poured slab');
  const describedAfter = afterDelete.some(
    (r) => String(r.work_description || '').trim() === 'Poured slab');
  ok(describedBefore && !describedAfter,
    'THE REAL CONSEQUENCE: what he wrote is gone from the log entirely');
}

{
  // Matched on COMPANY ALONE, deliberately: the duplicate exists because the
  // two rows disagree about the trade.
  const differentTrades = crewDeleteImpact(dup, handIdx);
  ok(dup[handIdx].trade !== dup[gateIdx].trade,
    'the two rows really do disagree about the trade');
  ok(differentTrades.stranded !== null,
    'and the sibling is still found — a (company, trade) key would miss it');
}

{
  // No description: nothing is stranded, so the copy must not claim otherwise.
  const plain = [{ ...HAND, work_description: '' }, GATE];
  const impact = crewDeleteImpact(plain, 0);
  ok(!impact.hasDescription, 'an undescribed card reports no description');
  ok(impact.stranded === null, 'and strands nobody');
}

{
  // Described, but nothing to inherit it — the words are simply lost.
  const lone = [{ ...HAND, company: 'Vanguard Masonry' }];
  const impact = crewDeleteImpact(lone, 0);
  ok(impact.hasDescription && impact.stranded === null,
    'a described card with no sibling reports a loss, not a stranding');
}

{
  // A sibling that already has work described is NOT stranded by the delete.
  const bothDescribed = [HAND, { ...GATE, work_description: 'Formwork' }];
  ok(crewDeleteImpact(bothDescribed, 0).stranded === null,
    'a sibling that already has its own description is not stranded');
}

{
  // A sibling with nobody on it cannot be stranded either — a 0-worker crew is
  // not asked for work at all (#244).
  const emptySibling = [HAND, { ...GATE, num_workers: '0', worker_ids: [], worker_names: [] }];
  ok(crewDeleteImpact(emptySibling, 0).stranded === null,
    'a sibling with no workers is not stranded — it is not asked for work');
}

// ═══════════════════════════════════════════════════════════════════════════
// 4. THE LAST-ROW EDGE. Deleting everything does not empty the log.
// ═══════════════════════════════════════════════════════════════════════════
{
  const only = [{ ...HAND, company: 'Vanguard Masonry' }];
  ok(crewDeleteImpact(only, 0).isLastRow, 'the only crew reports isLastRow');
  ok(!crewDeleteImpact(dup, handIdx).isLastRow,
    'one of two does not');

  // The behaviour the note describes is real: an emptied list reloads the
  // whole gate roster.
  const emptied = reconcileCrewsWithRoster([], [GATE]);
  ok(emptied.length === 1,
    'an emptied log reloads the gate roster — which is what the note says');
}

// ═══════════════════════════════════════════════════════════════════════════
// 5. THE SCREEN. The copy states a consequence and the refusal is on screen.
// ═══════════════════════════════════════════════════════════════════════════
{
  const I18N = path.join(__dirname, '..', 'i18n', 'en.js');
  const stripped = fs.readFileSync(I18N, 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default /m, 'const __default = ');
  // eslint-disable-next-line no-new-func
  const EN = new Function(`${stripped}; return __default;`)().dailyJobsite;

  ok(/\{crew\}/.test(EN.deleteCrewStrands) && /\{n\}/.test(EN.deleteCrewStrands),
    'the stranding copy interpolates the crew and the count');
  ok(/no work recorded/i.test(EN.deleteCrewStrands),
    'and states the CONSEQUENCE, not just that a description exists');
  ok(/other card/i.test(EN.deleteCrewStrands),
    'and says where he will have to describe the work instead');
  ok(!/are you sure/i.test(Object.values(EN).join(' ')),
    'nothing in this namespace asks a bare "are you sure"');
  ok(/does not empty/i.test(EN.deleteCrewLastRow)
     && /read again/i.test(EN.deleteCrewLastRow),
    'the last-row note says the log is not emptied and why');
  ok(/tapped in/i.test(EN.deleteCrewRefused) && /count to 0/i.test(EN.deleteCrewRefused),
    'the refusal gives the reason AND the thing to do instead');

  const screen = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', 'logbooks', 'daily_jobsite.jsx'), 'utf8');
  const tree = parser.parse(screen, { sourceType: 'module', plugins: ['jsx'] });

  const seen = new Set();
  let usesPredicate = false;
  let usesImpact = false;
  let refusalRendered = false;
  let splicesByFilter = false;
  (function walk(n) {
    if (!n || typeof n !== 'object' || seen.has(n)) return;
    seen.add(n);
    if (n.type === 'CallExpression' && n.callee.type === 'Identifier') {
      if (n.callee.name === 'isDeletableCrew') usesPredicate = true;
      if (n.callee.name === 'crewDeleteImpact') usesImpact = true;
    }
    if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
        && n.callee.property.name === 'filter') splicesByFilter = true;
    if (n.type === 'StringLiteral' && n.value === 'deleteCrewRefused') refusalRendered = true;
    for (const k of Object.keys(n)) {
      const v = n[k];
      if (Array.isArray(v)) v.forEach(walk);
      else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v);
    }
  }(tree));

  ok(usesPredicate, 'the screen gates the control on isDeletableCrew');
  ok(usesImpact, 'and builds the confirm from crewDeleteImpact');
  ok(refusalRendered,
    'a gate card RENDERS the refusal rather than silently omitting the control');
  ok(splicesByFilter, 'the removal is a filter, not a mutating splice');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
