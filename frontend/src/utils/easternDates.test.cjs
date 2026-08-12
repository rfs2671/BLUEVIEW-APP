/**
 * THE EASTERN DATE HELPER, AND EVERY CALLER THAT WAS USING UTC.
 *
 * `new Date().toISOString().split('T')[0]` reads as "just format the date" and
 * silently means "in UTC". From 20:00 EDT — 19:00 EST — that is TOMORROW in
 * New York. It shipped thirteen times against two correct inline copies.
 *
 * Two different failures came out of it:
 *   * in a QUERY the screen asks for the wrong day and looks empty;
 *   * on a RECORD a logbook is FILED stamped with tomorrow's date. That one
 *     persists and an inspector reads it.
 *
 * THIS TEST PINS THE CLOCK. The bug is invisible before 20:00 Eastern, so a
 * test reading the real current time would pass all morning and prove nothing.
 * The helper is the REAL shipped module, stripped of its exports and evaluated
 * here, then driven with fixed instants in both DST regimes.
 *
 * Run:  node src/utils/easternDates.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SRC = fs.readFileSync(path.join(__dirname, 'dates.js'), 'utf8');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── load the REAL module ────────────────────────────────────────────────────
const D = (() => {
  const body = SRC
    .replace(/^export default[\s\S]*?;\s*$/m, '')
    .replace(/^export function /gm, 'function ');
  // eslint-disable-next-line no-new-func
  return new Function(`${body}; return { easternDate, easternToday, easternDayOffset, shiftDate };`)();
})();

// ── 1. the helper, against a pinned clock ───────────────────────────────────
// EDT (UTC-4): UTC rolls over at 20:00 Eastern.
const EDT = [
  ['2026-08-09T11:00:00Z', '2026-08-09', '07:00 EDT — shift start'],
  ['2026-08-09T23:59:00Z', '2026-08-09', '19:59 EDT — UTC still agrees'],
  ['2026-08-10T00:00:00Z', '2026-08-09', '20:00 EDT — UTC rolls, Eastern does NOT'],
  ['2026-08-10T01:00:00Z', '2026-08-09', '21:00 EDT — the hour that broke the roster'],
  ['2026-08-10T03:59:00Z', '2026-08-09', '23:59 EDT — still the same Eastern day'],
  ['2026-08-10T04:00:00Z', '2026-08-10', '00:00 EDT — Eastern midnight, now it rolls'],
];
// EST (UTC-5): an hour earlier.
const EST = [
  ['2026-01-15T23:59:00Z', '2026-01-15', '18:59 EST — UTC agrees'],
  ['2026-01-16T00:00:00Z', '2026-01-15', '19:00 EST — UTC rolls, Eastern does NOT'],
  ['2026-01-16T04:59:00Z', '2026-01-15', '23:59 EST — still the same Eastern day'],
  ['2026-01-16T05:00:00Z', '2026-01-16', '00:00 EST — Eastern midnight'],
];
for (const [iso, want, why] of [...EDT, ...EST]) {
  const got = D.easternDate(new Date(iso));
  ok(got === want, `easternDate ${why}: -> ${got} (want ${want})`);
}

// The cases must actually discriminate, or they prove nothing.
ok(new Date('2026-08-10T01:00:00Z').toISOString().split('T')[0] === '2026-08-10'
   && D.easternDate(new Date('2026-08-10T01:00:00Z')) === '2026-08-09',
  'at 21:00 EDT the UTC and Eastern answers genuinely differ');
ok(new Date('2026-01-16T00:00:00Z').toISOString().split('T')[0] === '2026-01-16'
   && D.easternDate(new Date('2026-01-16T00:00:00Z')) === '2026-01-15',
  'at 19:00 EST they differ too — the winter boundary is an hour earlier');
ok(new Date('2026-08-09T11:00:00Z').toISOString().split('T')[0]
   === D.easternDate(new Date('2026-08-09T11:00:00Z')),
  'at 07:00 EDT they agree — which is why this shipped unnoticed');

// ── 2. calendar arithmetic must not touch a time zone ───────────────────────
ok(D.shiftDate('2026-08-09', -1) === '2026-08-08', 'shiftDate: back one day');
ok(D.shiftDate('2026-08-09', 1) === '2026-08-10', 'shiftDate: forward one day');
ok(D.shiftDate('2026-03-08', 1) === '2026-03-09', 'shiftDate: across the spring DST jump');
ok(D.shiftDate('2026-11-01', 1) === '2026-11-02', 'shiftDate: across the autumn DST jump');
ok(D.shiftDate('2026-01-01', -1) === '2025-12-31', 'shiftDate: across a year boundary');
ok(D.shiftDate('2026-02-28', 1) === '2026-03-01', 'shiftDate: across a month boundary');
ok(D.easternDayOffset(-1, new Date('2026-08-10T01:00:00Z')) === '2026-08-08',
  'easternDayOffset: yesterday at 21:00 EDT is the 8th, not the 9th');

// ── 3. every fixed caller uses the helper and NOT toISOString ───────────────
// TIER 1 writes a date onto a persisted record; TIER 2 only queries with it.
const SITES = [
  // RE-POINTED, not weakened. EMPTY_ENTRY moved out of the screen and into
  // src/utils/oshaLogModel.js when osha_log was ported onto the shared stepper
  // — same call, same guarantee, one address further in. Both ends are still
  // checked: the model must make the call, the screen must consume the model,
  // and NEITHER may carry a UTC calendar date.
  // The model is a sibling of dates.js, so its import is './dates'.
  ['TIER 1', 'src/utils/oshaLogModel.js', /date: easternToday\(\)/, /from '\.\/dates'/],
  ['TIER 1', 'app/logbooks/osha_log.jsx', /EMPTY_ENTRY/, /from '.*utils\/oshaLogModel'/],
  ['TIER 2', 'app/daily-log.jsx', /const todayISO = \(\) => easternToday\(\)/],
  ['TIER 2', 'app/logbooks/subcontractor_orientation.jsx', /const todayISO = \(\) => easternToday\(\)/],
  ['TIER 2', 'app/site/daily-logs.jsx', /const todayStr = \(\) => easternToday\(\)/],
  ['TIER 2', 'app/site/index.jsx', /const today = easternToday\(\)/],
  ['TIER 2', 'app/reports.jsx', /useState\(easternToday\(\)\)/],
];
for (const [tier, rel, re, importRe] of SITES) {
  const src = fs.readFileSync(path.join(FRONTEND, rel), 'utf8');
  ok(re.test(src), `${tier} ${rel}: uses the helper`);
  // Most sites import dates.js directly; a site that reaches the helper
  // through a model declares the import it actually has.
  ok((importRe || /from '.*utils\/dates'/).test(src), `${tier} ${rel}: imports it`);
  ok(!/toISOString\(\)\.split\('T'\)\[0\]/.test(src),
    `${tier} ${rel}: no UTC calendar date left`);
}

// reports.jsx had three more, including the future-guard that unlocked
// tomorrow's report every evening.
{
  const src = fs.readFileSync(path.join(FRONTEND, 'app', 'reports.jsx'), 'utf8');
  ok(/if \(newDate > easternToday\(\)\) return;/.test(src),
    'reports.jsx: the future-guard compares against the NEW YORK today');
  ok(/const isToday = previewDate === easternToday\(\);/.test(src),
    'reports.jsx: "is today" is the New York today');
  ok(/shiftDate\(previewDate, direction\)/.test(src),
    'reports.jsx: date navigation is calendar arithmetic, not local Date parsing');
  ok(!/new Date\(previewDate \+ 'T12:00:00'\)/.test(src),
    'reports.jsx: no device-local parsing of a calendar string');
}

// ── 4. the two confirmed-correct sites are untouched ────────────────────────
{
  const src = fs.readFileSync(path.join(FRONTEND, 'app', 'site', 'checkins.jsx'), 'utf8');
  ok(/timeZone: 'America\/New_York'/.test(src),
    'site/checkins.jsx: still Eastern-first (it was already correct)');
  ok(/toISOString\(\)\.slice\(0, 10\)/.test(src),
    'site/checkins.jsx: its UTC line is a catch-fallback and stays');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
console.log('ALL PASSED');
