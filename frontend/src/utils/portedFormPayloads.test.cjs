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

// A gate refusal is recorded as DENIED and never as a certification.
const blocked = OSHA.buildEntriesFromCheckins([{
  worker_id: 'w4', worker_name: 'Pat', blocked: true, blocks: ['CERT_BLOCK'],
}], '2026-08-12');
ok(blocked[0].certification_type === 'MISSING OSHA' && blocked[0].blocked === true,
  'a worker turned away at the gate is DENIED, not credited with a card');
ok(blocked[0].card_number === '' && blocked[0].expiration === '',
  'and carries no card number — the gate established that he had none');

// The screen's completeness rule must agree with the renderer's drop rule.
// server.py:13472 skips a row with none of these five fields as an untouched
// seed; if the pip disagreed, the CP would see a filled step print blank.
ok(OSHA.entryHasContent(row) === true, 'a real row counts as content');
ok(OSHA.entryHasContent(OSHA.EMPTY_ENTRY()) === false,
  'an untouched EMPTY_ENTRY does NOT — the same rule the renderer drops it by');
const seedSkipFields = [...new Set(
  [...oshaBranch.matchAll(/has\(e, k\) for k in\s*\n?\s*\(([^)]*)\)/g)]
    .flatMap((m) => [...m[1].matchAll(/"([a-z_]+)"/g)].map((x) => x[1])),
)].sort();
ok(seedSkipFields.length === 5,
  `the renderer's seed-skip rule names 5 fields (${seedSkipFields.join(', ')})`);
for (const f of seedSkipFields) {
  const probe = { ...OSHA.EMPTY_ENTRY(), [f]: 'x' };
  ok(OSHA.entryHasContent(probe) === true,
    `entryHasContent agrees with the renderer on "${f}"`);
}

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
ok(/submitDisabled=\{!cpSignature \|\| filledRows === 0\}/.test(OSHA_SCREEN),
  'an empty register cannot be filed, restoring the guard the #123 port dropped');
ok(/sharedWorkerIds\(entries\)/.test(OSHA_SCREEN)
  && /sameWorkerNote/.test(OSHA_SCREEN),
  'two rows for one man are labelled as his two cards, not left looking duplicated');
ok(/unlinkedNote/.test(OSHA_SCREEN),
  'and a row that has lost its id says so');

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
