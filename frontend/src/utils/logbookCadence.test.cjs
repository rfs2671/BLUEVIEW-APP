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

console.log('\n-- hot_work is untouched, before and after --');
{
  // NO ROW IS EMITTED FOR hot_work by any server rule, because nobody has
  // defined when a hot-work permit log is due. periodSatisfied answers null,
  // which is not true, so it is never hidden and never leaves the count.
  const s = screen({ required: SIX, periods: [SATISFIED] });
  ok(s.keys.includes('hot_work'), 'hot_work keeps its tile');
  ok(s.total === 5 && s.keys.length === 5,
    'and its entry in the denominator — only the orientation left');
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
ok(periodSatisfied(logbookPeriods({ periods: [SATISFIED] }), 'hot_work') === null,
  'a type with NO row reads null — the question does not apply');
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
  ok(cadenceStatus(q, 'hot_work', 'pending') === 'pending',
    'a type with no row keeps its by-date answer');
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
