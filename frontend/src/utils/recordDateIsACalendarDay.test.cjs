/**
 * A DOB RECORD'S DATE IS THE DAY DOB WROTE, NOT THE DAY BEFORE IT.
 *
 *   node frontend/src/utils/recordDateIsACalendarDay.test.cjs
 *
 * ── WHAT THIS CAUGHT ───────────────────────────────────────────────────────
 *
 * app/project/[id]/dob-logs.jsx built every date with `new Date(str)` and, for
 * an eight-digit one, forced `…T00:00:00Z`. A bare calendar day parsed as UTC
 * midnight prints the PREVIOUS day through `toLocaleDateString` anywhere behind
 * UTC:
 *
 *     '20260721'    -> "Jul 20, 2026"
 *     '2026-07-01'  -> "Jun 30, 2026"     <- the wrong MONTH
 *
 * The row is labelled "Issue Date" on a DOB violation. `violation_date` is
 * Socrata's `issue_date` raw -- YYYYMMDD for ECB -- and its fallback is a bare
 * 'YYYY-MM-01', so the month-boundary case was the fallback, not an edge.
 *
 * ── THIS FILE REFUSES TO RUN WHERE IT CANNOT FAIL ──────────────────────────
 *
 * Every assertion below passes against the BROKEN code when the runner sits at
 * UTC or ahead of it, because UTC midnight is still the right day there. A
 * green tick from such a runner would mean nothing, so this exits 2 rather than
 * reporting. Its sibling insuranceExpiry.test.cjs does the same for the same
 * reason; that is the standard here, not a special case.
 */
const { loadEsm } = require('./esmHarness.cjs');

const offsetMinutes = new Date().getTimezoneOffset();   // > 0 means behind UTC
if (offsetMinutes <= 0 && !process.env.RECORD_DATE_TEST_REEXEC) {
  // BEHIND UTC OR NOTHING. Re-exec once; the env marker stops it recursing if
  // the child's zone is still not behind UTC (a machine with no tzdata), in
  // which case the child's own message is the report.
  const { spawnSync } = require('child_process');
  console.log('  runner is at/ahead of UTC — re-running in America/New_York,'
    + ' where this defect is observable');
  const r = spawnSync(process.execPath, [__filename], {
    stdio: 'inherit',
    env: { ...process.env, TZ: 'America/New_York', RECORD_DATE_TEST_REEXEC: '1' },
  });
  process.exit(r.status === null ? 1 : r.status);
}
if (offsetMinutes <= 0) {
  console.error(
    'REFUSING TO RUN: re-exec with TZ=America/New_York still reports a zone at'
    + ` or ahead of UTC (offset ${-offsetMinutes} min). Every assertion here`
    + ' passes against the broken code in such a zone, so a pass would prove'
    + ' nothing. This machine is probably missing tzdata.');
  process.exit(2);
}

// A REPO-RELATIVE PATH, which is what the harness takes -- an absolute one is
// re-prefixed with the frontend root and fails to open.
const { parseRecordDate, formatRecordDate } = loadEsm('src/utils/dates.js');

let pass = 0; let fail = 0;
const ok = (cond, label) => {
  if (cond) { pass += 1; console.log('  ok   ', label); }
  else { fail += 1; console.log('  FAIL ', label); }
};

console.log('\n1. A CALENDAR DAY RENDERS AS ITSELF');
ok(formatRecordDate('20260721') === 'Jul 21, 2026',
   `YYYYMMDD renders its own day (got ${formatRecordDate('20260721')})`);
ok(formatRecordDate('2026-07-21') === 'Jul 21, 2026',
   `YYYY-MM-DD renders its own day (got ${formatRecordDate('2026-07-21')})`);

console.log('\n2. THE MONTH BOUNDARY — the fallback shape, and the worst case');
ok(formatRecordDate('2026-07-01') === 'Jul 1, 2026',
   `the 1st does not fall into June (got ${formatRecordDate('2026-07-01')})`);
ok(formatRecordDate('20260101') === 'Jan 1, 2026',
   `and not into the previous YEAR (got ${formatRecordDate('20260101')})`);

console.log('\n3. THE TWO SHAPES AGREE');
ok(formatRecordDate('20260701') === formatRecordDate('2026-07-01'),
   'YYYYMMDD and YYYY-MM-DD are the same day');

console.log('\n4. AN INSTANT IS LEFT ALONE — the half a fix could break');
{
  // 02:30 UTC on the 21st is still the 20th in New York. A timestamp names a
  // moment; anchoring it to noon would MOVE it, which is a data bug dressed as
  // a display fix.
  const iso = '2026-07-21T02:30:00Z';
  const viaUs = parseRecordDate(iso);
  const viaDate = new Date(iso);
  ok(viaUs.getTime() === viaDate.getTime(),
     'a timestamp is parsed as the instant it is, not re-anchored');
  ok(formatRecordDate(iso) === viaDate.toLocaleDateString('en-US',
       { month: 'short', day: 'numeric', year: 'numeric' }),
     'and renders in local time, as a timestamp should');
}

console.log('\n5. UNREADABLE AND BLANK');
ok(formatRecordDate('') === '—', 'blank renders an em dash');
ok(formatRecordDate(null) === '—', 'null renders an em dash');
ok(formatRecordDate('not a date') === 'not a date'.slice(0, 10),
   'unreadable falls back to the raw head, never to a guess');
ok(parseRecordDate('2026-13-45') === null,
   'an impossible day is null, not a rolled-over date');

console.log('\n6. ORDERING SURVIVES THE ANCHOR');
{
  // parseRecordDate also feeds the screen's sort and its permit-open check.
  const a = parseRecordDate('2026-07-20');
  const b = parseRecordDate('2026-07-21');
  ok(a < b, 'consecutive days still order correctly');
  // A permit expiring TODAY must not read as expired: noon today is after
  // midnight today. Under the old UTC-midnight anchor it was 20:00 yesterday.
  const today = new Date();
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`
            + `-${String(today.getDate()).padStart(2, '0')}`;
  const t0 = new Date(); t0.setHours(0, 0, 0, 0);
  ok(parseRecordDate(iso).getTime() >= t0.getTime(),
     'a record dated today is not already in the past');
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
