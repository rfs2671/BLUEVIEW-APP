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
const { loadEsm } = require('./esmHarness.cjs');

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

/** Build the function with the component's closure supplied as data.
 *
 * `periods` and `periodSatisfied` are the REAL ones — the payload key and the
 * shared helper the screen imports — so this cannot pass on a stub that
 * answers differently from the module in production. */
// logbookCadence.js is ESM and imports nothing, so esmHarness loads the
// SHIPPED module — not a copy of its rule kept in step by eye.
const { logbookPeriods, periodSatisfied } = loadEsm('src/utils/logbookCadence.js');

function build({ requiredLogbooks = null, logTypeCatalog = null,
  scaffoldActive = false, toolboxDoneThisWeek = false, notifications = {} } = {}) {
  // eslint-disable-next-line no-new-func
  return new Function('env', 'periodSatisfied', `
    const semantic = { neutral: '#94a3b8' };
    ${FALLBACK_SRC}
    const requiredLogbooks = env.requiredLogbooks;
    const logTypeCatalog = env.logTypeCatalog;
    const scaffoldActive = env.scaffoldActive;
    const toolboxDoneThisWeek = env.toolboxDoneThisWeek;
    const notifications = env.notifications;
    const periods = env.periods;
    ${FN_SRC}
    return getVisibleLogTypes();
  `)({ requiredLogbooks, logTypeCatalog, scaffoldActive, toolboxDoneThisWeek,
    notifications, periods: logbookPeriods(requiredLogbooks) }, periodSatisfied);
}

// STANDS IN FOR WHAT /api/logbook-types SERVES, so it has to say what the
// server says. LOGBOOK_TYPE_REGISTRY is the source; nothing here asserts a
// label's text except the crane row below, so a stale name fails no test and
// is only ever read by the next person — which is exactly how a wrong name
// gets learned. preshift_signin said "Pre-Shift Safety Meeting" until #259
// moved the registry onto the name the filed document and the worker's gate
// affirmation both use.
//
// IT CARRIES `frequency` NOW, and that is not decoration. The catalog wins
// over FALLBACK_LOG_TYPES in getVisibleLogTypes' byKey merge, so a stand-in
// without the field would have given every type `undefined` here while the
// real server sends the registry's word — and the as-needed rule below would
// have been tested against a shape the app never sees. The frequencies are
// checked against LOGBOOK_TYPE_REGISTRY at the foot of this file.
const CATALOG = [
  { key: 'daily_jobsite', label: 'Daily Jobsite Log', frequency: 'daily' },
  { key: 'preshift_signin', label: 'Pre-Shift Sign-In', frequency: 'daily' },
  { key: 'toolbox_talk', label: 'Tool Box Talk', frequency: 'weekly' },
  { key: 'subcontractor_orientation', label: 'Subcontractor Safety Orientation', frequency: 'as_needed' },
  { key: 'osha_log', label: 'OSHA Log Book', frequency: 'daily' },
  { key: 'scaffold_maintenance', label: 'Scaffold Maintenance Log', frequency: 'daily' },
  { key: 'ssc_daily_safety_log', label: 'SSC/SSM Daily Safety Log', frequency: 'daily' },
  { key: 'hot_work', label: 'Hot Work Permit Log', frequency: 'as_needed' },
  { key: 'concrete_operations', label: 'Concrete Operations Log', frequency: 'daily' },
  { key: 'crane_operations', label: 'Crane Operations Log', frequency: 'daily' },
  { key: 'excavation_monitoring', label: 'Excavation Monitoring Log', frequency: 'daily' },
  { key: 'fall_protection', label: 'Fall Protection Equipment Log', frequency: 'daily' },
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
    'exactly the required set, in the server’s order, when the server has said '
    + 'nothing about any of them being satisfied');
  ok(rows.every((r) => r.label && !/^[a-z_]+$/.test(r.label)),
    'every row carries a real label, not a raw key');
}

console.log('\n-- REQUIRED IS NOT DUE: a satisfied as-needed log leaves the list --');
// ── THIS BLOCK USED TO ASSERT THE DEFECT ───────────────────────────────────
//
// The assertion above said "exactly the required set" FULL STOP, with no
// `periods` in play, and that was read as the rule. It is not the rule, and
// holding it as one is what kept a broken tile on three CPs' screens:
//
//   `subcontractor_orientation` is `frequency: as_needed`. It is required on
//   every project — get_required_logbooks resolves it for every §3310 class
//   and is RIGHT to — but it is DUE for exactly one reason: a worker checked
//   in and has no orientation on this project. The tile asked
//   `todayLogs[type]`, a by-DATE read, so it answered Pending every morning.
//
//   MEASURED READ-ONLY ON ALL THREE LIVE PROJECTS: 8 Walworth 0 workers / 0
//   orientations, 588 Thomas 63 checked in / 65 oriented, 857 Prescott 13/13.
//   Nobody anywhere was waiting for an orientation, and every CP saw a
//   permanently-Pending tile inside a count that read 4/6.
//
// The old assertion could not tell "the screen renders the server's set" from
// "the screen renders the server's set and ignores everything else the server
// says about it". It now carries the condition it was always implicitly
// making — no periods, no opinion — and the rule proper is below.
{
  const required = ['daily_jobsite', 'preshift_signin', 'osha_log',
    'toolbox_talk', 'subcontractor_orientation'];
  const payload = {
    required_logbooks: required,
    classification_assessed: true,
    periods: [
      { log_type: 'subcontractor_orientation', frequency: 'as_needed',
        satisfied: true, due_reason: null, uncovered_workers: [],
        uncovered_worker_count: 0 },
    ],
  };
  const rows = build({ requiredLogbooks: payload, logTypeCatalog: CATALOG });
  ok(!keysOf(rows).includes('subcontractor_orientation'),
    'a satisfied as-needed log is not on today’s list');
  ok(keysOf(rows).length === required.length - 1,
    'and it leaves the DENOMINATOR with it — the count is derived from this '
    + 'same list, so 6 becomes 5 with no second edit');
  ok(JSON.stringify(keysOf(rows))
     === JSON.stringify(required.filter((k) => k !== 'subcontractor_orientation')),
    'nothing else moves, and the server’s order is kept');
}
{
  // THE OTHER HALF, and it is the half that matters more. A missing
  // obligation on a compliance screen is invisible in the way an extra one is
  // not, so a DUE as-needed log must stay exactly where it was.
  const payload = {
    required_logbooks: ['daily_jobsite', 'subcontractor_orientation'],
    classification_assessed: true,
    periods: [
      { log_type: 'subcontractor_orientation', frequency: 'as_needed',
        satisfied: false, due_reason: 'WORKER_NOT_ORIENTED',
        uncovered_workers: ['Andre Duval'], uncovered_worker_count: 1 },
    ],
  };
  ok(keysOf(build({ requiredLogbooks: payload, logTypeCatalog: CATALOG }))
    .includes('subcontractor_orientation'),
    'a DUE as-needed log stays on the list');
}
{
  // AN OLDER SERVER SENDS NO `periods` AT ALL. periodSatisfied answers null,
  // which is not `true`, so nothing is hidden — the same fail-open the
  // cadence module is built around.
  const rows = build({
    requiredLogbooks: {
      required_logbooks: ['daily_jobsite', 'subcontractor_orientation'],
      classification_assessed: true,
    },
    logTypeCatalog: CATALOG,
  });
  ok(keysOf(rows).includes('subcontractor_orientation'),
    'no periods key hides nothing');
}
{
  // ── HOT WORK HAS A RULING NOW, AND THIS IS WHAT IT LOOKS LIKE HERE ───────
  //
  // This block used to assert the opposite: that `hot_work` KEEPS its tile
  // when another type's row is satisfied, because NO SERVER RULE SAID WHEN A
  // HOT-WORK PERMIT LOG WAS DUE and the predicate's silence was the only thing
  // between it and being hidden. It needed the operator's ruling.
  //
  // The ruling: "due only on days hot work happens. CP or super toggles it on
  // for that day. Dated, not persistent." So the server emits a row, and on a
  // day nobody declared it says satisfied and the tile goes — which is the
  // defect being fixed. 8 Walworth has the STANDING permit on, which is why
  // hot_work is in its required set, and its tile read Pending every morning.
  //
  // THE PREDICATE DID NOT MOVE. The block below this one re-pins the fail-open
  // property on a type that has no rule, which is what these assertions were
  // really protecting.
  const quiet = build({
    requiredLogbooks: {
      required_logbooks: ['daily_jobsite', 'hot_work'],
      classification_assessed: true,
      periods: [
        { log_type: 'hot_work', frequency: 'as_needed', satisfied: true,
          period_start: '2026-09-18', period_end: '2026-09-18',
          declared: false },
      ],
    },
    logTypeCatalog: CATALOG,
  });
  ok(!keysOf(quiet).includes('hot_work'),
    'a day nobody declared: hot_work leaves the list');

  const declared = build({
    requiredLogbooks: {
      required_logbooks: ['daily_jobsite', 'hot_work'],
      classification_assessed: true,
      periods: [
        { log_type: 'hot_work', frequency: 'as_needed', satisfied: false,
          period_start: '2026-09-18', period_end: '2026-09-18',
          due_reason: 'HOT_WORK_DECLARED', declared: true },
      ],
    },
    logTypeCatalog: CATALOG,
  });
  ok(keysOf(declared).includes('hot_work'),
    'and a declared one is back on it');
}
{
  // ── THE FAIL-OPEN PROPERTY, RE-PINNED ON A TYPE THAT STILL NEEDS IT ──────
  //
  // Both as-needed types in the registry now have rules, so the instance has
  // to be the NEXT one — a type added before anybody writes its rule. With no
  // row for a key, periodSatisfied answers null, which is not `true`, so the
  // predicate never fires and the tile and denominator entry both survive.
  //
  // A missing obligation is invisible in the way an extra one is not, so
  // silence must keep the tile. That has not changed.
  const rows = build({
    requiredLogbooks: {
      required_logbooks: ['daily_jobsite', 'a_type_with_no_rule_yet'],
      classification_assessed: true,
      periods: [
        { log_type: 'hot_work', frequency: 'as_needed', satisfied: true },
      ],
    },
    logTypeCatalog: [...CATALOG,
      // NOT A REGISTRY TYPE, and named so nobody goes looking for it in
      // server.py. The registry cross-check at the foot of this file only
      // compares stand-ins the server DOES declare, so this one is ignored by
      // it by construction.
      { key: 'a_type_with_no_rule_yet', label: 'Future As-Needed Log',
        frequency: 'as_needed' }],
  });
  ok(keysOf(rows).includes('a_type_with_no_rule_yet'),
    'a type the server has said nothing about is never hidden');
}
{
  // A satisfied WEEKLY log keeps its tile. cadenceStatus paints it
  // "This week" and the denominator already drops it; hiding it would take
  // away the door a CP files next week's talk through.
  const rows = build({
    requiredLogbooks: {
      required_logbooks: ['daily_jobsite', 'toolbox_talk'],
      classification_assessed: true,
      periods: [
        { log_type: 'toolbox_talk', frequency: 'weekly', satisfied: true,
          filed_on: ['2026-09-15'] },
      ],
    },
    logTypeCatalog: CATALOG,
  });
  ok(keysOf(rows).includes('toolbox_talk'),
    'the predicate is as-needed ONLY — a done weekly log keeps its tile');
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
  // TWO FACTS, NOT ONE. `mine` used to be `act.activated_by !== 'admin'` —
  // a statement about the LOG only. For an admin-activated type that refused
  // every caller INCLUDING AN ADMIN, and since this is the only call site of
  // logbookActivationAPI.set in the app, superintendent_log_active and
  // hot_work_permitted could not be switched on from any screen by anybody.
  // The invariant this assertion names is still the one that matters: the
  // log's owner comes from the SERVER's answer, never a client-side list of
  // log types. The user's role is a separate fact and belongs in the test.
  ok(/act\.activated_by/.test(block),
    'ownership is read off the server’s answer');
  ok(!/log_type\s*===\s*['"]/.test(block) && !/site_superintendent_log/.test(block),
    'no client-side list of log types decides who owns a switch');
  ok(/const mine = \(act\.activated_by !== 'admin' \|\| isAdminUser\)/.test(block),
    'an admin can activate an admin-activated log');
  // ── AND `available` IS THE THIRD FACT, ADDED FOR THE HOT-WORK DAY ────────
  //
  // The dated declaration is the CP's, but only where the office has filed
  // the site's permit — "no permit, no day", the operator's ruling, enforced
  // by the endpoint. An unavailable row is therefore not his either, and it
  // reuses the admin-owned sentence because it is the same message: the log
  // exists, and an admin is who turns it on.
  ok(/&& act\.available !== false;/.test(block),
    'and a dated control with no standing permit behind it is not his to flip');
  // THE SERVER'S WORD, NOT A CLIENT-SIDE LIST. `available` and `scope` ride on
  // the row exactly as `activated_by` does.
  ok(!/hot_work/.test(block),
    'no log type is named in the block that decides who owns a switch');
  ok(/act\.scope === 'day'/.test(block),
    'the dated row gets its own copy, keyed on the server’s scope');
  ok(/key=\{`\$\{act\.log_type\}:\$\{act\.scope \|\| 'standing'\}`\}/.test(block),
    'and rows are keyed on type AND scope — hot work sends two of them, and '
    + 'matching on the type alone would move both switches on one tap');
  ok(block.includes('It clears itself tomorrow'),
    'the ON copy names the expiry — a day is not a setting, and nobody has to '
    + 'remember to switch it back off');
  // AND THE STANDING ROW ABOVE IT STOPPED CLAIMING THE LIST. "On — it is on
  // your logbook list" is FALSE for a permit with a dated row beside it: on
  // every day nobody declared, the permit is on and the log is not on his
  // list. The branch is keyed on whether the SERVER sent a day row for that
  // type, not on a client-side list of log types.
  ok(/const datedPeer = act\.scope !== 'day' && activations\.some\(/.test(block),
    'a standing row knows whether a dated row sits beside it');
  ok(block.includes('Declare the days below'),
    'and says what ON actually means for it, pointing at the control that does '
    + 'put the log on his list');
  // IT USED TO BE `['admin', 'owner'].includes(...)`. The role "owner" is
  // retired -- it was what every self-serve signup received, never a rank --
  // and the server's gate is now `holds_rank(user, COMPANY_ADMIN_ROLES)`,
  // which admits role 'admin' and the platform operator by his flag.
  // `isCompanyAdmin` is the client half of exactly that, so this still asks
  // the one question it always asked: does the screen mirror the server?
  ok(/const isAdminUser = isCompanyAdmin\(user\);/.test(SCREEN),
    'isAdminUser mirrors the server gate - one shared predicate, not a list');
  ok(!/'owner'/.test(SCREEN),
    'and the retired role is named nowhere on the screen');
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

  // ── AND THE STAND-IN'S FREQUENCIES ARE THE REGISTRY'S ────────────────────
  //
  // The CATALOG above stands in for /api/logbook-types. The file's own note
  // says a stale LABEL there fails no test and is only ever read by the next
  // person; `frequency` is worse than a label now, because the screen DECIDES
  // on it — a satisfied as-needed type leaves the list. A stand-in that said
  // "daily" where the registry says "as_needed" would test the opposite rule
  // and pass.
  const regBody = reg.slice(0, reg.indexOf('\n]'));
  const entries = [...regBody.matchAll(
    /^\s*"key": "([a-z_]+)",[\s\S]*?^\s*"frequency": "([a-z_]+)",/gm)];
  ok(entries.length === 13,
    `ANCHOR: a frequency read for each of 13 registry entries (${entries.length})`);
  const serverFreq = Object.fromEntries(entries.map((m) => [m[1], m[2]]));
  const drift = CATALOG.filter((c) => serverFreq[c.key]
    && serverFreq[c.key] !== c.frequency);
  ok(drift.length === 0,
    'every stand-in frequency matches LOGBOOK_TYPE_REGISTRY. Drifted: '
    + JSON.stringify(drift.map((c) => `${c.key}: ${c.frequency} vs ${serverFreq[c.key]}`)));
  ok(serverFreq.subcontractor_orientation === 'as_needed'
     && serverFreq.hot_work === 'as_needed',
    'the two as-needed types are still as-needed on the server — the rule '
    + 'above keys on this word and on nothing else');

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
