/**
 * THE CP CAN CORRECT A CREW'S HEADCOUNT, AND THE CORRECTION HAS TO SURVIVE.
 *
 * #244 gave him a card that explains why a 0-worker crew is not being asked for
 * work. He could not act on it: there is no headcount edit on that screen.
 *
 * The trap this file exists to hold shut is not the edit control, it is
 * reconcileCrewsWithRoster. It runs on EVERY load and refreshed num_workers
 * from the roster unconditionally, so an edit shipped on its own would have
 * been reverted the next time the CP opened the screen -- a control that
 * appears to work and quietly does not, which is worse than no control.
 *
 * And the gate's own number is RETAINED rather than replaced. If the CP's 4
 * overwrites the gate's 6 and the 6 is gone, the override is unauditable: a
 * signed 3301.2 record could not show that a person changed a turnstile count,
 * or what it had been.
 *
 * The model is EXECUTED, not grepped. Every assertion below runs the shipped
 * reconcile/edit functions against real rows.
 *
 * Run:  node src/utils/crewHeadcountEdit.test.cjs
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

// ── load the real model ────────────────────────────────────────────────────
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
  reconcileCrewsWithRoster, applyHeadcountEdit, isHeadcountOverridden,
  gateHeadcount, headcountSource, hasNoWorkersOnSite, describableRows,
  crewsWithoutWork, stepComplete, buildCrewsFromRoster, headcountDisplay,
  GATE_SOURCE, CP_SOURCE,
} = mod;

// THE EXPORTS THIS FILE IS ABOUT, CHECKED BY NAME BEFORE ANYTHING RUNS.
//
// Destructuring a missing export leaves `undefined`, and the first call site
// threw a raw TypeError -- one stack trace against a tree without the feature,
// instead of the named guarantees that say what is absent. A test that cannot
// report WHICH guarantee is missing is a worse regression signal than no test.
{
  const required = {
    applyHeadcountEdit, isHeadcountOverridden, gateHeadcount, headcountSource,
    headcountDisplay, reconcileCrewsWithRoster,
  };
  let missing = 0;
  for (const [name, fn] of Object.entries(required)) {
    const present = typeof fn === 'function';
    ok(present, `dailyJobsiteModel exports ${name}`);
    if (!present) missing += 1;
  }
  if (missing > 0) {
    console.log(`
  ${passed} passed, ${failed} failed`);
    console.log('  (stopping: the model does not carry the headcount-edit rule)');
    process.exit(1);
  }
}

const gateRow = (over) => ({
  crew_id: 'C1', company: 'Arkon Builders', trade: 'concrete',
  num_workers: '6', gate_num_workers: '6', num_workers_source: GATE_SOURCE,
  gate_sourced: true, worker_ids: ['w1', 'w2'], worker_names: ['A', 'B'],
  check_in_time: '2026-08-27T11:00:00Z', work_description: '', work_locations: '',
  ...over,
});

const freshRow = (over) => ({
  crew_id: 'C1', company: 'Arkon Builders', trade: 'concrete',
  num_workers: '6', gate_num_workers: '6', num_workers_source: GATE_SOURCE,
  gate_sourced: true, worker_ids: ['w1', 'w2'], worker_names: ['A', 'B'],
  check_in_time: '2026-08-27T11:00:00Z',
  ...over,
});

// ═══════════════════════════════════════════════════════════════════════════
// 1. A CP OVERRIDE SURVIVES A RELOAD AND A RECONCILE.
// ═══════════════════════════════════════════════════════════════════════════
{
  const edited = { ...gateRow(), ...applyHeadcountEdit(gateRow(), '4') };
  ok(edited.num_workers === '4', 'an edit sets the printed count');
  ok(headcountSource(edited) === CP_SOURCE, 'an edit marks the source as cp');
  ok(isHeadcountOverridden(edited), 'a cp number on a gate row is an override');

  // The reload: stored rows meet a fresh roster that still says 6.
  const [after] = reconcileCrewsWithRoster([edited], [freshRow()]);
  ok(after.num_workers === '4',
    'THE OVERRIDE SURVIVES the reconcile (roster still says 6)');
  ok(headcountSource(after) === CP_SOURCE,
    'the override keeps its cp marker through the reconcile');

  // And again -- a second load must not erode it.
  const [twice] = reconcileCrewsWithRoster([after], [freshRow()]);
  ok(twice.num_workers === '4', 'it survives a SECOND reconcile');

  // A crew that stops appearing at the gate entirely.
  const [absent] = reconcileCrewsWithRoster([edited], []);
  ok(absent.num_workers === '4',
    'the override stands even when the gate reports the crew absent');
  ok(absent.gate_num_workers === '0',
    'and the gate count for an absent crew is recorded as 0');
}

// ═══════════════════════════════════════════════════════════════════════════
// 2. A GATE ROW WITH NO OVERRIDE STILL TRACKS THE ROSTER.
// ═══════════════════════════════════════════════════════════════════════════
{
  const stored = gateRow({ num_workers: '6', gate_num_workers: '6' });
  const [after] = reconcileCrewsWithRoster([stored], [freshRow({ num_workers: '9' })]);
  ok(after.num_workers === '9', 'an un-overridden gate row follows the roster up');
  ok(after.gate_num_workers === '9', 'and its retained gate count follows too');
  ok(headcountSource(after) === GATE_SOURCE, 'it stays marked as gate-sourced');

  const [gone] = reconcileCrewsWithRoster([stored], []);
  ok(gone.num_workers === '0',
    'a gate crew absent today still drops to 0 (#244 ruling kept)');
  ok(gone.worker_ids.length === 0, 'and its worker identities are cleared');

  // The CP's words are never touched by any of this.
  const worded = gateRow({ work_description: 'Poured slab on 3', work_locations: '3rd floor' });
  const [kept] = reconcileCrewsWithRoster([worded], [freshRow({ num_workers: '9' })]);
  ok(kept.work_description === 'Poured slab on 3' && kept.work_locations === '3rd floor',
    'the reconcile still leaves what the CP wrote alone');

  // A hand-added row is not reconciled at all.
  const hand = { crew_id: 'C2', company: 'Vanguard', trade: 'masonry',
    num_workers: '3', num_workers_source: CP_SOURCE, gate_sourced: false };
  const [handAfter] = reconcileCrewsWithRoster([hand, gateRow()], [freshRow()]);
  ok(handAfter.num_workers === '3', 'a hand-added crew is untouched by the reconcile');
  ok(!isHeadcountOverridden(handAfter),
    'a hand-added crew is NOT an override -- it has nothing to stand over');
}

// ═══════════════════════════════════════════════════════════════════════════
// 3. THE RETAINED GATE COUNT IS ON THE FILED DOCUMENT.
// ═══════════════════════════════════════════════════════════════════════════
{
  const edited = { ...gateRow(), ...applyHeadcountEdit(gateRow(), '4') };
  const [after] = reconcileCrewsWithRoster([edited], [freshRow()]);
  ok(after.gate_num_workers === '6',
    'the gate number is RETAINED beside the override, not replaced');
  ok(gateHeadcount(after) === 6, 'and is readable as a number');

  // buildCrewsFromRoster stamps it from birth, so it is never absent on a
  // gate row the app itself created.
  const built = buildCrewsFromRoster(
    [{ worker_id: 'w1', worker_name: 'A', company: 'Arkon Builders', trade: 'concrete',
      check_in_time: '2026-08-27T11:00:00Z' }],
    [],
  );
  ok(built.length === 1 && built[0].gate_num_workers === '1',
    'a freshly built crew carries the gate count from birth');
  ok(built[0].num_workers_source === GATE_SOURCE,
    'a freshly built crew is marked gate-sourced');

  // The draft body ships activities whole, so these fields reach the server.
  const screen = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', 'logbooks', 'daily_jobsite.jsx'), 'utf8');
  const tree = parser.parse(screen, { sourceType: 'module', plugins: ['jsx'] });
  let shipsActivitiesWhole = false;
  (function walk(n, seen = new Set()) {
    if (!n || typeof n !== 'object' || seen.has(n)) return;
    seen.add(n);
    if (n.type === 'ObjectProperty' && n.key && n.key.name === 'activities'
        && n.value && n.value.type === 'Identifier') shipsActivitiesWhole = true;
    for (const k of Object.keys(n)) {
      const v = n[k];
      if (Array.isArray(v)) v.forEach((c) => walk(c, seen));
      else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v, seen);
    }
  }(tree));
  ok(shipsActivitiesWhole,
    'draftBody ships the activity rows WHOLE, so both fields reach the record');
}

// ═══════════════════════════════════════════════════════════════════════════
// 4. EDITING 0 -> 4 RE-ARMS THE STEP GATE. CORRECT AND INTENDED -- PINNED SO
//    NOBODY "FIXES" IT.
// ═══════════════════════════════════════════════════════════════════════════
{
  const empty = gateRow({ num_workers: '0', gate_num_workers: '0',
    worker_ids: [], worker_names: [] });

  ok(hasNoWorkersOnSite(empty), 'a 0-worker crew reads as nobody on site');
  ok(describableRows([empty]).length === 0,
    'and is NOT asked for work (the #244 ruling)');
  ok(crewsWithoutWork([empty]).length === 0, 'so it does not block Next');
  ok(stepComplete(2, { activities: [empty] }) === false,
    'a day of nothing but an empty crew is still not a completed Step 2');

  const corrected = { ...empty, ...applyHeadcountEdit(empty, '4') };
  ok(!hasNoWorkersOnSite(corrected), 'correcting it to 4 puts men back on site');
  ok(describableRows([corrected]).length === 1,
    'THE ROW RE-ENTERS describableRows -- the log starts asking again');
  ok(crewsWithoutWork([corrected]).length === 1,
    'and Next is DISABLED again until he describes the work. Intended.');

  const described = { ...corrected, work_description: 'Poured slab', work_locations: '3' };
  ok(crewsWithoutWork([described]).length === 0,
    'describing the work clears it, exactly as for any other crew');
}

// ═══════════════════════════════════════════════════════════════════════════
// 5. THE EDIT RULE ITSELF.
// ═══════════════════════════════════════════════════════════════════════════
{
  const g = gateRow();
  ok(applyHeadcountEdit(g, '0').num_workers === '0'
     && applyHeadcountEdit(g, '0').num_workers_source === CP_SOURCE,
    'typing 0 is a real CP assertion, not a blank');

  // CLEARING THE BOX WITHDRAWS THE OVERRIDE rather than asserting an empty
  // count. '' means "nobody counted", and on a crew the turnstile DID count
  // that would be false.
  const overridden = { ...g, ...applyHeadcountEdit(g, '4') };
  const cleared = { ...overridden, ...applyHeadcountEdit(overridden, '') };
  ok(cleared.num_workers === '6',
    'clearing a gate row reverts to the gate count, not to blank');
  ok(!isHeadcountOverridden(cleared), 'and withdraws the override');

  const hand = { company: 'Vanguard', num_workers: '3',
    num_workers_source: CP_SOURCE, gate_sourced: false };
  ok(applyHeadcountEdit(hand, '').num_workers === '',
    'clearing a HAND-ADDED row leaves it blank -- nobody counted is honest there');

  for (const junk of ['abc', '-1', '3.5', '4x', ' ']) {
    ok(Object.keys(applyHeadcountEdit(g, junk)).length === 0
       || applyHeadcountEdit(g, junk).num_workers === '6',
      `a non-numeric entry (${JSON.stringify(junk)}) changes nothing`);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// 6. THE SCREEN WIRES THE RULE, NOT ITS OWN COPY OF IT.
// ═══════════════════════════════════════════════════════════════════════════
{
  const screen = fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', 'logbooks', 'daily_jobsite.jsx'), 'utf8');
  const tree = parser.parse(screen, { sourceType: 'module', plugins: ['jsx'] });

  let usesHelper = false;
  let writesNumWorkersDirectly = false;
  (function walk(n, seen = new Set()) {
    if (!n || typeof n !== 'object' || seen.has(n)) return;
    seen.add(n);
    if (n.type === 'CallExpression' && n.callee.type === 'Identifier'
        && n.callee.name === 'applyHeadcountEdit') usesHelper = true;
    // updateActivity(i, 'num_workers', v) would bypass the rule and leave a row
    // claiming a source it does not have.
    if (n.type === 'CallExpression' && n.callee.type === 'Identifier'
        && n.callee.name === 'updateActivity'
        && n.arguments[1] && n.arguments[1].value === 'num_workers') {
      writesNumWorkersDirectly = true;
    }
    for (const k of Object.keys(n)) {
      const v = n[k];
      if (Array.isArray(v)) v.forEach((c) => walk(c, seen));
      else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v, seen);
    }
  }(tree));

  ok(usesHelper, 'the screen applies the edit through applyHeadcountEdit');
  ok(!writesNumWorkersDirectly,
    'nothing sets num_workers through the generic setter, which would skip the source');
}

console.log(`\n  ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
