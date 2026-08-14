/**
 * toolbox_talk, ported onto the shared stepper.
 *
 * TWO THINGS THIS FILE EXISTS FOR.
 *
 * 1. THE PAYLOAD KEYS SURVIVE. Both PDF renderers and the kiosk read this log
 *    by key. A renamed key does not crash anything — it silently blanks a
 *    section on a filed §3301.12.3 record. The keys are checked against the
 *    RENDERER'S OWN reads, pulled out of server.py, not a copy typed here.
 *
 * 2. THE #130 RECONCILE SURVIVED THE REWRITE. It is the piece most at risk in
 *    a port, and it is what stops a man who never checked in staying on a
 *    signed attendance sheet — the production case on project
 *    6a5f63bc147407d3261df2c7, where six men were listed on a day five
 *    checked in and the sixth had been refused at the gate.
 *
 * Run:  node src/utils/toolboxTalkModel.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');
const SERVER = fs.readFileSync(
  path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
const SCREEN = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'toolbox_talk.jsx'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// Load the real modules under bare node.
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
  `const withGateSnapshot = ${RR.withGateSnapshot.toString()};
   const reconcileRoster = ${RR.reconcileRoster.toString()};
   const rowKey = ${RR.rowKey.toString()};
   const isCpEdited = ${RR.isCpEdited.toString()};`);

// ── 1. THE PAYLOAD ──────────────────────────────────────────────────────────
console.log('\n-- the keys the renderer reads --');

const branch = SERVER.slice(
  SERVER.indexOf('#  TOOLBOX TALK'),
  SERVER.indexOf('#  PRE-SHIFT SIGN-IN'),
);
ok(branch.length > 0, 'located the toolbox branch of the combined report');

const topLevel = [...new Set(
  [...branch.matchAll(/td_data\.get\("([a-z_]+)"/g)].map((m) => m[1]),
)].sort();
const body = M.draftBody({
  location: 'Gate', companyName: 'AAZ', typeOfWork: 'Concrete',
  meetingTime: '07:30 AM', performedBy: 'Carl CP',
  checkedTopics: { hard_hats: true }, attendees: [],
});
for (const k of topLevel) {
  ok(Object.prototype.hasOwnProperty.call(body, k),
    `payload carries "${k}" — the renderer reads it`);
}
ok(Object.keys(body).length === 7, `the payload is exactly 7 keys (${Object.keys(body).join(', ')})`);

// (?<![\w.]) so "td_data.get(" does not match as "a.get(" — it did.
const attKeys = [...new Set(
  [...branch.matchAll(/(?<![\w.])a\.get\("([a-z_]+)"/g)].map((m) => m[1]),
)].sort();
const row = M.buildAttendees([{
  worker_id: 'w1', worker_name: 'Segundo Pilamunga', company: 'AAZ',
  trade: 'Concrete / Cement', check_in_time: '2026-08-14T11:12:00Z',
  toolbox_talk_confirmed: true, toolbox_talk_confirmed_at: '2026-08-14T11:12:00Z',
}])[0];
for (const k of attKeys) {
  ok(Object.prototype.hasOwnProperty.call(row, k),
    `attendee row carries "${k}" — the renderer reads it`);
}
ok(row.title === 'Concrete / Cement', 'the trade reaches the Title column');
ok(row.gate_confirmed === true, 'and the gate confirmation reaches Confirmed');
ok(row.signature === null,
  'signature stays NULL — a worker does not sign a toolbox talk');
ok(row.signed === false, 'and Present starts unticked; it is the CP\'s mark');

// ── 2. THE #130 RECONCILE ───────────────────────────────────────────────────
console.log('\n-- the reconcile survived the port --');

const FRESH = [{ worker_id: 'w1', worker_name: 'Wilmer Carrillo', company: 'AAZ' }];
const stale = M.buildAttendees([
  { worker_id: 'w1', worker_name: 'Wilmer Carrillo', company: 'AAZ' },
  { worker_id: 'w9', worker_name: 'Segundo Pilamunga', company: 'AAZ' },
]);

let out = M.reconcileAttendees(stale, FRESH);
ok(out.length === 1 && !out.some((a) => a.name === 'Segundo Pilamunga'),
  'DROP: an untouched auto row with no check-in today is gone');

const handAdded = [{ ...M.EMPTY_ATTENDEE(), name: 'Segundo Pilamunga' }];
ok(M.reconcileAttendees(handAdded, FRESH).some((a) => a.name === 'Segundo Pilamunga'),
  'KEEP: a hand-added attendee survives — the CP said he was there');

const edited = stale.map((a) => (a.worker_id === 'w9' ? { ...a, signed: true } : a));
ok(M.reconcileAttendees(edited, FRESH).some((a) => a.name === 'Segundo Pilamunga'),
  'KEEP: an auto row the CP ticked present survives — the tick proves it is his');

ok(M.reconcileAttendees([], FRESH).length === 1,
  'ADD: a man who checked in and was not listed is added');

ok(M.reconcileAttendees(stale, null).length === 2,
  'OFFLINE: a failed fetch keeps everyone — never drop a man because the server was unreachable');

// A blocked worker is not an attendee.
ok(M.buildAttendees([{ worker_id: 'b', worker_name: 'Turned Away', blocked: true }]).length === 0,
  'a worker refused at the gate never reaches an ATTENDANCE roster');
ok(M.buildAttendees([{ worker_id: 'c', worker_name: 'Alert Row', source: 'cert_block' }]).length === 0,
  'and neither does a cert_block alert row');

// ── 3. THE SCREEN IS WIRED TO IT ────────────────────────────────────────────
console.log('\n-- both load paths re-check, as in #130 --');

ok((SCREEN.match(/reconcileAttendees\(/g) || []).length === 2,
  'reconcileAttendees is called on BOTH load paths, not just the server one');
const draftBlock = SCREEN.slice(0, SCREEN.indexOf('setLoading(false);'));
ok(draftBlock.includes('getCheckinsForDate(projectId, date)'),
  'the DRAFT path fetches today\'s check-ins before returning — that early return was the defect');
ok(!SCREEN.includes('setAttendees(d.attendees);'),
  'the stored payload is never trusted unchecked');

// ── THE CASE THAT WAS NEVER TESTED ──────────────────────────────────────────
//
// DEVICE ROUND 4, findings 6/17/3, all one mechanism. The draft path only
// re-checked when the stored roster was NON-EMPTY:
//
//     if (draft.data.attendees.length > 0) { ...fetch and reconcile... }
//     // no else — and the function returns here
//
// so an EMPTY stored roster returned without fetching anything at all. And an
// empty stored roster is trivial to create: draftBody always writes
// `attendees: []` and the autosave fires 800ms after load, so merely OPENING
// this form before anyone tapped in wrote a permanent empty roster for that
// project and date. Production: 13 men checked in, step 3 listed nobody, four
// were added by hand — which is why their In and Title columns printed blank.
//
// The `length > 0` guard came in with #130. It was mine, and this is the case
// it never considered: nothing stored is exactly when the roster must BUILD.
ok(draftBlock.includes('buildAttendees('),
  'the DRAFT path can BUILD, not only reconcile — an empty stored roster rebuilds');
ok(draftBlock.includes('storedRoster.length > 0')
  && draftBlock.indexOf('getCheckinsForDate') < draftBlock.indexOf('storedRoster.length > 0'),
  'and it fetches BEFORE deciding which of the two to do');
// The fetch must not be inside the non-empty branch again.
ok(!/attendees\.length > 0\) \{[\s\S]{0,200}getCheckinsForDate/.test(draftBlock),
  'the fetch is no longer conditional on there being something stored');

// Executed, not grepped: build-from-empty is the behaviour, not the wiring.
ok(M.buildAttendees(FRESH).length === FRESH.length && M.buildAttendees(FRESH).length > 0,
  'buildAttendees turns the day check-ins into a roster');
ok(M.buildAttendees([]).length === 0 && M.buildAttendees(null).length === 0,
  'and an absent check-in list builds nothing rather than throwing');
// OFFLINE STILL KEEPS EVERYONE. The rebuild must not become a new way to lose
// men: `fresh` null means the fetch failed, and the screen passes [] to
// buildAttendees only when there was nothing stored to lose in the first place.
ok(draftBlock.includes('Array.isArray(fresh) ? fresh : []'),
  'offline builds an empty roster only when the stored one was already empty');
ok(M.reconcileAttendees([{ name: 'Kept', worker_id: 'k1' }], null).length === 1,
  'a stored roster is still never dropped when the fetch fails');

// ── 3b. THE WEEKLY GAP — ruling C ───────────────────────────────────────────
console.log('\n-- the weekly gap --');

// A toolbox talk is a WEEKLY obligation and the roster is built from TODAY's
// check-ins, so the men who worked Monday-Wednesday and not today were counted
// against the CP on the home screen and never offered to him on the form.
// Production: 26 worked the week, 13 were on site the day.
const MISSING = [
  { worker_id: 'm1', worker_name: 'Andre Duval', company: 'AAZ' },
  { worker_id: 'm2', worker_name: 'Luis Alvarez', company: 'Vanguard' },
];
ok(M.weeklyGapWorkers(MISSING, []).length === 2,
  'with nobody on the sheet, everyone in the gap is offered');
ok(M.weeklyGapWorkers(MISSING, [{ worker_id: 'm1', name: 'Andre Duval' }]).length === 1,
  'a man already on the roster is NOT offered again');
ok(M.weeklyGapWorkers(MISSING, [{ worker_id: null, name: '  andre   DUVAL ' }]).length === 1,
  'matched by normalised NAME too — the two lists come from different queries');
ok(M.weeklyGapWorkers([...MISSING, MISSING[0]], []).length === 2,
  'and the gap list itself is deduped');
ok(M.weeklyGapWorkers(null, null).length === 0, 'null in, empty out');
ok(M.weeklyGapWorkers([{ worker_id: null, worker_name: '' }], []).length === 0,
  'a row with neither an id nor a name is not a man');

// THE PAYLOAD MUST TELL THE TWO CLAIMS APART. The gate saying a man was on site
// and the CP saying a man attended are different assertions, and a signed sheet
// that renders them identically is the stronger one borrowing the weaker one's
// authority.
const gapRow = M.weeklyGapAttendee(MISSING[0]);
ok(gapRow.added_from === M.ATTENDEE_SOURCES.WEEKLY_GAP,
  'a weekly-gap row is marked as the CP assertion it is');
ok(M.buildAttendees(FRESH)[0].added_from === M.ATTENDEE_SOURCES.GATE,
  'a row built from today check-ins is marked as the gate');
ok(M.EMPTY_ATTENDEE().added_from === M.ATTENDEE_SOURCES.MANUAL,
  'and a hand-typed row is marked as neither');
ok(gapRow.time === '' && gapRow.gate_confirmed === false,
  'a weekly-gap row claims NO check-in time and no gate confirmation — it has none');
ok(gapRow.signed === false,
  'and starts UNTICKED: adding a man to the list is not marking him present');
ok(gapRow.gate_snapshot === undefined,
  'no gate snapshot either — the gate never supplied this row');
ok(M.ATTENDEE_KEYS.includes('added_from'),
  'added_from is part of the asserted payload, so it cannot be dropped silently');

// ── 3c. STEP 1 IS THE ONE GATED STEP ────────────────────────────────────────
console.log('\n-- step 1 --');
const FULL = {
  location: 'Gate', companyName: 'AAZ', typeOfWork: 'Demo',
  meetingTime: '07:30 AM', performedBy: 'CP',
};
ok(M.missingStepOneFields(FULL).length === 0, 'a complete step 1 is complete');
ok(M.STEP_ONE_FIELDS.length === 5, 'all five fields are gated');
for (const k of M.STEP_ONE_FIELDS) {
  ok(M.missingStepOneFields({ ...FULL, [k]: '' })[0] === k,
    `${k} empty is reported BY NAME, so the control can mark itself`);
}
ok(M.missingStepOneFields({ ...FULL, location: '   ' }).includes('location'),
  'whitespace is not a value');
ok(M.missingStepOneFields({}).length === 5 && M.missingStepOneFields(null).length === 5,
  'an absent form is entirely incomplete rather than throwing');

// The screen must mark AND gate from the same list, or the button and the
// fields disagree about what is missing.
ok(SCREEN.includes('const missingStep1 = missingStepOneFields({'),
  'the screen derives the missing list once');
ok(SCREEN.includes('nextDisabled={step === 1 && missingStep1.length > 0}'),
  'Next is gated on step 1 from that list');
ok(SCREEN.includes('missing && s.inputRequired') || SCREEN.includes('missing && <Text style={s.requiredText}>'),
  'and each empty control marks itself rather than one blanket error');
// GATED ONLY ON STEP 1. Steps 2-4 must page freely — everywhere else in this
// app an incomplete step marks and never gates.
ok(!/nextDisabled=\{(?!step === 1)/.test(SCREEN),
  'no other step is gated');

// ── 3d. AUTOFILL ────────────────────────────────────────────────────────────
console.log('\n-- autofill --');
ok(/if \(!existing\?\.data\?\.location\) \{/.test(SCREEN),
  'location autofills only when the record does not already carry one');
ok(/if \(!existing\?\.data\?\.performed_by\) \{/.test(SCREEN),
  'and so does performed_by — a filed value always wins');
ok(/projectData\?\.address \|\| projectData\?\.location \|\| projectData\?\.name/.test(SCREEN),
  'location comes from the project the CP is standing on');
ok(/user\?\.full_name \|\| user\?\.name/.test(SCREEN),
  'performed_by comes from the man holding the phone');

// ── 4. THE PORT CARRIED THE REST ────────────────────────────────────────────
console.log('\n-- what the port had to carry --');

for (const [needle, label] of [
  ['LogbookStepper', 'uses the shared stepper'],
  ['submitDisabled={!isAffirmedSignature(cpSignature)}',
    'an UNAFFIRMED submit is UNREACHABLE (immediate type)'],
  ['gateCopy', 'gateCopy — the server never renders its own English'],
  ['recordFinalizeError', 'a foreground refusal leaves the durable banner'],
  ['freezeIfImmediate', 'the signature is the freeze'],
  ['markPending', 'the draft lifecycle'],
  ['TimeField', 'a time picker for meeting_time'],
  ["useT('toolboxTalk')", 'copy comes from i18n'],
]) {
  ok(SCREEN.includes(needle), label);
}
// CODE ONLY. The screen's own docstring explains why the photo machinery was
// not carried, and asserting against raw source matched that sentence — the
// self-referential shape this project has hit before.
const SCREEN_CODE = SCREEN
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '');
ok(!/persistPhoto|compressUnderCap/.test(SCREEN_CODE),
  'no photo machinery — this form has no camera, so carrying it would be dead weight');
ok(!/Save Draft|saveDraft/.test(SCREEN), 'no Save Draft button — the stepper autosaves');
ok(!/¿|¡|á|é|í|ó|ú|ñ/.test(SCREEN), 'no Spanish — a logbook is an English record');

// The 24 topic labels must stay OUT of i18n: the filed PDF prints them.
const en = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');
ok(!en.includes('Hard Hats') && !en.includes('Ladder Safety'),
  'topic labels live in the model, not i18n — the PDF prints the same strings');
// 21, not 22: 'covid19' was removed by ruling (device round 4, finding 9).
ok(M.ALL_TOPIC_KEYS.length === 21,
  `all topic keys are enumerated (got ${M.ALL_TOPIC_KEYS.length})`);
ok(!M.ALL_TOPIC_KEYS.includes('covid19'), 'covid19 is gone from the picker');
// HISTORICAL RECORDS ARE NOT REWRITTEN. The PDF prints whichever checked_topics
// keys are true rather than looking them up here, so a filed talk that carries
// covid19 still renders it. Removing a chip must not edit the past.
ok(SERVER.includes('for k, v in topics.items() if v'),
  'the renderer prints whichever stored topics are true, so a filed talk keeps covid19');

// ── 5. The step pips ────────────────────────────────────────────────────────
console.log('\n-- the pips mark, they never gate --');
ok(JSON.stringify(M.incompleteSteps({
  location: '', performedBy: '', checkedTopics: {}, attendees: [], cpSignature: '',
})) === '[1,2,3,4]', 'an untouched talk marks all four steps');
// STEP 1 NOW NEEDS ALL FIVE — it is the one gated step, so the pip and the
// gate must agree about what "complete" means or the CP is marked incomplete
// on a step the button let him leave.
ok(JSON.stringify(M.incompleteSteps({
  location: 'Gate', companyName: 'AAZ', typeOfWork: 'Demo',
  meetingTime: '07:30 AM', performedBy: 'CP', checkedTopics: { hard_hats: true },
  attendees: [{ name: 'W' }], cpSignature: 'sig',
})) === '[]', 'a complete, signed talk marks none');
ok(M.incompleteSteps({
  location: 'Gate', companyName: '', typeOfWork: 'Demo',
  meetingTime: '07:30 AM', performedBy: 'CP', checkedTopics: { hard_hats: true },
  attendees: [{ name: 'W' }], cpSignature: 'sig',
}).includes(1), 'one empty step-1 field marks step 1');
ok(M.topicCount({ hard_hats: true, gloves: false }) === 1, 'an unticked topic is not counted');
ok(M.namedAttendees([{ name: '' }, { name: 'W' }]).length === 1,
  'a nameless row is not an attendee — the same rule the renderer drops it by');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
