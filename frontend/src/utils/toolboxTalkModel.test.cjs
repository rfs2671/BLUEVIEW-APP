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

// ── 4. THE PORT CARRIED THE REST ────────────────────────────────────────────
console.log('\n-- what the port had to carry --');

for (const [needle, label] of [
  ['LogbookStepper', 'uses the shared stepper'],
  ['submitDisabled={!cpSignature}', 'an unsigned submit is UNREACHABLE (immediate type)'],
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
ok(M.ALL_TOPIC_KEYS.length === 22,
  `all topic keys are enumerated (got ${M.ALL_TOPIC_KEYS.length})`);

// ── 5. The step pips ────────────────────────────────────────────────────────
console.log('\n-- the pips mark, they never gate --');
ok(JSON.stringify(M.incompleteSteps({
  location: '', performedBy: '', checkedTopics: {}, attendees: [], cpSignature: '',
})) === '[1,2,3,4]', 'an untouched talk marks all four steps');
ok(JSON.stringify(M.incompleteSteps({
  location: 'Gate', performedBy: 'CP', checkedTopics: { hard_hats: true },
  attendees: [{ name: 'W' }], cpSignature: 'sig',
})) === '[]', 'a complete, signed talk marks none');
ok(M.topicCount({ hard_hats: true, gloves: false }) === 1, 'an unticked topic is not counted');
ok(M.namedAttendees([{ name: '' }, { name: 'W' }]).length === 1,
  'a nameless row is not an attendee — the same rule the renderer drops it by');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
