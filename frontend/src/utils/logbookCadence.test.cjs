/**
 * THE COUNT UNDER "TODAY'S LOG BOOKS", AND THE MODULE THAT DECIDES IT.
 *
 * ── UNCOVERED GROUND ────────────────────────────────────────────────────────
 *
 * logbookCadence.js had NO test file, and the `submitted/total` arithmetic in
 * app/logbooks/index.jsx had none either. Both shipped. This is the first test
 * for either, written because a change landed on them:
 *
 *   `subcontractor_orientation` is `frequency: as_needed`. It is REQUIRED on
 *   every project — get_required_logbooks resolves it for every §3310 class —
 *   but it is DUE for exactly one reason: a worker checked in and has no
 *   orientation on this project. Nothing answered that question, so the tile
 *   fell back to a by-DATE read, said Pending every morning, and was counted.
 *
 *   MEASURED READ-ONLY ON ALL THREE LIVE PROJECTS: 8 Walworth 0 workers / 0
 *   orientations, 588 Thomas 63 checked in / 65 oriented, 857 Prescott 13/13.
 *   Zero uncovered workers anywhere. The operator read 4/6 where the sixth
 *   item was not due at all.
 *
 * ── WHAT THIS FILE HOLDS TO ─────────────────────────────────────────────────
 *
 * The arithmetic is lifted OUT OF THE SCREEN SOURCE and executed, not grepped.
 * "The filter exists" is exactly what was true the whole time the count was
 * wrong: `periodSatisfied(periods, lt.key) !== true` was already there and did
 * nothing for this type, because no row was ever emitted for it.
 *
 * Run:  node src/utils/logbookCadence.test.cjs
 */
const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.join(__dirname, '..', '..');
const SCREEN_RAW = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'index.jsx'), 'utf8');

const {
  logbookPeriods, periodFor, periodSatisfied, cadenceStatus, cadenceLabel,
} = loadEsm('src/utils/logbookCadence.js');
const { mayFile } = loadEsm('src/utils/csFilingRights.js');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── Lift the real code out of the screen and run it ─────────────────────────
function slice(src, start, end) {
  const i = src.indexOf(start);
  if (i < 0) throw new Error(`not found: ${start}`);
  const j = src.indexOf(end, i);
  if (j < 0) throw new Error(`no end for: ${start}`);
  return src.slice(i, j + end.length);
}

const FALLBACK_SRC = slice(SCREEN_RAW, 'const FALLBACK_LOG_TYPES = [', '\n];');
const FN_SRC = slice(SCREEN_RAW, '  const getVisibleLogTypes = () => {', '\n  };');
const COUNT_SRC = slice(
  SCREEN_RAW,
  '                  const countable = visibleLogs.filter(',
  'const pct = total > 0 ? Math.round((submitted / total) * 100) : 0;');

// ANCHORS. Every one of these slices is found by a literal from the screen; a
// rename that silently shrank one to nothing would make the assertions below
// pass over an empty string.
ok(FALLBACK_SRC.length > 200, 'ANCHOR: the fallback list slice is non-empty');
ok(FN_SRC.length > 400, 'ANCHOR: the getVisibleLogTypes slice is non-empty');
ok(COUNT_SRC.includes('submitted') && COUNT_SRC.includes('total'),
  'ANCHOR: the count slice holds the arithmetic');

const CATALOG = [
  { key: 'daily_jobsite', label: 'Daily Jobsite Log', frequency: 'daily' },
  { key: 'preshift_signin', label: 'Pre-Shift Sign-In', frequency: 'daily' },
  { key: 'toolbox_talk', label: 'Tool Box Talk', frequency: 'weekly' },
  { key: 'subcontractor_orientation', label: 'Subcontractor Safety Orientation', frequency: 'as_needed' },
  { key: 'osha_log', label: 'OSHA Log Book', frequency: 'daily' },
  { key: 'hot_work', label: 'Hot Work Permit Log', frequency: 'as_needed' },
  // NOT A REGISTRY TYPE. The fail-open guard is about the NEXT as-needed log
  // added before anybody writes its rule, and both as-needed types that exist
  // today now have one — so the instance has to be invented here. It is named
  // for what it is so nobody goes looking for it in server.py.
  { key: 'a_type_with_no_rule_yet', label: 'Future As-Needed Log', frequency: 'as_needed' },
];

/**
 * The screen's own list and its own count, over one payload.
 *
 * `filed` is the set of log types the CP has submitted TODAY — what
 * getLogStatus answers off `todayLogs`.
 */
function screen({ required, periods = null, filed = [], filing = null }) {
  const payload = {
    required_logbooks: required,
    classification_assessed: true,
    ...(periods ? { periods } : {}),
    ...(filing ? { filing } : {}),
  };
  // eslint-disable-next-line no-new-func
  return new Function('env', 'periodSatisfied', 'mayFile', `
    const semantic = { neutral: '#94a3b8' };
    ${FALLBACK_SRC}
    const requiredLogbooks = env.requiredLogbooks;
    const logTypeCatalog = env.logTypeCatalog;
    const scaffoldActive = false;
    const toolboxDoneThisWeek = false;
    const notifications = {};
    const periods = env.periods;
    const rights = env.rights;
    const getLogStatus = env.getLogStatus;
    ${FN_SRC}
    const visibleLogs = getVisibleLogTypes();
    ${COUNT_SRC}
    return { keys: visibleLogs.map((l) => l.key), submitted, total, pct };
  `)({
    requiredLogbooks: payload,
    logTypeCatalog: CATALOG,
    periods: logbookPeriods(payload),
    rights: payload.filing || null,
    getLogStatus: (key) => (filed.includes(key) ? 'submitted' : 'pending'),
  }, periodSatisfied, mayFile);
}

const SATISFIED = {
  log_type: 'subcontractor_orientation',
  frequency: 'as_needed',
  period_start: null,
  period_end: null,
  satisfied: true,
  filed_on: [],
  due_reason: null,
  uncovered_weekend_workers: [],
  uncovered_workers: [],
  uncovered_worker_count: 0,
};
const DUE = {
  ...SATISFIED,
  satisfied: false,
  due_reason: 'WORKER_NOT_ORIENTED',
  uncovered_workers: ['Andre Duval', 'Marcus Reilly'],
  uncovered_worker_count: 2,
};

// ── THE HOT-WORK ROW ────────────────────────────────────────────────────────
//
// `period_start` and `period_end` carry the DAY, unlike the orientation row
// above, which sets them null because an as-needed log has no cadence. A
// hot-work day IS a date — the operator's ruling is literally a date — so
// naming it reports the declaration rather than inventing a cadence.
//
// There is no `uncovered_workers` on it: that is the orientation's field, this
// row is not about people, and an empty list there would read as "nobody is
// waiting", which is a different claim.
const HOT_QUIET = {
  log_type: 'hot_work',
  frequency: 'as_needed',
  period_start: '2026-09-18',
  period_end: '2026-09-18',
  satisfied: true,
  filed_on: [],
  due_reason: null,
  uncovered_weekend_workers: [],
  declared: false,
  declared_by: null,
};
const HOT_DECLARED = {
  ...HOT_QUIET,
  satisfied: false,
  due_reason: 'HOT_WORK_DECLARED',
  declared: true,
  declared_by: 'Andre Duval',
};

const SIX = ['daily_jobsite', 'preshift_signin', 'osha_log', 'toolbox_talk',
  'subcontractor_orientation', 'hot_work'];

console.log('\n-- the denominator: a satisfied as-needed type LEAVES the count --');
{
  const before = screen({ required: SIX, filed: ['daily_jobsite'] });
  ok(before.total === 6, `the defect: all six are counted (${before.total})`);
  ok(before.keys.includes('subcontractor_orientation'),
    'and the orientation is one of them');

  const after = screen({
    required: SIX, periods: [SATISFIED], filed: ['daily_jobsite'],
  });
  ok(after.total === 5, `a satisfied orientation leaves the count (${after.total})`);
  ok(!after.keys.includes('subcontractor_orientation'),
    'and leaves the tile list — ONE predicate does both');
  ok(after.submitted === before.submitted,
    'the numerator is untouched: nothing he filed stopped counting');
}
{
  // THE OPERATOR'S ACTUAL SCREEN. Four of five daily/weekly logs filed, the
  // orientation not due, and nobody waiting for one.
  const s = screen({
    required: SIX.filter((k) => k !== 'hot_work'),
    periods: [SATISFIED],
    filed: ['daily_jobsite', 'preshift_signin', 'osha_log', 'toolbox_talk'],
  });
  ok(`${s.submitted}/${s.total}` === '4/4',
    `it reads 4/4, not 4/5 with a sixth item that is not due (${s.submitted}/${s.total})`);
  ok(s.pct === 100, 'and the bar reaches the end');
}

console.log('\n-- a DUE one stays in the count --');
{
  const s = screen({ required: SIX, periods: [DUE], filed: ['daily_jobsite'] });
  ok(s.total === 6, `all six are still counted (${s.total})`);
  ok(s.keys.includes('subcontractor_orientation'),
    'and the tile is still there — a missing obligation is invisible in the '
    + 'way an extra one is not');
}
{
  // Filing it does NOT remove it from the denominator; it moves it to the
  // numerator. The two are different facts and were never the same edit.
  const s = screen({
    required: SIX, periods: [DUE],
    filed: ['subcontractor_orientation'],
  });
  ok(s.total === 6 && s.submitted === 1,
    `filed today: 1/6, not 1/5 (${s.submitted}/${s.total})`);
}

console.log('\n-- a hot-work day: the tile appears, then disappears --');
{
  // THE OPERATOR'S RULING: "due only on days hot work happens. CP or super
  // toggles it on for that day. Dated, not persistent." 8 Walworth has the
  // STANDING permit on, which is why hot_work is in its required set at all —
  // and before this, the tile read Pending there every morning forever.
  //
  // A QUIET DAY. No declaration, so the row says satisfied and the tile and
  // its denominator entry both go. This is the fix.
  const quiet = screen({ required: SIX, periods: [SATISFIED, HOT_QUIET] });
  ok(!quiet.keys.includes('hot_work'),
    'a day nobody declared: the hot-work tile is gone');
  ok(quiet.total === 4 && quiet.keys.length === 4,
    `and out of the denominator — both as-needed types left (${quiet.total})`);

  // THE CP DECLARES A DAY. Same payload, one row flipped, and the tile is back
  // with its entry in the count.
  const declared = screen({ required: SIX, periods: [SATISFIED, HOT_DECLARED] });
  ok(declared.keys.includes('hot_work'),
    'he declares hot work for today: the tile is back');
  ok(declared.total === 5, `and back in the denominator (${declared.total})`);

  // HE FILES IT. Filing does NOT remove it — the row still says the day is
  // declared, and cadenceStatus gives a log filed today the last word, so the
  // tile reads Done and stays up. Hot work is `immediate`-class: a second
  // operation that afternoon is a second discrete log, opened through this
  // same tile.
  const filed = screen({
    required: SIX, periods: [SATISFIED, HOT_DECLARED], filed: ['hot_work'],
  });
  ok(filed.keys.includes('hot_work') && filed.submitted === 1 && filed.total === 5,
    `filed today: 1/5 with the tile still there (${filed.submitted}/${filed.total})`);

  // TOMORROW. Nobody switched anything off; the next day's row is about the
  // next day, which nobody declared.
  const tomorrow = screen({ required: SIX, periods: [SATISFIED, HOT_QUIET] });
  ok(!tomorrow.keys.includes('hot_work'),
    'the next morning it is gone again — with nobody having switched it off');
}

console.log('\n-- and the fail-open guard did not move --');
{
  // THE PROPERTY #611 PINNED, on a type that is still an instance of it. Hot
  // work stopped relying on the silence by acquiring a RULE; the predicate
  // itself is unchanged, so a type the server says nothing about still keeps
  // its tile and its denominator entry.
  const s = screen({
    required: [...SIX, 'a_type_with_no_rule_yet'],
    periods: [SATISFIED, HOT_QUIET],
  });
  ok(s.keys.includes('a_type_with_no_rule_yet'),
    'an as-needed type with no row keeps its tile');
  ok(s.total === 5, `and its entry in the denominator (${s.total})`);
}

console.log('\n-- the whose-log filter still works on the other axis --');
{
  // A log the server will not let him file can never leave the numerator, so
  // it was already dropped from the denominator. The new predicate is a
  // SECOND reason to drop a row, not a replacement for that one.
  const s = screen({
    required: ['daily_jobsite', 'site_superintendent_log'],
    filing: { site_superintendent_log: { may_file: false, owner_name: 'R. Okafor' } },
  });
  ok(s.total === 1, `the CS log is not counted against the CP (${s.total})`);
  ok(s.keys.includes('site_superintendent_log'),
    'but its TILE stays — he must be able to see it exists and learn who owns it');
}

console.log('\n-- periodSatisfied: three answers, and null is not false --');
ok(periodSatisfied(logbookPeriods({ periods: [SATISFIED] }),
  'subcontractor_orientation') === true, 'satisfied reads true');
ok(periodSatisfied(logbookPeriods({ periods: [DUE] }),
  'subcontractor_orientation') === false, 'due reads false');
ok(periodSatisfied(logbookPeriods({ periods: [SATISFIED] }),
  'a_type_with_no_rule_yet') === null,
  'a type with NO row reads null — the question does not apply');
ok(periodSatisfied(logbookPeriods({ periods: [HOT_QUIET] }), 'hot_work') === true,
  'an undeclared hot-work day reads true — not due');
ok(periodSatisfied(logbookPeriods({ periods: [HOT_DECLARED] }), 'hot_work') === false,
  'a declared one reads false');
ok(periodSatisfied(logbookPeriods({}), 'subcontractor_orientation') === null,
  'and a payload with no periods key reads null, not false');
ok(periodSatisfied(logbookPeriods({ periods: [{ log_type: 'x', satisfied: 'yes' }] }),
  'x') === null, 'a non-boolean satisfied is not an answer');
ok(periodFor(logbookPeriods({ periods: [SATISFIED] }), 'nope') === null,
  'periodFor is null for an absent type');
ok(logbookPeriods({ periods: 'not-an-array' }) && Object.keys(
  logbookPeriods({ periods: 'not-an-array' })).length === 0,
  'a malformed periods value is no rows, not a crash');

console.log('\n-- cadenceStatus does not argue with a log he filed today --');
{
  const p = logbookPeriods({ periods: [DUE] });
  ok(cadenceStatus(p, 'subcontractor_orientation', 'submitted') === 'submitted',
    'filed today reads submitted even when the period says due');
  ok(cadenceStatus(p, 'subcontractor_orientation', 'pending') === 'pending',
    'and a due one stays pending');
  const q = logbookPeriods({ periods: [SATISFIED] });
  ok(cadenceStatus(q, 'subcontractor_orientation', 'pending') === 'period_done',
    'a satisfied one is period_done, never pending');
  ok(cadenceStatus(q, 'a_type_with_no_rule_yet', 'pending') === 'pending',
    'a type with no row keeps its by-date answer');
  const h = logbookPeriods({ periods: [HOT_DECLARED] });
  ok(cadenceStatus(h, 'hot_work', 'submitted') === 'submitted',
    'a hot-work log filed on its declared day reads submitted, and the tile stays');
  ok(cadenceStatus(h, 'hot_work', 'pending') === 'pending',
    'and an unfiled declared day is still pending');
}

console.log('\n-- the label does not call an as-needed log weekly --');
{
  const due = cadenceLabel(logbookPeriods({ periods: [DUE] }),
    'subcontractor_orientation');
  ok(!/week/i.test(due),
    `no week is claimed for a log that has no period (${JSON.stringify(due)})`);
  ok(/2 workers/.test(due), 'it says how many men are waiting');
  ok(/Andre Duval/.test(due) && /Marcus Reilly/.test(due),
    'and NAMES them — "due" tells a CP there is work, a name tells him who');
  const sat = cadenceLabel(logbookPeriods({ periods: [SATISFIED] }),
    'subcontractor_orientation');
  ok(!/week/i.test(sat), 'and the satisfied wording claims no week either');
}
{
  const many = {
    ...DUE,
    uncovered_workers: ['A One', 'B Two', 'C Three', 'D Four'],
    uncovered_worker_count: 9,
  };
  const s = cadenceLabel(logbookPeriods({ periods: [many] }),
    'subcontractor_orientation');
  ok(/9 workers/.test(s), 'the COUNT is the full count');
  ok(/and 6 more/.test(s), 'and the names are trimmed rather than the count');
}
{
  const one = { ...DUE, uncovered_workers: ['Andre Duval'], uncovered_worker_count: 1 };
  const s = cadenceLabel(logbookPeriods({ periods: [one] }),
    'subcontractor_orientation');
  ok(/1 worker /.test(s) && /has no orientation/.test(s),
    `one man reads in the singular (${JSON.stringify(s)})`);
}
{
  // A row that lost its names still says the log is due. A missing name is
  // not a missing obligation.
  const bare = { ...DUE, uncovered_workers: [], uncovered_worker_count: 0 };
  const s = cadenceLabel(logbookPeriods({ periods: [bare] }),
    'subcontractor_orientation');
  ok(typeof s === 'string' && s.length > 0 && !/week/i.test(s),
    'a nameless due row still produces a line');
}

console.log('\n-- the hot-work line is about a DAY, not a week and not a man --');
{
  const due = cadenceLabel(logbookPeriods({ periods: [HOT_DECLARED] }), 'hot_work');
  ok(!/week/i.test(due),
    `no week is claimed for a one-day obligation (${JSON.stringify(due)})`);
  // "AGAIN" IS THE WEEKLY ROW'S WORD. Two hot-work days in a week are two
  // independent facts, not a rhythm, and "due again" would tell a CP the app
  // had lost the log he filed on Tuesday.
  ok(!/again/i.test(due), 'and no recurrence is claimed either');
  ok(/today/i.test(due), `it names the day (${JSON.stringify(due)})`);
  ok(/Andre Duval/.test(due),
    'and NAMES who declared it — the log is open on somebody’s word');
  // It must not borrow the orientation's sentence. That one is about people
  // with no orientation; this is about a day somebody said is happening.
  ok(!/orientation/i.test(due) && !/waiting/i.test(due),
    'and it does not borrow the orientation wording');

  const quiet = cadenceLabel(logbookPeriods({ periods: [HOT_QUIET] }), 'hot_work');
  ok(!/week/i.test(quiet) && !/waiting for one/.test(quiet),
    `the quiet day reads as a day, not as coverage (${JSON.stringify(quiet)})`);

  const nameless = cadenceLabel(
    logbookPeriods({ periods: [{ ...HOT_DECLARED, declared_by: null }] }), 'hot_work');
  ok(typeof nameless === 'string' && /today/i.test(nameless),
    'a declaration whose name was never captured still produces a line');

  // THE ORIENTATION'S OWN LINE IS UNTOUCHED by the type branch added for hot
  // work — asserted here, beside it, rather than trusted.
  ok(/no orientation/.test(
    cadenceLabel(logbookPeriods({ periods: [DUE] }), 'subcontractor_orientation')),
    'and the orientation line still says what it always said');
}

console.log('\n-- the weekly wording is unchanged --');
{
  const weekly = {
    log_type: 'toolbox_talk', frequency: 'weekly', satisfied: true,
    filed_on: ['2026-09-15'], due_reason: null, uncovered_weekend_workers: [],
  };
  ok(cadenceLabel(logbookPeriods({ periods: [weekly] }), 'toolbox_talk')
     === 'Done this week — filed 2026-09-15',
    'a done week still names the day it was filed');
  const reopened = {
    ...weekly, satisfied: false, due_reason: 'WEEKEND_WORKER_NOT_COVERED',
    uncovered_weekend_workers: ['w1', 'w2'],
  };
  ok(/2 weekend workers/.test(
    cadenceLabel(logbookPeriods({ periods: [reopened] }), 'toolbox_talk')),
    'and a weekend re-opening still names the men');
  ok(cadenceLabel(logbookPeriods({ periods: [] }), 'toolbox_talk') === null,
    'no row, no line');
}

console.log('\n-- the empty state is reachable and reads correctly --');
{
  // If every visible type were dropped the screen renders "All caught up!".
  // It cannot happen on a real project — daily_jobsite is required on every
  // §3310 class and is never as_needed — but the copy is checked because the
  // filter above is the only thing that can shorten this list.
  const s = screen({
    required: ['subcontractor_orientation'], periods: [SATISFIED],
  });
  ok(s.keys.length === 0, 'an all-satisfied list is empty');
  ok(s.total === 0 && s.pct === 0, 'and the count is 0/0 rather than NaN%');
  ok(SCREEN_RAW.includes('All caught up! No logbooks needed right now.'),
    'which the screen renders as "All caught up!", not as a blank card');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
