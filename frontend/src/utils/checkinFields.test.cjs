/**
 * "Companies 1" WAS A COUNT OF ONE `undefined`.
 *
 * workers.jsx counted distinct companies as
 *
 *     new Set(todayCheckIns.map((c) => c.workerCompany)).size
 *
 * against an API that returns snake_case. `worker_company` is what
 * /api/checkins serialises (the check-in field whitelist in server.py names
 * `worker_company`, `project_name`, `project_id`); `workerCompany` is produced
 * NOWHERE as a check-in row field. So every row mapped to undefined and the
 * counter read `new Set([undefined, ...]).size === 1` -- 1 for any non-empty
 * roster, whatever was actually on site, and 0 only when nobody had checked in.
 *
 * The first two tests below are the whole finding: sixteen workers from five
 * companies, counted the old way, gives 1.
 *
 * Run:  node src/utils/checkinFields.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const APP = path.join(UTILS, '..', '..', 'app');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const src = fs.readFileSync(path.join(UTILS, 'checkinFields.js'), 'utf8')
  .replace(/^export default[\s\S]*$/m, '')
  .replace(/^export /gm, '');
// eslint-disable-next-line no-new-func
const F = new Function(`${src}; return {
  checkinCompany, checkinProject, checkinWorker, nameKey,
  distinctCompanies, distinctProjects };`)();

// The shape /api/checkins actually returns. Five companies, sixteen men.
const COMPANIES = ['Arkon Builders', 'Sanchez Concrete', 'Vertex Steel',
  'Delta Electric', 'Iron Works LLC'];
const ROSTER = Array.from({ length: 16 }, (_, i) => ({
  worker_name: `Worker ${i}`,
  worker_company: COMPANIES[i % COMPANIES.length],
  project_name: '588 Thomas',
  project_id: 'p1',
}));

console.log('\n-- the finding --');

ok(new Set(ROSTER.map((c) => c.workerCompany)).size === 1,
  'THE OLD EXPRESSION: 16 workers from 5 companies counted as 1 -- because '
  + 'every row maps to undefined and a Set of undefined has size 1');
ok(F.distinctCompanies(ROSTER) === 5, 'the new one counts 5');

console.log('\n-- reading the field, whatever it is spelled --');

for (const [row, want, why] of [
  [{ worker_company: 'Arkon' }, 'Arkon', 'snake_case, what the API sends'],
  [{ workerCompany: 'Arkon' }, 'Arkon', 'camelCase, tolerated'],
  [{ company: 'Arkon' }, 'Arkon', 'bare, tolerated'],
  [{ worker_company: 'Arkon', company: 'Other' }, 'Arkon', 'first candidate wins'],
  [{ worker_company: '  Arkon  ' }, 'Arkon', 'the winner is stripped'],
  [{}, '', 'a row naming no company reads empty, not undefined'],
]) {
  ok(F.checkinCompany(row) === want, `${why} -> "${want}"`);
}

ok(F.checkinCompany(null) === '' && F.checkinCompany(undefined) === '',
  'a missing row does not throw');
ok(F.checkinCompany({ worker_company: '   ' }) === '',
  'whitespace-only is truthy, wins, and strips to "" -- matching '
  + '(a || b || "").trim() at every original call site and _worker_company');

console.log('\n-- case and whitespace are not identity --');

ok(F.distinctCompanies([
  { worker_company: 'Arkon Builders' },
  { worker_company: 'arkon builders' },
  { worker_company: 'Arkon  Builders ' },
]) === 1,
'one company written three ways is one company -- a doubled space already '
+ 'printed the same man twice on a production pre-shift sheet');

console.log('\n-- a row that names no company is not a company --');

ok(F.distinctCompanies([
  { worker_company: 'Arkon' }, {}, { worker_company: '' }, { worker_company: '  ' },
]) === 1,
'blanks are dropped, not counted as a company -- an unnamed company is a gap '
+ 'in the record, and counting it makes the gap look like a fact');
ok(F.distinctCompanies([]) === 0, 'an empty roster is zero companies, not one');
ok(F.distinctCompanies(null) === 0, 'and a missing roster does not throw');

console.log('\n-- projects, which had the identical defect --');

ok(new Set(ROSTER.map((c) => c.projectName || c.projectId)).size === 1,
  'the old expression also counted one undefined -- it merely LOOKED right '
  + 'because the operator was on a single project');
ok(F.distinctProjects(ROSTER) === 1, 'one project is one project');
ok(F.distinctProjects([{ project_name: 'A' }, { project_name: 'B' }]) === 2,
  'two projects are two -- the case the old expression could never report');

console.log('\n-- the screens read through the helper --');

/**
 * A file's CODE, with comments removed.
 *
 * FIVE assertions this session were written as text searches over source and
 * matched the very prose explaining the thing they forbid -- turning correct
 * implementations into red tests. The first draft of the next assertion did it
 * again, matching the comment above the fixed counter that quotes the old
 * `c.workerCompany` read to explain why it was wrong.
 *
 * The Python suite solved this with ast.unparse (`_code_only`). JSX has no such
 * parser to hand here, so this strips block and line comments -- crude, but it
 * removes exactly the class of false match that keeps recurring. String
 * literals containing `//` are not defended; none exist in these files.
 */
function codeOnly(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

const workers = codeOnly(fs.readFileSync(path.join(APP, 'workers.jsx'), 'utf8'));
const site = codeOnly(fs.readFileSync(path.join(APP, 'site', 'checkins.jsx'), 'utf8'));

ok(/distinctCompanies\(todayCheckIns\)/.test(workers), 'the counter uses it');
ok(/distinctProjects\(todayCheckIns\)/.test(workers), 'and so does the project counter');
ok(!/c\.workerCompany/.test(workers), 'the camelCase read is gone');
ok(!/c\.projectName \|\| c\.projectId/.test(workers), 'and so is its twin');
ok(/checkinCompany\(checkin\)/.test(workers) && /checkinCompany\(checkin\)/.test(site),
  'BOTH row renderers read the same helper the counters do -- the rows naming '
  + 'the right companies while the counter said 1 is what made this survivable '
  + 'for so long');
ok(!/checkin\.worker_company \|\| checkin\.workerCompany/.test(workers + site),
  'no screen retypes the or-chain any more');

console.log('\n-- the label --');

ok(/label: 'Companies on site'/.test(workers),
  '"Companies on site", the number the data can honestly produce');
ok(!/label: 'Subcontractors'/.test(workers),
  'NOT "Subcontractors" -- the gate records no GC flag, so nothing here can '
  + "tell a general contractor's own crew from a sub's");

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) { console.log('FAILURES ABOVE'); process.exit(1); }
console.log('ALL PASSED');
