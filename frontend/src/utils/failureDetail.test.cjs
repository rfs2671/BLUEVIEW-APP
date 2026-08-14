/**
 * SHOW WHAT ACTUALLY HAPPENED.
 *
 * Three defects this session were hidden by generic client copy: the
 * assign-project failure, the silent gate reroute, and the worker detail
 * screen — where GET /api/workers/{id} was returning a 500 (a pydantic
 * ValidationError, because WorkerResponse required `company` and the check-in
 * writer deliberately stopped recording it) and the screen rendered "Could not
 * load this worker. Try again." for every one of them.
 *
 * Each cost a round trip to diagnose. This asserts the four outcomes a person
 * can act on, and the one thing that must NOT be rendered.
 *
 * Run:  node src/utils/failureDetail.test.cjs
 */
const fs = require('fs');
const path = require('path');

const SRC = fs.readFileSync(path.join(__dirname, 'offlineState.js'), 'utf8');
// eslint-disable-next-line no-new-func
const M = new Function(`${SRC
  .replace(/^import .*$/gm, '')
  .replace(/^export default [\s\S]*$/m, '')
  .replace(/^export (async function|function|const) /gm, '$1 ')}
  return { failureDetail };`)();

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const err = (status, detail) => ({ response: { status, data: { detail } } });

console.log('\n-- the four outcomes a person can act on --');

ok(/reconnect/i.test(M.failureDetail('offline', null, 'this worker')),
  'offline says reconnect');
ok(/not found/i.test(M.failureDetail('error', err(404), 'this worker')),
  '404 says not found, so he stops retrying');
ok(/permission/i.test(M.failureDetail('error', err(403, 'Access denied'), 'this worker')),
  '403 says no permission, and names who to ask');
ok(/session/i.test(M.failureDetail('error', err(401), 'this worker')),
  '401 says the session expired');

console.log('\n-- the 500 that started this --');

const real = M.failureDetail('error',
  err(500, "1 validation error for WorkerResponse\\ncompany\\n  Field required"),
  'this worker');
ok(real.includes('500'), 'a server error names its status code');
ok(real.includes('Field required'),
  "and carries the server's own detail — the thing that was being thrown away");

console.log('\n-- what must NOT be rendered --');

// This codebase's convention: a refusal carries a machine CODE and the client
// owns the wording. Those details are DICTS. Rendering one at a person is
// worse than the generic sentence.
const coded = M.failureDetail('error',
  err(400, { code: 'SUBMIT_MISSING_CP_SIGNATURE' }), 'this log');
ok(!coded.includes('code'), 'a machine-code dict is NOT rendered raw at a person');
ok(!coded.includes('{'), 'and no object literal leaks into the copy');
ok(/400/.test(coded), 'but the status is still named, so it is not a dead end');

console.log('\n-- a client-side throw is distinguishable from a server one --');

const thrown = M.failureDetail('error', new TypeError("Cannot read properties of undefined (reading 'name')"));
ok(thrown.includes('Cannot read properties'),
  'a thrown TypeError shows its message rather than masquerading as a server failure');
ok(!thrown.includes('Server error'), 'and is not labelled a server error');
ok(M.failureDetail('error', null).length > 0, 'a null error still yields a sentence');
ok(M.failureDetail('error', {}).length > 0, 'and so does an empty one');

console.log('\n-- the subject is named, not hardcoded --');
ok(M.failureDetail('offline', null, 'this project').includes('this project'),
  'the caller says what failed to load');

console.log('\n-- the screen is wired to it --');
const SCREEN = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'workers', '[id].jsx'), 'utf8');
ok(/import \{ settleFetch, failureDetail \}/.test(SCREEN),
  'the worker screen imports the helper');
ok(/setDetailError\(failureDetail\(/.test(SCREEN), 'and records what went wrong');
ok(/detailError \|\| 'Could not load this worker/.test(SCREEN),
  'renders it, falling back to the old sentence only when there is nothing better');
ok(/NOT a statement that the worker has no SST card/.test(SCREEN),
  'and the offline branch keeps its load-bearing disclaimer');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
