/**
 * THE FALL PROTECTION EQUIPMENT LOG, executed.
 *
 * WHAT THIS FILE GUARDS, in order of how badly it would hurt to get wrong:
 *
 *  1. WHAT THE APP CLAIMS THIS LOG IS. OSHA 1926.502(d)(21) mandates the
 *     INSPECTION and not a written record of each one; the documented
 *     inspection comes from ANSI Z359, an industry consensus standard. The
 *     sentence is in TWO places — the screen and both PDF renderers — and this
 *     asserts they agree word for word, and that the registry entry carries NO
 *     dob_reference at all. Mislabelling this log is the same unsourced-claim
 *     problem the required-logs work was opened to fix.
 *
 *  2. A ROW MUST CARRY A WORKER — Group 1's rule, IMPORTED rather than written
 *     a third time. Asserted by identity, not by behaviour that happens to
 *     match.
 *
 *  3. THE THREE-STATE RESULT. #153: a control whose "not recorded" state is
 *     unreachable makes a CP who taps twice file a verdict he believes he
 *     cleared. Here the verdict is on fall-arrest equipment.
 *
 *  4. FAIL AND REMOVED NEED THEIR DETAIL. "Failed" with no defect named is the
 *     empty record the tick was, and the photo is the part an inspector can
 *     actually check.
 *
 * Run:  node src/utils/fallProtectionModel.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');
const SERVER = fs.readFileSync(
  path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
const EN = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');
const SCREEN_RAW = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'fall_protection.jsx'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const strip = (text) => text
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')
  .replace(/\s\/\/[^\n'"`]*$/gm, '');
const SCREEN = strip(SCREEN_RAW);
ok(/rowsForFiling/.test(SCREEN) && !/a half-typed row is ordinary work/.test(SCREEN),
  'the comment stripper removes prose but keeps code');

// The real modules, executed. fallProtectionModel imports the OSHA predicate,
// so that one is loaded first and injected — which is also how this file
// proves the two are the SAME function rather than two that agree today.
function load(rel, extra = '') {
  const src = fs.readFileSync(path.join(UTILS, rel), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default [\s\S]*$/m, '')
    .replace(/^export (async function|function|const) /gm, '$1 ');
  const names = [...src.matchAll(/^(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  // eslint-disable-next-line no-new-func
  return new Function(`${extra}\n${src}\nreturn { ${[...new Set(names)].join(', ')} };`)();
}
const OSHA = load('oshaLogModel.js', "const easternToday = () => '2026-08-18';");
const M = load('fallProtectionModel.js',
  `const entryNamesWorker = ${OSHA.entryNamesWorker.toString()};`);

const ROW = (over = {}) => ({ ...M.EMPTY_ROW('t1'), ...over });
const NAMED = (over = {}) => ROW({ worker_name: 'Wilmer Carrillo', ...over });
const PHOTO = [{ id: 'ph1', uri: 'file:///x.jpg' }];

console.log('\n-- what the app says this log IS --');
{
  // \r?\n, not \n. server.py is checked out CRLF on Windows, so `)\n` never
  // matched there — this passed on a LF working copy and on Linux CI, and
  // would have failed on a fresh Windows clone. A test that depends on line
  // endings reports on the checkout, not on the code.
  const notice = /FALL_PROTECTION_NOTICE = \(\s*([\s\S]*?)\)\r?\n/.exec(SERVER);
  ok(!!notice, 'the server declares the notice in one place');
  const serverText = [...notice[1].matchAll(/"([^"]*)"/g)].map((m) => m[1]).join('');
  const enText = /standardNotice: '([^']+)'/.exec(EN);
  ok(!!enText, 'the screen has the same sentence in its catalogue');
  ok(serverText === enText[1],
    'and the two agree WORD FOR WORD — one wording, three surfaces');
  ok(/1926\.502\(d\)\(21\)/.test(serverText),
    'it cites the rule that mandates the INSPECTION');
  ok(/does not require a written record/.test(serverText),
    'and says plainly that the RECORD is not required');
  ok(/ANSI Z359/.test(serverText) && /consensus standard/.test(serverText),
    'and names where the documented inspection actually comes from');
  ok(/not a DOB or OSHA filing/.test(serverText),
    'and refuses the claim outright');
}
{
  // The registry entry must carry NO citation — absent, not empty.
  const entry = SERVER.slice(SERVER.indexOf('"key": "fall_protection"'));
  // COMMENTS STRIPPED. The entry's own comment explains at length why there is
  // no dob_reference, and an absence assertion that matches the EXPLANATION is
  // the exact trap backend/tests/source_text.py exists for.
  const cut = entry.slice(0, entry.indexOf('\n    },')).replace(/^\s*#.*$/gm, '');
  ok(!/dob_reference/.test(cut),
    'the registry entry carries NO dob_reference — absent, so nothing can '
    + 'render an empty citation for it');
  ok(/"subtitle": "Equipment inspection — industry standard, not DOB-required"/.test(cut),
    'and the subtitle says so on the row the CP taps');
  ok(/"conditional": "fall_protection_active"/.test(cut)
     && /"activated_by": "cp"/.test(cut),
    'toggled, and the CP owns the switch — work at height is something he sees');
}
{
  // Every OTHER registry entry still has one, so the absence above is a
  // decision about this log rather than a field nobody fills in any more.
  const refs = (SERVER.match(/"dob_reference":/g) || []).length;
  const keys = (SERVER.match(/^        "key": "/gm) || []).length;
  ok(refs === keys - 1,
    `exactly one registry entry has no citation (${refs} of ${keys})`);
}
ok(/standardNotice/.test(SCREEN),
  'the CP sees it on the step he signs from, not only on the filed PDF');

console.log('\n-- a row must carry a worker: the SAME rule, not a copy --');
{
  // IDENTITY, asserted at the source. The harness injects the OSHA predicate as
  // a fresh function object, so `===` here would compare two copies and prove
  // nothing — the claim is about the MODULE, which binds the imported symbol
  // rather than declaring a second predicate.
  const modSrc = fs.readFileSync(path.join(UTILS, 'fallProtectionModel.js'), 'utf8');
  ok(/import \{ entryNamesWorker \} from '\.\/oshaLogModel'/.test(modSrc),
    'the module imports the OSHA predicate');
  ok(/export const rowNamesWorker = entryNamesWorker;/.test(modSrc),
    'and BINDS it rather than declaring a third copy of the rule');
  ok(!/function rowNamesWorker/.test(strip(modSrc)),
    'there is no local implementation of it to drift from the imported one');
  // And they still agree on every case that matters.
  for (const row of [NAMED(), ROW(), ROW({ worker_name: '  ' }),
    ROW({ worker_name: 'x', equipment_id: 'SN-1' }), null, 'junk']) {
    ok(M.rowNamesWorker(row) === OSHA.entryNamesWorker(row),
      `the two agree on ${JSON.stringify((row && row.worker_name) ?? row)}`);
  }
}
ok(M.rowNamesWorker(NAMED()) === true, 'a named row qualifies');
ok(M.rowNamesWorker(ROW({ equipment_id: 'SN-4471', result: 'Pass' })) === false,
  'a serial and a verdict against NO NAME does not');
ok(M.rowNamesWorker(ROW({ worker_name: '   ' })) === false, 'nor whitespace');

console.log('\n-- the result is three-state, and re-tapping clears it --');
{
  const r1 = M.applyResult(ROW(), 'Pass');
  ok(r1.result === 'Pass', 'a tap records the verdict');
  ok(M.applyResult(r1, 'Pass').result === null,
    'RE-TAPPING THE SAME ONE returns the row to unrecorded — the state the '
    + 'form opens in must be reachable, or a CP who taps twice files a '
    + 'verdict he believes he cleared (#153)');
  ok(M.applyResult(r1, 'Fail').result === 'Fail', 'a different tap replaces it');
  ok(M.EMPTY_ROW('x').result === null,
    'and a fresh row is UNRECORDED, never a Pass nobody performed');
}
{
  // Clearing the verdict must not strand the detail it required.
  const failed = ROW({ result: 'Fail', defect_found: 'cut webbing', action_taken: 'binned' });
  const cleared = M.applyResult(failed, 'Fail');
  ok(cleared.result === null && cleared.defect_found === '' && cleared.action_taken === '',
    'clearing a Fail clears its defect and action — a defect against no '
    + 'verdict reads as one somebody declined to grade');
  const passed2 = M.applyResult(failed, 'Pass');
  ok(passed2.defect_found === '' && passed2.action_taken === '',
    'and so does grading it Pass');
}
{
  const y = M.applyImpactLoaded(ROW(), true);
  ok(y.impact_loaded === true, 'impact loading records Yes');
  ok(M.applyImpactLoaded(y, true).impact_loaded === null, 're-tapping clears it');
  ok(M.applyImpactLoaded(ROW(), false).impact_loaded === false,
    'and No is a real answer, distinct from unrecorded');
  ok(M.EMPTY_ROW('x').impact_loaded === null,
    'seeded NULL — a silent No is the answer that keeps impact-loaded '
    + 'equipment in service (1926.502(d)(19))');
}

console.log('\n-- what is filed, and what is dropped --');
ok(M.rowsForFiling([NAMED({ result: 'Pass' })]).length === 1,
  'a named row with a verdict is filed');
ok(M.rowsForFiling([NAMED()]).length === 0,
  'a named row with NO verdict is not — the roster seed says a man was on '
  + 'site, which the pre-shift sheet already says');
ok(M.rowsForFiling([ROW({ result: 'Pass', equipment_id: 'SN-1' })]).length === 0,
  'and an inspection against nobody is not');
ok(M.rowsForFiling([NAMED({ result: 'Nonsense' })]).length === 0,
  'a verdict outside the closed set is not a verdict');
ok(M.rowsForFiling(null).length === 0, 'malformed input does not throw');
{
  const reported = M.unfilableRows([
    NAMED({ result: 'Pass' }),
    ROW({ equipment_id: 'SN-9', result: 'Pass' }),
    NAMED({ equipment_type: 'Harness' }),
    ROW(),
  ]);
  ok(reported.length === 2, 'both touched-but-unfilable rows are reported');
  ok(reported[0].row === 2 && reported[0].reason === 'unnamed',
    'the nameless one by position, with its reason');
  ok(reported[1].row === 3 && reported[1].reason === 'no-result',
    'and the ungraded one with a DIFFERENT reason — they need different fixes');
  ok(!reported.some((u) => u.row === 4),
    'an untouched seed row is not reported — it is dropped silently');
}

console.log('\n-- Fail and Removed need their detail --');
{
  const bare = NAMED({ result: 'Fail' });
  const missing = M.rowsMissingAdverseDetail([bare]);
  ok(missing.length === 1, 'a bare Fail is caught');
  ok(JSON.stringify(missing[0].missing) === JSON.stringify(['defect', 'action', 'photo']),
    'and every missing part is named, so the gate can point at the field');
}
ok(M.rowsMissingAdverseDetail([
  NAMED({ result: 'Removed from service', defect_found: 'deployed indicator', action_taken: 'destroyed', photos: PHOTO }),
]).length === 0, 'a complete Removed row passes');
ok(M.rowsMissingAdverseDetail([
  NAMED({ result: 'Removed from service', defect_found: 'x', action_taken: 'y' }),
])[0].missing.join() === 'photo',
  'the PHOTO is required on an adverse row — a sentence about a cut strap is '
  + 'an assertion, the photo is the part an inspector can check');
ok(M.rowsMissingAdverseDetail([NAMED({ result: 'Pass' })]).length === 0,
  'and a PASS needs no photo — there is nothing to show');
ok(M.isAdverse('Fail') && M.isAdverse('Removed from service')
   && !M.isAdverse('Pass') && !M.isAdverse(null),
  'the two adverse verdicts are the two that trigger it');

console.log('\n-- impact loading is a WARNING, never a correction --');
{
  const warned = M.impactLoadedNotRemoved([
    NAMED({ result: 'Pass', impact_loaded: true }),
    NAMED({ result: 'Removed from service', impact_loaded: true }),
    NAMED({ result: 'Pass', impact_loaded: false }),
  ]);
  ok(warned.length === 1 && warned[0].row === 1,
    'impact-loaded and still in service is flagged');
  ok(warned[0].result === 'Pass',
    'and the flag carries what he actually recorded');
  // ANSWERING Yes must not touch the verdict. The row starts UNANSWERED, so
  // this call actually sets the flag — an earlier version of this assertion
  // passed a row already marked Yes, which cleared it instead and never
  // exercised the path a silent rewrite would live on.
  const answering = M.applyImpactLoaded(NAMED({ result: 'Pass' }), true);
  ok(answering.impact_loaded === true && answering.result === 'Pass',
    'recording Yes does NOT rewrite his verdict — the app tells him, it does '
    + 'not decide for him');
  const clearing = M.applyImpactLoaded(NAMED({ result: 'Pass', impact_loaded: true }), true);
  ok(clearing.impact_loaded === null && clearing.result === 'Pass',
    'and clearing it leaves the verdict alone too');
  ok(M.impactLoadedNotRemoved([answering]).length === 1,
    'the contradiction is REPORTED instead — that is the whole mechanism');
}

console.log('\n-- the roster builds the rows: picked, not typed --');
{
  const built = M.buildRowsFromCheckins([
    { worker_id: 'w1', worker_name: 'Wilmer Carrillo', company: 'AAZ' },
    { worker_id: 'w2', worker_name: '', company: 'AAZ' },
    null,
  ], 'seed');
  ok(built.length === 1, 'a check-in with no name builds no row');
  ok(built[0].worker_name === 'Wilmer Carrillo' && built[0].company === 'AAZ',
    'the name and company come off the gate record, never typed');
  ok(built[0].worker_id === 'w1', 'and the row is linked to the worker');
  ok(built[0].result === null,
    'with NO verdict seeded — a row exists because a man is on site, not '
    + 'because his equipment was inspected');
  ok(built[0].activity_id.startsWith('fp_'),
    'the row id carries the fp_ prefix that gives this log its own R2 folders');
}
ok(M.EMPTY_ROW('x').worker_id === null,
  'a hand-added row is not linked to anybody, and does not pretend to be');

console.log('\n-- the payload, and the machinery it plugs into --');
{
  const body = M.draftBody([NAMED({ result: 'Pass' })]);
  ok(Object.keys(body).length === 1 && Array.isArray(body.activities),
    'draftBody is { activities: [...] } — the container the ONE production '
    + 'photo reader indexes');
  ok(M.ROW_KEYS.every((k) => k in M.EMPTY_ROW('x')),
    'EMPTY_ROW carries every declared key');
  ok(M.ROW_KEYS.includes('activity_id'),
    'including activity_id, which uploadPendingActivityPhotos keys the R2 '
    + 'folder off — naming it anything else would mean a second uploader');
}
{
  const branch = SERVER.slice(SERVER.indexOf('elif log_type == "fall_protection":'));
  const cut = branch.slice(0, branch.indexOf('elif log_type ==', 10));
  ok(/data\.get\("activities"\)/.test(cut), 'the PDF renderer reads activities');
  ok(/if not has\(r, "worker_name"\)/.test(cut),
    'and drops a row that names nobody');
  ok(/FALL_PROTECTION_NOTICE/.test(cut), 'and prints the notice on the document');
}
{
  const report = SERVER.slice(SERVER.indexOf('_filed_log(logbooks, "fall_protection")'));
  const cut = report.slice(0, report.indexOf('SCAFFOLD MAINTENANCE'));
  ok(/if not str\(r\.get\("worker_name"\) or ""\)\.strip\(\)/.test(cut),
    'the combined report drops the same rows');
  ok(/FALL_PROTECTION_NOTICE/.test(cut),
    'and prints the same notice — this is the copy investors and lenders read');
}

console.log('\n-- the screen blocks at SUBMIT, never on Next --');
{
  const sign = SCREEN.indexOf('const handleSubmitAndSign');
  const push = SCREEN.indexOf("persistAndPush('submitted')");
  for (const [fn, label] of [
    ['rowsMissingAdverseDetail(now)', 'the adverse-detail gate'],
    ['unfilableRows(now)', 'the will-not-be-filed gate'],
    ['rowsForFiling(now)', 'the nothing-to-file gate'],
  ]) {
    const at = SCREEN.indexOf(fn);
    ok(at > sign && at < push, `${label} runs inside submit, before any write`);
  }
  const stepAt = SCREEN.indexOf('const onStepChange');
  const stepEnd = SCREEN.indexOf('\n  };', stepAt);
  const stepFn = SCREEN.slice(stepAt, stepEnd);
  ok(!/unfilableRows|rowsMissingAdverseDetail/.test(stepFn),
    'and NONE of them runs on Next — a half-typed row is ordinary mid-shift work');
}
ok(/isAffirmedSignature\(cpSignature\)/.test(SCREEN),
  'the submit button asks the AFFIRMED question, not "is anything there"');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
