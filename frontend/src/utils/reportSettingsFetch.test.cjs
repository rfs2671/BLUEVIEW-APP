/**
 * Regression test for the Report Settings brace bug.
 *
 * fetchProject() reads report_email_list / report_send_time from the SERVER
 * (projectsAPI.getById) and must push them into state via setEmailList /
 * setSendTime. A missing `}` after the `throw` had trapped setProject /
 * setEmailList / setSendTime inside `if (!projectData) { … }`, so on the success
 * path they never ran and the screen reopened empty.
 *
 * This extracts the REAL fetchProject body verbatim from report-settings.jsx and
 * runs it with stubbed deps. It asserts the fetched values reach the setters —
 * which FAILS against the brace placement (setters trapped in the if) and passes
 * once the brace is fixed.
 *
 * HARNESS REPAIR (no assertion was weakened). The screen has since adopted the
 * app-wide offline-settle pattern: fetchProject now calls settleFetch, falls
 * back to readCachedProject, and reports through setFetchState / setHasChanges.
 * The harness injected a fixed list of seven closure vars and none of those
 * four were on it, so the extracted body threw
 * `ReferenceError: settleFetch is not defined` before a single assertion ran —
 * exit code 2, and CI's `set -e` halted the whole frontend job there. The three
 * original assertions are unchanged and still the point; the missing vars are
 * now injected, and the offline path the screen gained is covered too.
 *
 * settleFetch is the REAL one, evaluated out of src/utils/offlineState.js
 * rather than stubbed — a stub of the very thing under test would prove
 * nothing about the status values the screen branches on.
 *
 * Run:  node src/utils/reportSettingsFetch.test.cjs
 */
const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', '..', 'app', 'project', '[id]', 'report-settings.jsx');
const src = fs.readFileSync(file, 'utf8');

// The real settleFetch / isOfflineError. offlineState.js imports nothing, so
// stripping the export keywords is enough to run the shipped code here.
const offlineSrc = fs.readFileSync(path.join(__dirname, 'offlineState.js'), 'utf8')
  .replace(/^export default [\s\S]*$/m, '')
  .replace(/^export (async function|function|const) /gm, '$1 ');
// eslint-disable-next-line no-new-func
const { settleFetch } = new Function(`${offlineSrc}\nreturn { settleFetch, isOfflineError };`)();

// Extract the `const fetchProject = async () => { … }` body verbatim.
const anchor = 'const fetchProject = async () => {';
const at = src.indexOf(anchor);
if (at < 0) throw new Error('fetchProject not found in report-settings.jsx');
const braceStart = src.indexOf('{', at + anchor.length - 1);
let depth = 0, i = braceStart;
for (; i < src.length; i += 1) {
  if (src[i] === '{') depth += 1;
  else if (src[i] === '}') { depth -= 1; if (depth === 0) { i += 1; break; } }
}
const body = src.slice(braceStart, i); // includes the outer { … }

// Build a callable with the component's closure vars injected as params.
// console / Error are globals; the rest are stubbed.
const PARAMS = ['projectsAPI', 'setProject', 'setEmailList', 'setSendTime',
  'setLoading', 'toast', 'projectId', 'settleFetch', 'readCachedProject',
  'setFetchState', 'setHasChanges'];
const make = new Function(...PARAMS, `return (async () => ${body});`);

let passed = 0, failed = 0;
const ok = (c, l) => { if (c) { passed += 1; console.log('  PASS  ' + l); } else { failed += 1; console.log('  FAIL  ' + l); } };

// GUARD: the harness must inject every free variable the real body uses. When
// the screen gained settleFetch this list went stale and the file died with a
// ReferenceError before any assertion ran — which reads as "test failing" but
// was "test not running at all", and it took the rest of CI's frontend job
// down with it. This catches the next such drift as a NAMED failure.
// Comments are stripped first (the body documents cacheProject() in prose,
// which is not a call), and a name preceded by `.` is a METHOD on something
// already injected, not a free variable of its own.
const scanBody = body.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
const missing = [...new Set(
  [...scanBody.matchAll(/(^|[^.\w$])([a-z][A-Za-z0-9_]*)\s*\(/g)].map((m) => m[2]),
)].filter((n) => !PARAMS.includes(n)
  && !['console', 'Error', 'String', 'Number', 'Boolean', 'Array', 'Object',
    'JSON', 'Promise', 'setTimeout', 'if', 'for', 'while', 'return', 'await',
    'async', 'function', 'catch', 'switch', 'typeof'].includes(n));
ok(missing.length === 0,
  `harness injects every dependency fetchProject calls${missing.length ? ` — MISSING ${JSON.stringify(missing)}` : ''}`);

const SERVER = { report_email_list: ['rfs2671@gmail.com'], report_send_time: '17:00', id: 'p1' };

/** Run the real body against one server outcome. */
async function run({ getById, cached = null }) {
  const c = { states: [], changes: [] };
  const fetchProject = make(
    { getById },
    (v) => { c.project = v; },
    (v) => { c.emailList = v; },
    (v) => { c.sendTime = v; },
    (v) => { c.loading = v; },
    { error: () => {}, success: () => {}, info: () => {}, warning: () => {} },
    'p1',
    settleFetch,
    async () => cached,
    (v) => { c.states.push(v); },
    (v) => { c.changes.push(v); },
  );
  c.status = await fetchProject();
  return c;
}

(async () => {
  // ── The original regression: the success path must reach the setters ──────
  {
    const c = await run({ getById: async () => SERVER });
    ok(Array.isArray(c.emailList) && c.emailList[0] === 'rfs2671@gmail.com',
      'fetched report_email_list reaches setEmailList');
    ok(c.sendTime === '17:00', 'fetched report_send_time reaches setSendTime');
    ok(c.project === SERVER, 'fetched project reaches setProject');
    ok(c.status === 'ok', 'a served read reports ok');
    ok(c.states.includes('ok'), 'and the screen records that state');
  }

  // ── The offline path the screen gained ────────────────────────────────────
  // A dead zone must serve the CACHED settings, never a blank form. Reopening
  // to an empty email list reads as "nobody is on the report" — the same class
  // of confident-empty lie the offline discriminator exists to kill.
  {
    const netErr = Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' });
    const c = await run({
      getById: async () => { throw netErr; },
      cached: { report_email_list: ['cached@example.com'], report_send_time: '09:00', id: 'p1' },
    });
    ok(c.status === 'offline', 'a network failure reports offline, not error');
    ok(c.emailList[0] === 'cached@example.com',
      'OFFLINE: the cached email list is shown rather than a blank form');
    ok(c.sendTime === '09:00', 'OFFLINE: the cached send time is shown too');
    ok(c.changes.includes(false),
      'OFFLINE: the unsaved-changes flag is cleared — a cached read is not a save target');
  }

  // A server that ANSWERED with an error is not offline, and must say so.
  {
    const httpErr = Object.assign(new Error('Boom'), { response: { status: 500 } });
    const c = await run({ getById: async () => { throw httpErr; }, cached: null });
    ok(c.status === 'error', 'a 5xx reports error, not offline — the server did answer');
    ok(c.emailList === undefined,
      'and with no cache to fall back on, nothing is invented into the form');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})().catch((e) => { console.error(e); process.exit(2); });
