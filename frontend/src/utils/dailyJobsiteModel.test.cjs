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
           isUnassignedWorkerRow, workRows, crewsWithoutWork,
           observationComplete, incompleteObservations, formatLogDate,
           formatCheckInTime, stepComplete,
           isUnassignedTrade, cleanTrade, tradeLabel, NO_TRADE_LABEL,
           INSPECTION_PASS, INSPECTION_FAIL, EMPTY_INSPECTION, inspectionRow,
           inspectionComplete, incompleteInspections,
           composeChipBands, CHIP_SLOTS, OTHER_CHIP_ID };
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
    work_description: 'formwork', work_locations: 'Floor 3' };
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
ok(!M.stepComplete(2, { activities: [{ work_description: 'formwork' }] }),
  'step 2 is STILL incomplete with work but no location — the pip and the Next '
  + 'gate ask for the same pair');
ok(M.stepComplete(2, { activities: [{ work_description: 'formwork', work_locations: 'Floor 3' }] }),
  'step 2 completes when every crew has an activity AND a location');
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

// ═════════════════════════════════════════════════════════════════════════════
// DEVICE ROUND 4, FINDING 11 — four slots per crew, composed
// ═════════════════════════════════════════════════════════════════════════════
console.log('\n-- four slots, composed --');

// The card was offering the whole catalogue: 86 chips on a cold start, 78 with
// a prior. Four cannot be a top-four slice of one band, because the bands
// answer different questions.
const chip = (id, band, label) => ({ id, band, label: label || id });
const SUGG = (n) => Array.from({ length: n }, (_, i) => chip(`s${i}`, 'suggested'));
const ALW = ['site_cleanup', 'material_delivery', 'rain_no_work']
  .map((i) => chip(i, 'always_available'));
const CAT = (n) => Array.from({ length: n }, (_, i) => chip(`c${i}`, 'catalog'));

// ── with a prior: four, in graph order ──────────────────────────────────────
{
  const r = M.composeChipBands({
    chips: [...SUGG(8), ...ALW, ...CAT(50)], priorDate: '2026-08-13',
  });
  ok(r.primary.length === M.CHIP_SLOTS, `a prior gives exactly ${M.CHIP_SLOTS} (got ${r.primary.length})`);
  ok(r.primary.map((c) => c.id).join() === 's0,s1,s2,s3',
    'and they are the TOP four in the ranker order, not a resort');
  ok(r.basis === 'sequence', 'ranked off yesterday, and it says so');
}

// ── COLD START: FOUR, like everything else ──────────────────────────────────
//
// THIS ASSERTED FIVE, and the ruling behind it was made when the band was
// ranked and the fifth chip was a real suggestion. A cold start is not that: it
// is the project-start set in declaration order, encoding nothing about
// yesterday, so there is no ranking to respect. The operator asked for four per
// contractor and reported "still too many" across three rounds.
{
  const r = M.composeChipBands({ chips: [...SUGG(5), ...ALW, ...CAT(60)], priorDate: null });
  ok(r.primary.length === M.CHIP_SLOTS,
    `FOUR on a cold start too (got ${r.primary.length}) — the band is four slots, `
    + 'and the cold-start set is not a ranking that a cap would damage');
  ok(r.basis === 'cold_start',
    'and the basis STILL distinguishes it from a real prior — the card must not '
    + 'imply a ranking that does not exist just because the count now matches');
  ok(r.rest.some((c) => c.id === 's4'),
    'the fifth is FOLDED, not dropped — the expander still reaches it');
}
// And the cap holds however many the ranker returns.
{
  for (const n of [1, 4, 5, 9]) {
    const r = M.composeChipBands({ chips: [...SUGG(n), ...ALW], priorDate: null });
    ok(r.primary.length === Math.min(n, M.CHIP_SLOTS),
      `cold start with ${n} suggested yields ${Math.min(n, M.CHIP_SLOTS)}`);
  }
}

// ── ALWAYS-AVAILABLE never competes for a slot ──────────────────────────────
{
  const r = M.composeChipBands({ chips: [...SUGG(8), ...ALW, ...CAT(20)], priorDate: '2026-08-13' });
  ok(r.always.length === 3,
    'always-available is returned in FULL — what any crew can log on any day');
  ok(r.primary.every((c) => c.band !== 'always_available'),
    'and never occupies one of the four');
  ok(r.rest.every((c) => c.band !== 'always_available'),
    'nor is it folded behind the expander — burying "rain / no work" on a rain day is worse than a longer list');
  ok(r.always.some((c) => c.id === 'rain_no_work'), 'rain / no work stays on the card');
}

// ── a trade with NO sequenced successors says so ────────────────────────────
{
  const r = M.composeChipBands({
    chips: [...ALW, ...CAT(14)], resolvedTrades: ['Carpentry (rough)'],
    priorDate: '2026-08-13',
  });
  ok(r.primary.length === M.CHIP_SLOTS && r.primary.every((c) => c.band === 'catalog'),
    'a trade whose activities carry no graph edges still gets four');
  ok(r.basis === 'trade',
    'but the basis is TRADE — declaration order encodes nothing about yesterday, and the card must not imply it did');
  ok(r.basis !== 'sequence', 'it never claims a ranking it does not have');
}

// ── an unresolved trade is not narrowed, and does not inline the catalogue ──
{
  const all = [...SUGG(8), ...ALW, ...CAT(60)];
  const r = M.composeChipBands({ chips: all, resolvedTrades: [], priorDate: '2026-08-13' });
  ok(r.primary.length === M.CHIP_SLOTS && r.basis === 'sequence',
    'an UNMAPPED trade still gets four sequenced chips — the slot cap makes an alias miss survivable');
  ok(r.primary.every((c) => c.band === 'suggested'),
    'and the catalogue is never promoted for a crew whose trade did not resolve');
}

// ── nothing is hidden, only folded ──────────────────────────────────────────
{
  const r = M.composeChipBands({ chips: [...SUGG(8), ...ALW, ...CAT(50)], priorDate: '2026-08-13' });
  const shown = new Set([...r.primary, ...r.always].map((c) => c.id));
  const reachable = new Set([...shown, ...r.rest.map((c) => c.id)]);
  ok(r.rest.length === 54,
    `everything else is still reachable through the expander (${r.rest.length})`);
  ok([...SUGG(8), ...CAT(50)].every((c) => reachable.has(c.id)),
    'EVERY chip is reachable — a cap on what is offered first is not a cap on what can be logged');
  ok(r.hidden === r.rest.length, 'and the count of what is folded is reported, not silent');
}

// ── the expander shows ALL activities, not the rest of this trade's ─────────
{
  const mine = [...ALW, ...CAT(14)];
  const everything = [...SUGG(8), ...ALW, ...CAT(60)];
  const r = M.composeChipBands({
    chips: mine, allChips: everything, resolvedTrades: ['Carpentry (rough)'],
    priorDate: '2026-08-13',
  });
  ok(r.rest.length > 14,
    '"All activities" is drawn from the UNFILTERED list, so it means all activities');
}

// ── "Other" is never in any band ────────────────────────────────────────────
{
  const withOther = [...SUGG(8), ...ALW, chip(M.OTHER_CHIP_ID, 'other')];
  const r = M.composeChipBands({ chips: withOther, priorDate: '2026-08-13' });
  ok(![...r.primary, ...r.always, ...r.rest].some((c) => c.id === M.OTHER_CHIP_ID),
    'Other is never in a band — the screen renders it itself, always last and always visible');
}

// ── it never throws, whatever it is handed ──────────────────────────────────
for (const junk of [undefined, null, {}, { chips: null }, { chips: 'x' },
  { chips: [null, undefined] }]) {
  const r = M.composeChipBands(junk || {});
  ok(Array.isArray(r.primary) && Array.isArray(r.always) && Array.isArray(r.rest),
    `a well-formed result for ${JSON.stringify(junk)} — chips must never stop a CP logging a day`);
}

console.log('\n-- a crew on site whose work nobody described --');
{
  // stepComplete(2) has held this rule the whole time and only MARKED with it,
  // so a filed daily log could name four subs and say what none of them did.
  // Every complete row carries BOTH fields — the rule is activity AND location.
  const crews = [
    { company: 'Kestrel Electric', trade: 'Electrical', work_description: 'branch rough-in', work_locations: 'Floor 3' },
    { company: 'Air Star Mechanical', trade: 'HVAC', work_description: '', work_locations: 'Floor 2' },
    { company: 'Vanguard Concrete', trade: 'Concrete', work_description: '   ', work_locations: 'Floor 1' },
  ];
  const bare = M.crewsWithoutWork(crews);
  ok(bare.length === 2, 'both crews with nothing described are reported');
  ok(bare[0].crew === 'Air Star Mechanical' && bare[0].trade === 'HVAC',
    'carrying the company and trade, so he knows it is the right card');
  ok(bare[1].crew === 'Vanguard Concrete',
    'and whitespace is not a description');
  ok(M.crewsWithoutWork([crews[0]]).length === 0,
    'a described crew is not reported and the CP is never stopped');
  ok(M.crewsWithoutWork(null).length === 0, 'malformed input does not throw');
  // POSITION AND TOTAL — "Crew 3 of 5", not a bare count. A count makes him
  // hunt down the list comparing what he sees against a number.
  ok(bare[0].row === 2 && bare[0].total === 3,
    'each gap carries WHICH crew and HOW MANY there are');
  ok(bare[1].row === 3 && bare[1].total === 3, 'and the positions are distinct');
}
{
  // A LOCATION IS REQUIRED TOO. An activity with nowhere attached is half a
  // record: the §3301.2 table has a Location column and the photo caption is
  // built from it.
  const rows = [
    { company: 'A', work_description: 'formwork', work_locations: 'Floor 3' },
    { company: 'B', work_description: 'formwork', work_locations: '' },
    { company: 'C', work_description: '', work_locations: 'Floor 2' },
    { company: 'D', work_description: '', work_locations: '' },
  ];
  const gaps = M.crewsWithoutWork(rows);
  ok(gaps.length === 3, 'a crew missing EITHER field is reported');
  eq(gaps.find((g) => g.crew === 'B').missing, ['location'],
    'the one missing only a location says so');
  eq(gaps.find((g) => g.crew === 'C').missing, ['activity'],
    'and the one missing only an activity says so');
  eq(gaps.find((g) => g.crew === 'D').missing, ['activity', 'location'],
    'and a crew missing both names both — one trip, not two');
  ok(!gaps.some((g) => g.crew === 'A'), 'a complete crew is never reported');
}
{
  // The POSITION is within workRows, which is the list step 2 renders. An
  // unassigned-worker row has no card, so counting it would point at a crew
  // that is not on screen.
  const rows = [
    { gate_sourced: true, company: '', work_description: '', work_locations: '' },
    { company: 'Kestrel', work_description: '', work_locations: '' },
  ];
  const gaps = M.crewsWithoutWork(rows);
  ok(gaps.length === 1 && gaps[0].row === 1 && gaps[0].total === 1,
    'the unassigned row is neither reported nor counted in the position');
}
{
  // AN UNASSIGNED WORKER IS NOT A CREW. He gets no activity card, so asking
  // him for a work description would block every day on which one man tapped
  // in with no company assigned.
  const rows = [
    { gate_sourced: true, company: '', work_description: '', work_locations: '' },
    { company: 'Kestrel Electric', work_description: 'branch rough-in', work_locations: 'Floor 3' },
  ];
  ok(M.crewsWithoutWork(rows).length === 0,
    'the unassigned worker row is not asked for work');
  ok(M.crewsWithoutWork(rows).length === M.workRows(rows)
    .filter((a) => !String(a.work_description || '').trim()
      || !String(a.work_locations || '').trim()).length,
    'and it inherits workRows rather than re-deriving which rows count');
}
{
  // The gate and the step pip must agree, or he is stopped by something the
  // screen showed as complete.
  // THE PIP AND THE GATE READ ONE SOURCE. Both take `activities` and both go
  // through workRows, so they cannot disagree by construction — asserted both
  // ways, because a CP stopped by something the screen showed as complete
  // learns to distrust the screen.
  const bare = [{ company: 'Kestrel Electric', work_description: '', work_locations: 'Floor 3' }];
  ok(M.stepComplete(2, { activities: bare }) === false
     && M.crewsWithoutWork(bare).length === 1,
    'the pip and the gate answer the same question');
  const done = [{ company: 'Kestrel Electric', work_description: 'rough-in', work_locations: 'Floor 3' }];
  ok(M.stepComplete(2, { activities: done }) === true
     && M.crewsWithoutWork(done).length === 0,
    'and they agree when it is done too');
  // AND THEY AGREE ON THE LOCATION HALF TOO. stepComplete(2) asked only for the
  // description while the gate also wanted a location, so a crew with work and
  // no floor made the pip read COMPLETE and the Next button sit dead — a CP
  // stopped by something the screen has just told him is finished.
  const noLoc = [{ company: 'Kestrel Electric', work_description: 'rough-in', work_locations: '' }];
  ok(M.stepComplete(2, { activities: noLoc }) === false
     && M.crewsWithoutWork(noLoc).length === 1,
    'a missing LOCATION marks the step incomplete AND stops Next — one answer');
  const noAct = [{ company: 'Kestrel Electric', work_description: '', work_locations: 'Floor 3' }];
  ok(M.stepComplete(2, { activities: noAct }) === false
     && M.crewsWithoutWork(noAct).length === 1,
    'and so does a missing activity — neither field belongs to the pip alone');
}
{
  const screen = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', 'logbooks', 'daily_jobsite.jsx'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  const at = screen.indexOf('crewsWithoutWork(activitiesRef.current');
  ok(at > screen.indexOf('const handleSubmitAndSign'),
    'the gate runs inside handleSubmitAndSign');
  ok(at < screen.indexOf("persistAndPush('submitted')"),
    'and BEFORE anything is written');
  // `goNext`, not `onStepChange`. This screen has no function by that name, so
  // the old form matched -1 and the `step === -1 ||` escape hatch made the
  // assertion pass against ANY code — a mutation that put the gate on the step
  // path walked straight through it. Named after what this screen actually
  // calls, with no escape hatch.
  // GATING NEXT ON STEP 2 — the documented exception, same as toolbox step 1.
  // This asserted the opposite until the ruling changed: a crew row with no
  // activity and no location makes the whole log unfilable, and every field is
  // known the moment the card is on screen. Being stopped at step 2 beats
  // discovering it at step 5 with four steps behind him.
  ok(/nextDisabled=\{step === 2 && crewGaps\.length > 0\}/.test(screen),
    'Next is disabled on step 2 while a crew is incomplete');
  ok(/nextHint=\{crewGaps\.length > 0 \? crewGapSentence\(crewGaps\) : ''\}/.test(screen),
    'and it says WHICH crew — a dead button with no sentence is where a CP stops');
  ok(/nextDisabled=\{step === 2/.test(screen) && !/nextDisabled=\{true\}/.test(screen),
    'and only on step 2 — the mark-never-gate rule stands everywhere else');
  // ── THE DAY'S DESCRIPTION, GATED AT STEP 5 ───────────────────────────────
  //
  // The report printed "Description: — Not recorded" on filed logs. Nothing was
  // losing the field — the payload carries it and both renderers read the right
  // key — it was empty because the auto-draft only lands once he REACHES the
  // review step. That rule is correct and stays: he is attesting to that
  // sentence, so the app may propose it and may not file words he never read.
  // The fix is that he cannot SIGN while it is empty.
  ok(/const descriptionEmpty = String\(generalDescription \|\| ''\)\.trim\(\) === '';/
    .test(screen), 'the empty state is computed once');
  ok(/submitDisabled=\{!isAffirmedSignature\(cpSignature\) \|\| descriptionEmpty\}/
    .test(screen), 'and the sign control is unavailable while it is empty');
  ok(/descriptionEmpty \? t\('descriptionRequiredHint'\) : ''/.test(screen),
    'with a hint that says so — a dead button with no sentence is where a CP stops');
  {
    // THE SIGNATURE REASON COMES FIRST. A CP with no affirmed credential cannot
    // fix the description into a filed log either, so leading with the
    // description would send him to the wrong repair.
    const hint = screen.slice(screen.indexOf('submitHint={affirmationHintKey'));
    ok(hint.indexOf('affirmationHintKey') < hint.indexOf('descriptionEmpty'),
      'and the signature reason is offered before the description one');
  }
  // THE AUTO-DRAFT IS UNCHANGED — drafting sooner would file a sentence nobody
  // had read, which is worse than a blank.
  ok(/if \(step !== TOTAL_STEPS\) return;/.test(screen),
    'the draft still lands only once he is looking at the review step');
  ok(/if \(descriptionTouched\) return;/.test(screen),
    'and never overwrites what he has typed');
  ok(screen.indexOf("t('descriptionRequiredTitle')")
     > screen.indexOf('const handleSubmitAndSign'),
    'the handler keeps a backstop for state that moved under the press');

  // The submit check stays as a BACKSTOP: the state can move under the press.
  ok(screen.indexOf('crewsWithoutWork(activitiesRef.current')
     > screen.indexOf('const handleSubmitAndSign'),
    'and the submit backstop survives, for a roster refresh mid-signature');
  ok(/setStep\(2\);/.test(screen.slice(at - 200, at + 400)),
    'it sends him back to the step that holds the fix');
}

console.log(`
${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
