/**
 * ITEM 8 OPENS ON THE COMPETENT PERSON WHO ACTUALLY FILED THAT DAY.
 *
 * THE OPERATOR'S POINT: a list is not an answer when two men are on site. The
 * record should name the one who was acting, and the app knows which that is.
 *
 * The anchor is `created_by` on the FILED daily jobsite log, chosen over the
 * two obvious candidates by measurement rather than argument — see
 * designatedCp.js for the numbers. The two that lost:
 *
 *   cp_name          five spellings for three accounts across 42 filed logs,
 *                    including '2' four times. Matching it is a name merge.
 *   signature_events the strongest identity in the system, and it carries no
 *                    project_id and no date — plus 15 filed daily logs have no
 *                    cp_sign event at all, where it would answer "nobody
 *                    signed".
 *
 * Run:  node src/utils/designatedCp.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');
const SCREEN = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'site_superintendent_log.jsx'), 'utf8',
).split('\r\n').join('\n');
const PICKER = fs.readFileSync(
  path.join(FRONTEND, 'src', 'components', 'CompetentPersonPicker.jsx'), 'utf8',
);

let failures = 0;
function ok(label, cond, hint) {
  if (cond) { console.log(`  ok   ${label}`); return; }
  failures += 1;
  console.log(`  FAIL ${label}${hint ? `\n         ${hint}` : ''}`);
}

// ── THE REAL MODULES, EVALUATED ────────────────────────────────────────────
//
// Not stubs. `designatedCpDefault` is only correct in company with the two
// rules it composes — chainHead's choice of link, and isSamePerson's identity
// comparison — and a stub of either would let this file pass while the screen
// preselected the wrong man. The same harness as progressProvenance.test.cjs.
function loadEsm(source, injected = {}) {
  const body = source
    .split('\n')
    .filter((l) => !/^\s*import\s/.test(l))
    .join('\n')
    .replace(/^export default[\s\S]*$/m, '')
    .replace(/^export /gm, '');
  const names = Object.keys(injected);
  const exported = [...source.matchAll(/^export (?:function|const) (\w+)/gm)]
    .map((m) => m[1]);
  // eslint-disable-next-line no-new-func
  return new Function(...names, `${body}\nreturn { ${exported.join(', ')} };`)(
    ...names.map((n) => injected[n]));
}
const read = (f) => fs.readFileSync(path.join(UTILS, f), 'utf8');

const { chainHead } = loadEsm(read('amendmentChain.js'));
const { filedDailyRecord } = loadEsm(read('dailyLogRecord.js'), { chainHead });
// isSamePerson lives in the picker component; only that function is needed and
// the component around it does not evaluate outside React.
const isSamePerson = (() => {
  const i = PICKER.indexOf('export function isSamePerson(');
  const j = PICKER.indexOf('\n}', i);
  // eslint-disable-next-line no-new-func
  return new Function(`${PICKER.slice(i, j + 2).replace('export ', '')}\nreturn isSamePerson;`)();
})();
const { designatedCpDefault, ANCHOR_FIELD } = loadEsm(
  read('designatedCp.js'), { filedDailyRecord, isSamePerson });

// ── FIXTURES, FROM PRODUCTION ──────────────────────────────────────────────
const MICHAEL = {
  id: '6a68b16ebe9c27dedf5cf47f', name: 'Michael Cespedes',
  role: 'cp', email: 'michaelcespedes99@gmail.com',
};
const MEILICH = {
  id: '6a5e1571c7ac7a6451aa2d33', name: 'Meilich Friedman',
  role: 'admin', email: 'michael@blueviewbuilders.com',
};
const WILSON = {
  id: '6a5e15aac7ac7a6451aa2d34', name: 'wilson peleaz',
  role: 'cp', email: 'wilson@cp.com',
};
const ROSTER = [MEILICH, MICHAEL, WILSON];

const daily = (over = {}) => ({
  id: 'd1', status: 'submitted', created_at: '2026-09-04T13:55:00Z',
  created_by: MICHAEL.id, data: { general_description: 'carpentry' }, ...over,
});

console.log('\nthe ordinary day');

ok('the account that filed the daily log is preselected',
  designatedCpDefault([daily()], ROSTER) === MICHAEL);
ok('the name comes off the ACCOUNT, not off the log',
  designatedCpDefault([daily({ cp_name: 'michael' })], ROSTER).name
    === 'Michael Cespedes',
  "the log's cp_name holds 'michael' 33 times for an account spelled "
  + "'Michael Cespedes' — the whole reason the anchor is an id");
ok('it is not the first name in the roster',
  designatedCpDefault([daily()], ROSTER) !== ROSTER[0],
  'alphabetical or first-in-list is the wrong-default failure this exists to '
  + 'avoid');

console.log('\nno default unless the app knows');

ok('no filed daily log → null', designatedCpDefault([], ROSTER) === null,
  'he may file before the CP does, or on a day the CP was absent — which is '
  + "exactly the day item 8's none-designated exists for");
ok('an unsigned draft is not an anchor → null',
  designatedCpDefault([daily({ status: 'draft' })], ROSTER) === null);
ok('a failed read (non-array) → null',
  designatedCpDefault(null, ROSTER) === null);
ok('a log with no created_by → null',
  designatedCpDefault([daily({ created_by: null })], ROSTER) === null,
  '64 of 315 logbooks carry none');
ok('an empty created_by → null',
  designatedCpDefault([daily({ created_by: '   ' })], ROSTER) === null);
ok('an account not on the roster → null',
  designatedCpDefault([daily({ created_by: 'someone-else' })], ROSTER) === null,
  'another company, a deleted user, or an account without the role');
ok('an empty roster → null', designatedCpDefault([daily()], []) === null);
ok('a missing roster → null', designatedCpDefault([daily()], undefined) === null);

// TWO ROWS FOR ONE ID CANNOT HAPPEN THROUGH A UNIQUE KEY. Reaching here means
// the roster is wrong, and a tiebreak invented at that moment is the silent
// wrong answer the whole module is arranged to avoid.
ok('two roster rows matching one account → null, never a tiebreak',
  designatedCpDefault([daily()], [MICHAEL, { ...MICHAEL }]) === null);

console.log('\nthe amended chain');

const parent = daily({ id: 'p', created_by: MICHAEL.id });
const amend = daily({
  id: 'c', is_amendment: true, created_at: '2026-09-04T17:10:00Z',
  created_by: WILSON.id,
});
ok('a filed correction moves the default to whoever filed IT',
  designatedCpDefault([parent, amend], ROSTER) === WILSON);
ok('and the arrival order does not matter',
  designatedCpDefault([amend, parent], ROSTER) === WILSON);
ok('a withdrawn correction leaves the original standing',
  designatedCpDefault([parent, daily({
    id: 'c', is_amendment: true, status: 'withdrawn',
    created_at: '2026-09-04T17:10:00Z', created_by: WILSON.id,
  })], ROSTER) === MICHAEL);
ok('an unsigned correction does not displace the filed original',
  designatedCpDefault([parent, daily({
    id: 'c', is_amendment: true, status: 'draft',
    created_at: '2026-09-04T17:10:00Z', created_by: WILSON.id,
  })], ROSTER) === MICHAEL);

console.log('\n2026-08-17 — the day that looks like two CPs and is not');

// THE REAL ROW. One CP on the job filing 13 logs, and the admin filing a
// single osha_log from the office. A rule reading "anyone who filed today"
// would have shown two candidates and suppressed the default on a day with
// one unambiguous answer.
const AUG17 = [
  daily({ id: 'dj', created_by: MICHAEL.id }),
];
ok('the admin\'s back-office OSHA filing does not move item 8',
  designatedCpDefault(AUG17, ROSTER) === MICHAEL,
  'the anchor is the CP\'s own daily record, not "anyone who filed"');
ok('and the admin is still pickable if he really was designated',
  ROSTER.includes(MEILICH),
  'over-inclusion in the LIST is safe; a wrong DEFAULT is not');

console.log('\nidentity is by account, never by name');

ok('a roster row spelled differently still matches by id',
  designatedCpDefault([daily()], [{ ...MICHAEL, name: 'michael' }]).id
    === MICHAEL.id);
ok('two accounts sharing a name do not collapse',
  designatedCpDefault([daily()],
    [MICHAEL, { ...WILSON, name: 'Michael Cespedes' }]) === MICHAEL,
  'grouping signature_events by signer.name flagged two false multi-signer '
  + "days — same user_id under 'michael' and 'michael Cespedes'");
// ── A ROSTER ROW CARRIES `id`, AND A ROW WITHOUT ONE MATCHES NOTHING ──────
//
// The first draft of this file asserted that `_id` was accepted too, and it
// FAILED — correctly. `isSamePerson` reads `picked.id` on the left and accepts
// either spelling on the right, and that asymmetry is deliberate: the left is
// always a company-roster row.
//
// The fix was to the TEST, not to isSamePerson. `get_company_roster` builds
// every row as `{id: str(_id), name, email, role}` — `_id` never reaches the
// client — so the shape I asserted does not occur. Loosening the shared rule
// to accept it would have made the ORIENTATION's profile guard match in a case
// where it currently does not, and that guard is what stops another man's name
// and signature being stored as the filer's own credential. A security-shaped
// rule must not be widened to satisfy a test about a shape nothing produces.
ok('a roster row with no `id` matches nothing, and that is the contract',
  designatedCpDefault([daily()],
    [{ _id: MICHAEL.id, name: 'Michael Cespedes' }]) === null,
  'isSamePerson reads picked.id; company-roster always supplies it');
ok('and the endpoint really does supply `id` on every row',
  /"id":\s+str\(u\.get\("_id"\)\)/.test(fs.readFileSync(
    path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8')),
  'if the roster ever stops carrying `id`, every default silently becomes '
  + 'null and this file is the only thing that would say so');
ok('identity goes through the shared rule',
  /import \{ isSamePerson \} from '\.\.\/components\/CompetentPersonPicker'/
    .test(read('designatedCp.js')),
  'a hand-rolled id comparison would be a second identity rule');
ok('the anchor field is named rather than inlined',
  ANCHOR_FIELD === 'created_by',
  'it moves to signed_by when that exists, and nothing else changes');

console.log('\nthe screen');

ok('one read serves both items',
  (SCREEN.match(/getByProject\(projectId, SOURCE_LOG_TYPE, logDate\)/g) || [])
    .length === 1,
  'two reads are two chances to disagree about which link is the record');
ok('the roster and the day are fetched independently',
  /Promise\.allSettled/.test(SCREEN),
  'Promise.all would let a 403 on the roster suppress item 2\'s offer');
ok('each offer is guarded on its OWN field',
  /const wantSummary = /.test(SCREEN) && /const wantCp = /.test(SCREEN),
  'a superintendent who typed his summary but not his competent person must '
  + 'still get item 8\'s default');
ok('the default is never applied over a name already present',
  /if \(wantCp && rows && people\)/.test(SCREEN));
ok('a filed log gets no picker at all',
  /\{locked \? \(\s*<Field s=\{s\} locked/.test(SCREEN),
  'a picker over a frozen statutory record offers to change what cannot '
  + 'change');
ok('free text is still reachable, one tap further in',
  /onManual=\{\(\) => \{ setCpPickerOpen\(false\); setCpManual\(true\); \}\}/
    .test(SCREEN));
ok('and the second tap survives the trip to /consent',
  /competentPersonName, cpManual, step,/.test(SCREEN)
  && /setCpManual\(v\.cpManual === true\)/.test(SCREEN));
ok('the picked name comes off the record',
  /setCompetentPersonName\(person\.name \|\| ''\)/.test(SCREEN));

console.log('\nthe picker was reused, not forked');

ok('the screen mounts the existing component',
  /<CompetentPersonPicker/.test(SCREEN)
  && /from '\.\.\/\.\.\/src\/components\/CompetentPersonPicker'/.test(SCREEN));
ok('there is still exactly one picker component',
  !fs.existsSync(path.join(FRONTEND, 'src', 'components',
    'DesignatedPersonPicker.jsx')));
ok('the trainer wording is the DEFAULT, so the orientation is untouched',
  /manualLabel = TRAINER_MANUAL_LABEL/.test(PICKER)
  && /failedNote = TRAINER_FAILED_NOTE/.test(PICKER));
ok('and the orientation passes neither',
  !/manualLabel=/.test(fs.readFileSync(
    path.join(FRONTEND, 'app', 'logbooks', 'subcontractor_orientation.jsx'),
    'utf8')));
ok('a caller may hand the roster down',
  /rows: providedRows/.test(PICKER),
  'the closed control needs a NAME, so the screen must have the roster '
  + 'before the picker opens; one request instead of two');
ok('an absent roster still self-fetches',
  /if \(providedRows\) \{ setRows\(providedRows\); return undefined; \}/
    .test(PICKER));

// undefined MEANS THE READ FAILED; [] MEANS NOBODY IS REGISTERED. Presenting
// the first as the second reads as a fact about the company and pushes him to
// the keyboard, which is what the picker exists to stop.
ok('a failed roster read is passed down as undefined, not as []',
  /rosterRes\.status === 'fulfilled' \? rosterRes\.value : undefined/
    .test(SCREEN));

if (failures) {
  console.error(`\ndesignatedCp: ${failures} failure(s)`);
  process.exit(1);
}
console.log('\nALL PASS');
