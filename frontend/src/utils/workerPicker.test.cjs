/**
 * + Add Row PICKS A MAN. IT DOES NOT TAKE A TYPED NAME BY DEFAULT.
 *
 * One man appeared twice on one filed compliance report — "Jose Castaneda"
 * typed by a CP on the pre-shift roster beside "Jose Julio Castaneda" from his
 * orientation. Nothing downstream can reconcile that: every normaliser in the
 * tree splits those two, and every relaxation that would unite them is
 * asserted AGAINST by a regression guard written after a production failure in
 * that direction (backend/tests/test_report_six_defects.py:356-357). Merging
 * them deletes a man from the record of who was on site, and a deletion is
 * invisible where a duplicate is not.
 *
 * So the fix is upstream, and these are its two halves:
 *
 *   1. the default path is a PICK from the project's roster, and the record
 *      supplies name, company, OSHA number and worker_id;
 *   2. duplicates are SHOWN — the CP is the only person who knows two records
 *      are one man, and a picker that hid one would perform in the UI exactly
 *      the merge the normalisers are forbidden to perform.
 *
 * AND MANUAL ENTRY SURVIVES, one tap further in. Nothing blocks a worker: a
 * man can be on site who has never checked in here. It carries NO flag on the
 * row, deliberately — `workers` is posted verbatim as `data.workers[]`, so a
 * flag would be a field on a filed document that the 329 rows already filed
 * could never carry, leaving an absent flag meaning either "gate-verified" or
 * "filed before the field existed". That is the absent-versus-empty shape and
 * it was declined rather than introduced.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const PICKER = path.join(ROOT, 'src', 'components', 'WorkerPicker.jsx');
const SCREEN = path.join(ROOT, 'app', 'logbooks', 'preshift_signin.jsx');

let failures = 0;
function ok(name, cond, detail) {
  if (cond) { console.log(`  ok  ${name}`); return; }
  failures += 1;
  console.error(`  FAIL ${name}${detail ? ` — ${detail}` : ''}`);
}

function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

// ── filterRoster, EXECUTED ──────────────────────────────────────────────────
// Lifted and run rather than grepped: the ruling is about what the CP is shown,
// which is behaviour, not spelling.
const pickerSrc = fs.readFileSync(PICKER, 'utf8');
const fnSrc = pickerSrc.slice(
  pickerSrc.indexOf('export function filterRoster'),
  pickerSrc.indexOf('export default function WorkerPicker'),
);
// NO TRANSPILER. `filterRoster` is plain ES with no JSX, so it runs as written
// once the `export` keyword is dropped. The two suite files that DO transpile
// pull in @babel/core, a declared dependency; @babel/preset-env is NOT
// installed, and a test that needs an absent preset fails on its harness
// rather than on its subject.
const mod = { exports: {} };
const EXPORT_TAIL = ';\nmodule.exports = { filterRoster };';
// eslint-disable-next-line no-new-func
new Function('module', 'exports',
  fnSrc.replace('export function', 'function') + EXPORT_TAIL)(mod, mod.exports);
const { filterRoster } = mod.exports;

const ROSTER = [
  { worker_id: 'w1', name: 'Wilmer Carrillo', company: 'AAZ' },
  { worker_id: 'w2', name: 'Wilmer J Carrillo', company: 'AAZ' },
  { worker_id: 'w3', name: 'Jose Castaneda', company: 'Arkon' },
  { worker_id: 'w4', name: 'Jose Julio Castaneda', company: 'Arkon Builders' },
  { worker_id: 'w5', name: 'Segundo Pilamunga', company: 'AAZ' },
];

ok('an empty query shows everyone', filterRoster(ROSTER, '').length === 5);
ok('it matches on name', filterRoster(ROSTER, 'segundo').length === 1);
ok('it matches on company', filterRoster(ROSTER, 'arkon').length === 2);
ok('it is case-insensitive', filterRoster(ROSTER, 'WILMER').length === 2);

// THE RULING, ASSERTED DIRECTLY.
ok('BOTH spellings of one man survive a query matching both',
  filterRoster(ROSTER, 'carrillo').length === 2,
  'the picker collapsed a duplicate — that is the merge the guards forbid');
ok('and both Castaneda records survive too',
  filterRoster(ROSTER, 'castaneda').length === 2);

// The other direction: it must actually filter, or every assertion above is
// satisfied by a function that returns its input.
ok('a query that matches nobody returns nothing',
  filterRoster(ROSTER, 'zzzz').length === 0);
ok('and it is not just returning the input array',
  filterRoster(ROSTER, 'segundo')[0].name === 'Segundo Pilamunga');
ok('a null roster does not throw', filterRoster(null, 'x').length === 0);

// ── The screen's wiring ─────────────────────────────────────────────────────
const screen = stripComments(fs.readFileSync(SCREEN, 'utf8'));

ok('+ Add Row no longer pushes a blank row straight onto the roster',
  !/const addRow = \(\) => \{\s*setWorkers/.test(screen),
  'addRow still appends EMPTY_WORKER() with no pick in between');
ok('+ Add Row opens the picker',
  /const addRow = \(\) => setPickerOpen\(true\)/.test(screen));
ok('the picker is rendered', /<WorkerPicker/.test(screen));
ok('and it is imported', /from '\.\.\/\.\.\/src\/components\/WorkerPicker'/.test(screen));

ok('a picked man carries his worker_id onto the row',
  /addPickedWorker[\s\S]{0,600}worker_id: row\.worker_id/.test(screen),
  'without it the row is a string that resembles a man, not a reference to one');
ok('and his company comes from the record',
  /addPickedWorker[\s\S]{0,600}company: row\.company/.test(screen));

// NOTHING BLOCKS A WORKER. The standing rule, and the reason manual entry is
// moved rather than removed.
ok('manual entry still exists', /const addManualRow = /.test(screen));
ok('manual entry still appends a blank row',
  /addManualRow[\s\S]{0,300}EMPTY_WORKER\(\)/.test(screen));
ok('and it is reachable from the picker',
  /onManual=\{addManualRow\}/.test(screen));

// NO FLAG ON THE ROW, per ruling. Asserted as an absence, anchored to the
// construct rather than to a bare word.
const picked = screen.slice(screen.indexOf('const addPickedWorker'),
  screen.indexOf('const addManualRow'));
for (const banned of ['entered_manually', 'picked_from_roster', 'provenance']) {
  ok(`no ${banned} field is written onto the row`, !picked.includes(banned));
}

// ── The picker's own refusals ───────────────────────────────────────────────
const picker = stripComments(pickerSrc);
ok('a failed roster read is not shown as an empty roster',
  /setFailed\(true\)/.test(picker) && /Could not load/.test(picker),
  'offline would otherwise read as "nobody has ever worked here" and push the '
  + 'CP to type — the exact thing this component exists to prevent');
ok('the endpoint is the project roster',
  /\/api\/projects\/\$\{projectId\}\/roster/.test(picker));

if (failures) {
  console.error(`\nworkerPicker: ${failures} failure(s)`);
  process.exit(1);
}
console.log('\nALL PASS');
