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

// STANDS IN FOR WHAT /api/logbook-types SERVES, so it has to say what the
// server says. LOGBOOK_TYPE_REGISTRY is the source; nothing here asserts a
// label's text except the crane row below, so a stale name fails no test and
// is only ever read by the next person — which is exactly how a wrong name
// gets learned. preshift_signin said "Pre-Shift Safety Meeting" until #259
// moved the registry onto the name the filed document and the worker's gate
// affirmation both use.
const CATALOG = [
  { key: 'daily_jobsite', label: 'Daily Jobsite Log' },
  { key: 'preshift_signin', label: 'Pre-Shift Sign-In' },
  { key: 'toolbox_talk', label: 'Tool Box Talk' },
  { key: 'subcontractor_orientation', label: 'Subcontractor Safety Orientation' },
  { key: 'osha_log', label: 'OSHA Log Book' },
  { key: 'scaffold_maintenance', label: 'Scaffold Maintenance Log' },
  { key: 'ssc_daily_safety_log', label: 'SSC/SSM Daily Safety Log' },
  { key: 'hot_work', label: 'Hot Work Permit Log' },
  { key: 'concrete_operations', label: 'Concrete Operations Log' },
  { key: 'crane_operations', label: 'Crane Operations Log' },
  { key: 'excavation_monitoring', label: 'Excavation Monitoring Log' },
  { key: 'fall_protection', label: 'Fall Protection Equipment Log' },
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

console.log('\n-- there is no unassessed banner any more --');
// REMOVED BY RULING. This block asserted that an unassessed project was TOLD
// why two extra logs appeared rather than being handed them silently. That was
// right while "unassessed" was a state a project could be in.
//
// The operator has ruled that a project starts REGULAR, so there is no
// unassessed state for the banner to explain.
//
// THE SERVER FLAG IS DELIBERATELY LEFT ALONE. get_required_logbooks still
// fails closed on a class it cannot resolve and still reports
// classification_assessed, because it reads the RAW stored document, where a
// legacy project's class is still absent. What went is the SCREEN's
// explanation, not the rule. Asserted so a future reader does not take the
// missing banner as licence to drop the flag too.
ok(!/classification_assessed === false/.test(SCREEN),
  'the screen no longer explains an unassessed state');
ok(!/Building classification not set/.test(SCREEN),
  'and the copy is gone with it');

console.log('\n-- the four toggles are rendered from the model, not hardcoded --');
ok(/const activations = requiredLogbooks\?\.activations \|\| \[\];/.test(SCREEN),
  'the rows come from the server’s activations list');
ok(/activations\.map\(\(act\) =>/.test(SCREEN),
  'one row per conditional type — a fifth appears with no change here');
{
  // The scaffold toggle used to be the only one, hardcoded against its own
  // endpoint and its own state variable.
  ok(!/handleToggleScaffold/.test(SCREEN), 'the single hardcoded handler is gone');
  ok(!/saveScaffoldInfo\(projectId, \{ scaffold_erected/.test(SCREEN),
    'and so is its bespoke write path');
  ok(/handleToggleLogbook/.test(SCREEN), 'replaced by one handler for all of them');
}

console.log('\n-- who owns which switch --');
{
  const at = SCREEN.indexOf('activations.map((act)');
  const block = SCREEN.slice(at, SCREEN.indexOf('</>', at));
  ok(block.includes("const mine = act.activated_by !== 'admin';"),
    'ownership is read off the server’s answer, never a client-side list of types');
  ok(/mine\s*\?\s*handleToggleLogbook\(act\)/.test(block.replace(/\s+/g, ' ')),
    'a CP-owned switch flips');
  ok(block.includes('An admin sets this one'),
    'an admin-owned one explains itself instead of doing nothing');
  ok(block.includes('an admin switches this one on'),
    'and its OFF state says WHO turns it on — a CP hunting for the hot-work log '
    + 'needs to know it exists, not to find a dead control');
}
{
  // The client must not be the guard: the server enforces `activated_by`, and
  // hiding a control is a courtesy on top of that.
  // STRIPPED — the doc comment on this client explains that the SERVER owns
  // `activated_by`, and matching that sentence would satisfy the assertion
  // while proving nothing. Same trap backend/tests/source_text.py exists for.
  const api = strip(fs.readFileSync(
    path.join(FRONTEND, 'src', 'utils', 'api.js'), 'utf8'));
  ok(api.includes('/activation'), 'the client posts to the activation endpoint');
  ok(!/activated_by/.test(api),
    'and does not decide ownership itself — that answer only comes from the server');
}
{
  const at = SCREEN.indexOf('const handleToggleLogbook');
  const fn = SCREEN.slice(at, SCREEN.indexOf('\n  };', at));
  ok(fn.includes('e?.response?.status === 403'),
    'a refusal is told apart from a failure to save');
  ok(fn.includes('active: act.active'),
    'and the optimistic switch is put back on any error');
  ok(fn.includes('res?.required_logbooks'),
    'the recomputed set comes back in the same response, so the list below '
    + 'cannot disagree with the switch above it');
}

console.log('\n-- the day he never signed reaches the CP --');
{
  // The sweep leaves an unsigned stale log OPEN on purpose and tells the admin
  // through compliance_alerts. The CP is the only person who can finish it and
  // has no admin login, so the same fact reaches him here.
  //
  // IT IS NOW ONE CARD. The two detectors overlap totally on a `cp_signature: {}`
  // row, so the old pair counted the same days twice and tapped to opposite ends
  // of the same list. The server merges and de-duplicates them into
  // `attestation_gaps`; what the CP must still be TOLD is unchanged, and that is
  // what this block holds to.
  ok(/const gaps = notifications\?\.attestation_gaps \|\| \[\];/.test(SCREEN),
    'the list comes off the notifications endpoint, already de-duplicated');
  const at = SCREEN.indexOf('{gaps.length > 0 && (');
  ok(at > -1, 'and the card is gated on it');
  const card = SCREEN.slice(at, SCREEN.indexOf('OLDER SERVER FALLBACK'));
  ok(card.length > 200, 'ANCHOR: the card slice is non-empty');
  ok(/never signed/.test(card), 'it says what happened');
  // JSX wraps the copy across lines, so the assertion tolerates the wrap
  // rather than the copy being reflowed to suit a test.
  ok(/still yours\s+to finish/.test(card),
    'and that it is HIS to finish — an unfinished obligation, not a sealed record');
  ok(/not affirmed for that day/.test(card),
    'and the OTHER state is named separately, because it needs a different act');
  ok(/You do not need to sign again/.test(card),
    'THE LINE THAT STOPS A SECOND SIGNATURE. A `{}` signature is present but '
    + 'unaffirmed; tell him it was "never signed" and he concludes the app lost '
    + 'his mark and signs again, which is the one thing that must not happen');
  ok(/handleOpenGap/.test(card),
    'tapping it opens the log rather than being a dead badge');
}
{
  const fn = SCREEN.slice(SCREEN.indexOf('const handleOpenGap'),
    SCREEN.indexOf('const gapLabel'));
  ok(fn.length > 100, 'ANCHOR: the handler slice is non-empty');
  ok(/handleOpenGap = \(gap\)/.test(fn),
    'EVERY ROW IS A DOOR. The handler takes the row it was tapped from, so the '
    + 'CP is not made to fix the oldest and refetch to discover the second');
  ok(fn.includes('router.push('),
    'and it deep-links to that exact day, not to the list');
  ok(/!gap\) return;/.test(fn), 'a missing row taps to nothing');
}
{
  // THE WIDENING. A count with one door still hides everything behind the
  // first row; and a list windowed to today drops a filed log the morning
  // after, which is how three of these sat unseen for three weeks.
  ok(/const gapsOldestFirst = \[...gaps\].reverse\(\);/.test(SCREEN),
    'OLDEST first — the server sorts newest-first for the count, but a worklist '
    + 'reads with the most overdue day at the top');
  const card = SCREEN.slice(SCREEN.indexOf('{gaps.length > 0 && ('),
    SCREEN.indexOf('OLDER SERVER FALLBACK'));
  ok(card.length > 200, 'ANCHOR: the card slice is non-empty');
  ok(/gapsOldestFirst.map\(/.test(card), 'EVERY gap row is rendered, not just a count');
  ok(/onPress={\(\) => handleOpenGap\(g\)}/.test(card),
    'and each row opens its own day');
  ok(/g.state === 'unsigned' \? 'never signed' : 'not affirmed'/.test(card),
    'the row names which of the two states it is in, because they need '
    + 'different acts from him');
  ok(/gapLabel\(g.log_type\)/.test(card),
    'and it names the log the same way the list above it does');
  ok(!/gapOldest/.test(SCREEN),
    'the single-door path is GONE, not left beside the list to disagree with it');
}
{
  // A DATE THAT IS OFF BY ONE IS WORSE THAN AN ISO STRING. `new Date('2026-08-11')`
  // is UTC midnight and renders as the 10th on New York time, so the card would
  // name a different day than the log is filed under.
  const fn = SCREEN.slice(SCREEN.indexOf('const gapDate'),
    SCREEN.indexOf('const getLogStatus'));
  ok(fn.length > 100, 'ANCHOR: the formatter slice is non-empty');
  ok(fn.includes("split(&-&)".replace(/&/g, String.fromCharCode(39))),
    'the ISO date is split by string');
  ok(!fn.includes('new Date('), 'and never parsed through Date, which would shift it a day');
  ok(fn.includes('today.slice(0, 4)'),
    'the year shows only when it is not this one — an inspector asking about '
    + 'last August must not read it as this August');
}
{
  // NOT A NEW TREATMENT. It reuses the card the two it replaced both used.
  const mine = SCREEN.slice(SCREEN.indexOf('{gaps.length > 0 && ('),
    SCREEN.indexOf('OLDER SERVER FALLBACK'));
  const theirs = SCREEN.slice(SCREEN.indexOf('{gaps.length === 0 && ('),
    SCREEN.indexOf('{gaps.length === 0 && (') + 1200);
  ok(mine.length > 200 && theirs.length > 200, 'ANCHOR: both slices are non-empty');
  for (const bit of ['styles.notifCard', 'styles.notifHeader', 'AlertTriangle',
    'semantic.attention', 'styles.notifTitle', 'styles.notifWorker']) {
    ok(mine.includes(bit) && theirs.includes(bit),
      `reuses the unaffirmed card's ${bit} rather than inventing a variant`);
  }
}
{
  // THE FALLBACK MUST NOT DOUBLE UP. An older SERVER sends only the two counts
  // and its CP would otherwise lose the cards entirely; a current server sends
  // the merged list, and the old pair has to disappear the moment it arrives or
  // the double-count is back with one extra card.
  ok(SCREEN.includes('{gaps.length === 0 && (unaffirmedLogbooks > 0 || staleUnsigned > 0) && ('),
    'the old pair renders ONLY when the merged list is absent');
  ok(/const staleUnsigned = notifications\?\.stale_unsigned_logbooks \|\| 0;/.test(SCREEN),
    'and the old counts are still read, so that fallback has something to show');
}
ok(SCREEN.includes('stale_unsigned_logbooks: 0, stale_unsigned_logbook_refs: [], attestation_gaps: []'),
  'the offline default carries the new keys, so a failed fetch reads 0/[] not undefined');

{
  // ── AND THE TILE IT RENDERS GOES SOMEWHERE ──────────────────────────────
  //
  // The chain this file guards has one more link than it was checking. The
  // required set reaches the screen; the screen renders a tile; the tile
  // routes BY CONVENTION —
  //
  //     router.push(`/logbooks/${log_type}?projectId=...`)
  //
  // so the registry key IS the route, and the route IS the filename under
  // app/logbooks/. Nothing enforced that. site_superintendent_log shipped as
  // site_superintendent_log.jsx, and the tile for a log the server marks required
  // on EVERY project class routed to a screen that does not exist.
  //
  // It fails the way this file's original defect failed: nothing crashes at
  // build, no gate mentions it, and the screen looks complete from every angle
  // except tapping the tile. Read from the SERVER's registry rather than a
  // hand-copied list, so a fourteenth type cannot ship half-wired.
  const SERVER = fs.readFileSync(
    path.join(FRONTEND, '..', 'backend', 'server.py'), 'utf8');
  const reg = SERVER.slice(SERVER.indexOf('LOGBOOK_TYPE_REGISTRY = ['));
  const keys = [...reg.slice(0, reg.indexOf('\n]')).matchAll(/^\s*"key": "([a-z_]+)"/gm)]
    .map((m) => m[1]);
  ok(keys.length === 13, `ANCHOR: 13 registry keys read from server.py (${keys.length})`);

  const screens = new Set(fs.readdirSync(path.join(FRONTEND, 'app', 'logbooks'))
    .filter((f) => f.endsWith('.jsx'))
    .map((f) => f.replace(/\.jsx$/, '')));
  const unreachable = keys.filter((k) => !screens.has(k));
  ok(unreachable.length === 0,
    'every required log type has a screen at its own name, so the dashboard tile '
    + `reaches an editor rather than an unmatched route. Missing: ${JSON.stringify(unreachable)}`);

  ok(/router\.push\(`\/logbooks\/\$\{log_type\}\?projectId=/.test(SCREEN),
    'ANCHOR: the tile still routes by log_type — if that changes, the rule above '
    + 'is no longer the rule and this check must be rewritten, not deleted');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
