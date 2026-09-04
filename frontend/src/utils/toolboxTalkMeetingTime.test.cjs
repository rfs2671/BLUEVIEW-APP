/**
 * THE MEETING TIME IS NOT THE APP'S TO INVENT.
 *
 * THE DEFECT. `meetingTime` was seeded from `new Date().toLocaleTimeString(...)`
 * — the moment the screen mounted — and hydrate re-applied a stored value with
 * `if (d.meeting_time)`. An EMPTY stored value is falsy, so hydrate did nothing
 * and the field kept the seed. Re-opening a talk whose `meeting_time` was
 * stored empty and saving wrote THE CURRENT TIME onto a filed §3301.12.3
 * record, presented as the minute the talk was held. Nobody typed it and
 * nobody looked at it.
 *
 * It is the third of a family the operator has named — a value the app
 * invented and presented as recorded — after a departure time stamped at the
 * moment of signing and a signature object printed as the superintendent's own
 * record of his presence.
 *
 * THE TWO HALVES, and neither alone is enough:
 *
 *   1. THE SEED IS EMPTY. A prefilled time the CP never looked at is the
 *      fabrication; an empty field he must fill is the record. Step 1 is the
 *      one gated step in the app, so an empty meeting time now BLOCKS Next —
 *      he cannot leave the step without answering.
 *
 *   2. HYDRATION DISTINGUISHES ABSENT FROM EMPTY. `if (d.meeting_time)`
 *      collapses "the key is not on the document" with "the key is on the
 *      document and holds nothing". Those are different facts about a filed
 *      record and this codebase does not collapse them anywhere else —
 *      server.py's renderer `has()` is the same distinction on the reading
 *      side. With an empty seed the two happen to agree TODAY; the presence
 *      test is what stops the next non-empty seed re-opening the hole, and
 *      what makes an amendment that CLEARS a field actually clear it on a
 *      re-hydrate rather than leave the previous value on screen.
 *
 * WHAT IS NOT FIXED HERE. Three readers still disagree about one stored empty
 * meeting time — see the report; the renderer change is another worker's.
 *
 * Run:  node src/utils/toolboxTalkMeetingTime.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');
const LOGBOOKS = path.join(FRONTEND, 'app', 'logbooks');
const SCREEN = fs.readFileSync(path.join(LOGBOOKS, 'toolbox_talk.jsx'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// Same loader idiom as toolboxTalkModel.test.cjs — the REAL module, executed.
function load(rel, extra = '') {
  const src = fs.readFileSync(path.join(UTILS, rel), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default [\s\S]*$/m, '')
    .replace(/^export (async function|function|const) /gm, '$1 ');
  const names = [...src.matchAll(/^(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  // eslint-disable-next-line no-new-func
  return new Function(`${extra}\n${src}\nreturn { ${[...new Set(names)].join(', ')} };`)();
}
const RR = load('rosterReconcile.js');
const M = load('toolboxTalkModel.js',
  `const withGateSnapshot = ${RR.withGateSnapshot};
   const reconcileRoster = ${RR.reconcileRoster};`);

// ── THE SEED ────────────────────────────────────────────────────────────────
console.log('\n-- 1. the seed is empty, not now() --');

// The declaration, matched across lines: the seed used to be a two-line arrow
// returning toLocaleTimeString, which is why a single-line grep for
// "useState(new Date" found nothing on this file for as long as it was there.
const seedDecl = /const\s+\[meetingTime,\s*setMeetingTime\]\s*=\s*useState\(([\s\S]*?)\);/
  .exec(SCREEN);
ok(!!seedDecl, 'meetingTime is declared with useState');
ok(!!seedDecl && seedDecl[1].trim() === "''",
  `meetingTime seeds EMPTY (got ${seedDecl ? JSON.stringify(seedDecl[1].trim()) : 'no match'})`);

// The whole screen, not just that line. A clock anywhere in this file would be
// a value the app can assert about a talk it did not attend.
const CODE = SCREEN.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
ok(!/new\s+Date\s*\(|Date\.now\s*\(|toLocaleTimeString|toISOString|nowHHMM/.test(CODE),
  'no live clock anywhere in the toolbox talk screen');

// ── THE GATE THE EMPTY SEED TURNS ON ────────────────────────────────────────
console.log('\n-- and an empty meeting time now GATES step 1 --');
ok(M.missingStepOneFields({
  location: 'Gate', companyName: 'AAZ', typeOfWork: 'Demo',
  meetingTime: '', performedBy: 'CP',
}).includes('meetingTime'),
  'an empty meeting time is a MISSING step-1 field');
// The screen wires that list straight into nextDisabled, so the CP cannot page
// past step 1 without filling it. Marked, gated, and never invented.
ok(/nextDisabled=\{step === 1 && missingStep1\.length > 0\}/.test(SCREEN),
  'and missingStep1 is what disables Next — an empty field he must fill');
ok(M.missingStepOneFields({
  location: 'Gate', companyName: 'AAZ', typeOfWork: 'Demo',
  meetingTime: '07:30 AM', performedBy: 'CP',
}).length === 0, 'a filled meeting time clears the gate');

// ── ABSENT IS NOT EMPTY ─────────────────────────────────────────────────────
console.log('\n-- 2. hydration distinguishes ABSENT from EMPTY --');
ok(typeof M.hasStoredKey === 'function',
  'the model exports an explicit presence test');
if (typeof M.hasStoredKey === 'function') {
  ok(M.hasStoredKey({ meeting_time: '07:30 AM' }, 'meeting_time') === true,
    'a written value is stored');
  ok(M.hasStoredKey({ meeting_time: '' }, 'meeting_time') === true,
    'AN EMPTY STRING IS STORED — the key is on the document and holds nothing');
  ok(M.hasStoredKey({ meeting_time: '   ' }, 'meeting_time') === true,
    'so is whitespace: the CP cleared it, which is a fact about the record');
  ok(M.hasStoredKey({}, 'meeting_time') === false,
    'an ABSENT key is not stored');
  ok(M.hasStoredKey({ meeting_time: null }, 'meeting_time') === false,
    'and neither is an explicit null — nothing to put in a text field');
  ok(M.hasStoredKey({ meeting_time: undefined }, 'meeting_time') === false,
    'nor undefined');
  ok(M.hasStoredKey(null, 'meeting_time') === false, 'a null document stores nothing');
  ok(M.hasStoredKey('nope', 'meeting_time') === false, 'and neither does a non-object');
  // The distinction has to be a REAL one or the helper is decoration.
  ok(M.hasStoredKey({ meeting_time: '' }, 'meeting_time')
     !== M.hasStoredKey({}, 'meeting_time'),
    'ABSENT and EMPTY give DIFFERENT answers — the whole point of the helper');
}

// ── THE REAL hydrate, EXECUTED ──────────────────────────────────────────────
// Not grepped. The function is plain JS inside a JSX file, so it is lifted out
// verbatim and run against stub setters. If someone re-writes it back to a
// truthiness test these assertions fail on behaviour, not on wording.
console.log('\n-- the real hydrate, lifted out of the screen and run --');
const hy = /const hydrate = \(d\) => \{[\s\S]*?\n {2}\};/.exec(SCREEN);
ok(!!hy, 'hydrate was located in the screen source');
if (hy) {
  const runHydrate = (doc, seeds) => {
    const state = { ...seeds };
    // eslint-disable-next-line no-new-func
    const fn = new Function('hasStoredKey', 'setLocation', 'setCompanyName',
      'setTypeOfWork', 'setMeetingTime', 'setPerformedBy', 'setCheckedTopics',
      `${hy[0]}\nreturn hydrate;`)(
      M.hasStoredKey,
      (v) => { state.location = v; },
      (v) => { state.companyName = v; },
      (v) => { state.typeOfWork = v; },
      (v) => { state.meetingTime = v; },
      (v) => { state.performedBy = v; },
      (v) => { state.checkedTopics = v; },
    );
    fn(doc);
    return state;
  };

  // THE PRODUCTION CASE. A stored talk whose meeting_time is empty, re-opened.
  // The seed used to be now(); this proves the field ends EMPTY whatever the
  // component was holding, so the autosave 800ms later writes '' and not a
  // fabricated clock reading.
  const reopened = runHydrate(
    { location: 'Gate 2', company_name: 'AAZ', meeting_time: '' },
    { meetingTime: '09:47 AM' },
  );
  ok(reopened.meetingTime === '',
    `a stored EMPTY meeting_time CLEARS the field (got ${JSON.stringify(reopened.meetingTime)})`);
  ok(reopened.location === 'Gate 2', 'and a written field still hydrates');

  // ABSENT leaves the field alone — there is nothing on the document to apply,
  // and the autofill chain below hydrate is what owns that case.
  const absent = runHydrate({ location: 'Gate 2' }, { meetingTime: '' });
  ok(absent.meetingTime === '', 'an ABSENT meeting_time leaves the empty seed empty');

  const written = runHydrate({ meeting_time: '07:30 AM' }, { meetingTime: '' });
  ok(written.meetingTime === '07:30 AM', 'a written meeting_time hydrates verbatim');

  // AN AMENDMENT THAT CLEARS A FIELD. fetchData is re-run by onAmended, so
  // hydrate runs over state that already holds the parent's value. Truthiness
  // left the old value on screen under a new document; presence clears it.
  const amended = runHydrate(
    { location: '', company_name: '', type_of_work: '', meeting_time: '',
      performed_by: '' },
    { location: 'OLD', companyName: 'OLD', typeOfWork: 'OLD',
      meetingTime: 'OLD', performedBy: 'OLD' },
  );
  ok(amended.location === '' && amended.companyName === '' && amended.typeOfWork === ''
     && amended.meetingTime === '' && amended.performedBy === '',
    'a re-hydrate over a CLEARED document clears every step-1 field, not just the time');
}

// ── THE PAYLOAD ─────────────────────────────────────────────────────────────
console.log('\n-- what an unanswered meeting time STORES --');
const body = M.draftBody({
  location: 'Gate 2', companyName: 'AAZ', typeOfWork: 'Demo',
  meetingTime: '', performedBy: 'CP', checkedTopics: {}, attendees: [],
});
ok(Object.prototype.hasOwnProperty.call(body, 'meeting_time'),
  'the key is still WRITTEN when unanswered — the readers need it present');
ok(body.meeting_time === '', 'and it holds the empty string, not a clock reading');
// This is the state the three readers disagree about; see the report.

// ── THE SWEEP, MADE DURABLE ─────────────────────────────────────────────────
// The operator's question was whether any OTHER editor seeds state from a live
// clock. The answer today is no. This is what keeps it no — over every logbook
// editor, by BALANCED PAREN so a multi-line seed cannot hide from it the way
// this one did for as long as it existed.
console.log('\n-- 3. no logbook editor seeds useState from a live clock --');
const CLOCK = /new\s+Date\s*\(|Date\.now\s*\(|toLocaleTimeString|toLocaleDateString|toISOString|nowHHMM|nowClock|performance\.now/;
const editors = fs.readdirSync(LOGBOOKS).filter((f) => f.endsWith('.jsx'));
ok(editors.length >= 13, `the logbook directory holds ${editors.length} screens`);
const offenders = [];
let seedsScanned = 0;
for (const f of editors) {
  const src = fs.readFileSync(path.join(LOGBOOKS, f), 'utf8');
  const re = /\buseState\s*\(/g;
  let m;
  while ((m = re.exec(src))) {
    let i = m.index + m[0].length - 1; let depth = 0; let j = i;
    for (; j < src.length; j += 1) {
      if (src[j] === '(') depth += 1;
      else if (src[j] === ')') { depth -= 1; if (depth === 0) break; }
    }
    seedsScanned += 1;
    if (CLOCK.test(src.slice(i + 1, j))) {
      offenders.push(`${f}:${src.slice(0, m.index).split('\n').length}`);
    }
  }
}
ok(seedsScanned > 100, `the scan actually read ${seedsScanned} useState seeds`);
ok(offenders.length === 0,
  `no logbook editor seeds useState from a clock (offenders: ${offenders.join(', ') || 'none'})`);

// A CONTROL ON THE SCANNER ITSELF. If the balanced-paren walk were broken the
// assertion above would pass vacuously — this proves it still SEES the shape
// the defect had, including across a line break.
const CANARY = "const [t, setT] = useState(\n  () => new Date().toLocaleTimeString('en-US'),\n);";
{
  const re = /\buseState\s*\(/g;
  const m = re.exec(CANARY);
  let i = m.index + m[0].length - 1; let depth = 0; let j = i;
  for (; j < CANARY.length; j += 1) {
    if (CANARY[j] === '(') depth += 1;
    else if (CANARY[j] === ')') { depth -= 1; if (depth === 0) break; }
  }
  ok(CLOCK.test(CANARY.slice(i + 1, j)),
    'the scanner still catches the multi-line seed this defect was written as');
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
