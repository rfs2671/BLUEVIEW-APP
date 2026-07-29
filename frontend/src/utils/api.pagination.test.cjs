/**
 * Unit tests for the three paginated-endpoint client unwrappers in api.js:
 *   checkinsAPI.getByDate, dailyLogsAPI.getByProject, logbooksAPI.getByProject.
 *
 * This repo has NO JavaScript test runner (no jest/vitest, no "test" script).
 * api.js also cannot be imported under bare node — it pulls in axios and RN
 * modules at module top, and is ESM. So, following the RiskScoreCircle.bandFor
 * harness in this repo, this test reads the REAL api.js source, extracts the
 * three shipped async function bodies VERBATIM (keyed by their unique request
 * URL / signature), and evaluates just those with a stubbed apiClient. If a
 * function's shape changes, extraction either tracks it or throws loudly — it
 * is never a hand-copy of the logic.
 *
 * WHY THIS EXISTS — the regression under test:
 * These three endpoints return the paginated wrapper {items,total,limit,skip,
 * has_more}. The clients used to `return response.data` (the raw object). Every
 * consumer applies Array.isArray to that object, gets false, and collapses to
 * []. For the logbook editors that meant `existing = null`, so they reopened
 * blank and re-entered the create path; POST /logbooks upserts on
 * (project_id, log_type, date) with $set on the whole `data` object. A real
 * toolbox_talk on project 6a5f63bc147407d3261df2c7 dated 2026-07-29 was created
 * 16:36:12.450Z and OVERWRITTEN 19:40:06.918Z, losing the first submission with
 * no audit trail. Unwrapping here restores `existing`, so the editors reload
 * the record and the second same-day submit preserves it.
 *
 * Run:  node src/utils/api.pagination.test.cjs
 */

const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, 'api.js');
const src = fs.readFileSync(file, 'utf8');

// ── Extract a shipped arrow-function body verbatim, anchored on a unique
//    substring (the request URL / signature that only this function contains).
//    Walks back to the enclosing `=> {` and forward via brace-matching. The
//    three target bodies contain only balanced braces (template ${} and inline
//    objects), so naive depth counting is exact for them.
function extractFn(anchor) {
  const uidx = src.indexOf(anchor);
  if (uidx < 0) throw new Error(`anchor not found in api.js: ${anchor}`);
  const arrowIdx = src.lastIndexOf('=> {', uidx);
  if (arrowIdx < 0) throw new Error(`no arrow before anchor: ${anchor}`);
  const paramOpen = src.lastIndexOf('(', arrowIdx);
  const params = src.slice(paramOpen, arrowIdx).trim(); // e.g. "(projectId)"
  const bodyStart = src.indexOf('{', arrowIdx);
  let depth = 0;
  let i = bodyStart;
  for (; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) { i += 1; break; }
    }
  }
  const body = src.slice(bodyStart, i); // includes the outer { ... }
  // Sanity: the shipped fix must be present, or the test is asserting nothing.
  if (!/Array\.isArray\(data\)\s*\?\s*data\s*:\s*\(data\?\.items\s*\?\?\s*\[\]\)/.test(body)) {
    throw new Error(`unwrap expression missing from function at anchor: ${anchor}`);
  }
  // Build a callable with `apiClient` injected as the sole closure dependency.
  const make = new Function('apiClient', `return (async ${params} => ${body});`);
  return make;
}

const GET_BY_DATE = '/api/checkins?date=';
const DAILYLOGS_BY_PROJECT = '/api/daily-logs/project/';
const LOGBOOKS_BY_PROJECT = '/api/logbooks/project/';

// A stub apiClient whose .get() returns a caller-controlled response body.
function clientReturning(dataValue) {
  return { get: async () => ({ data: dataValue }) };
}

const makeGetByDate = extractFn(GET_BY_DATE);
const makeDailyLogsByProject = extractFn(DAILYLOGS_BY_PROJECT);
const makeLogbooksByProject = extractFn(LOGBOOKS_BY_PROJECT);

// Each target invoked with representative args (getByDate needs a real Date for
// its Intl.DateTimeFormat call; the getByProject variants take ids/filters).
const CALLS = [
  { name: 'checkinsAPI.getByDate', run: (data) => makeGetByDate(clientReturning(data))(new Date('2026-07-29T12:00:00Z')) },
  { name: 'dailyLogsAPI.getByProject', run: (data) => makeDailyLogsByProject(clientReturning(data))('p1') },
  { name: 'logbooksAPI.getByProject', run: (data) => makeLogbooksByProject(clientReturning(data))('6a5f63bc147407d3261df2c7', 'toolbox_talk', '2026-07-29') },
];

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const eqArr = (a, b) => Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => x === b[i]);

(async () => {
  for (const { name, run } of CALLS) {
    // 1. wrapper {items:[a,b]} → [a,b]
    const A = { id: 'a' };
    const B = { id: 'b' };
    ok(eqArr(await run({ items: [A, B], total: 2, limit: 50, skip: 0, has_more: false }), [A, B]),
      `${name}: {items:[a,b]} -> [a,b]`);

    // 2. bare array passes through unchanged
    const bare = [A, B];
    const out2 = await run(bare);
    ok(eqArr(out2, bare), `${name}: bare array -> same array unchanged`);

    // 3a. empty wrapper → []
    ok(eqArr(await run({ items: [], total: 0, limit: 50, skip: 0, has_more: false }), []),
      `${name}: {items:[]} -> []`);

    // 3b. malformed object (no items) → [] and does not throw
    let threw = false;
    let out3b;
    try { out3b = await run({ foo: 1 }); } catch (e) { threw = true; }
    ok(!threw && eqArr(out3b, []), `${name}: malformed object -> [] (no throw)`);

    // 3c. null body → [] and does not throw (data?.items ?? [])
    let threw3c = false;
    let out3c;
    try { out3c = await run(null); } catch (e) { threw3c = true; }
    ok(!threw3c && eqArr(out3c, []), `${name}: null body -> [] (no throw)`);
  }

  // 4. Regression: logbooksAPI.getByProject MUST return an array so the
  //    Array.isArray guard in the ten editors passes and `existing` is computed
  //    from the loaded record — preventing the blank-reopen create-path that
  //    overwrote the toolbox_talk on 2026-07-29 (see file header).
  const runLb = (data) => makeLogbooksByProject(clientReturning(data))('6a5f63bc147407d3261df2c7', 'toolbox_talk', '2026-07-29');
  const lbWrapped = await runLb({ items: [{ id: 'lb1' }], total: 1, limit: 50, skip: 0, has_more: false });
  ok(Array.isArray(lbWrapped) && lbWrapped.length === 1, 'REGRESSION logbooksAPI.getByProject returns an array (Array.isArray guard passes)');

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})().catch((e) => { console.error(e); process.exit(2); });
