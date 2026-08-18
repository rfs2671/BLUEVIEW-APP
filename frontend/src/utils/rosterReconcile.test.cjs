/**
 * The roster re-check, executed.
 *
 * PRODUCTION CASE: project 6a5f63bc147407d3261df2c7, 2026-08-13. Five men
 * checked in. The pre-shift sheet and the toolbox roster both listed SIX — the
 * sixth being "Segundo pilamunga", who has no check-in that day and was
 * refused at the gate. A man on a signed sign-in sheet who never checked in is
 * a false record.
 *
 * The four rules, and the one that makes them safe: an edit is detected by
 * comparing a field against what the GATE said (gate_snapshot), so no "edited"
 * flag has to be maintained and a reload cannot lose it.
 *
 * Run:  node src/utils/rosterReconcile.test.cjs
 */
const fs = require('fs');
const path = require('path');

const SRC = fs.readFileSync(path.join(__dirname, 'rosterReconcile.js'), 'utf8');
// eslint-disable-next-line no-new-func
const M = new Function(`${SRC
  .replace(/^export default [\s\S]*$/m, '')
  .replace(/^export (function|const) /gm, '$1 ')}
  return { rowKey, withGateSnapshot, isCpEdited, reconcileRoster };`)();

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const FIELDS = ['name', 'company', 'osha_number'];
const ANSWERS = ['had_injury', 'inspected_ppe', 'signed'];

const auto = (over = {}) => M.withGateSnapshot({
  worker_id: 'w1', name: 'WILMER CARRILLO', company: 'AAZ',
  osha_number: '4YU1RY8KKM', had_injury: null, inspected_ppe: null,
  signed: false, auto_filled: true, ...over,
}, FIELDS);

console.log('\n-- the snapshot is what proves an edit --');
ok(auto().gate_sourced === true, 'a built row is marked gate_sourced');
ok(auto().gate_snapshot.company === 'AAZ', 'and records what the gate said');
ok(M.isCpEdited(auto(), FIELDS, ANSWERS) === false, 'an untouched auto row is not an edit');
ok(M.isCpEdited({ ...auto(), company: 'Vanguard' }, FIELDS, ANSWERS) === true,
  'changing a field the gate supplied IS an edit');
ok(M.isCpEdited({ ...auto(), had_injury: 'no' }, FIELDS, ANSWERS) === true,
  'answering injury is an edit — the gate never supplies it');
ok(M.isCpEdited({ ...auto(), signed: true }, FIELDS, ANSWERS) === true,
  'and so is ticking present');
ok(M.isCpEdited({ ...auto(), had_injury: null }, FIELDS, ANSWERS) === false,
  'a null answer is not an edit');
ok(M.isCpEdited({ worker_id: 'x', name: 'Hand Added' }, FIELDS, ANSWERS) === true,
  'a row with NO provenance is treated as the CP\'s — the safe default');

console.log('\n-- the four rules --');

const FRESH = [auto(), auto({ worker_id: 'w2', name: 'Luis Alvarez', osha_number: 'B2' })];

// DROP: the production sixth man. Auto, no check-in today, untouched.
const segundo = auto({ worker_id: 'w9', name: 'Segundo pilamunga', osha_number: '' });
let r = M.reconcileRoster({ stored: [auto(), segundo], fresh: FRESH, fields: FIELDS, answers: ANSWERS });
ok(r.rows.some((x) => x.name === 'Segundo pilamunga') === false,
  'DROP: an auto row with no check-in today and no edit is gone');
ok(r.dropped === 1, 'and the drop is counted');

// KEEP a hand-added row.
const handAdded = { worker_id: null, name: 'Segundo pilamunga', company: 'AAZ', auto_filled: false };
r = M.reconcileRoster({ stored: [handAdded], fresh: FRESH, fields: FIELDS, answers: ANSWERS });
ok(r.rows.some((x) => x.name === 'Segundo pilamunga'),
  'KEEP: a hand-added row survives — the CP asserting a man was present is his call');

// KEEP an edited auto row even with no check-in today.
const edited = auto({ worker_id: 'w9', name: 'Segundo pilamunga', had_injury: 'no' });
r = M.reconcileRoster({ stored: [edited], fresh: FRESH, fields: FIELDS, answers: ANSWERS });
ok(r.rows.length === 3 && r.rows.some((x) => x.name === 'Segundo pilamunga'),
  'KEEP: an auto row the CP edited survives — the comparison proves it');

// ADD anyone who checked in and is not listed.
r = M.reconcileRoster({ stored: [auto()], fresh: FRESH, fields: FIELDS, answers: ANSWERS });
ok(r.added === 1 && r.rows.some((x) => x.name === 'Luis Alvarez'),
  'ADD: a man who checked in and was not on the list is added');
ok(r.rows.length === 2 && r.rows.filter((x) => x.name === 'WILMER CARRILLO').length === 1,
  'and nobody is duplicated');

console.log('\n-- nothing is re-hydrated --');
const blank = auto({ name: 'WILMER CARRILLO', company: 'AAZ' });
delete blank.osha_number;                       // an old row missing a column
r = M.reconcileRoster({ stored: [blank], fresh: FRESH, fields: FIELDS, answers: ANSWERS });
ok(r.rows[0].osha_number === undefined,
  'a kept row is returned EXACTLY as stored — blank stays blank, by ruling');

console.log('\n-- old payloads still load --');
const legacy = [
  { worker_id: 'w1', name: 'WILMER CARRILLO', company: 'AAZ' },
  { worker_id: null, name: 'Someone Else', company: '' },
];
r = M.reconcileRoster({ stored: legacy, fresh: FRESH, fields: FIELDS, answers: ANSWERS });
ok(r.dropped === 0, 'a payload with NO markers loses nobody');
ok(r.rows.length === 3, 'and today\'s missing man is still added alongside');
ok(r.rows[0].gate_sourced === undefined,
  'the old rows are returned untouched — no marker is invented for them');

console.log('\n-- offline and malformed --');
ok(M.reconcileRoster({ stored: [auto()], fresh: [], fields: FIELDS, answers: ANSWERS }).dropped === 1,
  'an EMPTY check-in list does drop an untouched auto row (nobody checked in)');
ok(M.reconcileRoster({ stored: null, fresh: null, fields: FIELDS }).rows.length === 0,
  'null in, empty out — no crash');
ok(M.rowKey({ worker_id: 'w1' }) === 'id:w1', 'matched by id when there is one');
ok(M.rowKey({ name: '  Wilmer   Carrillo ' }) === 'name:wilmer carrillo',
  'and by normalised name when there is not');
ok(M.rowKey({}) === '', 'a row with neither has no key');

// Two men sharing a name must not collapse when they carry ids — osha_log had
// to allow exactly that.
const twins = [auto({ worker_id: 'a', name: 'Luis Alvarez' }),
  auto({ worker_id: 'b', name: 'Luis Alvarez' })];
r = M.reconcileRoster({ stored: twins, fresh: twins, fields: FIELDS, answers: ANSWERS });
ok(r.rows.length === 2, 'two men sharing a name stay two rows');

console.log('\n-- both screens are actually wired --');
const APP = path.join(__dirname, '..', '..', 'app', 'logbooks');
for (const [file, helper, stored] of [
  ['preshift_signin.jsx', '_reconcileWorkers', 'd.workers'],
]) {
  const s2 = fs.readFileSync(path.join(APP, file), 'utf8');
  ok(/from '\.\.\/\.\.\/src\/utils\/rosterReconcile'/.test(s2),
    file + ': imports the module');
  ok(s2.includes('withGateSnapshot({'), file + ': gate-stamps the rows it builds');
  ok(new RegExp('const ' + helper + ' = ').test(s2), file + ': ' + helper + ' is defined');
  ok((s2.match(new RegExp('\\b' + helper + '\\(', 'g')) || []).length === 2,
    file + ': ' + helper + ' is called on BOTH load paths');
  ok(!s2.includes('setWorkers(' + stored + ');') && !s2.includes('setAttendees(' + stored + ');'),
    file + ': the stored payload is never trusted unchecked');
  const draftBlock = s2.slice(0, s2.indexOf('setLoading(false);'));
  ok(draftBlock.includes('getCheckinsForDate(projectId, date)'),
    file + ': the draft path fetches check-ins before returning');

  // AN EMPTY STORED ROSTER MUST STILL REBUILD — device round 4, findings
  // 6/17/3, one mechanism. The `length > 0` guard came in with THIS change and
  // was the bug: it only re-checked when there was something stored, so an
  // empty roster returned without fetching anything and could never rebuild.
  // This form trips it more easily than toolbox_talk, because the draft branch
  // is entered on `(d.workers?.length || d.company)` and `company` is prefilled
  // from the project — an empty roster with a prefilled company was enough.
  // A morning sign-in sheet listing nobody while men are at the gate.
  ok(draftBlock.includes('buildWorkerList(_fresh)'),
    file + ': an EMPTY stored roster is BUILT from today check-ins, not left empty');
  ok(draftBlock.indexOf('getCheckinsForDate') < draftBlock.indexOf('_stored.length > 0'),
    file + ': and the fetch happens BEFORE the empty/non-empty decision');
  ok(!draftBlock.includes('if (d.workers && d.workers.length > 0) {'),
    file + ': the fetch is no longer conditional on there being something stored');
  // The rebuild must not become a new way to LOSE men: offline the fetch fails
  // and there is nothing to build from, so the stored (empty) roster stands.
  ok(draftBlock.includes('} else if (Array.isArray(_fresh)) {'),
    file + ': offline builds nothing rather than clearing the screen');
}

// TOOLBOX_TALK MOVED. The port put its reconcile in src/utils/toolboxTalkModel
// as `reconcileAttendees`, so the screen no longer defines a local helper. Same
// guarantee, one address further in — re-pointed rather than dropped, and
// toolboxTalkModel.test.cjs asserts the behaviour end to end.
{
  const s2 = fs.readFileSync(path.join(APP, 'toolbox_talk.jsx'), 'utf8');
  const model = fs.readFileSync(path.join(__dirname, 'toolboxTalkModel.js'), 'utf8');
  // ORDER- AND LENGTH-INDEPENDENT. A fixed character window broke the moment a
  // sixth name joined the import; what is being asserted is MEMBERSHIP of that
  // block, not where in it the name sits.
  const tbImport = (s2.match(/import \{([\s\S]*?)\} from '\.\.\/\.\.\/src\/utils\/toolboxTalkModel'/) || [])[1] || '';
  ok(tbImport.split(',').map((x) => x.trim()).includes('reconcileAttendees'),
    'toolbox_talk.jsx: imports reconcileAttendees from its model');
  ok(model.includes('withGateSnapshot({'),
    'toolboxTalkModel: gate-stamps the rows it builds');
  ok((s2.match(/reconcileAttendees\(/g) || []).length === 2,
    'toolbox_talk.jsx: reconciles on BOTH load paths');
  ok(!s2.includes('setAttendees(d.attendees);')
    && !s2.includes('setAttendees(draft.data.attendees);'),
    'toolbox_talk.jsx: the stored payload is never trusted unchecked');
  const draftBlock = s2.slice(0, s2.indexOf('setLoading(false);'));
  ok(draftBlock.includes('getCheckinsForDate(projectId, date)'),
    'toolbox_talk.jsx: the draft path fetches check-ins before returning');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
