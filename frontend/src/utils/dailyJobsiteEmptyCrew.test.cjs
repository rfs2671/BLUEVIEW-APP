/**
 * A CREW THAT WAS NOT ON SITE HAS NOTHING TO DESCRIBE.
 *
 * From the CP's device: AAZ showed "0 workers" on the roster step — no AAZ men
 * came through the gate that day — and the crew step still demanded an activity
 * and a location for them and held Next disabled. `num_workers` was consulted
 * NOWHERE: not in workRows, not in crewsWithoutWork, not in stepComplete.
 *
 * TWO PRODUCERS OF THE ZERO, and each needs its own half of the fix:
 *
 *   commitAddCrew    turned an untyped count into the literal string "0"
 *                    (`String(parseInt('') || 0)`) — the app asserting nobody
 *                    was there about a crew the CP had just said was. THIS PATH
 *                    HAS SINCE BEEN REMOVED from the screen entirely; section 4
 *                    below says what carries its rule now.
 *   no reconcile     a stored activity list was never compared against today's
 *                    roster again once non-empty, so a crew present when the
 *                    draft was opened kept its count all day — and, worse, a
 *                    crew that arrived AFTER it was opened never appeared at
 *                    all.
 *
 * Run:  node src/utils/dailyJobsiteEmptyCrew.test.cjs
 */
const fs = require('fs');
const path = require('path');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const eq = (a, b, label) => ok(
  JSON.stringify(a) === JSON.stringify(b),
  `${label}${JSON.stringify(a) === JSON.stringify(b) ? '' : ` — got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`}`,
);

// ── Load the shipped model, imports and all (it has none) ───────────────────
const SRC = path.join(__dirname, 'dailyJobsiteModel.js');
const raw = fs.readFileSync(SRC, 'utf8');
const body = raw
  .replace(/^export default [\s\S]*$/m, '')
  .replace(/^export (const|function|let) /gm, '$1 ');
// EACH EXPORT PICKED UP DEFENSIVELY. A bare `return { crewHeadcount, ... }`
// throws ReferenceError on a model that does not have them yet, which kills the
// run before a single assertion prints — so against a tree without this change
// the output is a stack trace instead of the list of things that are missing.
// `typeof` yields undefined instead, and the assertions below report it.
// applyHeadcountEdit joined the list when the hand-add path was removed: it is
// the only writer of num_workers left on the screen, so section 4's rule is now
// asked of it.
const NAMES = ['EMPTY_ACTIVITY', 'crewHeadcount', 'hasNoWorkersOnSite', 'workRows',
  'describableRows', 'crewsWithoutWork', 'stepComplete',
  'reconcileCrewsWithRoster', 'buildCrewsFromRoster', 'applyHeadcountEdit'];
// eslint-disable-next-line no-new-func
const M = new Function(`
  ${body}
  return { ${NAMES.map((n) => `${n}: typeof ${n} !== 'undefined' ? ${n} : undefined`).join(', ')} };
`)();
for (const n of NAMES) {
  if (typeof M[n] !== 'function') {
    failed += 1;
    console.log(`  FAIL  dailyJobsiteModel exports ${n}`);
  }
}
// Stubs so one missing export cannot cascade into a crash and hide the rest.
for (const n of NAMES) if (typeof M[n] !== 'function') M[n] = () => undefined;

const crew = (over = {}) => ({
  ...M.EMPTY_ACTIVITY(), company: 'Quality Plumbing', trade: 'Plumbing',
  num_workers: '4', gate_sourced: true, ...over,
});

// ═══════════════════════════════════════════════════════════════════════════
// 1. ZERO IS NOT BLANK
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- an explicit zero means nobody; a blank means nobody counted --');
{
  eq(M.crewHeadcount({ num_workers: '4' }), 4, 'a real count parses');
  eq(M.crewHeadcount({ num_workers: '0' }), 0, 'an explicit zero parses to 0');
  eq(M.crewHeadcount({ num_workers: '' }), null, 'a blank is null — never counted');
  eq(M.crewHeadcount({}), null, 'a missing key is null');
  eq(M.crewHeadcount(null), null, 'a missing row does not throw');

  ok(M.hasNoWorkersOnSite({ num_workers: '0' }), '"0" -> nobody on site');
  ok(!M.hasNoWorkersOnSite({ num_workers: '' }),
    '"" -> NOT nobody. A count that was never taken is not evidence of absence, '
    + 'and reading it as one would silently stop asking a crew that WAS here');
  ok(!M.hasNoWorkersOnSite({ num_workers: '4' }), '"4" -> on site');
  ok(!M.hasNoWorkersOnSite(null), 'a missing row does not throw');
}

// ═══════════════════════════════════════════════════════════════════════════
// 2. THE GATE STOPS DEMANDING — AND STILL DEMANDS FROM EVERYONE ELSE
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- the reported defect --');
{
  const aaz = crew({ company: 'AAZ', trade: 'Framing', num_workers: '0' });
  eq(M.crewsWithoutWork([aaz]), [],
    'a crew with nobody on it is not asked for an activity or a location');
  ok(M.workRows([aaz]).length === 1,
    'and it is NOT hidden — it still renders, still prints, still holds anything written on it');
  ok(M.describableRows([aaz]).length === 0,
    'it is only dropped from the set the log demands work from');
}
{
  // The gate must not have gone slack for everyone else.
  const real = crew({ num_workers: '4' });
  const gaps = M.crewsWithoutWork([real]);
  ok(gaps.length === 1 && gaps[0].missing.join(',') === 'activity,location',
    'a crew that WAS on site is still required to name its work and its floor');
  const done = crew({ num_workers: '4', work_description: 'grade beams', work_locations: 'Cellar' });
  eq(M.crewsWithoutWork([done]), [], 'and is cleared once it does');
}
{
  // POSITIONS STILL POINT AT THE RIGHT CARD. "Crew 3 of 3" is how the CP finds
  // it on screen, so the empty crew has to be counted in the numbering even
  // though it is not asked — filtering before the index would send him to the
  // wrong card.
  const rows = [
    crew({ company: 'Quality Plumbing', num_workers: '4' }),
    crew({ company: 'AAZ', num_workers: '0' }),
    crew({ company: 'Arkon Builders', num_workers: '6' }),
  ];
  const gaps = M.crewsWithoutWork(rows);
  eq(gaps.map((g) => `${g.crew}:${g.row}/${g.total}`),
    ['Quality Plumbing:1/3', 'Arkon Builders:3/3'],
    'the empty crew is skipped but still occupies its on-screen position');
}
{
  // The pip and the Next gate must agree, or the CP is stopped by something
  // the screen has just told him is finished.
  const filled = crew({ num_workers: '4', work_description: 'formwork', work_locations: 'L3' });
  const empty = crew({ company: 'AAZ', num_workers: '0' });
  ok(M.stepComplete(2, { activities: [filled, empty] }),
    'step 2 completes with an empty crew alongside a described one');
  eq(M.crewsWithoutWork([filled, empty]), [],
    'and the Next gate agrees — same set, so they cannot disagree');
}

// ═══════════════════════════════════════════════════════════════════════════
// 3. RECONCILIATION
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- the stored list is brought back into line with the roster --');
{
  const fresh = [crew({ num_workers: '4' })];
  eq(M.reconcileCrewsWithRoster([], fresh).length, 1,
    'an empty stored list still returns the freshly built one (the old rebuild)');
}
{
  // A gate row's FACTS are refreshed; the CP's WORDS are not touched.
  const stored = crew({
    num_workers: '2', worker_ids: ['a'], worker_names: ['Ana'],
    work_description: 'grade beams', work_locations: 'Cellar',
    photos: [{ id: 'p1' }],
  });
  const fresh = crew({
    num_workers: '5', worker_ids: ['a', 'b'], worker_names: ['Ana', 'Bo'],
    check_in_time: '2026-08-27T11:00:00Z',
  });
  const [out] = M.reconcileCrewsWithRoster([stored], [fresh]);
  eq(out.num_workers, '5', 'the headcount is refreshed from today\'s roster');
  eq(out.worker_names, ['Ana', 'Bo'], 'and so are the names');
  eq(out.work_description, 'grade beams', 'the CP\'s activity is UNTOUCHED');
  eq(out.work_locations, 'Cellar', 'and his location');
  eq(out.photos.length, 1, 'and his photos');
}
{
  // A gate crew that is not on the roster today drops to zero rather than
  // being deleted — deleting it would take anything already written with it.
  const stored = crew({ company: 'AAZ', trade: 'Framing', num_workers: '3',
    work_description: 'sheathing' });
  const [out] = M.reconcileCrewsWithRoster([stored], [crew({ num_workers: '4' })]);
  eq(out.num_workers, '0', 'a crew absent from today\'s roster reads zero');
  eq(out.work_description, 'sheathing', 'and keeps what the CP had written');
  eq(M.crewsWithoutWork([out]), [], 'so the log stops demanding from it');
}
{
  // THE HALF A RECONCILIATION CANNOT FIX. A hand-added row is the CP asserting
  // a crew the gate missed; the gate has no standing to correct it. This is
  // why the headcount filter is needed as well.
  const hand = crew({ company: 'Typed Co', gate_sourced: false, num_workers: '0' });
  const [out] = M.reconcileCrewsWithRoster([hand], []);
  eq(out.num_workers, '0', 'a hand-added row is returned untouched by reconciliation');
  ok(M.crewsWithoutWork([out]).length === 0,
    'and it takes the headcount filter — not the reconcile — to stop it blocking');
}
{
  // THE WORSE HALF OF THE BUG: a crew that arrived after the draft was opened.
  const stored = [crew({ company: 'Quality Plumbing', num_workers: '4',
    work_description: 'x', work_locations: 'y', crew_id: 'C1' })];
  const fresh = [
    crew({ company: 'Quality Plumbing', num_workers: '4' }),
    crew({ company: 'Arkon Builders', trade: 'Framing', num_workers: '6' }),
  ];
  const out = M.reconcileCrewsWithRoster(stored, fresh);
  eq(out.length, 2, 'a crew that arrived later is added to the log');
  eq(out[1].company, 'Arkon Builders', 'and it is the new one');
  eq(out[1].crew_id, 'C2', 'with a crew_id that does not collide with an existing row');
  eq(out[0].work_description, 'x', 'the crew already there is undisturbed');
}
{
  // crew_id counts from the highest present, not from the list length — it is
  // the PDF's first column and must never be reused by a different crew.
  const stored = [crew({ company: 'A', crew_id: 'C7', num_workers: '1' })];
  const fresh = [crew({ company: 'B', trade: 'Framing', num_workers: '2' })];
  const out = M.reconcileCrewsWithRoster(stored, fresh);
  eq(out.find((r) => r.company === 'B').crew_id, 'C8',
    'the appended crew takes the next free id, not C2');
}
{
  // Loose rows carry no CP content (they render no card) so they are replaced.
  const loose = (id) => ({ ...M.EMPTY_ACTIVITY(), company: '', gate_sourced: true,
    num_workers: '1', worker_ids: [id] });
  const out = M.reconcileCrewsWithRoster([loose('old')], [loose('new')]);
  eq(out.length, 1, 'one loose row in, one out');
  eq(out[0].worker_ids, ['new'], 'and it is today\'s, not yesterday\'s');
}

{
  // A TRADE BEING RESOLVED IS NOT A NEW CREW. Found by testing this change
  // against the NEXT one rather than after merging it: once the roster
  // resolves a pairing, the crew arrives carrying a trade it did not have,
  // the (company, trade) key misses, and the same crew appears TWICE -- one
  // row holding the description with nobody on it, one row with the men and
  // nothing written. Both print on the filed log.
  //
  // Reachable today without any roster change: POST /checkins/{id}/assign-trade
  // already rewrites checkins.worker_trade.
  const stored = [crew({ company: 'Arkon Builders', trade: '', num_workers: '6',
    crew_id: 'C1', work_description: 'sheathing', work_locations: 'L2' })];
  const fresh = [crew({ company: 'Arkon Builders', trade: 'Framers', num_workers: '6' })];
  const out = M.reconcileCrewsWithRoster(stored, fresh);
  eq(out.length, 1, 'a resolved trade updates the crew in place -- it does not duplicate it');
  eq(out[0].trade, 'Framers', 'and the row adopts the trade the roster now resolves');
  eq(out[0].work_description, 'sheathing', 'while keeping what the CP wrote against it');
  eq(out[0].crew_id, 'C1', 'and its crew_id, which is the PDF first column');
}
{
  // ONLY WHEN UNAMBIGUOUS. One company can field two crews in different trades;
  // guessing would put a description against the wrong trade on a signed
  // record, so the untraded row is left alone instead.
  const stored = [crew({ company: 'Arkon', trade: '', num_workers: '6',
    crew_id: 'C1', work_description: 'x' })];
  const fresh = [crew({ company: 'Arkon', trade: 'Framing', num_workers: '4' }),
    crew({ company: 'Arkon', trade: 'Concrete', num_workers: '2' })];
  const out = M.reconcileCrewsWithRoster(stored, fresh);
  eq(out.length, 3, 'two candidate crews means no guess: the untraded row stays');
  eq(out[0].num_workers, '0', 'it reads zero, which is visible and wrong in the safe direction');
  eq(out[0].work_description, 'x', 'and still holds what he wrote');
}

// ═══════════════════════════════════════════════════════════════════════════
// 4. THE PRODUCER — nothing mints a zero from a blank
//
// THE PRODUCER IS GONE, WHICH IS NOT THE SAME AS THE RULE BEING GONE.
// commitAddCrew and the "Add a crew the gate missed" button that opened it were
// removed by ruling, so the expression this block used to extract and RUN no
// longer exists to extract. The rule it carried — an untyped count is unknown,
// never the string "0" — still has to hold, because rows it wrote are still in
// stored logs and drafts and are still edited.
//
// So the block asserts the same rule against what is left:
//   • the `|| 0` expression is absent from the screen (unchanged, and it is now
//     absent because the whole path is, which is a stronger absence);
//   • the hand-add path really is gone, rather than having quietly survived
//     somewhere this file no longer looks;
//   • applyHeadcountEdit — the ONLY writer of num_workers left on this screen —
//     keeps a blank blank on a non-gate row, asserted by EXECUTION, which is
//     what the extracted expression was for.
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n-- an untyped count is unknown, not zero --');
{
  // CARRIAGE RETURNS STRIPPED. git normalises this repo's line endings on
  // checkout, so on a Windows working tree this file arrives CRLF and any
  // regex anchored on a bare newline silently stops matching -- the
  // extraction below went quiet and took five assertions with it, passing
  // the suite while testing nothing.
const SCREEN = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', 'logbooks', 'daily_jobsite.jsx'), 'utf8')
    .replace(/\r\n/g, '\n');
  // COMMENTS STRIPPED FIRST. The replacement comment quotes the old expression
  // verbatim to explain what it did, so a bare search matches the explanation
  // and reports the defect still present. Same guard as outdoorCanvasPin.
  const code = SCREEN
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/.*$/gm, '');
  ok(!/String\(parseInt\(c\.num, 10\) \|\| 0\)/.test(code),
    'the `|| 0` that manufactured the zero is gone from the CODE');

  // THE PATH ITSELF IS GONE. Asserted rather than assumed, and asserted on
  // three separate marks — the handler, the state that fed it, and the copy on
  // the button — because any one of them surviving alone would mean the
  // affordance had only half gone and could be wired back without notice.
  ok(!/commitAddCrew/.test(code),
    'the hand-add handler is gone from the screen');
  ok(!/setAddingCrew|addingCrew/.test(code),
    'and so is the modal state it wrote through');
  ok(!/t\('addCrew'\)|t\('addCrewTitle'\)/.test(code),
    'and nothing renders "Add a crew the gate missed" any more');

  // THE SURVIVING WRITER, EVALUATED. applyHeadcountEdit is now the only thing
  // on this screen that writes num_workers, so the unknown-is-not-zero rule
  // lives or dies there. Run for real against the shipped module — the same
  // standard the extracted expression was held to, moved onto what is left.
  const handRow = crew({ company: 'Typed Co', gate_sourced: false, num_workers: '4' });
  eq(M.applyHeadcountEdit(handRow, '').num_workers, '',
    'clearing the box on a non-gate row leaves it blank — unknown, not zero');
  eq(M.applyHeadcountEdit(handRow, '   ').num_workers, '',
    'whitespace is a blank, not a count');
  eq(M.applyHeadcountEdit(handRow, '6').num_workers, '6', 'a real count is kept');
  eq(M.applyHeadcountEdit(handRow, '0').num_workers, '0',
    'and a deliberately typed zero is still respected');
  eq(M.applyHeadcountEdit(handRow, 'abc').num_workers, undefined,
    'an unparseable entry writes nothing at all rather than a manufactured number');

  // A hand-added crew with no count keeps being asked for its work. No NEW ones
  // are created any more, but they arrive from stored logs and drafts, and the
  // rule is about the row, not about who made it.
  const handBlank = crew({ company: 'Typed Co', gate_sourced: false, num_workers: '' });
  ok(M.crewsWithoutWork([handBlank]).length === 1,
    'a hand-added crew with no count is still asked what it did');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
