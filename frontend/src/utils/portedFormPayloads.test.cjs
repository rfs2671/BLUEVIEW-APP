/**
 * THE PAYLOAD KEYS SURVIVED THE PORT.
 *
 * osha_log and scaffold_maintenance were rebuilt onto the shared stepper. Both
 * are FILED LEGAL RECORDS: two PDF renderers in backend/server.py and the kiosk
 * inspector in app/site/logbooks.jsx read their payloads by key. A key renamed
 * or dropped during the rebuild does not crash anything — it silently empties a
 * column on a document a DOB inspector reads, and nothing on the device would
 * ever show it.
 *
 * So this file does not trust the port. It EXECUTES the real models, builds the
 * real payload, and checks every key against the renderer's own list read out
 * of server.py — not against a copy typed in here, which would drift.
 *
 * Run:  node src/utils/portedFormPayloads.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');
const SERVER = fs.readFileSync(
  path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
const KIOSK = fs.readFileSync(
  path.join(FRONTEND, 'app', 'site', 'logbooks.jsx'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── Load the ESM models under bare node ──────────────────────────────────────
// Same technique as i18n.test.cjs: imports stripped, evaluated with a stub for
// the one helper they reach for, so the REAL shipped functions run here.
function loadModel(rel, extra = '') {
  const src = fs.readFileSync(path.join(UTILS, rel), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default [\s\S]*$/m, '')
    .replace(/^export (const|function) /gm, '$1 ');
  const names = [...src.matchAll(/^(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)]
    .map((m) => m[1]);
  // eslint-disable-next-line no-new-func
  return new Function(`
    ${extra}
    ${src}
    return { ${[...new Set(names)].join(', ')} };
  `)();
}
const OSHA = loadModel('oshaLogModel.js',
  "const easternToday = () => '2026-08-12';");
const SCAF = loadModel('scaffoldMaintenanceModel.js');
// The same stripping, returned as SOURCE rather than evaluated — so a model
// that imports a shared helper can be handed the helper's REAL code as its
// preamble instead of a stub that could drift from it. checklistMap decides
// what "not recorded" means on five filed documents; a stub of it here would
// test the stub.
function modelSource(rel) {
  return fs.readFileSync(path.join(UTILS, rel), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default [\s\S]*$/m, '')
    .replace(/^export (const|function) /gm, '$1 ');
}
const CHECKLIST_SRC = modelSource('checklistMap.js');
const CHK = loadModel('checklistMap.js');
const CONC = loadModel('concreteOperationsModel.js', CHECKLIST_SRC);
const CRANE = loadModel('craneOperationsModel.js', CHECKLIST_SRC);
const EXC = loadModel('excavationMonitoringModel.js');
// hotWorkModel reaches into TimeField for the clock parser — the REAL one, not
// a stub, because the fire-watch default is derived from whatever the picker
// wrote and a stub that disagreed about the format would prove nothing. The
// component's two pure exports are lifted the same way the models are.
const TIMEFIELD_SRC = fs.readFileSync(
  path.join(FRONTEND, 'src', 'components', 'logbookStepper', 'TimeField.jsx'), 'utf8')
  .replace(/^import .*$/gm, '')
  .replace(/^export default [\s\S]*$/m, '')
  .replace(/^export (const|function) /gm, '$1 ');
const HW = loadModel('hotWorkModel.js', TIMEFIELD_SRC);
const SSC = loadModel('sscDailySafetyLogModel.js');

// ═══ OSHA LOG ════════════════════════════════════════════════════════════════
console.log('\n-- osha_log: data.entries[] --');

// The renderer's own key list, read out of the `elif log_type == "osha_log"`
// branch rather than copied. If it starts reading a key the model does not
// write, that is the bug this catches.
const oshaBranch = SERVER.slice(
  SERVER.indexOf('elif log_type == "osha_log":'),
  SERVER.indexOf('elif log_type == "subcontractor_orientation":'),
);
ok(oshaBranch.length > 0, 'located the osha_log branch of the PDF renderer');
const rendererKeys = [...new Set(
  [...oshaBranch.matchAll(/e\.get\("([a-z_]+)"/g)].map((m) => m[1]),
)].sort();
ok(rendererKeys.length >= 6,
  `the renderer reads ${rendererKeys.length} entry keys: ${rendererKeys.join(', ')}`);

// A row as the register actually builds one, from a real check-in shape.
const built = OSHA.buildEntriesFromCheckins([{
  worker_id: 'w1',
  worker_name: 'Ray Fisher',
  company: 'Kestrel Electric',
  certifications: [{ name: 'SST', card_number: 'SST-9931', expiry: '2027-04-01' }],
}], '2026-08-12');
ok(built.length === 1, 'one certification produces one row');
const row = built[0];
for (const k of rendererKeys) {
  ok(Object.prototype.hasOwnProperty.call(row, k),
    `entry carries "${k}" — the renderer reads it`);
}
ok(row.date === '2026-08-12',
  "the row is stamped with the LOG's date, not the device's today");
ok(row.card_number === 'SST-9931' && row.expiration === '2027-04-01',
  'card number and expiry come off the certification, not the worker');

// ONE ROW PER CERTIFICATION — the shape the operator approved.
const two = OSHA.buildEntriesFromCheckins([{
  worker_id: 'w2',
  worker_name: 'Sam Ortiz',
  certifications: [{ name: 'OSHA 30' }, { name: 'SST' }],
}], '2026-08-12');
ok(two.length === 2, 'a worker holding two cards is TWO rows, not one');

// A worker with nothing on file is still on the register.
const bare = OSHA.buildEntriesFromCheckins([{ worker_id: 'w3', worker_name: 'Lee' }], '2026-08-12');
ok(bare.length === 1 && bare[0].certification_type === '',
  'a worker with no certification is still recorded — an absent row reads as an absent worker');

// NO FABRICATED CARD CLASS — device round 4, finding 2, ruled.
//
// This branch used to write the literal 'OSHA 40hr' whenever a worker had an
// OSHA number, asserting a 40-hour credential onto a DOB record on the strength
// of a number being present. An OSHA number establishes that a card exists and
// nothing whatever about its class. The operator ruled it deleted outright:
// blank is honest, a credential nobody verified is not.
//
// It printed for real. /checkins-today hardcodes `certifications: []` on the
// gate pass (server.py:17499), so EVERY gate-sourced row took this branch —
// which is also why #131's certLabel/certExpiration fix looked half-applied:
// those functions were never reached.
const numbered = OSHA.buildEntriesFromCheckins(
  [{ worker_id: 'w5', worker_name: 'Mora', osha_number: '4YU1RY8KKM' }], '2026-08-12');
ok(numbered[0].certification_type === '',
  'a worker with only an OSHA NUMBER gets NO card class — the number proves a card, not a class');
ok(numbered[0].card_number === '4YU1RY8KKM',
  'the number itself is still recorded — it is a fact, and the only one there is');
ok(numbered[0].expiration === '',
  'and the expiry stays blank until real card data exists to fill it');
ok(!/OSHA 40hr/.test(String(OSHA.buildEntriesFromCheckins(
  [{ worker_id: 'w6', worker_name: 'X', osha_number: '1' }], '2026-08-12')
  .map((r) => r.certification_type).join('|'))),
  'the literal cannot come back through this path unnoticed');
// Still reached when a row DOES carry cards — the fix removed a fabrication,
// not the real translation.
ok(OSHA.buildEntriesFromCheckins([{
  worker_id: 'w7', worker_name: 'Y', osha_number: '9',
  certifications: [{ type: 'OSHA_30', card_number: 'C9', expiration_date: '2027-04-01T00:00:00Z' }],
}], '2026-08-12')[0].certification_type === 'OSHA 30',
  'a row with real certifications still translates through certLabel');

// A gate refusal is recorded as DENIED and never as a certification.
const blocked = OSHA.buildEntriesFromCheckins([{
  worker_id: 'w4', worker_name: 'Pat', blocked: true, blocks: ['CERT_BLOCK'],
}], '2026-08-12');
ok(blocked[0].certification_type === 'MISSING OSHA' && blocked[0].blocked === true,
  'a worker turned away at the gate is DENIED, not credited with a card');
ok(blocked[0].card_number === '' && blocked[0].expiration === '',
  'and carries no card number — the gate established that he had none');

// The screen's FILING rule must agree with the renderer's drop rule, and as of
// device round 6 both are the worker name: a row carrying a card number and a
// signature mark against nobody is not an incomplete record of somebody, it is
// an assertion about a man the document does not identify. entryHasContent
// stayed behind as the TOUCHED question, which is what the row pip reads.
ok(OSHA.entryHasContent(row) === true, 'a real row counts as touched');
ok(OSHA.entryHasContent(OSHA.EMPTY_ENTRY()) === false,
  'an untouched EMPTY_ENTRY does NOT');
const dropFields = [...new Set(
  [...oshaBranch.matchAll(/has\(e, k\) for k in\s*\n?\s*\(([^)]*)\)/g)]
    .flatMap((m) => [...m[1].matchAll(/"([a-z_]+)"/g)].map((x) => x[1])),
)].sort();
ok(JSON.stringify(dropFields) === '["worker_name"]',
  `the renderer drops a row that names nobody (${dropFields.join(', ')})`);
for (const f of dropFields) {
  const probe = { ...OSHA.EMPTY_ENTRY(), [f]: 'x' };
  ok(OSHA.entryNamesWorker(probe) === true,
    `entriesForFiling agrees with the renderer on "${f}"`);
}
ok(OSHA.entriesForFiling([{ ...OSHA.EMPTY_ENTRY(), company: 'AAZ', card_number: 'C1' }])
  .length === 0,
  'and a company + card number with no name is filed by neither');

// The payload wrapper.
ok(JSON.stringify(Object.keys(OSHA.draftBody([]))) === '["entries"]',
  'the payload body is exactly { entries } — the key the renderer opens');

// The pips.
ok(JSON.stringify(OSHA.incompleteSteps({ entries: [], cpSignature: '' })) === '[1,2]',
  'an empty register marks both steps incomplete');
ok(JSON.stringify(OSHA.incompleteSteps({ entries: built, cpSignature: 'sig' })) === '[]',
  'a filled and signed register marks none');

// ── THE KEYS THE BACKEND ACTUALLY SENDS ─────────────────────────────────────
//
// This model read cert.name and cert.expiry. A stored certification carries
// `type` and `expiration_date` (server.py:2006-2016), passed through untouched
// by /checkins-today (:17559). So every auto-built row printed a BLANK
// certification type and a BLANK expiry on the filed register.
console.log('\n-- osha_log: the cert keys --');

const REAL_CERT = {
  type: 'SST_SUPERVISOR', card_number: '4YU1RY8KKM',
  issue_date: null, expiration_date: '2030-04-01T00:00:00Z',
  verified: false, needs_review: false,
};
const built1 = OSHA.buildEntriesFromCheckins([{
  worker_id: 'w1', worker_name: 'WILMER CARRILLO', company: 'AAZ',
  certifications: [REAL_CERT],
}], '2026-08-14')[0];

ok(built1.certification_type === 'SST Supervisor',
  `the stored type reaches the register (got ${JSON.stringify(built1.certification_type)})`);
ok(built1.expiration === '2030-04-01',
  `and so does the expiry (got ${JSON.stringify(built1.expiration)})`);
ok(built1.card_number === '4YU1RY8KKM', 'the card number still matches, as it always did');

// The regression itself, stated as a thing that must not come back.
ok(built1.certification_type !== '' && built1.expiration !== '',
  'neither column is blank — that blank pair is what printed on the filed document');

// Legacy / hand-entered rows may carry the OLD keys. Reading the new ones must
// not throw away a value that IS there.
const legacyCert = { name: 'SST', card_number: 'L1', expiry: '2029-01-15' };
const built2 = OSHA.buildEntriesFromCheckins([{
  worker_id: 'w2', worker_name: 'Legacy Man', certifications: [legacyCert],
}], '2026-08-14')[0];
ok(built2.certification_type === 'SST', 'a legacy `name` is still read');
ok(built2.expiration === '2029-01-15', 'and a legacy `expiry` is still read');

// NO CLASS IS INFERRED — that is Part 3A, deliberately not touched here.
ok(OSHA.certLabel({ type: 'SST_UNSPECIFIED' }) === 'SST_UNSPECIFIED',
  'an unreadable class is NOT dressed up as a class — it prints verbatim');
ok(OSHA.certLabel({ type: 'SOMETHING_NEW' }) === 'SOMETHING_NEW',
  'and an unknown code passes through rather than being guessed at');
ok(OSHA.certLabel({}) === '' && OSHA.certExpiration({}) === '',
  'a cert with neither key yields blanks, not "undefined"');
ok(OSHA.certExpiration({ expiration_date: null }) === '',
  'a null expiry is blank, not the string "null"');
ok(OSHA.certExpiration({ expiration_date: 'not a date' }) === 'not a date',
  'an unparseable value is echoed as stored — the CP may still need to see it');

// ── THE PRODUCTION DEFECT: a certification filed against the wrong man ───────
//
// Project 6a5f63bc147407d3261df2c7, 2026-08-11. worker_id
// 6a79b9f19d8cee518e4712c4 appeared TWICE in a signed register — once as the
// man the gate recorded, once as a different man entirely — and a third row
// was wholly empty. Reproduced here from that shape, not paraphrased.
console.log('\n-- osha_log: a row never carries another man\'s id --');

const WID = '6a79b9f19d8cee518e4712c4';

// The register auto-builds ONE ROW PER CERTIFICATION, which is how one
// worker_id legitimately reaches two rows. That is the shape the CP misread.
const wilmerTwoCards = OSHA.buildEntriesFromCheckins([{
  worker_id: WID,
  worker_name: 'WILMER CARRILLO',
  company: 'AAZ',
  certifications: [{ name: 'SST' }, { name: 'OSHA 30' }],
}], '2026-08-11');
ok(wilmerTwoCards.length === 2 && wilmerTwoCards.every((e) => e.worker_id === WID),
  'two certifications produce two rows carrying the SAME worker_id — the approved shape');
ok(OSHA.sharedWorkerIds(wilmerTwoCards).has(WID),
  'and the screen can see they are the same man, so it can say so instead of looking duplicated');
ok(OSHA.sharedWorkerIds(wilmerTwoCards.slice(0, 1)).size === 0,
  'one row for a worker is not flagged as shared');
ok(OSHA.sharedWorkerIds([{ worker_id: null }, { worker_id: null }]).size === 0,
  'and unlinked rows are never treated as the same man');

// THE DEFECT. Typing a second man's name over one of those rows used to leave
// the first man's id on it.
const overtyped = OSHA.applyEntryEdit(wilmerTwoCards[1], 'worker_name', 'Segundo pilamunga ');
ok(overtyped.worker_id === null,
  'editing the name DETACHES the worker_id — the row stops claiming to be Wilmer');
ok(overtyped.worker_name === 'Segundo pilamunga ',
  'and the typed name is kept exactly as entered, trailing space and all');

// The old behaviour, stated as the thing that must never come back.
ok(!(OSHA.applyEntryEdit(wilmerTwoCards[1], 'worker_name', 'Segundo').worker_id === WID),
  "Segundo's certification can never be filed against Wilmer's worker record");

// Editing anything ELSE is not an identity change and must not detach.
for (const f of ['company', 'certification_type', 'card_number', 'expiration', 'signed']) {
  ok(OSHA.applyEntryEdit(wilmerTwoCards[0], f, 'x').worker_id === WID,
    `editing "${f}" does NOT detach the id — it is not a claim about who this is`);
}
// A no-op edit is not an edit.
ok(OSHA.applyEntryEdit(wilmerTwoCards[0], 'worker_name', 'WILMER CARRILLO').worker_id === WID,
  're-entering the same name detaches nothing');
ok(OSHA.applyEntryEdit(wilmerTwoCards[0], 'worker_name', '  WILMER CARRILLO  ').worker_id === WID,
  'and neither does whitespace around it');
// A row that never had an id cannot lose one, and must not gain one.
ok(OSHA.applyEntryEdit(OSHA.EMPTY_ENTRY(), 'worker_name', 'Anyone').worker_id === null,
  'a manually added row stays unlinked — null is honest, the app cannot identify him');

console.log('\n-- osha_log: an empty row cannot be filed --');

// The third production row: worker_id null, every field blank, company only.
const abandoned = { ...OSHA.EMPTY_ENTRY(), company: 'AAZ' };
ok(OSHA.entryHasContent(abandoned) === true,
  'a row with only a company still counts as content — the CP typed something');
const trulyEmpty = OSHA.EMPTY_ENTRY();
ok(OSHA.entryHasContent(trulyEmpty) === false, 'a row with nothing typed does not');
const mixed = [...wilmerTwoCards, trulyEmpty, OSHA.EMPTY_ENTRY()];
ok(OSHA.entriesForFiling(mixed).length === 2,
  'filing drops the abandoned rows and keeps the real ones');
ok(OSHA.entriesForFiling([]).length === 0 && OSHA.entriesForFiling(null).length === 0,
  'and it is safe on an empty or missing register');
// The filed register and the printed register must contain the same rows.
ok(OSHA.entriesForFiling(mixed).every((e) => OSHA.entryHasContent(e)),
  'every filed row passes the same rule the PDF renderer drops rows by');

// ═══ SCAFFOLD MAINTENANCE ════════════════════════════════════════════════════
console.log('\n-- scaffold_maintenance: data.general_info + data.answers --');

const scafBranch = SERVER.slice(
  SERVER.indexOf('elif log_type == "scaffold_maintenance":'),
  SERVER.indexOf('elif log_type == "ssc_daily_safety_log":'),
);
ok(scafBranch.length > 0, 'located the scaffold_maintenance branch of the PDF renderer');

// THE 19 QUESTIONS, key AND label, read out of the renderer's own tuple list.
// The label must match word for word: the device and the filed PDF have to ask
// the same question, or the CP answered something the document does not say.
const serverQs = [...scafBranch.matchAll(/\("([a-z_]+)",\s*"([^"]+)"\),/g)]
  .map((m) => ({ key: m[1], label: m[2] }));
ok(serverQs.length === 19, `the renderer lists 19 questions (got ${serverQs.length})`);
ok(SCAF.MAINTENANCE_QUESTIONS.length === 19,
  `the model lists 19 questions (got ${SCAF.MAINTENANCE_QUESTIONS.length})`);
const qMismatch = serverQs.filter((q, i) => (
  SCAF.MAINTENANCE_QUESTIONS[i].key !== q.key
  || SCAF.MAINTENANCE_QUESTIONS[i].label !== q.label
));
ok(qMismatch.length === 0,
  `every question matches the renderer, key and label and ORDER${qMismatch.length ? ` — ${JSON.stringify(qMismatch.slice(0, 3))}` : ''}`);

// drawings_on_site is question 19 and is NOT a general_info key.
ok(SCAF.MAINTENANCE_QUESTIONS[18].key === 'drawings_on_site',
  'drawings_on_site is question 19, where the CP answers it');
ok(!SCAF.GENERAL_INFO_KEYS.includes('drawings_on_site'),
  'and it is NOT a general_info key — nothing on this form seeds an answer');
ok(!Object.prototype.hasOwnProperty.call(SCAF.EMPTY_GENERAL_INFO(), 'drawings_on_site'),
  'the blank general_info does not carry it either');

// The nine general_info keys the renderer prints, read out of field_lines.
const giBlock = scafBranch.slice(scafBranch.indexOf('field_lines(gi, ['));
const serverGiKeys = [...new Set(
  [...giBlock.matchAll(/\("([a-z_]+)",\s*"[^"]*",\s*_/g)].map((m) => m[1]),
)];
ok(serverGiKeys.length === 9,
  `the renderer prints 9 general_info fields (got ${serverGiKeys.length})`);
const missingGi = serverGiKeys.filter((k) => !SCAF.GENERAL_INFO_KEYS.includes(k));
ok(missingGi.length === 0,
  `the model writes every field the renderer prints${missingGi.length ? ` — MISSING ${JSON.stringify(missingGi)}` : ''}`);
const blank = SCAF.EMPTY_GENERAL_INFO();
for (const k of serverGiKeys) {
  ok(Object.prototype.hasOwnProperty.call(blank, k),
    `general_info carries "${k}" from the moment the form opens`);
}

// Prefill takes the nine and nothing else — a stray project field must not
// ride into a signed log.
const filled = SCAF.prefillFromScaffoldInfo({
  scaffold_erector: 'Vanguard', permit_number: 'P-1', shed_type: 'Light',
  drawings_on_site: 'YES', something_else: 'x',
});
ok(filled.scaffold_erector === 'Vanguard' && filled.shed_type === 'Light',
  'prefill carries the shed forward from project memory');
ok(!('drawings_on_site' in filled) && !('something_else' in filled),
  'and drops everything that is not one of the nine — including a legacy drawings_on_site');
ok(SCAF.prefillFromScaffoldInfo({}).shed_type === 'Heavy',
  'shed_type defaults to Heavy when memory holds none');
ok(SCAF.prefillFromScaffoldInfo(null).scaffold_erector === '',
  'a failed getScaffoldInfo yields a blank form, not a crash');

// The project write must drop undefined, or update_scaffold_info stores null
// over whatever the project already had.
const forSave = SCAF.scaffoldInfoForSave({ a: 'x', b: undefined, c: '' });
ok(!('b' in forSave) && forSave.c === '',
  'undefined keys are dropped before the project write; empty strings are NOT');

// The payload wrapper.
ok(JSON.stringify(Object.keys(SCAF.draftBody({}, {}))) === '["general_info","answers"]',
  'the payload body is exactly { general_info, answers }');

// Answers are the three strings the renderer prints, never booleans.
ok(JSON.stringify(SCAF.ANSWER_OPTIONS) === '["YES","NO","N/A"]',
  'the three answers are strings — an N/A the CP CHOSE is a real answer');
ok(/ANSWER_OPTIONS :\d+ = YES\/NO\/N\/A/.test(SERVER)
  || scafBranch.includes('YES / NO / N/A'),
  'and the renderer says so too');

// The pips.
ok(JSON.stringify(SCAF.incompleteSteps({ generalInfo: {}, answers: {}, cpSignature: '' })) === '[1,2,3]',
  'an untouched inspection marks all three steps incomplete');
const allAnswered = {};
for (const q of SCAF.MAINTENANCE_QUESTIONS) allAnswered[q.key] = 'YES';
ok(JSON.stringify(SCAF.incompleteSteps({
  generalInfo: { scaffold_erector: 'V' }, answers: allAnswered, cpSignature: 'sig',
})) === '[]', 'a complete, signed inspection marks none');
ok(SCAF.incompleteSteps({
  generalInfo: { scaffold_erector: 'V' },
  answers: { signs_on_parapets: 'YES' },
  cpSignature: 'sig',
}).includes(2), 'ONE of nineteen answered still marks the checks incomplete');
ok(SCAF.answeredCount({ signs_on_parapets: 'N/A' }) === 1,
  'N/A counts as answered — it is a real answer');
ok(SCAF.answeredCount({ signs_on_parapets: '' }) === 0,
  'a blank does not');

// ── THE SCREEN IS ACTUALLY WIRED TO ALL THAT ────────────────────────────────
//
// A correct model behind an unwired screen ships the same defect. These assert
// the editor reaches identity and filing through the model and nowhere else.
console.log('\n-- osha_log.jsx uses the model, not its own spread --');

const OSHA_SCREEN = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'osha_log.jsx'), 'utf8');

ok(/applyEntryEdit\(e, field, value\)/.test(OSHA_SCREEN),
  'updateEntry goes through applyEntryEdit');
ok(!/i === index \? \{ \.\.\.e, \[field\]: value \}/.test(OSHA_SCREEN),
  'and the raw spread that lost the id is GONE — it cannot come back unnoticed');
ok(/entriesForFiling\(rows\)/.test(OSHA_SCREEN),
  'the submitted payload is trimmed to rows with content');
ok(/submitStatus === 'submitted' \? entriesForFiling\(rows\) : rows/.test(OSHA_SCREEN),
  'a DRAFT keeps every row — a half-typed row must survive a save');
ok(/submitDisabled=\{!isAffirmedSignature\(cpSignature\) \|\| filledRows === 0\}/.test(OSHA_SCREEN),
  'an empty register cannot be filed, restoring the guard the #123 port dropped');
ok(/sharedWorkerIds\(entries\)/.test(OSHA_SCREEN)
  && /sameWorkerNote/.test(OSHA_SCREEN),
  'two rows for one man are labelled as his two cards, not left looking duplicated');
ok(/unlinkedNote/.test(OSHA_SCREEN),
  'and a row that has lost its id says so');

// ═══ THE THREE READERS, PULLED OUT OF THEIR OWN SOURCE ═══════════════════════
//
// concrete_operations and crane_operations are read by THREE surfaces, not one:
// the filed-PDF renderer, generate_combined_report, and the kiosk inspector.
// None of them would crash on a renamed key — each would quietly print an empty
// section on a document a DOB inspector reads.
//
// So the key lists below are not typed here. They are EXTRACTED from each
// reader's own source, and the model is checked against the union. A key that
// only two of the three read is still a key the payload must carry.

/** The `elif log_type == "X":` arm of render_logbook_pdf. */
function pdfBranch(logType, nextLogType) {
  const a = SERVER.indexOf(`elif log_type == "${logType}":`);
  const b = SERVER.indexOf(`elif log_type == "${nextLogType}":`);
  return (a > -1 && b > a) ? SERVER.slice(a, b) : '';
}
/** The `X_lb = _filed_log(logbooks, "X")` arm of generate_combined_report. */
function reportBranch(logType, endMarker) {
  const a = SERVER.indexOf(`_filed_log(logbooks, "${logType}")`);
  const b = SERVER.indexOf(endMarker, a + 1);
  return (a > -1 && b > a) ? SERVER.slice(a, b) : '';
}
/** One `const renderX = (log) => {` block of app/site/logbooks.jsx. */
function kioskBranch(name, nextName) {
  const a = KIOSK.indexOf(`const ${name} = (log) => {`);
  const b = KIOSK.indexOf(`const ${nextName} = (log) => {`);
  return (a > -1 && b > a) ? KIOSK.slice(a, b) : '';
}
const uniq = (xs) => [...new Set(xs)].sort();
const grab = (src, re) => [...src.matchAll(re)].map((m) => m[1]);

/** Every TOP-LEVEL payload key a PDF branch reads. */
function pdfTopKeys(branch) {
  return uniq([
    ...grab(branch, /data\.get\("([a-z_]+)"/g),
    // field_lines' 3-tuples: ("key", "Label", _formatter),
    ...grab(branch, /\("([a-z_]+)",\s*"[^"]*",\s*_/g),
    ...grab(branch, /toggle_block\(data,\s*"([a-z_]+)"/g),
  ]);
}
/** Every top-level key a combined-report branch reads. */
const reportTopKeys = (branch) => uniq(grab(branch, /\bd\.get\("([a-z_]+)"/g));
/**
 * Every top-level key a kiosk renderer reads.
 *
 * The `['key', t('…')]` pair shape is used TWICE in these blocks: by DocFields
 * for top-level payload fields, and by ToggleTable for the items INSIDE a
 * checklist map. Scanning the whole block would hand back the fifteen crane
 * check keys as if they were payload keys, so the pair scan is confined to the
 * `specs={[…]}` list and the slice is asserted non-empty.
 */
function kioskSpecs(branch) {
  const a = branch.indexOf('specs={[');
  const b = branch.indexOf(']}', a);
  return (a > -1 && b > a) ? branch.slice(a, b) : '';
}
function kioskTopKeys(branch) {
  return uniq([
    ...grab(branch, /\bdata\.([a-z_]+)/g),
    ...grab(kioskSpecs(branch), /\['([a-z_]+)',\s*t\(/g),
  ]);
}
/** The two-tuple checklists a renderer prints verbatim: [key, label]. */
const tupleList = (branch) => [...branch.matchAll(/\("([a-z_]+)",\s*"([^"]+)"\),/g)]
  .map((m) => ({ key: m[1], label: m[2] }));

/**
 * The model carries every key all three readers open, and the readers were
 * actually FOUND — an empty branch would make every assertion below vacuous,
 * which is the exact shape assertionsCanFail.test.cjs exists to catch.
 */
function assertPayloadCovers(label, body, sources) {
  const all = uniq(sources.flatMap(([name, branch, keys]) => {
    ok(branch.length > 0, `${label}: located the ${name}`);
    ok(keys.length > 0, `${label}: the ${name} reads ${keys.length} top-level keys`);
    return keys;
  }));
  const missing = all.filter((k) => !Object.prototype.hasOwnProperty.call(body, k));
  ok(missing.length === 0,
    `${label}: the payload carries every key the three readers open${missing.length ? ` — MISSING ${JSON.stringify(missing)}` : ''}`);
  return all;
}

// ═══ CONCRETE OPERATIONS ═════════════════════════════════════════════════════
console.log('\n-- concrete_operations: the eight top-level keys --');

const concPdf = pdfBranch('concrete_operations', 'scaffold_maintenance');
const concReport = reportBranch('concrete_operations', 'handled_types = {');
const concKiosk = kioskBranch('renderConcreteOperations', 'renderScaffoldMaintenance');

const concBody = CONC.draftBody({}, [], {});
ok(kioskSpecs(concKiosk).length > 0,
  'concrete_operations: the kiosk DocFields specs list was found, not silently empty');
const concKeys = assertPayloadCovers('concrete_operations', concBody, [
  ['PDF renderer', concPdf, pdfTopKeys(concPdf)],
  ['combined report', concReport, reportTopKeys(concReport)],
  ['kiosk inspector', concKiosk, kioskTopKeys(concKiosk)],
]);
ok(concKeys.length === 8,
  `all three readers together open 8 keys (${concKeys.join(', ')})`);
// A BLANK FORM ALREADY CARRIES THEM ALL. A scalar that only appears once it is
// typed is a scalar that can go missing from a filed document.
ok(CONC.DETAIL_KEYS.every((k) => concBody[k] === ''),
  'every scalar is present and empty on an untouched pour, not absent');
ok(Array.isArray(concBody.slump_tests) && !concBody.slump_tests.length,
  'slump_tests is an empty ARRAY, the shape the renderers iterate');
ok(concBody.formwork_checklist && !Object.keys(concBody.formwork_checklist).length,
  'formwork_checklist is an empty MAP — every item unrecorded, which is where it starts');

// THE FOUR FORMWORK ITEMS, key AND label, out of BOTH renderers' own lists.
// The label must match word for word: the device and the filed PDF have to ask
// the same thing, or the CP answered something the document does not say.
for (const [name, branch] of [['PDF renderer', concPdf], ['combined report', concReport]]) {
  const items = tupleList(branch);
  ok(items.length === 4, `${name} lists 4 formwork items (got ${items.length})`);
  const bad = items.filter((q, i) => (
    CONC.FORMWORK_ITEMS[i]?.key !== q.key || CONC.FORMWORK_ITEMS[i]?.label !== q.label
  ));
  ok(bad.length === 0,
    `the model matches the ${name}, key and label and ORDER${bad.length ? ` — ${JSON.stringify(bad)}` : ''}`);
}

console.log('\n-- concrete_operations: a slump row, and the renderer\'s drop rule --');

// THE SCREEN'S RULE MUST BE THE RENDERER'S RULE. server.py:13428 drops a row
// with `not t and not v and p is None`; the three fields it names are read out
// of that condition rather than copied, and slumpHasContent is executed against
// each of them. If the screen disagreed, a filed row would print where the CP
// saw none, or vanish where he saw one.
const slumpDropFields = uniq([
  ...grab(concPdf, /st\.get\("([a-z_]+)"/g),
  ...grab(concKiosk, /\bst\.([a-z_]+)/g),
]);
ok(slumpDropFields.length === 3,
  `the renderers read 3 slump fields (${slumpDropFields.join(', ')})`);
for (const f of slumpDropFields) {
  ok(Object.prototype.hasOwnProperty.call(CONC.EMPTY_SLUMP_TEST(), f),
    `EMPTY_SLUMP_TEST carries "${f}" — the renderer reads it`);
}
ok(CONC.slumpHasContent(CONC.EMPTY_SLUMP_TEST()) === false,
  'an untouched EMPTY_SLUMP_TEST is NOT content — the same rule the renderer drops it by');
ok(CONC.slumpHasContent({ ...CONC.EMPTY_SLUMP_TEST(), time: '09:30 AM' }) === true,
  'a time alone is content');
ok(CONC.slumpHasContent({ ...CONC.EMPTY_SLUMP_TEST(), value: '4' }) === true,
  'a slump value alone is content');
ok(CONC.slumpHasContent({ ...CONC.EMPTY_SLUMP_TEST(), pass: false }) === true,
  'a recorded FAIL with no time and no value is still content — dropping it would '
  + 'delete a failed test off a pour record');
ok(CONC.slumpHasContent({ ...CONC.EMPTY_SLUMP_TEST(), time: '   ' }) === false,
  'and whitespace is not, which is how the renderer strips it too');

// `pass` IS TRI-STATE, and the third state has to be reachable.
ok(CONC.EMPTY_SLUMP_TEST().pass === null,
  'a fresh row is seeded null — unrecorded, which both renderers print as nothing');
const p1 = CONC.applySlumpResult(CONC.EMPTY_SLUMP_TEST(), true);
ok(p1.pass === true, 'tapping PASS records a pass');
ok(CONC.applySlumpResult(p1, false).pass === false, 'tapping FAIL over it records a fail');
ok(CONC.applySlumpResult(p1, true).pass === null,
  'tapping the CHOSEN result again clears it back to null — the seeded state has to be '
  + 'reachable, or a mis-tapped Fail can only be removed by deleting the row');
ok(CONC.applySlumpResult(CONC.applySlumpResult(p1, false), false).pass === null,
  'and the same holds from FAIL');
ok(CONC.applySlumpResult({ time: '08:00 AM', value: '5', pass: null }, true).time === '08:00 AM',
  'setting a result touches nothing else on the row');

// Filing drops the seeds and keeps the tests.
const slumpMixed = [
  { time: '09:30 AM', value: '4', pass: true },
  CONC.EMPTY_SLUMP_TEST(),
  { time: '', value: '', pass: false },
];
ok(CONC.slumpTestsForFiling(slumpMixed).length === 2,
  'filing drops the untouched seed and keeps both real tests');
ok(CONC.slumpTestsForFiling(slumpMixed).every((r) => CONC.slumpHasContent(r)),
  'every filed row passes the same rule the renderers drop rows by');
ok(CONC.slumpTestsForFiling(null).length === 0 && CONC.slumpTestsForFiling(undefined).length === 0,
  'and it is safe on a missing table');

console.log('\n-- concrete_operations: the pips --');

ok(JSON.stringify(CONC.incompleteSteps({
  details: {}, slumpTests: [], formworkChecklist: {}, cpSignature: '',
})) === '[1,2,3,4]', 'an untouched pour marks all four steps incomplete');
const concFull = {};
for (const it of CONC.FORMWORK_ITEMS) concFull[it.key] = true;
ok(JSON.stringify(CONC.incompleteSteps({
  details: { pour_location: '3rd floor slab' },
  slumpTests: [{ time: '09:30 AM', value: '4', pass: true }],
  formworkChecklist: concFull,
  cpSignature: 'sig',
})) === '[]', 'a filled and signed pour marks none');
ok(CONC.incompleteSteps({
  details: { pour_location: 'x' },
  slumpTests: [{ time: '09:30 AM', value: '4', pass: true }],
  formworkChecklist: { shores_plumb: false },
  cpSignature: 'sig',
}).includes(3), 'ONE of four formwork items answered still marks the inspection incomplete');
ok(!CONC.incompleteSteps({
  details: { pour_location: 'x' },
  slumpTests: [{ time: '09:30 AM', value: '4', pass: true }],
  formworkChecklist: Object.fromEntries(CONC.FORMWORK_ITEMS.map((it) => [it.key, false])),
  cpSignature: 'sig',
}).includes(3), 'four NOs is a COMPLETE inspection — a No is an answer');

// ═══ CRANE OPERATIONS ════════════════════════════════════════════════════════
console.log('\n-- crane_operations: the six top-level keys --');

const cranePdf = pdfBranch('crane_operations', 'excavation_monitoring');
const craneReport = reportBranch('crane_operations', '_filed_log(logbooks, "excavation_monitoring")');
const craneKiosk = kioskBranch('renderCraneOperations', 'renderExcavationMonitoring');

const craneBody = CRANE.draftBody({}, {}, []);
ok(kioskSpecs(craneKiosk).length > 0,
  'crane_operations: the kiosk DocFields specs list was found, not silently empty');
const craneKeys = assertPayloadCovers('crane_operations', craneBody, [
  ['PDF renderer', cranePdf, pdfTopKeys(cranePdf)],
  ['combined report', craneReport, reportTopKeys(craneReport)],
  ['kiosk inspector', craneKiosk, kioskTopKeys(craneKiosk)],
]);
ok(craneKeys.length === 6,
  `all three readers together open 6 keys (${craneKeys.join(', ')})`);
ok(CRANE.DETAIL_KEYS.every((k) => craneBody[k] === ''),
  'every scalar is present and empty on an untouched crane log, not absent');
ok(Array.isArray(craneBody.load_entries) && !craneBody.load_entries.length,
  'load_entries is an empty ARRAY, the shape the renderers iterate');
ok(craneBody.pre_operation_checklist
  && !Object.keys(craneBody.pre_operation_checklist).length,
  'pre_operation_checklist is an empty MAP — every check unrecorded, which is where it starts');

// THE FIFTEEN PRE-OP CHECKS, key AND label, out of BOTH renderers' own lists.
for (const [name, branch] of [['PDF renderer', cranePdf], ['combined report', craneReport]]) {
  const items = tupleList(branch);
  ok(items.length === 15, `${name} lists 15 pre-operation checks (got ${items.length})`);
  const bad = items.filter((q, i) => (
    CRANE.PRE_OP_CHECKLIST_ITEMS[i]?.key !== q.key
    || CRANE.PRE_OP_CHECKLIST_ITEMS[i]?.label !== q.label
  ));
  ok(bad.length === 0,
    `the model matches the ${name}, key and label and ORDER${bad.length ? ` — ${JSON.stringify(bad)}` : ''}`);
}

console.log('\n-- crane_operations: a lift row, and the renderer\'s drop rule --');

// The four fields all three readers test a row's emptiness by, read out of
// their own conditions rather than copied.
const liftDropFields = uniq([
  ...grab(cranePdf, /le\.get\("([a-z_]+)"/g),
  ...grab(craneReport, /le\.get\("([a-z_]+)"/g),
  ...grab(craneKiosk, /\ble\.([a-z_]+)/g),
]);
ok(liftDropFields.length === 4,
  `the renderers read 4 lift fields (${liftDropFields.join(', ')})`);
ok(JSON.stringify([...CRANE.LOAD_ENTRY_KEYS].sort()) === JSON.stringify(liftDropFields),
  'and the model names exactly those four');
for (const f of liftDropFields) {
  ok(Object.prototype.hasOwnProperty.call(CRANE.EMPTY_LOAD_ENTRY(), f),
    `EMPTY_LOAD_ENTRY carries "${f}" — the renderer reads it`);
  ok(CRANE.loadEntryHasContent({ ...CRANE.EMPTY_LOAD_ENTRY(), [f]: 'x' }) === true,
    `loadEntryHasContent agrees with the renderer on "${f}"`);
}
ok(CRANE.loadEntryHasContent(CRANE.EMPTY_LOAD_ENTRY()) === false,
  'an untouched EMPTY_LOAD_ENTRY is NOT a lift — the same rule the renderer drops it by');
ok(CRANE.loadEntryHasContent({ ...CRANE.EMPTY_LOAD_ENTRY(), radius: '  ' }) === false,
  'and whitespace is not a lift either');
ok(CRANE.loadEntryHasContent(null) === false && CRANE.loadEntryHasContent('x') === false,
  'a non-row is never a lift');

const liftMixed = [
  { time: '07:15 AM', description: 'Rebar bundle', load_weight: '2400', radius: '60' },
  CRANE.EMPTY_LOAD_ENTRY(),
  { time: '', description: 'Formwork panels', load_weight: '', radius: '' },
];
ok(CRANE.loadEntriesForFiling(liftMixed).length === 2,
  'filing drops the untouched seed and keeps both real lifts');
ok(CRANE.filledLiftCount(liftMixed) === 2, 'and the screen counts the same two');
ok(CRANE.loadEntriesForFiling([]).length === 0 && CRANE.loadEntriesForFiling(null).length === 0,
  'and it is safe on an empty or missing log');

console.log('\n-- crane_operations: the pips --');

ok(JSON.stringify(CRANE.incompleteSteps({
  details: {}, preOpChecklist: {}, loadEntries: [], cpSignature: '',
})) === '[1,2,3,4]', 'an untouched crane log marks all four steps incomplete');
const craneFull = {};
for (const it of CRANE.PRE_OP_CHECKLIST_ITEMS) craneFull[it.key] = true;
ok(JSON.stringify(CRANE.incompleteSteps({
  details: { crane_type: 'Tower Crane' },
  preOpChecklist: craneFull,
  loadEntries: liftMixed,
  cpSignature: 'sig',
})) === '[]', 'a filled and signed crane log marks none');
ok(CRANE.incompleteSteps({
  details: { crane_type: 'Tower Crane' },
  preOpChecklist: { wire_ropes: true },
  loadEntries: liftMixed,
  cpSignature: 'sig',
}).includes(2), 'ONE of fifteen checks answered still marks the pre-lift walk incomplete');

// ═══ EXCAVATION MONITORING ═══════════════════════════════════════════════════
console.log('\n-- excavation_monitoring: the nine top-level keys --');

const excPdf = pdfBranch('excavation_monitoring', 'concrete_operations');
const excReport = reportBranch('excavation_monitoring', '_filed_log(logbooks, "scaffold_maintenance")');
const excKiosk = kioskBranch('renderExcavationMonitoring', 'renderConcreteOperations');

ok(kioskSpecs(excKiosk).length > 0,
  'excavation_monitoring: the kiosk DocFields specs list was found, not silently empty');
const excBody = EXC.draftBody({}, []);
const excKeys = assertPayloadCovers('excavation_monitoring', excBody, [
  ['PDF renderer', excPdf, pdfTopKeys(excPdf)],
  ['combined report', excReport, reportTopKeys(excReport)],
  ['kiosk inspector', excKiosk, kioskTopKeys(excKiosk)],
]);
ok(excKeys.length === 9,
  `all three readers together open 9 keys (${excKeys.join(', ')})`);

// ── THE TWO DERIVED VALUES ARE IN THE PAYLOAD FROM THE FIRST AUTOSAVE ───────
//
// THE DEFECT THIS CLOSES. The screen computed `delta` and
// `vibration_over_threshold` in its SAVE handler only, so the debounced
// autosave wrote a draft carrying neither. The offline drain pushes the DRAFT,
// and server.py gates the whole Status line on `has(data,
// "vibration_over_threshold")` — so a log that reached the server through the
// drain rather than through Submit printed "— Not recorded" over two perfectly
// good readings. draftBody derives both, so there is no second shape.
console.log('\n-- excavation_monitoring: the derived pair, on every path --');

ok(Object.prototype.hasOwnProperty.call(excBody, 'vibration_over_threshold'),
  'an UNTOUCHED log already carries vibration_over_threshold — the autosave path '
  + 'used to omit it, and the drain pushes what the autosave wrote');
ok(excBody.vibration_over_threshold === false,
  'and it is a real boolean, which is what the renderer branches on');
const excGate = /has\(data, "vibration_over_threshold"\)/.test(excPdf);
ok(excGate,
  'the renderer still gates the Status line on the key being present');

const excWithRows = EXC.draftBody(
  { vibration_threshold: '0.50', vibration_current: '0.75' },
  [{ address: '12 Bond', baseline_reading: '1.000', current_reading: '1.004' }],
);
ok(excWithRows.vibration_over_threshold === true,
  '0.75 over a 0.50 threshold is over');
ok(excWithRows.adjacent_buildings[0].delta === '0.004',
  'and every row carries its computed delta, on the autosave path too');
ok(EXC.draftBody({ vibration_threshold: '0.50', vibration_current: '0.50' }, [])
  .vibration_over_threshold === false, 'exactly at the threshold is not over');
ok(EXC.draftBody({ vibration_threshold: '', vibration_current: '0.75' }, [])
  .vibration_over_threshold === false,
  'a reading with NO threshold is not over — there is nothing to be over');
// ...and that false is precisely why the renderers refuse to print it alone.
ok(EXC.thresholdStatusIsMeaningful('', '0.75') === false,
  'and the model agrees it must not be shown: a bare "within threshold" over a '
  + 'missing threshold is a finding the CP never made');
ok(EXC.thresholdStatusIsMeaningful('0.50', '0.75') === true,
  'with both readings the status IS meaningful');

console.log('\n-- excavation_monitoring: delta, and the rows that file --');

ok(EXC.calcDelta('1.000', '1.004') === '0.004', 'movement is the gap between the readings');
ok(EXC.calcDelta('1.004', '1.000') === '0.004',
  'and it is ABSOLUTE — 4 thou down is the same finding as 4 thou up');
ok(EXC.calcDelta('1.000', '') === '' && EXC.calcDelta('', '1.000') === '',
  'one reading yields a BLANK, not a zero — "no reading" and "no movement" are '
  + 'opposite findings on an excavation record');
ok(EXC.calcDelta('abc', '1.000') === '', 'and so does an unparseable one');
ok(EXC.calcDelta('1', '2') === '1.000', 'always three decimals, as the column has always printed');

const bldDropFields = uniq([
  ...grab(excPdf, /\bb\.get\("([a-z_]+)"/g),
  ...grab(excReport, /\bb\.get\("([a-z_]+)"/g),
  ...grab(excKiosk, /\bb\.([a-z_]+)/g),
]);
ok(bldDropFields.length === 4,
  `the renderers read 4 monitoring-point fields (${bldDropFields.join(', ')})`);
ok(JSON.stringify([...EXC.BUILDING_KEYS].sort()) === JSON.stringify(bldDropFields),
  'and the model names exactly those four');
// delta is DERIVED, so it is absent from the seed and present in the payload.
// Both are asserted, because a seeded blank delta would make a row with no
// readings look like a row whose readings agreed.
ok(!Object.prototype.hasOwnProperty.call(EXC.EMPTY_ADJACENT_BUILDING(), 'delta'),
  'a fresh row carries NO delta — it is derived, not typed');
for (const f of bldDropFields) {
  ok(Object.prototype.hasOwnProperty.call(excWithRows.adjacent_buildings[0], f),
    `the FILED row carries "${f}" — the renderer reads it`);
  ok(EXC.buildingHasContent({ ...EXC.EMPTY_ADJACENT_BUILDING(), [f]: 'x' }) === true,
    `buildingHasContent agrees with the renderer on "${f}"`);
}
ok(EXC.buildingHasContent(EXC.EMPTY_ADJACENT_BUILDING()) === false,
  'an untouched row is NOT a monitoring point — the same rule the renderer drops it by');

const excMixed = [
  { address: '12 Bond', baseline_reading: '1.000', current_reading: '1.004' },
  EXC.EMPTY_ADJACENT_BUILDING(),
  { address: '', baseline_reading: '', current_reading: '2.000' },
];
ok(EXC.buildingsForFiling(excMixed).length === 2,
  'filing drops the untouched seed and keeps both surveyed points');
ok(EXC.draftBody({}, excMixed).adjacent_buildings.length === 3,
  'but a DRAFT keeps all three — a half-typed row must survive a save');
ok(EXC.draftBody({}, excMixed, { forFiling: true }).adjacent_buildings.length === 2,
  'and the filing flag is what trims it');

// ── TWO REAL BOOLEANS, DELIBERATELY NOT A THREE-STATE MAP ───────────────────
//
// The combined report prints a bare Yes/No for these with NO not-recorded
// branch (server.py:19677-19678), so giving them a third state would file
// "unrecorded" into a renderer with no way to print it. Asserted, because the
// obvious next move after checklistMap is to run these through it too.
console.log('\n-- excavation_monitoring: the two switches have TWO states --');

ok(/\{"Yes" if d\.get\("groundwater_observed"\) else "No"\}/.test(excReport),
  'the combined report has no not-recorded branch for groundwater');
ok(/\{"Yes" if d\.get\("atmospheric_testing"\) else "No"\}/.test(excReport),
  'nor for atmospheric testing');
for (const k of ['groundwater_observed', 'atmospheric_testing']) {
  ok(excBody[k] === false, `${k} is present and FALSE on a blank log, never absent`);
  ok(EXC.draftBody({ [k]: true }, [])[k] === true, `${k} records a real true`);
  ok(EXC.draftBody({ [k]: undefined }, [])[k] === false,
    `${k} coerces a missing value to false rather than passing undefined through`);
}

console.log('\n-- excavation_monitoring: the pips --');

ok(JSON.stringify(EXC.incompleteSteps({
  details: {}, adjacentBuildings: [], cpSignature: '',
})) === '[1,2,3,4]', 'an untouched log marks all four steps incomplete');
ok(JSON.stringify(EXC.incompleteSteps({
  details: {
    excavation_depth: '12', soil_type: 'Sand',
    vibration_threshold: '0.50', vibration_current: '0.20',
  },
  adjacentBuildings: excMixed,
  cpSignature: 'sig',
})) === '[]', 'a filled and signed log marks none');
ok(EXC.incompleteSteps({
  details: { excavation_depth: '12', vibration_threshold: '0.50' },
  adjacentBuildings: excMixed,
  cpSignature: 'sig',
}).includes(3), 'a threshold with no current reading leaves the vibration step incomplete');

// ═══ HOT WORK ════════════════════════════════════════════════════════════════
console.log('\n-- hot_work: the nine top-level keys --');

const hwPdf = pdfBranch('hot_work', 'crane_operations');
const hwReport = reportBranch('hot_work', '_filed_log(logbooks, "crane_operations")');
const hwKiosk = kioskBranch('renderHotWork', 'renderCraneOperations');

const hwBody = HW.draftBody({}, {});
// The kiosk builds hot work's specs as a `const specs = [` rather than inline,
// so the DocFields slice is anchored on that instead.
const hwSpecs = hwKiosk.slice(hwKiosk.indexOf('const specs = ['), hwKiosk.indexOf('];'));
ok(hwSpecs.length > 0, 'hot_work: the kiosk specs list was found, not silently empty');
const hwKioskKeys = uniq([
  ...grab(hwKiosk, /\bdata\.([a-z_]+)/g),
  ...grab(hwSpecs, /\['([a-z_]+)',\s*t\(/g),
]);
const hwKeys = assertPayloadCovers('hot_work', hwBody, [
  ['PDF renderer', hwPdf, pdfTopKeys(hwPdf)],
  ['combined report', hwReport, reportTopKeys(hwReport)],
  ['kiosk inspector', hwKiosk, hwKioskKeys],
]);
ok(hwKeys.length === 9,
  `all three readers together open 9 keys (${hwKeys.join(', ')})`);
ok(hwBody.precautions && !Object.keys(hwBody.precautions).length,
  'precautions is an empty MAP — every item unrecorded, which is where it starts');

// ── THE DEVICE ASKED A DIFFERENT QUESTION THAN THE DOCUMENT PRINTED ────────
//
// The screen this replaces said "(35ft)" and "Covered/Protected"; both server
// renderers and the kiosk all said "(35 ft)" and "Covered / Protected". Only
// the editor disagreed, so the CP ticked one sentence and the inspector read
// another. All THREE readers are checked here, not two, because the kiosk holds
// its copy in the i18n catalogue rather than inline.
console.log('\n-- hot_work: one sentence, on the device and on the permit --');

const EN = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');
for (const [name, branch] of [['PDF renderer', hwPdf], ['combined report', hwReport]]) {
  const items = tupleList(branch);
  ok(items.length === 7, `${name} lists 7 precautions (got ${items.length})`);
  const bad = items.filter((q, i) => (
    HW.PRECAUTION_ITEMS[i]?.key !== q.key || HW.PRECAUTION_ITEMS[i]?.label !== q.label
  ));
  ok(bad.length === 0,
    `the model matches the ${name}, key and label and ORDER${bad.length ? ` — ${JSON.stringify(bad)}` : ''}`);
}
for (const it of HW.PRECAUTION_ITEMS) {
  const m = new RegExp(`\\n\\s*p_${it.key}: '((?:[^'\\\\]|\\\\.)*)'`).exec(EN);
  ok(!!m, `the kiosk catalogue carries p_${it.key}`);
  ok(m && m[1] === it.label,
    `and it reads word for word as the permit prints it (${JSON.stringify(m && m[1])})`);
}
// The two the editor got wrong, named so they cannot drift back.
ok(HW.PRECAUTION_ITEMS[0].label === 'Area Cleared of Combustibles (35 ft)',
  'the 35 ft precaution has the SPACE the document prints');
ok(HW.PRECAUTION_ITEMS[3].label === 'Combustibles Covered / Protected',
  'and the covered/protected one has the spaces around the slash');

console.log('\n-- hot_work: the fire watch is DERIVED, and never guessed --');

// server.py labels this as a computed DEFAULT in both renderers because FDNY
// can require sixty minutes. The number itself is read out of the model.
ok(HW.FIRE_WATCH_MINUTES === 30, 'the default watch is 30 minutes past work end');
ok(/default: work end \+ 30 min/.test(hwPdf) && /default: work end \+ 30 min/.test(hwReport),
  'and both renderers label it as the default it is, never as a recorded watch-until');

ok(HW.calcFireWatchEnd('02:00 PM') === '02:30 PM', 'half an hour past the end of work');
ok(HW.calcFireWatchEnd('11:45 PM') === '12:15 AM',
  'and it wraps past midnight, because hot work does');
// READS THE OLD FORMAT. This field held 24-hour "HH:MM" before it became a
// tap-only picker, so a permit drafted on an older build must still derive.
ok(HW.calcFireWatchEnd('14:00') === '02:30 PM',
  'a 24-hour end time from an older draft still derives correctly');
ok(HW.calcFireWatchEnd('23:45') === '12:15 AM', 'including across midnight');
ok(HW.calcFireWatchEnd('') === '' && HW.calcFireWatchEnd(null) === '',
  'no end time yields a BLANK, which the renderers print as an em dash');
ok(HW.calcFireWatchEnd('sometime this afternoon') === '',
  'and an unparseable one is blank too — never a guessed watch-until on an FDNY permit');
ok(HW.draftBody({ end_time: '02:00 PM' }, {}).fire_watch_end_time === '02:30 PM',
  'draftBody derives it, so the autosave and the submit write the same permit');
ok(HW.draftBody({}, {}).fire_watch_end_time === '',
  'and a permit with no end time carries the key, blank, rather than omitting it');

console.log('\n-- hot_work: the pips --');

ok(JSON.stringify(HW.incompleteSteps({
  details: {}, precautions: {}, cpSignature: '',
})) === '[1,2,3,4]', 'an untouched permit marks all four steps incomplete');
const hwFull = {};
for (const it of HW.PRECAUTION_ITEMS) hwFull[it.key] = true;
ok(JSON.stringify(HW.incompleteSteps({
  details: { work_type: 'Welding', start_time: '08:00 AM' },
  precautions: hwFull,
  cpSignature: 'sig',
})) === '[]', 'a filled and signed permit marks none');
ok(HW.incompleteSteps({
  details: { work_type: 'Welding', start_time: '08:00 AM' },
  precautions: { area_cleared: false },
  cpSignature: 'sig',
}).includes(3), 'ONE of seven answered still marks the precautions incomplete');
ok(!HW.incompleteSteps({
  details: { work_type: 'Welding', start_time: '08:00 AM' },
  precautions: Object.fromEntries(HW.PRECAUTION_ITEMS.map((it) => [it.key, false])),
  cpSignature: 'sig',
}).includes(3), 'seven NOs is a COMPLETE walk — a No is an answer');

// ═══ SSC DAILY SAFETY LOG ════════════════════════════════════════════════════
console.log('\n-- ssc_daily_safety_log: the thirteen top-level keys --');

const sscPdf = pdfBranch('ssc_daily_safety_log', 'osha_log');
const sscReport = reportBranch('ssc_daily_safety_log', '_filed_log(logbooks, "concrete_operations")');
const sscKiosk = kioskBranch('renderSscDailySafetyLog', 'renderOshaLog');

/** A named tuple/array list inside a branch, sliced so its keys can be read. */
function namedList(branch, name, open, close) {
  const a = branch.indexOf(`${name} = ${open}`);
  const b = branch.indexOf(close, a);
  return (a > -1 && b > a) ? branch.slice(a, b) : '';
}
const listKeys = (src) => grab(src, /\("([a-z_]+)",\s*"[^"]+"\)/g);

// This form has no nested checklist MAP — every one of the thirteen is a
// top-level key — so the `['key', t(…)]` pairs the kiosk writes for its
// compliance and narrative lists are payload keys too, and the whole block is
// scanned rather than just the DocFields specs.
const sscKioskKeys = uniq([
  ...grab(sscKiosk, /\bdata\.([a-z_]+)/g),
  ...grab(sscKiosk, /\['([a-z_]+)',\s*t\(/g),
]);
// The PDF branch keeps its flags and its narrative prompts in two named lists
// that field_lines never sees, so both are read out by name.
const sscPdfFlags = namedList(sscPdf, 'SSC_FLAGS', '[', ']');
const sscPdfNarrative = namedList(sscPdf, 'NARRATIVE_FIELDS', '(', '\n        )');
const sscReportFlags = namedList(sscReport, 'SSC_FLAGS', '[', ']');
ok(sscPdfFlags.length > 0 && sscPdfNarrative.length > 0 && sscReportFlags.length > 0,
  'ssc_daily_safety_log: the flag and narrative lists were found in both renderers');
const sscPdfKeys = uniq([
  ...pdfTopKeys(sscPdf), ...listKeys(sscPdfFlags), ...listKeys(sscPdfNarrative),
]);
const sscReportKeys = uniq([...reportTopKeys(sscReport), ...listKeys(sscReportFlags)]);

const sscBody = SSC.draftBody({});
const sscKeys = assertPayloadCovers('ssc_daily_safety_log', sscBody, [
  ['PDF renderer', sscPdf, sscPdfKeys],
  ['combined report', sscReport, sscReportKeys],
  ['kiosk inspector', sscKiosk, sscKioskKeys],
]);
ok(sscKeys.length === 13,
  `all three readers together open 13 keys (${sscKeys.join(', ')})`);
ok(Object.keys(sscBody).length === 13,
  'and the payload carries exactly those thirteen, no more');

// THE FIVE FLAGS AND THE THREE PROMPTS, key AND label, out of both renderers'
// own lists. The label must match word for word: the device and the filed PDF
// have to ask the same thing.
const SSC_EN = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');
for (const [name, src, model] of [
  ['PDF renderer flags', sscPdfFlags, SSC.COMPLIANCE_FLAGS],
  ['combined report flags', sscReportFlags, SSC.COMPLIANCE_FLAGS],
  ['PDF renderer narrative', sscPdfNarrative, SSC.NARRATIVE_FIELDS],
]) {
  const items = [...src.matchAll(/\("([a-z_]+)",\s*"([^"]+)"\)/g)]
    .map((m) => ({ key: m[1], label: m[2] }));
  ok(items.length === model.length,
    `${name} lists ${model.length} items (got ${items.length})`);
  const bad = items.filter((q, i) => (
    model[i]?.key !== q.key || model[i]?.label !== q.label
  ));
  ok(bad.length === 0,
    `the model matches the ${name}, key and label and ORDER${bad.length ? ` — ${JSON.stringify(bad)}` : ''}`);
}
// The kiosk holds its copy in the catalogue rather than inline, so it is
// checked against the catalogue.
for (const f of SSC.COMPLIANCE_FLAGS) {
  const m = new RegExp(`\\n\\s*s_${f.key}: '((?:[^'\\\\]|\\\\.)*)'`).exec(SSC_EN);
  ok(!!m && m[1] === f.label,
    `the kiosk catalogue reads s_${f.key} word for word as the document prints it`);
}

// ── FIVE TWO-STATE SWITCHES, DELIBERATELY NOT A THREE-STATE MAP ────────────
//
// The combined report prints a bare Yes/No for these (server.py:19905) with no
// not-recorded branch and says so in as many words. Asserted, because the
// obvious next move after checklistMap is to run these through it too — and
// that would file a state that renderer cannot print.
console.log('\n-- ssc_daily_safety_log: the five switches have TWO states --');

ok(/Two-state ToggleRows \(seeded false, always present\)/.test(sscReport),
  'the combined report still states the two-state convention these follow');
ok(/\{"Yes" if d\.get\(key\) else "No"\}/.test(sscReport),
  'and prints a bare Yes/No with nothing in between');
for (const f of SSC.COMPLIANCE_FLAGS) {
  ok(sscBody[f.key] === false,
    `${f.key} is present and FALSE on a blank day, never absent`);
  ok(SSC.draftBody({ [f.key]: true })[f.key] === true, `${f.key} records a real true`);
  ok(SSC.draftBody({ [f.key]: undefined })[f.key] === false,
    `${f.key} coerces a missing value to false rather than passing undefined through`);
}
// Both filed surfaces qualify a rendered "No" as possibly an untouched default,
// and the screen says the same thing before the SSC signs.
ok(/Compliance items default to "No" if not explicitly set by the reviewer/.test(sscPdf),
  'the PDF still qualifies a bare "No" as a possible untouched default');

console.log('\n-- ssc_daily_safety_log: the incident detail --');

// THE RENDERERS' OWN RULE: the detail is printed only when an incident was
// reported — but if one WAS, a missing detail is an unanswered question.
ok(/show_incident = bool\(data\.get\("incidents_reported"\)\)/.test(sscPdf),
  'the PDF gates the incident narrative on the flag');
ok(SSC.incidentDetailsApply({ incidents_reported: true }) === true,
  'the screen asks for the detail under exactly that condition');
ok(SSC.incidentDetailsApply({ incidents_reported: false }) === false, 'and not otherwise');
ok(SSC.incidentDetailsApply(null) === false, 'and it is safe on a missing document');
// The key TRAVELS either way. Dropping it when the flag is off would delete a
// detail the SSC typed before un-ticking the flag by mistake.
ok(SSC.draftBody({ incidents_reported: false, incident_details: 'Cut hand, sent to clinic' })
  .incident_details === 'Cut hand, sent to clinic',
  'the detail survives the flag being turned off — the renderers decide what to '
  + 'PRINT, and a typed sentence is not the app’s to throw away');

console.log('\n-- ssc_daily_safety_log: prefill, and the pips --');

ok(SSC.prefillFromProject({ address: '12 Bond St', ssp_number: 'SSP-9' }).project_address === '12 Bond St',
  'the address comes off the project record');
ok(SSC.prefillFromProject({ location: '12 Bond St' }).project_address === '12 Bond St',
  'falling back to `location` when there is no `address`, as it always has');
ok(Object.keys(SSC.prefillFromProject({ address: 'x', ssp_number: 'y', budget: 99 })).length === 2,
  'and NOTHING else rides in from the project document');
ok(SSC.prefillFromProject(null).project_address === '',
  'a failed project fetch yields blanks, not a crash');

ok(JSON.stringify(SSC.incompleteSteps({ details: {}, cpSignature: '' })) === '[1,3,4]',
  'an untouched day marks the site, the narrative and the signature — NOT '
  + 'compliance, whose five switches are meaningfully false');
const sscFull = {
  project_address: '12 Bond St', weather: 'Sunny', workers_on_site_count: '14',
  site_conditions: 'Dry, clear', safety_violations_observed: 'None observed',
  corrective_actions_taken: 'None required',
};
ok(JSON.stringify(SSC.incompleteSteps({ details: sscFull, cpSignature: 'sig' })) === '[]',
  'a written and signed day marks none');
ok(SSC.incompleteSteps({
  details: { ...sscFull, corrective_actions_taken: '' }, cpSignature: 'sig',
}).includes(3), 'one prompt left blank marks the narrative incomplete');
ok(SSC.incompleteSteps({
  details: { ...sscFull, incidents_reported: true }, cpSignature: 'sig',
}).includes(3), 'and an INCIDENT with no detail does too — the document will ask for it');
ok(!SSC.incompleteSteps({
  details: { ...sscFull, incidents_reported: true, incident_details: 'Cut hand' },
  cpSignature: 'sig',
}).includes(3), 'once written, the step is complete');
ok(SSC.narrativeWrittenCount({ site_conditions: '   ' }) === 0,
  'whitespace is not a narrative');

// ═══ THE SPARSE TOGGLE MAP — three states, and all three reachable ═══════════
//
// backend/server.py:13029-13043 says it: "key present and False is an explicit
// No while key absent is untouched". Both ported forms answer through
// checklistMap, so the rule is executed once here rather than trusted twice.
console.log('\n-- checklistMap: absent / false / true, and back --');

ok(/key present and False is an explicit No while `key absent` is\s*\n?\s*#?\s*untouched/i.test(SERVER)
  || /key absent` is\s+untouched/i.test(SERVER),
  'the backend still states the absent-vs-false convention this module implements');

const ITEMS = [{ key: 'a' }, { key: 'b' }];
let m = {};
ok(CHK.recordedCount(m, ITEMS) === 0, 'an empty map has answered nothing');
m = CHK.applyChecklistAnswer(m, 'a', true);
ok(m.a === true && CHK.recordedCount(m, ITEMS) === 1, 'YES records true');
m = CHK.applyChecklistAnswer(m, 'a', false);
ok(m.a === false && CHK.recordedCount(m, ITEMS) === 1,
  'NO over it records an explicit false — which the document prints as "No", not as a blank');
m = CHK.applyChecklistAnswer(m, 'a', false);
ok(!Object.prototype.hasOwnProperty.call(m, 'a'),
  'answering the SAME way twice removes the key — the only route back to "not recorded", '
  + 'and the state every form opens in');
ok(CHK.recordedCount(m, ITEMS) === 0, 'and it stops counting as answered');
ok(CHK.allRecorded({ a: false, b: true }, ITEMS) === true,
  'two answers is complete even when both are NO');
ok(CHK.allRecorded({ a: true }, ITEMS) === false, 'one of two is not');
// A stored value that is not a boolean is not an answer. Old drafts and hand
// edited documents both exist.
ok(CHK.recordedCount({ a: 'yes' }, ITEMS) === 0,
  'a non-boolean is not an answer — the renderers only branch on truthiness of a bool');
ok(CHK.applyChecklistAnswer(null, 'a', true).a === true,
  'a missing map is treated as empty, not as a crash');
// The original map is never mutated — React state depends on it.
const frozenSrc = { a: true };
CHK.applyChecklistAnswer(frozenSrc, 'a', false);
ok(frozenSrc.a === true, 'the source map is not mutated');

// ── THE SCREENS ARE ACTUALLY WIRED TO ALL THAT ──────────────────────────────
//
// A correct model behind an unwired screen ships the same defect.
console.log('\n-- both screens go through the models, not their own spreads --');

/**
 * Source with comments removed — the shared stripper every absence assertion
 * in this suite runs against. Both screens DOCUMENT the patterns they ban
 * ("NOT `!prev[key]`", "applySlumpResult, NOT a spread"), and an absence test
 * that reads prose passes on the documentation of the very fix it checks for.
 * Comments describe; code behaves. Only code is asserted.
 */
function stripComments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\s\/\/[^\n'"`]*$/gm, '');
}
const screenSrc = (f) => stripComments(fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', `${f}.jsx`), 'utf8'));
const CONC_SCREEN = screenSrc('concrete_operations');
const CRANE_SCREEN = screenSrc('crane_operations');
const EXC_SCREEN = screenSrc('excavation_monitoring');
const HW_SCREEN = screenSrc('hot_work');
const SSC_SCREEN = screenSrc('ssc_daily_safety_log');
ok(/LogbookStepper/.test(CONC_SCREEN) && !/THE PAYLOAD IS UNCHANGED/.test(CONC_SCREEN),
  'the comment stripper removes prose but keeps code');

// The freeze classification, read out of server.py's own table rather than
// typed here — the backend is authoritative and this suite must not carry a
// second opinion about which logs freeze on signature.
const TIMING_TABLE = SERVER.slice(
  SERVER.indexOf('LOGBOOK_TIMING_CLASS = {'),
  SERVER.indexOf('def logbook_timing_class'),
);
ok(TIMING_TABLE.length > 0, 'located LOGBOOK_TIMING_CLASS in server.py');
const END_OF_DAY_TYPES = [...TIMING_TABLE.matchAll(/"([a-z_]+)":\s*"end_of_day"/g)]
  .map((m) => m[1]);
ok(END_OF_DAY_TYPES.length === 2
  && END_OF_DAY_TYPES.includes('daily_jobsite')
  && END_OF_DAY_TYPES.includes('ssc_daily_safety_log'),
  `exactly two logs are daily narratives (${END_OF_DAY_TYPES.join(', ')})`);

const PORTED_SCREENS = [
  ['concrete_operations', CONC_SCREEN],
  ['crane_operations', CRANE_SCREEN],
  ['excavation_monitoring', EXC_SCREEN],
  ['hot_work', HW_SCREEN],
  ['ssc_daily_safety_log', SSC_SCREEN],
];

for (const [name, src] of PORTED_SCREENS) {
  // On the shared stepper, with the chrome it owns.
  ok(/<LogbookStepper/.test(src), `${name}: renders the shared stepper`);
  ok(!/<AnimatedBackground>/.test(src) && !/<ScrollView/.test(src),
    `${name}: owns no chrome of its own — the header, scroll and footer are the stepper's`);
  ok(!/Save Draft|'draft'/.test(src),
    `${name}: there is no Save Draft button and no draft submit — every change autosaves`);
  ok(!/GlassCard|GlassButton|LogbookLockBar/.test(src),
    `${name}: the old glass chrome is GONE, lock bar included`);
  // The carried-forward lifecycle, each named because each was a separate fix.
  //
  // CHECKED BELOW THE IMPORTS, and that is the point: an import line mentions
  // the name whether or not anything calls it, so asserting on the whole file
  // passes for a screen that imports adoptAmendment and never reaches it —
  // which is exactly the shape a mutation ran through here. `const LOG_TYPE` is
  // the first line of code in every one of these screens.
  const importsAt = src.indexOf('const LOG_TYPE');
  ok(importsAt > 0, `${name}: the import block ends where it always has`);
  const body = src.slice(importsAt);
  for (const fn of ['readDraft', 'writeDraft', 'setDraftBackendId', 'markPending',
    'clearPending', 'markFinalized', 'adoptAmendment',
    'recordFinalizeError', 'clearFinalizeError', 'finalizeErrorCode',
    'isOfflineError', 'recordSignatureEvent']) {
    ok(new RegExp(`\\b${fn}\\s*\\(`).test(body), `${name}: CALLS ${fn}`);
  }
  // THE FREEZE MODEL IS A LEGAL CLASSIFICATION, not a UI preference, and the
  // five ported forms do not share one. Four are IMMEDIATE — the signature IS
  // the freeze, so freezeIfImmediate runs and there is no separate /finalize.
  // ssc_daily_safety_log is END_OF_DAY (server.py's LOGBOOK_TIMING_CLASS puts
  // it with daily_jobsite): the narrative accumulates all day and freezes once,
  // at an explicit /finalize plus a local markFinalized. Getting this backwards
  // either freezes a day that is still being written or leaves a REQUIRED log
  // unfrozen, so each form is asserted to carry ITS model and NOT the other.
  const endOfDay = name === 'ssc_daily_safety_log';
  ok(END_OF_DAY_TYPES.includes(name) === endOfDay,
    `${name}: the backend agrees this is ${endOfDay ? 'END_OF_DAY' : 'IMMEDIATE'}`);
  if (endOfDay) {
    ok(!/freezeIfImmediate/.test(src),
      `${name}: does NOT freeze on signature — it is a daily narrative`);
    ok(/logbooksAPI\.finalize\(savedId\)/.test(body) && /markFinalized\(_key\)/.test(body),
      `${name}: closes the day with an explicit finalize plus a local freeze`);
  } else {
    ok(/freezeIfImmediate\s*\(/.test(body),
      `${name}: CALLS freezeIfImmediate — the signature IS the freeze`);
    ok(!/logbooksAPI\.finalize\(/.test(body),
      `${name}: and never calls /finalize separately, which would contradict that`);
  }
  // And the payload is built in ONE place. A screen that assembles a `data: {}`
  // literal anywhere has a second shape the model does not decide — which is
  // how excavation_monitoring's autosave came to omit two derived keys the
  // renderers gate whole sections on.
  ok(!/data: \{/.test(body),
    `${name}: no path hand-builds a data object — draftBody decides the shape`);
  // The affirmation gate — this is an IMMEDIATE type, so submit must be
  // UNREACHABLE without one, not merely warned about.
  ok(/submitDisabled=\{!isAffirmedSignature\(cpSignature\)\}/.test(src),
    `${name}: an unaffirmed signature makes Submit unreachable`);
  ok(/submitHint=\{affirmationHintKey\(cpSignature, profileLoaded\)/.test(src),
    `${name}: and the dead button says why`);
  // The refusal split: a 4xx is a JUDGEMENT and must not freeze.
  ok(/refused && submitStatus === 'submitted'/.test(src)
    && /if \(savedId === undefined\) return;/.test(src),
    `${name}: a server REFUSAL is not offline — it reports and does not freeze`);
  // gateCopy — the server's English `detail` never renders.
  ok(/const key = `code_\$\{code\}`/.test(src) && /tFinalize\('genericError'\)/.test(src),
    `${name}: the client owns the wording; an unmapped code falls back`);
  // No camera on either form, so neither may quietly grow one.
  ok(!/persistPhoto|compressUnderCap|Camera/.test(src),
    `${name}: no camera — persistPhoto and compressUnderCap are deliberately absent`);
  // No roster, so the empty-roster trap has no surface here.
  ok(!/getCheckinsForDate|getCheckinsRoster|buildEntriesFromCheckins/.test(src),
    `${name}: builds no roster, so it cannot carry the empty-roster trap`);
  // A time-of-day field is TAPPED, not typed — on the forms that have one.
  // excavation_monitoring and ssc_daily_safety_log record no time of day at
  // all, so neither may grow a picker for a field that does not exist.
  if (name === 'excavation_monitoring' || name === 'ssc_daily_safety_log') {
    ok(!/<TimeField/.test(src) && !/placeholder="HH:MM"/.test(src),
      `${name}: has no time-of-day field, and no picker for one`);
  } else {
    ok(/<TimeField/.test(src) && !/placeholder="HH:MM"/.test(src),
      `${name}: times are chosen with TimeField, not typed into a free-text box`);
  }
}

// The two edits that are the whole point of the models.
ok(/applySlumpResult\(row, value\)/.test(CONC_SCREEN),
  'concrete_operations: the result goes through applySlumpResult, which can reach null');
ok(!/pass: [^,\n]*\? *true *: *false/.test(CONC_SCREEN)
  && !/pass: !/.test(CONC_SCREEN),
  'and there is no boolean flip that would make "not recorded" unreachable');
ok(/slumpTestsForFiling\(b\.slumpTests\)/.test(CONC_SCREEN)
  && /submitStatus === 'submitted'\s*\?\s*slumpTestsForFiling/.test(CONC_SCREEN),
  'concrete_operations: SUBMIT trims the abandoned rows; a draft keeps them');
ok(/loadEntriesForFiling\(b\.loadEntries\)/.test(CRANE_SCREEN)
  && /submitStatus === 'submitted'\s*\?\s*loadEntriesForFiling/.test(CRANE_SCREEN),
  'crane_operations: SUBMIT trims the abandoned rows; a draft keeps them');
for (const [name, src] of [['concrete_operations', CONC_SCREEN],
  ['crane_operations', CRANE_SCREEN], ['hot_work', HW_SCREEN]]) {
  ok(/applyChecklistAnswer\(p, key, value\)/.test(src),
    `${name}: the checklist goes through applyChecklistAnswer`);
  ok(!/\[key\]: !p\[key\]/.test(src) && !/!prev\[key\]/.test(src),
    `${name}: the binary flip that could not express "not recorded" is GONE`);
}

// excavation_monitoring's two switches are the DELIBERATE exception — real
// booleans, because the combined report prints a bare Yes/No for them and has
// no not-recorded branch to print. Asserted so the obvious next move (running
// them through checklistMap too) cannot be made silently.
ok(/const toggleFlag = \(key\) => setDetails\(\(p\) => \(\{ \.\.\.p, \[key\]: !p\[key\] \}\)\);/
  .test(EXC_SCREEN),
  'excavation_monitoring: the two condition switches stay a plain boolean flip');
ok(!/applyChecklistAnswer/.test(EXC_SCREEN),
  'and they are NOT routed through the three-state helper');

// The two derived values must reach the payload through the model, on every
// path — that is the whole point of the excavation port.
ok((EXC_SCREEN.match(/draftBody\(b\.details, b\.adjacentBuildings\)/g) || []).length === 2,
  'excavation_monitoring: BOTH the debounced autosave and the step-change flush '
  + 'build the payload with draftBody — one of the two was where the derived keys '
  + 'went missing');
ok(/draftBody\(b\.details, b\.adjacentBuildings, \{ forFiling: filing \}\)/.test(EXC_SCREEN),
  'and so does the submit, with the same function and one flag');
ok(!/vibration_over_threshold:/.test(EXC_SCREEN) && !/delta:/.test(EXC_SCREEN),
  'neither derived value is spelled out in the screen — one place computes them');

// hot_work's offline-aware hydrate is this screen's alone and must survive.
ok(/settleFetch\(/.test(HW_SCREEN) && /<OfflineNotice/.test(HW_SCREEN),
  'hot_work: a failed load still SAYS so instead of opening a blank permit');
ok(!/getByProject\(projectId, LOG_TYPE, date\)\.catch\(\(\) => \[\]\)/.test(HW_SCREEN),
  'and the swallow-into-empty-array that hid it is not back');
ok(/setFetchState\(r\.status\)/.test(HW_SCREEN),
  'the outcome of the load is what the notice is driven from');
ok(!/calcFireWatchEnd = /.test(HW_SCREEN),
  'hot_work: the fire-watch derivation lives in the model, not in the screen');

// ── ssc_daily_safety_log signs with ITS OWN pad ─────────────────────────────
//
// The other four ported forms take the CP's signature from useCpProfile, which
// is right for them: one Competent Person signs his own logs all day. The
// SSC/SSM log is signed by a DIFFERENT person, and a cached CP credential
// pre-locking that pad would put one man's signature on another man's daily
// record. This screen therefore holds cpName/cpSignature locally, seeds them
// only from the loaded document, and leaves the pad editable.
ok(!/useCpProfile/.test(SSC_SCREEN),
  'ssc_daily_safety_log: does NOT reach for the cached CP profile signature');
ok(/const \[cpSignature, setCpSignature\] = useState\(null\);/.test(SSC_SCREEN),
  'the signature is this log’s own local state');
ok(/autoLock=\{false\}/.test(SSC_SCREEN),
  'and the pad opens editable so the SSC/SSM signs it himself');
for (const [name, src] of PORTED_SCREENS) {
  if (name === 'ssc_daily_safety_log') continue;
  ok(/useCpProfile/.test(src),
    `${name}: still takes the CP signature from the shared profile, as it always has`);
}
// The five compliance switches stay two-state — same deliberate exception as
// excavation_monitoring's two, and for the same renderer-shaped reason.
ok(/const toggleFlag = \(key\) => setDetails\(\(p\) => \(\{ \.\.\.p, \[key\]: !p\[key\] \}\)\);/
  .test(SSC_SCREEN),
  'ssc_daily_safety_log: the five compliance switches stay a plain boolean flip');
ok(!/applyChecklistAnswer/.test(SSC_SCREEN),
  'and they are NOT routed through the three-state helper');
// The guard that refuses `cp_signature: {}` — the shape production actually
// held, which the old `!cpSignature` presence check let straight through.
ok(/if \(!isAffirmedSignature\(cpSignature\)\) \{/.test(SSC_SCREEN),
  'ssc_daily_safety_log: the handler asks the renderer’s question, not "is anything there"');
ok(!/if \(!cpSignature\) \{/.test(SSC_SCREEN),
  'and the bare presence check that an empty object satisfied is gone');

// ── THE THREE FINALIZE OUTCOMES, AND ONLY ONE MAY FREEZE ────────────────────
//
// This is the END_OF_DAY shape, so the content push and the /finalize are two
// separate calls and the second one can fail on its own. Treating every
// finalize failure as offline produced three compounding lies on daily_jobsite:
// the CP was told the log was signed, locked and would sync when the server had
// said no and would keep saying no; markFinalized made the draft IMMUTABLE so
// he could not fix the very condition being refused; and the content push had
// SUCCEEDED, so no pending key existed and the drain would never retry.
//
// Asserted on the CATCH BLOCK ITSELF rather than on the presence of the
// helpers: recordFinalizeError is also called from the push path, so a screen
// that dropped the refusal branch's `return` still mentioned every name. A
// mutation walked straight through the earlier version of this.
{
  const a = SSC_SCREEN.indexOf('} catch (finalizeErr) {');
  const b = SSC_SCREEN.indexOf('await markFinalized(_key);', a);
  const catchBlock = (a > -1 && b > a) ? SSC_SCREEN.slice(a, b) : '';
  ok(catchBlock.length > 0,
    'ssc_daily_safety_log: located the finalize catch block');
  ok((catchBlock.match(/\breturn;/g) || []).length === 2,
    'a REFUSED and a FAILED finalize each return BEFORE the freeze — only the '
    + 'genuinely offline path falls through to it');
  ok(/if \(refused\) \{[\s\S]*?recordFinalizeError\(savedId, code, _key, 'editor'\);[\s\S]*?return;/
    .test(catchBlock),
    'and a refusal leaves the durable banner on its way out, so the toast is not '
    + 'the only trace four seconds later');
  ok(/if \(!offline && !refused\) \{[\s\S]*?return;/.test(catchBlock),
    'a 5xx is retryable, is not queued and is not announced as synced');
}

// ═══ THE KIOSK INSPECTOR ═════════════════════════════════════════════════════
console.log('\n-- the kiosk inspector reads the same keys --');

// app/site/logbooks.jsx renders filed logs on the site device. It reads the
// payload by key too, so a rename breaks it in the same silent way.
for (const k of ['general_info', 'answers']) {
  ok(KIOSK.includes(k), `kiosk reads data.${k} for the scaffold log`);
}
ok(/entries/.test(KIOSK), 'kiosk reads data.entries for the OSHA register');
// The one key the whole drawings_on_site fix turns on.
ok(/general_info\.drawings_on_site is a dead duplicate/.test(KIOSK),
  'kiosk still ignores the general_info copy of drawings_on_site');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
