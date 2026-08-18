/**
 * AN OSHA ENTRY MUST CARRY A WORKER.
 *
 * Device round 6, item 1. The register already refused the ABANDONED BLANK ROW
 * that reached production (project 6a5f63bc147407d3261df2c7, 2026-08-11) — a
 * row with no name, no card and no certification. It did not refuse the worse
 * shape, because the rule was any-of five fields: a row carrying a company, a
 * card number and a signature mark against NO NAME passed every gate and
 * printed on a signed certification register.
 *
 * A blank row says nothing. That row says something about a man it does not
 * name — nobody can be checked against it and nobody can be cleared by it.
 *
 * So the name is the whole filing rule, and this file EXECUTES it rather than
 * grepping for it. Four consumers have to agree, or a filed register and a
 * printed one disagree:
 *
 *   entriesForFiling                        what is written at Submit
 *   _SUBMIT_ROW_CONTENT_RULES["osha_log"]   the server backstop
 *   render_logbook_html, osha branch        the per-logbook PDF
 *   generate_combined_report, osha section  the emailed report
 *
 * The last three are read out of backend/server.py, not copied here.
 *
 * Run:  node src/utils/oshaLogModel.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');
const SERVER = fs.readFileSync(
  path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
const SCREEN_RAW = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'osha_log.jsx'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/** Comments stripped before any source assertion — the prose explains the rule
 *  at length here, and a grep that matches the explanation proves nothing. */
const strip = (text) => text
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')
  .replace(/\s\/\/[^\n'"`]*$/gm, '');
const SCREEN = strip(SCREEN_RAW);
ok(/entriesForFiling/.test(SCREEN) && !/an assertion about an unnamed man/.test(SCREEN),
  'the comment stripper removes prose but keeps code');

// The real module, executed.
function load(rel) {
  const src = fs.readFileSync(path.join(UTILS, rel), 'utf8')
    .replace(/^import .*$/gm, '')
    .replace(/^export default [\s\S]*$/m, '')
    .replace(/^export (async function|function|const) /gm, '$1 ');
  const names = [...src.matchAll(/^(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  // eslint-disable-next-line no-new-func
  return new Function(`const easternToday = () => '2026-08-17';\n${src}
    return { ${[...new Set(names)].join(', ')} };`)();
}
const M = load('oshaLogModel.js');

// The row that reached production, and the row this change is about.
const SEED = () => ({
  worker_id: null, worker_name: '', company: '', certification_type: '',
  card_number: '', expiration: '', signed: false, date: '2026-08-11',
});
const NAMELESS_CARD = { ...SEED(), company: 'AAZ', card_number: '12345678', signed: true };
const NAMED = { ...SEED(), worker_name: 'WILMER CARRILLO', card_number: '12345678' };

console.log('\n-- the filing rule is the NAME --');
ok(M.entryNamesWorker(NAMED) === true, 'a row that names a worker is filed');
ok(M.entryNamesWorker(NAMELESS_CARD) === false,
  'a card number + a signature mark + a company and NO NAME is not');
ok(M.entryNamesWorker({ ...SEED(), worker_name: '   ' }) === false,
  'and neither is whitespace pretending to be a name');
ok(M.entryNamesWorker(SEED()) === false, 'the untouched seed is not');
ok(M.entryNamesWorker(null) === false && M.entryNamesWorker('x') === false,
  'junk is not a row');

console.log('\n-- entriesForFiling drops it, whatever else it holds --');
{
  const filed = M.entriesForFiling([NAMED, NAMELESS_CARD, SEED()]);
  ok(filed.length === 1 && filed[0].worker_name === 'WILMER CARRILLO',
    'exactly one row of three survives, and it is the named one');
  ok(!filed.some((e) => e.card_number === '12345678' && !e.worker_name),
    'the card number does NOT reach the filed register on a nameless row');
}
ok(M.entriesForFiling([NAMELESS_CARD]).length === 0,
  'a register of nothing but nameless rows files nothing at all');
ok(M.entriesForFiling(null).length === 0 && M.entriesForFiling('x').length === 0,
  'and a malformed register does not throw');
{
  // The gate's own case: a worker turned away for missing OSHA is a DENIED row
  // and he IS named, so the refusal still reaches the register.
  const blocked = {
    ...SEED(), worker_name: 'SEGUNDO PILAMUNGA', certification_type: 'MISSING OSHA',
    blocked: true, blocks: ['osha'],
  };
  ok(M.entriesForFiling([blocked]).length === 1,
    'a DENIED row is named, so the gate refusal is still filed');
}

console.log('\n-- "touched" and "filed" are now two questions --');
ok(M.entryHasContent(NAMELESS_CARD) === true,
  'the nameless row still counts as TOUCHED — it is work in progress on screen');
ok(M.entryHasContent(SEED()) === false, 'the untouched seed is not touched');
ok(M.entryHasContent(NAMELESS_CARD) !== M.entryNamesWorker(NAMELESS_CARD),
  'and the two predicates DISAGREE about exactly the row the CP must be told about');

console.log('\n-- the CP is told which rows and why --');
{
  const rows = [NAMED, NAMELESS_CARD, SEED(), { ...SEED(), certification_type: 'SST' }];
  const reported = M.unnamedEntries(rows);
  ok(reported.length === 2, 'both touched-but-nameless rows are reported');
  ok(reported[0].row === 2 && reported[1].row === 4,
    'by their 1-based position, which is how they read on screen');
  ok(reported[0].company === 'AAZ' && reported[0].card_number === '12345678',
    'carrying what the row DOES hold, so he can recognise it');
  ok(!reported.some((u) => u.row === 3),
    'the untouched seed is NOT reported — dropped silently, as it always was');
  ok(M.unnamedEntries([NAMED]).length === 0,
    'a clean register reports nothing and the CP is never stopped');
}

console.log('\n-- step 1 is incomplete when nothing will be FILED --');
ok(M.incompleteSteps({ entries: [NAMELESS_CARD], cpSignature: 'x' }).includes(1),
  'a screen full of rows that all get dropped is an incomplete step');
ok(!M.incompleteSteps({ entries: [NAMED], cpSignature: 'x' }).includes(1),
  'and one named row completes it');

console.log('\n-- the screen blocks at SUBMIT, not on Next --');
ok(/const unnamed = unnamedEntries\(rowsNow\);/.test(SCREEN),
  'handleSubmitAndSign asks which rows will not be filed');
{
  const gate = SCREEN.indexOf('const unnamed = unnamedEntries(');
  const sign = SCREEN.indexOf('const handleSubmitAndSign');
  const push = SCREEN.indexOf("persistAndPush('submitted')");
  ok(gate > sign && gate < push,
    'inside handleSubmitAndSign and BEFORE anything is written');
  const step = SCREEN.indexOf('const onStepChange');
  const stepEnd = SCREEN.indexOf('};', step);
  ok(step > -1 && !SCREEN.slice(step, stepEnd).includes('unnamedEntries'),
    'and NOT on step change — moving on is never refused for a half-typed row');
}
ok(/t\('unnamedRowsTitle'\)/.test(SCREEN),
  'it warns rather than dropping the rows silently');

// ONE GATE, TWO REASONS. These were two checks, and which one fired decided
// whether the CP got a useful sentence or a generic "Nothing to file" —
// including for a register that empties for a reason this screen has not
// enumerated. The gate now computes what will be DROPPED, then says what that
// leaves.
{
  const gate = SCREEN.slice(SCREEN.indexOf('const unnamed = unnamedEntries('),
    SCREEN.indexOf("persistAndPush('submitted')"));
  ok(/const willFile = entriesForFiling\(rowsNow\)\.length;/.test(gate),
    'the gate asks what will be LEFT as well as what will go');
  ok(/if \(unnamed\.length > 0 \|\| willFile === 0\)/.test(gate),
    'and ONE condition covers both — no second check to fall through to');
  ok(/nothingLeftBody/.test(gate),
    'when both are true he gets the reason AND the consequence');
  ok(gate.indexOf('unnamedRowsBody') < gate.indexOf('nothingLeftBody'),
    'reason first: it is the half he can act on');
  ok(/nothingToFileBody/.test(gate),
    'and an untouched register still gets its own sentence');
}
{
  const en = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');
  ok(/unnamedRowsTitle:/.test(en) && /unnamedRowsBody:/.test(en),
    'and the copy exists, so the toast is a sentence and not a key name');
  ok(/\{rows\}/.test(en), 'with a slot for the row numbers');
}

console.log('\n-- the server agrees, field for field --');
{
  const m = /"osha_log": \("entries", \(\s*([^)]*)\)\),/.exec(SERVER);
  ok(!!m, 'the submit rule is readable from server.py');
  const fields = [...m[1].matchAll(/"([a-z_]+)"/g)].map((x) => x[1]);
  ok(JSON.stringify(fields) === JSON.stringify(['worker_name']),
    `_SUBMIT_ROW_CONTENT_RULES["osha_log"] requires worker_name alone (got ${fields})`);
}
{
  const branch = SERVER.slice(SERVER.indexOf('elif log_type == "osha_log":'));
  const cut = branch.slice(0, branch.indexOf('elif log_type ==', 10));
  const m = /has\(e, k\) for k in\s*\n?\s*\(([^)]*)\)/.exec(cut);
  const fields = m ? [...m[1].matchAll(/"([a-z_]+)"/g)].map((x) => x[1]) : null;
  ok(JSON.stringify(fields) === JSON.stringify(['worker_name']),
    'the per-logbook PDF drops the same rows');
}
ok(/_osha_content_fields = _SUBMIT_ROW_CONTENT_RULES\["osha_log"\]\[1\]/.test(SERVER),
  'and the combined report reads the rule rather than restating it');

console.log('\n-- the payload shape is unchanged --');
{
  const body = M.draftBody([NAMED]);
  ok(Object.keys(body).length === 1 && Array.isArray(body.entries),
    'draftBody is still { entries: [...] }');
  ok(M.ENTRY_KEYS.every((k) => k in M.EMPTY_ENTRY()),
    'and EMPTY_ENTRY still carries every declared key');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
