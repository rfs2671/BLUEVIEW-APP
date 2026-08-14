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
  ['toolbox_talk.jsx', '_reconcileAttendees', 'd.attendees'],
]) {
  const s2 = fs.readFileSync(path.join(APP, file), 'utf8');
  ok(/from '\.\.\/\.\.\/src\/utils\/rosterReconcile'/.test(s2),
    file + ': imports the module');
  ok(s2.includes('withGateSnapshot({'), file + ': gate-stamps the rows it builds');
  // Defined once, CALLED TWICE — the draft path and the server-copy path.
  // The draft path is the one that used to return early, so two is the number
  // that matters: one call would mean the early return is still unchecked.
  ok(new RegExp('const ' + helper + ' = ').test(s2), file + ': ' + helper + ' is defined');
  ok((s2.match(new RegExp('\\b' + helper + '\\(', 'g')) || []).length === 2,
    file + ': ' + helper + ' is called on BOTH load paths');
  ok(!s2.includes('setWorkers(' + stored + ');') && !s2.includes('setAttendees(' + stored + ');'),
    file + ': the stored payload is never trusted unchecked');
  // The draft path must FETCH before it can reconcile — that early return was
  // the whole defect.
  const draftBlock = s2.slice(0, s2.indexOf('setLoading(false);'));
  ok(draftBlock.includes('getCheckinsForDate(projectId, date)'),
    file + ': the draft path fetches check-ins before returning');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
