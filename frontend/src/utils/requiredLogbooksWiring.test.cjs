/**
 * THE RESOLVED REQUIRED SET REACHES THE CP'S SCREEN.
 *
 * The operator could not find five ported forms and concluded they were not
 * marked required for his project. That was true, and it was not the only
 * thing wrong: the required set had never reached this screen at all.
 *
 *   GET /api/projects/{id}/required-logbooks
 *     -> {project_id, project_class, classification_assessed, required_logbooks}
 *
 * and the screen read `reqLogbooks?.logbooks` — a key that does not exist. So
 * setRequiredLogbooks never fired, the dynamic branch of getVisibleLogTypes
 * never ran, and the list was ALWAYS the six hardcoded FALLBACK_LOG_TYPES. The
 * branch was broken twice over, too: it mapped `l.log_type` across what are
 * plain strings, so even with the right key it would have produced a list of
 * `undefined`. Neither half could be noticed while the other held.
 *
 * This file EXECUTES the real getVisibleLogTypes out of the screen source
 * rather than grepping it, because "the branch exists" is exactly what was
 * true the whole time it did nothing.
 *
 * Run:  node src/utils/requiredLogbooksWiring.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN_RAW = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'index.jsx'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

/** Comments out before any source assertion — this file's own prose names
 *  every symbol it checks for. */
const strip = (text) => text
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')
  .replace(/\s\/\/[^\n'"`]*$/gm, '');
const SCREEN = strip(SCREEN_RAW);
ok(/getVisibleLogTypes/.test(SCREEN) && !/a key that does not exist/.test(SCREEN),
  'the comment stripper removes prose but keeps code');

// ── Lift the real function out of the component and run it ─────────────────
function slice(src, start, end) {
  const i = src.indexOf(start);
  if (i < 0) throw new Error(`not found: ${start}`);
  const j = src.indexOf(end, i);
  if (j < 0) throw new Error(`no end for: ${start}`);
  return src.slice(i, j + end.length);
}

const FALLBACK_SRC = slice(SCREEN_RAW, 'const FALLBACK_LOG_TYPES = [', '\n];');
const FN_SRC = slice(SCREEN_RAW, '  const getVisibleLogTypes = () => {', '\n  };');

/** Build the function with the component's closure supplied as data. */
function build({ requiredLogbooks = null, logTypeCatalog = null,
  scaffoldActive = false, toolboxDoneThisWeek = false, notifications = {} } = {}) {
  // eslint-disable-next-line no-new-func
  return new Function('env', `
    const semantic = { neutral: '#94a3b8' };
    ${FALLBACK_SRC}
    const requiredLogbooks = env.requiredLogbooks;
    const logTypeCatalog = env.logTypeCatalog;
    const scaffoldActive = env.scaffoldActive;
    const toolboxDoneThisWeek = env.toolboxDoneThisWeek;
    const notifications = env.notifications;
    ${FN_SRC}
    return getVisibleLogTypes();
  `)({ requiredLogbooks, logTypeCatalog, scaffoldActive, toolboxDoneThisWeek, notifications });
}

const CATALOG = [
  { key: 'daily_jobsite', label: 'Daily Jobsite Log' },
  { key: 'preshift_signin', label: 'Pre-Shift Safety Meeting' },
  { key: 'toolbox_talk', label: 'Tool Box Talk' },
  { key: 'subcontractor_orientation', label: 'Subcontractor Safety Orientation' },
  { key: 'osha_log', label: 'OSHA Log Book' },
  { key: 'scaffold_maintenance', label: 'Scaffold Maintenance Log' },
  { key: 'ssc_daily_safety_log', label: 'SSC/SSM Daily Safety Log' },
  { key: 'hot_work', label: 'Hot Work Permit Log' },
  { key: 'concrete_operations', label: 'Concrete Operations Log' },
  { key: 'crane_operations', label: 'Crane Operations Log' },
  { key: 'excavation_monitoring', label: 'Excavation Monitoring Log' },
];
const keysOf = (rows) => rows.map((r) => r.key);

console.log('\n-- the server decides, and the screen renders that answer --');
{
  const required = ['daily_jobsite', 'preshift_signin', 'osha_log',
    'toolbox_talk', 'subcontractor_orientation'];
  const rows = build({
    requiredLogbooks: { required_logbooks: required, classification_assessed: true },
    logTypeCatalog: CATALOG,
  });
  ok(JSON.stringify(keysOf(rows)) === JSON.stringify(required),
    'exactly the required set, in the server’s order');
  ok(rows.every((r) => r.label && !/^[a-z_]+$/.test(r.label)),
    'every row carries a real label, not a raw key');
}
{
  // The whole point of the change: a toggled-on conditional form reaches him.
  const rows = build({
    requiredLogbooks: {
      required_logbooks: ['daily_jobsite', 'crane_operations', 'excavation_monitoring', 'hot_work'],
      classification_assessed: true,
    },
    logTypeCatalog: CATALOG,
  });
  ok(keysOf(rows).includes('crane_operations')
     && keysOf(rows).includes('excavation_monitoring')
     && keysOf(rows).includes('hot_work'),
    'the three toggled forms appear once the server requires them');
  ok(rows.find((r) => r.key === 'crane_operations').label === 'Crane Operations Log',
    'and are labelled from the registry, not key-cased');
}
{
  const rows = build({
    requiredLogbooks: { required_logbooks: ['daily_jobsite'], classification_assessed: true },
    logTypeCatalog: CATALOG,
  });
  ok(keysOf(rows).length === 1,
    'a type the server does NOT require is not shown, whatever the fallback holds');
}

console.log('\n-- the dead key is dead --');
{
  // The exact payload shape that used to reach this screen and do nothing.
  const rows = build({
    requiredLogbooks: { logbooks: [{ log_type: 'daily_jobsite' }] },
    logTypeCatalog: CATALOG,
  });
  ok(!rows.some((r) => r.key === undefined),
    'the `logbooks` key produces no undefined rows');
  ok(keysOf(rows).length > 1,
    'it is not treated as a required set at all — the screen falls back');
}

console.log('\n-- offline / first paint still shows something --');
{
  const rows = build({ requiredLogbooks: null, scaffoldActive: true });
  ok(keysOf(rows).includes('scaffold_maintenance'),
    'with no server answer the local fallback still renders');
  ok(keysOf(rows).includes('daily_jobsite'), 'including the daily core');
}
{
  const rows = build({
    requiredLogbooks: { required_logbooks: [], classification_assessed: true },
  });
  ok(rows.length > 0,
    'an EMPTY required set is treated as no answer, not as "nothing to file" — '
    + 'a CP is never shown a blank list because a request came back thin');
}
{
  const rows = build({
    requiredLogbooks: { required_logbooks: ['something_new'], classification_assessed: true },
    logTypeCatalog: CATALOG,
  });
  ok(keysOf(rows).join() === 'something_new' && !!rows[0].label,
    'a required type nothing describes is still rendered — a log the CP '
    + 'cannot open is worse than an ugly label');
}

console.log('\n-- the fetch reads the key the server sends --');
ok(/Array\.isArray\(reqLogbooks\?\.required_logbooks\)/.test(SCREEN),
  'the guard tests required_logbooks');
ok(!/reqLogbooks\?\.logbooks/.test(SCREEN), 'and the non-existent key is gone');
ok(/logbookTypesAPI\.getAll\(\)/.test(SCREEN),
  'the registry is fetched — it was served and never once requested');

console.log('\n-- an unassessed project is TOLD, not just given two extra logs --');
ok(/requiredLogbooks\.classification_assessed === false/.test(SCREEN),
  'the banner is gated on the server’s own assessment flag');
{
  const at = SCREEN.indexOf('classification_assessed === false');
  const card = SCREEN.slice(at, at + 900);
  ok(/Building classification not set/.test(card), 'it names the condition');
  ok(/Concrete Operations and SSC\/SSM/.test(card),
    'and names the two logs it explains, so the list stops reading as wrong');
  ok(/=== false/.test(SCREEN.slice(at - 40, at + 40)),
    'strict false — undefined (an older server) must not raise it');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
