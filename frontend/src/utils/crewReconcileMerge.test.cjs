/**
 * A gate crew confirming a company the CP already typed is CONFIRMATION,
 * not a second crew.
 *
 * WHAT THIS FIXES. reconcileCrewsWithRoster short-circuited every non-gate row
 * BEFORE the matcher:
 *
 *     if (!row.gate_sourced) { out.push(row); continue; }   // "the CP's, untouched"
 *
 * so a hand-added row could never match a gate crew, `matched` never gained
 * its key, and the append tail added the gate's crew as a SECOND row. On
 * 2026-08-31 that produced eight crews where four worked: C1-C4 typed by the
 * CP at 13:12, C5-C8 appended in one buildCrewsFromRoster call sharing a
 * single mint timestamp. The log was submitted that way, and the report's crew
 * table printed all eight on a compliance document.
 *
 * It fires every morning a CP starts his log before the men badge in, which is
 * the ordinary sequence on any site.
 *
 * THE SHORT-CIRCUIT MOVED, IT DID NOT GO AWAY, and that distinction is the
 * point of half this file. Deleting it outright — the obvious simplification —
 * drops an unmatched CP row into the gate-row `else` branch, which writes
 * num_workers '0' and empties worker_ids/worker_names, because
 * isHeadcountOverridden requires `gate_sourced` and returns false for a hand
 * row. That branch is right for a gate crew the roster no longer lists and
 * catastrophic for a crew the gate never saw. So the order is:
 *
 *     match  ->  merge          (either origin)
 *     no match, hand row        ->  untouched
 *     no match, gate row        ->  zeroed
 *
 * #244's OBJECTION IS ANSWERED BY RECORDING BOTH NUMBERS, NOT BY A SECOND ROW.
 * It held that silently folding the gate's men into a hand-typed row would
 * drop them from the headcount with nobody able to tell. gate_num_workers and
 * num_workers_source already exist for exactly that, so the merged row states
 * the CP's number AND the gate's, and says which is which.
 *
 * AND THE AMBIGUOUS CASE IS STILL PROTECTED. One company can legitimately
 * field two crews in different trades. The company-only match already required
 * exactly one candidate; with two, the CP row is left alone and both gate
 * crews append. Three rows, visible and correctable — #244's outcome, reached
 * conservatively instead of by default.
 *
 * Run:  node src/utils/crewReconcileMerge.test.cjs
 */

const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); } else { failed += 1; console.log(`  FAIL  ${label}`); }
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
  reconcileCrewsWithRoster, isHeadcountOverridden, gateHeadcount, CP_SOURCE,
} = mod;

const hand = (over = {}) => ({
  crew_id: 'C1', company: 'AAZ', trade: '', num_workers: '4',
  gate_sourced: false, worker_ids: [], worker_names: [],
  work_description: 'Set forms, north bay', work_locations: 'cellar',
  photos: [{ id: 'cap_1' }, { id: 'cap_2' }],
  ...over,
});

const gate = (over = {}) => ({
  crew_id: 'C5', company: 'AAZ', trade: 'concrete', num_workers: '6',
  gate_num_workers: '6', gate_sourced: true,
  worker_ids: ['w1', 'w2'], worker_names: ['A', 'B'],
  check_in_time: '2026-08-31T11:00:00Z',
  work_description: '', work_locations: '', photos: [],
  ...over,
});

console.log('\n1. THE MORNING SEQUENCE — one crew, not two');
{
  const out = reconcileCrewsWithRoster([hand()], [gate()]);
  ok(out.length === 1, 'a gate crew confirming a typed company MERGES, it does not append');
  const r = out[0];
  ok(r.work_description === 'Set forms, north bay', "the CP's work description survives");
  ok((r.photos || []).length === 2, 'and so do his photos');
  ok(r.gate_sourced === true, 'the merged row adopts gate_sourced — it has now been confirmed');
  ok(r.trade === 'concrete', 'an untyped trade adopts the gate\'s');
  ok((r.worker_ids || []).length === 2 && (r.worker_names || []).length === 2,
    'the gate\'s named men are carried onto it');
}

console.log('\n2. BOTH NUMBERS SURVIVE — a merge must not delete an assertion');
{
  const out = reconcileCrewsWithRoster([hand({ num_workers: '4' })], [gate({ num_workers: '6' })]);
  const r = out[0];
  ok(r.num_workers === '4', "THE CP TYPED 4 AND 4 STANDS — the gate does not overwrite him");
  ok(r.num_workers_source === CP_SOURCE, 'and the record says the number is his');
  ok(r.gate_num_workers === '6', "the gate's 6 is recorded beside it, not discarded");
  ok(gateHeadcount(r) === 6, 'and is readable through the accessor the renderers use');
  ok(isHeadcountOverridden(r) === true,
    'the merged row now reads as overridden, which only works because it gained gate_sourced');
}

console.log('\n3. A BLANK COUNT ADOPTS THE GATE\'S');
{
  const out = reconcileCrewsWithRoster(
    [hand({ num_workers: '', num_workers_source: undefined })], [gate({ num_workers: '6' })],
  );
  const r = out[0];
  ok(r.num_workers === '6', 'nobody counted, so the gate is the only number there is');
  ok(r.num_workers_source !== CP_SOURCE, 'and it is not attributed to the CP');
  ok(r.gate_num_workers === '6', 'the gate number is still recorded explicitly');
}

console.log('\n4. #244\'s CASE — TWO REAL CREWS FROM ONE COMPANY STAY PROTECTED');
{
  const twoTrades = [
    gate({ crew_id: 'C5', trade: 'concrete', num_workers: '6', worker_ids: ['w1'], worker_names: ['A'] }),
    gate({ crew_id: 'C6', trade: 'framing', num_workers: '3', worker_ids: ['w2'], worker_names: ['B'] }),
  ];
  const out = reconcileCrewsWithRoster([hand({ trade: '' })], twoTrades);

  ok(out.length === 3, 'THREE ROWS: the guard fails, so nothing is guessed');
  const cp = out.filter((r) => !r.gate_sourced);
  const gates = out.filter((r) => r.gate_sourced);
  ok(cp.length === 1, "the CP's untraded row STANDS — it is not merged into either crew");
  ok(cp[0].num_workers === '4' && cp[0].work_description === 'Set forms, north bay',
    'untouched: his count and his description are exactly as he left them');
  ok(gates.length === 2, 'and BOTH gate crews append');
  ok(gates.some((r) => r.trade === 'concrete') && gates.some((r) => r.trade === 'framing'),
    'one per trade, so no work is filed against the wrong one');
}

console.log('\n5. A TYPED TRADE MATCHES EXACTLY, AND ONLY ITS OWN CREW');
{
  const twoTrades = [
    gate({ crew_id: 'C5', trade: 'concrete', num_workers: '6' }),
    gate({ crew_id: 'C6', trade: 'framing', num_workers: '3' }),
  ];
  const out = reconcileCrewsWithRoster([hand({ trade: 'framing' })], twoTrades);
  ok(out.length === 2, 'the typed row merges with its own trade; the other appends');
  const merged = out.find((r) => r.trade === 'framing');
  ok(merged.work_description === 'Set forms, north bay',
    'the description landed on the framing crew, which is the one he typed');
  ok(merged.gate_num_workers === '3', "and it carries THAT crew's gate count, not the other's");
}

console.log('\n6. THE REORDERING — a CP crew the gate never reports is NOT emptied');
{
  const out = reconcileCrewsWithRoster([hand({ company: 'Nobody Ltd' })], [gate()]);
  const cp = out.find((r) => r.company === 'Nobody Ltd');
  ok(!!cp, 'the row is still there');
  ok(cp.num_workers === '4',
    'HIS HEADCOUNT STANDS. Deleting the short-circuit instead of moving it writes 0 here');
  ok((cp.photos || []).length === 2, 'his photos stand');
  ok(cp.work_description === 'Set forms, north bay', 'his description stands');
  ok(cp.gate_sourced !== true, 'and it never claims to have come from the gate');
  ok(out.length === 2, 'the unrelated gate crew still appends alongside it');
}

console.log('\n7. STABLE ON THE NEXT LOAD — a merged row matches, it does not re-append');
{
  const first = reconcileCrewsWithRoster([hand()], [gate()]);
  ok(first.length === 1, 'first load merges');
  const second = reconcileCrewsWithRoster(first, [gate()]);
  ok(second.length === 1, 'SECOND LOAD STILL ONE ROW — the merged row takes the matching branch');
  ok(second[0].work_description === 'Set forms, north bay', 'and keeps the description');
  ok(second[0].num_workers === '4', "and keeps the CP's number");
  const third = reconcileCrewsWithRoster(second, [gate()]);
  ok(third.length === 1, 'and again — it does not grow by one per load');
}

console.log('\n8. WHAT MUST NOT CHANGE');
{
  const appended = reconcileCrewsWithRoster([hand({ company: 'Nobody Ltd' })], [gate()]);
  ok(appended.some((r) => r.company === 'AAZ' && r.gate_sourced),
    'a gate company the CP never typed still appends');

  const left = reconcileCrewsWithRoster([gate()], []);
  ok(left.length === 1 && left[0].num_workers === '0',
    'a GATE row the roster no longer lists still reads zero — that branch is untouched');
  ok((left[0].worker_ids || []).length === 0,
    'and its named men are cleared, because the gate no longer reports them');

  const overridden = reconcileCrewsWithRoster(
    [gate({ num_workers: '9', num_workers_source: CP_SOURCE })], [],
  );
  ok(overridden[0].num_workers === '9',
    'a CP override on a gate crew still stands over the roster saying nobody');

  ok(reconcileCrewsWithRoster([], [gate()]).length === 1,
    'an empty stored list still returns the fresh rows');
  ok(reconcileCrewsWithRoster([hand()], []).length === 1,
    'an empty roster leaves the CP row alone');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
