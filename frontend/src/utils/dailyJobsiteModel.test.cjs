/**
 * The Daily Jobsite Log's decision logic, EXECUTED.
 *
 * Every rule asserted here decides something that ends up inside a signed
 * compliance record. The point of this file is that the assertions run the
 * real shipped functions rather than grepping for them — a rule that is merely
 * present in the source is not a rule that works.
 *
 * The headline one is FINDING C: the app must never write the work
 * description. The screen this replaced seeded `work_description: r.trade`, so
 * a signed log asserted the Concrete crew performed "Concrete". The app wrote
 * that sentence, not the CP.
 *
 * No test runner in this repo (see i18n.test.cjs); the ESM module is read,
 * stripped of its export keywords and evaluated.
 *
 * Run:  node src/utils/dailyJobsiteModel.test.cjs
 */
const fs = require('fs');
const path = require('path');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const eq = (a, b, label) => ok(JSON.stringify(a) === JSON.stringify(b),
  `${label}${JSON.stringify(a) === JSON.stringify(b) ? '' : ` — got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`}`);

// ── Load the model ───────────────────────────────────────────────────────────
const SRC = path.join(__dirname, 'dailyJobsiteModel.js');
const raw = fs.readFileSync(SRC, 'utf8');
ok(!/^import /m.test(raw),
  'the model imports nothing — it stays runnable outside the app');
const body = raw
  .replace(/^export default [\s\S]*$/m, '')
  .replace(/^export (const|function|let) /gm, '$1 ');
// eslint-disable-next-line no-new-func
const M = new Function(`
  ${body}
  return { rosterKey, isUnassignedCompany, EMPTY_ACTIVITY, EMPTY_OBSERVATION,
           buildCrewsFromRoster, rosterIdIndex, parseInstant, composeSelection,
           cameraReady, resolveRosterId, isUnboundCrew, deriveGeneralDescription,
           isUnassignedWorkerRow, workRows,
           observationComplete, incompleteObservations, formatLogDate,
           formatCheckInTime, stepComplete,
           isUnassignedTrade, cleanTrade, tradeLabel, NO_TRADE_LABEL,
           INSPECTION_PASS, INSPECTION_FAIL, EMPTY_INSPECTION, inspectionRow,
           inspectionComplete, incompleteInspections };
`)();

// ═════════════════════════════════════════════════════════════════════════════
// FINDING C — the app does not write the work description
// ═════════════════════════════════════════════════════════════════════════════
console.log('\n── Finding C: an unselected activity is EMPTY, never the trade ──');

const fresh = M.EMPTY_ACTIVITY();
eq(fresh.work_description, '', 'a new crew row starts with an EMPTY work description');
eq(fresh.activity_ids, [], 'a new crew row has no activity selected');

{
  // The exact shape /daily-headcount returns, carrying a trade.
  const roster = [
    { worker_id: 'w1', worker_name: 'A', company: 'Vanguard', trade: 'Concrete',
      check_in_time: '2026-03-04T12:00:00Z' },
  ];
  const crews = M.buildCrewsFromRoster(roster, []);
  eq(crews.length, 1, 'one crew is built from one worker');
  eq(crews[0].trade, 'Concrete', 'the trade is CARRIED on the row (it is a real fact)');
  eq(crews[0].work_description, '',
    'THE TRADE IS NOT WRITTEN INTO work_description — the CP has not said what they did');
  ok(crews[0].work_description !== crews[0].trade,
    'work_description is never seeded from trade');
}

eq(M.composeSelection([], new Map()), '',
  'composing nothing yields an empty string, not a guess');
eq(M.composeSelection(null, new Map()), '', 'a null selection is empty, and does not throw');
eq(M.composeSelection(['a'], new Map([['a', 'formwork']])), 'formwork',
  'one tapped chip composes to its label');
eq(M.composeSelection(['a', 'b'], new Map([['a', 'formwork'], ['b', 'rebar']])),
  'formwork, rebar', 'two tapped chips compose in tap order');
eq(M.composeSelection(['a', 'a'], new Map([['a', 'formwork']])), 'formwork',
  'a duplicate id is not repeated in the sentence');
eq(M.composeSelection(['ghost'], new Map()), '',
  'an id with no label contributes nothing rather than an id string');

// ═════════════════════════════════════════════════════════════════════════════
// THE CAMERA GATE — no photo without crew, activity AND location
// ═════════════════════════════════════════════════════════════════════════════
console.log('\n── The camera gate ──');

const withAll = {
  company: 'Vanguard', crew_id: 'C1',
  activity_ids: ['a'], work_description: 'formwork',
  location_ids: ['floor_3'], work_locations: 'Floor 3',
};
ok(M.cameraReady(withAll), 'crew + activity + location -> the camera opens');
ok(!M.cameraReady({ ...withAll, activity_ids: [], work_description: '' }),
  'NO ACTIVITY -> the camera stays shut');
ok(!M.cameraReady({ ...withAll, location_ids: [], work_locations: '' }),
  'NO LOCATION -> the camera stays shut');
ok(!M.cameraReady({ ...withAll, company: '', crew_id: '' }),
  'NO CREW -> the camera stays shut');
ok(!M.cameraReady(M.EMPTY_ACTIVITY()), 'a blank row can never open the camera');
ok(!M.cameraReady(null), 'a missing row does not open the camera and does not throw');
ok(!M.cameraReady({ ...withAll, activity_ids: ['a'], work_description: '   ' }),
  'a whitespace-only description does not count as an activity');

// ═════════════════════════════════════════════════════════════════════════════
// STEP 1 — who was here
// ═════════════════════════════════════════════════════════════════════════════
console.log('\n── Step 1: the roster ──');

{
  const roster = [
    { worker_id: 'w1', worker_name: 'A', company: 'Vanguard', trade: 'Concrete', check_in_time: '2026-03-04T13:00:00Z' },
    { worker_id: 'w2', worker_name: 'B', company: 'Vanguard', trade: 'Concrete', check_in_time: '2026-03-04T11:00:00Z' },
    { worker_id: 'w3', worker_name: 'C', company: 'Apex', trade: 'Electrical', check_in_time: '2026-03-04T12:00:00Z' },
  ];
  const crews = M.buildCrewsFromRoster(roster, []);
  eq(crews.length, 2, 'workers group into one row per (company, trade)');
  const v = crews.find((c) => c.company === 'Vanguard');
  eq(v.num_workers, '2', 'the crew carries its real headcount');
  eq(v.check_in_time.toISOString(), '2026-03-04T11:00:00.000Z',
    'the crew check-in time is the EARLIEST arrival, not the last');
  ok(v.gate_sourced === true, 'a gate-derived row is marked gate-sourced');
  eq(crews.map((c) => c.crew_id), ['C1', 'C2'], 'every row gets a crew id for the PDF column');
}

{
  // "A worker with no crew assignment appears as his own row. He is a real man
  // on site and the log must say so."
  const roster = [
    { worker_id: 'w1', worker_name: 'Solo One', company: '', trade: 'Labourer', check_in_time: '2026-03-04T12:00:00Z' },
    { worker_id: 'w2', worker_name: 'Solo Two', company: 'UNASSIGNED', trade: '', check_in_time: '2026-03-04T12:00:00Z' },
  ];
  const crews = M.buildCrewsFromRoster(roster, []);
  eq(crews.length, 2, 'two unassigned workers are TWO rows — they are not a crew');
  ok(crews.every((c) => c.company === ''),
    'the UNASSIGNED sentinel is never stamped onto the record as a company');
  ok(crews.every((c) => c.num_workers === '1'), 'each unassigned worker counts as himself');
  ok(crews.every((c) => c.gate_sourced === true),
    'he came through the gate, so the row says so');
}

{
  const roster = [
    { worker_id: 'w1', worker_name: 'Blocked Man', company: 'Vanguard', trade: 'Concrete',
      check_in_time: '2026-03-04T12:00:00Z', blocked: true },
    { worker_id: 'w2', worker_name: 'Admitted', company: 'Vanguard', trade: 'Concrete',
      check_in_time: '2026-03-04T12:00:00Z' },
  ];
  const crews = M.buildCrewsFromRoster(roster, []);
  eq(crews.length, 1, 'a turned-away worker does not create a crew');
  eq(crews[0].num_workers, '1',
    'a worker refused at the gate is NOT counted as having been on site');
}

{
  const headcount = [{ sub_name: 'Vanguard', trade: 'Concrete', subcontractor_id: 'srv_abc' }];
  const roster = [{ worker_id: 'w1', worker_name: 'A', company: ' vanguard ', trade: 'CONCRETE', check_in_time: null }];
  const crews = M.buildCrewsFromRoster(roster, headcount);
  eq(crews[0].subcontractor_id, 'srv_abc',
    'the roster id binds through case and whitespace, like the backend _roster_key');
  eq(crews[0].check_in_time, null, 'a missing check-in time is null, never invented');
  ok(!M.isUnboundCrew(crews[0]), 'a bound crew is not flagged unbound');
}

{
  const roster = [{ worker_id: 'w1', worker_name: 'A', company: 'Ghost Co', trade: 'Masonry' }];
  const crews = M.buildCrewsFromRoster(roster, []);
  eq(crews[0].subcontractor_id, null,
    'a sub the roster does not know gets NULL, never a fabricated id');
  ok(M.isUnboundCrew(crews[0]), 'and is flagged unbound for an admin');
}

eq(M.buildCrewsFromRoster(null, null), [], 'a failed roster read yields no crews and does not throw');

// ═════════════════════════════════════════════════════════════════════════════
// GATE PROVENANCE, AND THE ONE SURVIVING BINDING PATH
// ═════════════════════════════════════════════════════════════════════════════
//
// `applyCompanyCorrection` is GONE. Assigning a company or trade does not
// belong on the daily log — a worker sets his own at check-in, and a CP who
// has to fix one does it during safety orientation. What survives is the
// hand-added crew, which still has to resolve to a real roster row, and
// company_gate, which is still recorded as provenance.
console.log('\n── Gate provenance, and resolving a hand-added crew ──');

{
  const rosterIds = new Map([['acme drywall|drywall', 'srv_acme']]);
  eq(M.resolveRosterId('Acme Drywall', 'Drywall', rosterIds), 'srv_acme',
    'a crew the CP names that IS on the roster binds to its row');
  eq(M.resolveRosterId('  acme   drywall  '.replace(/\s+/g, ' ').trim(), 'DRYWALL', rosterIds),
    'srv_acme',
    'case and surrounding whitespace still resolve — same rule as the backend');
  eq(M.resolveRosterId('Ghost Co', 'Drywall', rosterIds), null,
    'a company the roster does not know gets NULL, never a fabricated id');
  eq(M.resolveRosterId('Acme Drywall', 'Concrete', rosterIds), null,
    'the RIGHT company on the WRONG trade is a different roster row — null, not a guess');
  eq(M.resolveRosterId('', 'Drywall', rosterIds), null,
    'no company means no identity');
  eq(M.resolveRosterId('Acme Drywall', 'Drywall', null), null,
    'no roster to match against resolves to null and does not throw');
}

{
  // company_gate survives as provenance and is set ONLY from the gate.
  const roster = [{ worker_id: 'w1', worker_name: 'A', company: 'Vanguard',
    trade: 'Concrete', check_in_time: null }];
  const [crew] = M.buildCrewsFromRoster(roster, []);
  eq(crew.company_gate, 'Vanguard',
    'a gate-sourced crew records what the gate said, so the two records can be compared');
  const hand = M.EMPTY_ACTIVITY();
  eq(hand.company_gate, null,
    'a hand-added row has no gate value and does not invent one');
  ok(!('company_corrected_by' in hand) && !('company_corrected_at' in hand),
    'the dead correction-trail keys are gone from the row entirely');
}

// ═════════════════════════════════════════════════════════════════════════════
// A WORKER WITH NO COMPANY IS PRESENT, BUT IS NOT A UNIT OF WORK
// ═════════════════════════════════════════════════════════════════════════════
console.log('\n── The unassigned worker gets no activity card ──');

{
  const roster = [
    { worker_id: 'w1', worker_name: 'A', company: 'Vanguard', trade: 'Concrete',
      check_in_time: '2026-03-04T12:00:00Z' },
    { worker_id: 'w2', worker_name: 'Solo', company: '', trade: 'Labourer',
      check_in_time: '2026-03-04T12:00:00Z' },
  ];
  const crews = M.buildCrewsFromRoster(roster, []);
  eq(crews.length, 2, 'he IS built — the log must show he was on site');

  const solo = crews.find((c) => !c.company);
  const van = crews.find((c) => c.company === 'Vanguard');
  ok(M.isUnassignedWorkerRow(solo), 'his row is identified as unassigned');
  ok(!M.isUnassignedWorkerRow(van), 'a real crew is not');

  eq(M.workRows(crews).length, 1,
    'only the COMPANY row is a work row — he gets no activity card');
  eq(M.workRows(crews)[0].company, 'Vanguard', 'and it is the right one');
}

{
  // A crew the CP typed in always has a company, so it can never be mistaken
  // for an unassigned worker even before he fills anything else in.
  const hand = { ...M.EMPTY_ACTIVITY(), company: 'Typed Co', gate_sourced: false };
  ok(!M.isUnassignedWorkerRow(hand), 'a hand-added crew is never treated as unassigned');
  const blank = M.EMPTY_ACTIVITY();
  ok(!M.isUnassignedWorkerRow(blank),
    'and neither is a blank row — the flag needs gate provenance');
  ok(!M.isUnassignedWorkerRow(null), 'a missing row does not throw');
}

{
  // THE STEP CAN STILL COMPLETE. Requiring work from a man who is never asked
  // for any would leave Step 2 permanently unfinished.
  const work = { ...M.EMPTY_ACTIVITY(), company: 'Vanguard', gate_sourced: true,
    work_description: 'formwork' };
  const solo = { ...M.EMPTY_ACTIVITY(), company: '', gate_sourced: true };
  ok(M.stepComplete(2, { activities: [work, solo] }),
    'step 2 completes with an unassigned worker present');
  ok(!M.stepComplete(2, { activities: [{ ...work, work_description: '' }, solo] }),
    '...but still refuses when a REAL crew has no work described');
  ok(!M.stepComplete(2, { activities: [solo] }),
    'and a day of nothing but unassigned workers is not a completed step 2');
}

{
  // ONCE HE IS ASSIGNED, HE JOINS THE EXISTING ROW. No merge code — crews are
  // keyed on (company, trade), so he simply falls into the bucket.
  const before = M.buildCrewsFromRoster([
    { worker_id: 'w1', worker_name: 'A', company: 'Vanguard', trade: 'Concrete' },
    { worker_id: 'w2', worker_name: 'Solo', company: '', trade: 'Concrete' },
  ], []);
  eq(before.length, 2, 'before assignment: a crew and a loose man');

  const after = M.buildCrewsFromRoster([
    { worker_id: 'w1', worker_name: 'A', company: 'Vanguard', trade: 'Concrete' },
    { worker_id: 'w2', worker_name: 'Solo', company: 'Vanguard', trade: 'Concrete' },
  ], []);
  eq(after.length, 1, 'after assignment he JOINS the crew — no second row');
  eq(after[0].num_workers, '2', 'and the headcount picks him up');
  eq(M.workRows(after).length, 1, 'and he now counts toward that crew as work');
}

// ═════════════════════════════════════════════════════════════════════════════
// THE GENERAL DESCRIPTION — drafted from trades, never guessed
// ═════════════════════════════════════════════════════════════════════════════
console.log('\n── The drafted general description ──');

{
  const trades = new Map([
    ['excavation', 'excavation'], ['site_prep', 'sitework'],
    ['slab_rebar', 'concrete'], ['edge_forms', 'concrete'],
    ['drywall', 'drywall'], ['other', 'gc'],
  ]);
  const crew = (ids) => ({ ...M.EMPTY_ACTIVITY(), activity_ids: ids });

  eq(M.deriveGeneralDescription([], trades), '',
    'no crews at all drafts NOTHING — never a default sentence');
  eq(M.deriveGeneralDescription([crew([])], trades), '',
    'a crew with no activity tapped contributes nothing');
  eq(M.deriveGeneralDescription(null, trades), '',
    'a missing activity list is empty, and does not throw');

  eq(M.deriveGeneralDescription([crew(['excavation'])], trades), 'excavation',
    'one tapped chip drafts its trade');
  eq(M.deriveGeneralDescription([crew(['slab_rebar', 'edge_forms'])], trades), 'concrete',
    'two chips of the SAME trade collapse to one word, not a repetition');
  eq(M.deriveGeneralDescription([crew(['excavation', 'site_prep'])], trades),
    'excavation, sitework', 'two trades are both named');

  // Ranked by how many crews were doing it, so the biggest activity leads.
  eq(M.deriveGeneralDescription(
    [crew(['excavation']), crew(['slab_rebar']), crew(['edge_forms'])], trades,
  ), 'concrete, excavation',
  'the trade the most crews were doing leads the sentence');

  // THE ESCAPE HATCH IS EXCLUDED even though its node reports trade "gc".
  eq(M.deriveGeneralDescription([crew(['other'])], trades), '',
    'the "Other" chip alone drafts NOTHING — it stands for free text, not a trade');
  eq(M.deriveGeneralDescription([crew(['excavation', 'other'])], trades), 'excavation',
    '...and it never contributes "gc" alongside a real trade');
  eq(M.deriveGeneralDescription([crew(['other:night pour'])], trades), '',
    'a remembered free-text entry has no trade and contributes nothing');

  eq(M.deriveGeneralDescription([crew(['ghost_chip'])], trades), '',
    'a chip with no trade on it contributes nothing rather than an id');
  eq(M.deriveGeneralDescription([crew(['excavation'])], null), '',
    'no trade map at all drafts nothing, and does not throw');

  // Deterministic: same input, same sentence, every time.
  const once = M.deriveGeneralDescription([crew(['excavation']), crew(['drywall'])], trades);
  const twice = M.deriveGeneralDescription([crew(['excavation']), crew(['drywall'])], trades);
  eq(once, twice, 'the draft is deterministic — the same day drafts the same sentence');
}

// ═════════════════════════════════════════════════════════════════════════════
// STEP 3 — an observation needs a corrective action
// ═════════════════════════════════════════════════════════════════════════════
console.log('\n── Step 3: no observation without a corrective action ──');

const obsBase = { description: 'Open riser', responsible_party: 'Vanguard', remedy: '', corrected_immediately: null };
ok(!M.observationComplete(obsBase), 'a hazard with NO remedy is incomplete');
ok(M.observationComplete({ ...obsBase, remedy: 'Covered and barricaded' }),
  'a written remedy completes it');
ok(M.observationComplete({ ...obsBase, corrected_immediately: true }),
  'corrected_immediately counts as the action being stated');
ok(!M.observationComplete({ ...obsBase, remedy: 'x', responsible_party: '' }),
  'a remedy with nobody responsible is still incomplete');
ok(!M.observationComplete({ ...obsBase, remedy: 'x', description: '' }),
  'a remedy with nothing described is still incomplete');
ok(!M.observationComplete({ ...obsBase, remedy: '   ' }),
  'a whitespace remedy is not a remedy');
ok(!M.observationComplete(null), 'a missing observation is incomplete, and does not throw');
eq(M.incompleteObservations([obsBase, { ...obsBase, remedy: 'done' }]), [0],
  'the incomplete ones are reported BY INDEX so the screen can point at them');
eq(M.incompleteObservations([]), [], 'no observations at all is a complete step');

// ═════════════════════════════════════════════════════════════════════════════
// DATES — the Eastern rule
// ═════════════════════════════════════════════════════════════════════════════
console.log('\n── Dates: no timezone touches a calendar day ──');

{
  // `new Date('2026-03-04').toLocaleDateString()` parses as UTC midnight and
  // then formats in the DEVICE zone, so a phone west of Greenwich renders
  // March 3. The record must not depend on where the phone is.
  const out = M.formatLogDate('2026-03-04');
  ok(/March 4, 2026/.test(out), `a YYYY-MM-DD renders as its own day (${out})`);
  ok(/Wednesday/.test(out), 'and its real weekday');
  eq(M.formatLogDate(''), '', 'an empty date renders empty rather than "Invalid Date"');
  eq(M.formatLogDate('nonsense'), 'nonsense', 'an unparseable date is passed through, not guessed');
}

{
  // 21:00 Eastern, both DST regimes. In each case the UTC calendar date is
  // already the NEXT day — which is exactly the bug that shipped thirteen times.
  const edt = new Date('2026-08-09T21:00:00-04:00');   // EDT, summer
  const est = new Date('2026-01-09T21:00:00-05:00');   // EST, winter
  eq(edt.toISOString().slice(0, 10), '2026-08-10',
    'CONTROL: at 21:00 EDT the UTC date is already tomorrow');
  eq(est.toISOString().slice(0, 10), '2026-01-10',
    'CONTROL: at 21:00 EST the UTC date is already tomorrow');
  eq(M.formatCheckInTime(edt.toISOString()), '9:00 PM',
    'a check-in at 21:00 EDT displays as 9:00 PM in New York, not 1:00 AM');
  eq(M.formatCheckInTime(est.toISOString()), '9:00 PM',
    'a check-in at 21:00 EST displays as 9:00 PM in New York — both DST regimes');
}
eq(M.formatCheckInTime(null), null, 'no check-in time renders as nothing, never as a made-up time');
eq(M.formatCheckInTime('garbage'), null, 'an unparseable instant renders as nothing');

// ═════════════════════════════════════════════════════════════════════════════
// STEP PROGRESS never blocks
// ═════════════════════════════════════════════════════════════════════════════
console.log('\n── Step marks ──');
ok(!M.stepComplete(1, { activities: [] }), 'step 1 is incomplete with no crews');
ok(M.stepComplete(1, { activities: [{}] }), 'step 1 completes once a crew exists');
ok(!M.stepComplete(2, { activities: [{ work_description: '' }] }),
  'step 2 is incomplete while a crew has no described work');
ok(M.stepComplete(2, { activities: [{ work_description: 'formwork' }] }),
  'step 2 completes when every crew has described work');
ok(M.stepComplete(3, { observations: [] }), 'step 3 completes with no observations');
ok(M.stepComplete(5, { cpSignature: 'data:...' }), 'step 5 completes once signed');

// ═════════════════════════════════════════════════════════════════════════════
// THE DAILY INSPECTIONS — a tick could not say what was FOUND
console.log('\n── The nine daily inspections ──');

const PASS = M.INSPECTION_PASS;
const FAIL = M.INSPECTION_FAIL;
ok(PASS === 'pass' && FAIL === 'fail', 'the two results are named, not typed literals');

// The whole reason the shape changed.
ok(M.inspectionRow({ k: { result: FAIL, note: 'north edge open' } }, 'k').result === FAIL,
  'a failed inspection is recorded as failed');
ok(M.inspectionRow({ k: { result: PASS, note: '' } }, 'k').result === PASS,
  'and a passed one as passed');

// NOT WALKED IS NOT A PASS. This is the assertion that stops the filed
// document claiming an inspection nobody did.
ok(M.inspectionRow({}, 'missing').result === null,
  'an item the CP never touched has NO result');
ok(M.inspectionRow({ k: { result: 'maybe', note: '' } }, 'k').result === null,
  'and a junk result is no result, never coerced into a pass');
ok(M.EMPTY_INSPECTION().result === null && M.EMPTY_INSPECTION().note === '',
  'a fresh row starts unanswered');

// LEGACY. A log filed while this was a tick-chip.
const legacy = M.inspectionRow({ fire_safety: true }, 'fire_safety');
ok(legacy.result === null, 'a legacy tick is NOT upgraded to a pass nobody recorded');
ok(legacy.legacy_ticked === true, 'it is flagged, so the screen can say what it is');
ok(M.inspectionRow({ fire_safety: false }, 'fire_safety').result === null,
  'and an unticked legacy item is simply unanswered');

// A FAIL MUST SAY WHAT FAILED.
ok(!M.inspectionComplete({ result: FAIL, note: '' }), 'a fail with no note is incomplete');
ok(!M.inspectionComplete({ result: FAIL, note: '   ' }), 'whitespace is not a note');
ok(M.inspectionComplete({ result: FAIL, note: 'north edge open' }), 'a noted fail is complete');
ok(M.inspectionComplete({ result: PASS, note: '' }), 'a pass needs no note');
ok(M.inspectionComplete({ result: null, note: '' }),
  'and an item he did not walk does NOT block him — he is not forced through all nine');
ok(M.inspectionComplete(undefined), 'an absent row blocks nothing');

// The sign gate reports KEYS, so adding a tenth item cannot renumber it.
const items = {
  street_frontage: { result: PASS, note: '' },
  fall_protections: { result: FAIL, note: '' },
  permits: { result: FAIL, note: 'expired' },
  plans: { result: null, note: '' },
};
ok(JSON.stringify(M.incompleteInspections(items)) === JSON.stringify(['fall_protections']),
  'exactly the un-noted fail blocks, named by key');
ok(M.incompleteInspections({}).length === 0, 'a form nobody touched blocks nothing');
ok(M.incompleteInspections(null).length === 0, 'and neither does a missing one');

// Step 4 is the inspections now; weather moved to Step 1 and never gated a step
// the CP could not fix.
ok(M.stepComplete(4, { checklistItems: items }) === false,
  'step 4 is incomplete while a fail has no note');
ok(M.stepComplete(4, items) === true,
  'and it reads state.checklistItems — a bare items object is not the state');
ok(M.stepComplete(4, { checklistItems: {
  ...items, fall_protections: { result: FAIL, note: 'north edge open' },
} }), 'and completes once every fail says what failed');
ok(M.stepComplete(4, { checklistItems: {} }),
  'an untouched form is complete — walking all nine is not compulsory');
ok(M.stepComplete(4, { weather: 'Sunny' }) === true,
  'weather no longer decides step 4');

console.log(`\n${passed} passed, ${failed} failed`);
// THE "UNASSIGNED" SENTINEL ON TRADE
console.log('\n-- The sentinel is a placeholder, not a trade --');

ok(M.isUnassignedTrade('UNASSIGNED'), 'the literal is recognised');
ok(M.isUnassignedTrade('unassigned') && M.isUnassignedTrade('  Unassigned  '),
  'case and padding do not smuggle it through');
ok(M.isUnassignedTrade('') && M.isUnassignedTrade(null),
  'and an absent trade is the same absence');
ok(!M.isUnassignedTrade('Electrical'), 'a real trade is not the sentinel');

ok(M.cleanTrade('UNASSIGNED') === '', 'cleanTrade strips it, as company already was');
ok(M.cleanTrade('  Electrical ') === 'Electrical', 'and trims a real one');

// THE DISPLAY RULE. Blank is ambiguous on a record somebody signs.
ok(M.tradeLabel('UNASSIGNED') === 'No trade assigned',
  'the absence is NAMED, never left blank');
ok(M.tradeLabel('') === M.NO_TRADE_LABEL && M.tradeLabel(null) === M.NO_TRADE_LABEL,
  'every empty form reads the same way');
ok(M.tradeLabel('Electrical') === 'Electrical', 'and a real trade reads as itself');
ok(!/none/i.test(M.NO_TRADE_LABEL), 'it does not say "none" - he has no trade YET');

// The boundary: it must not travel into a crew row at all.
const builtSentinel = M.buildCrewsFromRoster(
  [{ worker_id: 'w1', name: 'A', company: 'Kestrel Electric', trade: 'UNASSIGNED' }], [],
);
ok(builtSentinel.length === 1 && builtSentinel[0].trade === '',
  'buildCrewsFromRoster strips it, so it never reaches data.activities[].trade');
ok(M.buildCrewsFromRoster(
  [{ worker_id: 'w2', name: 'B', company: 'X', trade: 'Electrical' }], [],
)[0].trade === 'Electrical', 'and a real trade still survives the boundary');

console.log(`
${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
