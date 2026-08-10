/**
 * THE CP HOME MUST ASK FOR THE NEW YORK DATE, NOT THE UTC ONE.
 *
 * app/logbooks/index.jsx computed `today` with toISOString(), which is UTC.
 * That value is passed straight to every logbook form as ?date=... , and
 * /checkins-today bounds the date it receives to EASTERN midnight
 * (server.py get_day_range_est). From 20:00 EDT — 19:00 EST — UTC has already
 * rolled over, so the app asked for TOMORROW and the pre-shift and toolbox
 * rosters came back EMPTY, while the CP-home badge kept counting the same
 * check-ins because it applies no day bound at all. Count and roster disagreed.
 *
 * THIS TEST PINS THE CLOCK. The bug is invisible before 20:00 Eastern, so a
 * test that reads the real current time would pass all morning and prove
 * nothing. Every case below evaluates the REAL expression lifted out of the
 * shipped source against a FIXED instant.
 *
 * Run:  node src/utils/cpHomeEasternDate.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const INDEX = path.join(FRONTEND, 'app', 'logbooks', 'index.jsx');
const API = path.join(FRONTEND, 'src', 'utils', 'api.js');

const src = fs.readFileSync(INDEX, 'utf8');
const apiSrc = fs.readFileSync(API, 'utf8');

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

// ── 1. lift the REAL expression out of the shipped file ─────────────────────
// `;\r?\n` — this file is CRLF in the working tree, and anchoring on a bare
// \n silently matches nothing, which reads as "the expression is missing".
const m = /const today = ([\s\S]*?);\r?\n/.exec(src);
ok(!!m, 'found the `const today = ...` expression in app/logbooks/index.jsx');
const expr = m ? m[1] : 'null';

ok(!/toISOString/.test(expr),
  'today is NOT derived from toISOString() — that is the UTC source that caused this');
ok(/timeZone:\s*'America\/New_York'/.test(expr),
  "today is derived in the America/New_York time zone");

// No third variant: it must be the same formatter the rest of the app uses.
ok(/new Intl\.DateTimeFormat\('en-CA',\s*\{\s*timeZone:\s*'America\/New_York'\s*\}\)/.test(expr),
  'uses the same Intl en-CA / America-New_York formatter as checkinsAPI.getByDate');
ok(/new Intl\.DateTimeFormat\('en-CA',\s*\{\s*timeZone:\s*'America\/New_York'\s*\}\)/.test(apiSrc),
  'src/utils/api.js still uses that same formatter (the pattern being matched)');

// ── 2. run it against a PINNED clock ────────────────────────────────────────
// Substitute the `new Date()` inside the lifted expression with a fixed
// instant. Everything else — the formatter, the locale, the time zone — is the
// shipped code running for real.
function todayAt(iso) {
  const pinned = expr.replace(/new Date\(\)/, `new Date(${JSON.stringify(iso)})`);
  // eslint-disable-next-line no-new-func
  return new Function(`return (${pinned});`)();
}

// EDT (UTC-4). The window where the old code was wrong is 20:00 -> 24:00.
const EDT_CASES = [
  ['2026-08-09T11:00:00Z', '2026-08-09', '07:00 EDT — shift start, UTC agrees'],
  ['2026-08-09T23:59:00Z', '2026-08-09', '19:59 EDT — last minute UTC still agrees'],
  ['2026-08-10T00:00:00Z', '2026-08-09', '20:00 EDT — UTC rolls over, Eastern does NOT'],
  ['2026-08-10T01:00:00Z', '2026-08-09', '21:00 EDT — the hour the seed ran'],
  ['2026-08-10T03:59:00Z', '2026-08-09', '23:59 EDT — still the same Eastern day'],
  ['2026-08-10T04:00:00Z', '2026-08-10', '00:00 EDT — Eastern midnight, now it rolls'],
];
for (const [iso, want, why] of EDT_CASES) {
  const got = todayAt(iso);
  ok(got === want, `${why}: ${iso} -> ${got} (want ${want})`);
}

// EST (UTC-5). The rollover is an hour earlier in winter; the old code was
// wrong from 19:00.
const EST_CASES = [
  ['2026-01-15T23:59:00Z', '2026-01-15', '18:59 EST — UTC agrees'],
  ['2026-01-16T00:00:00Z', '2026-01-15', '19:00 EST — UTC rolls over, Eastern does NOT'],
  ['2026-01-16T04:59:00Z', '2026-01-15', '23:59 EST — still the same Eastern day'],
  ['2026-01-16T05:00:00Z', '2026-01-16', '00:00 EST — Eastern midnight'],
];
for (const [iso, want, why] of EST_CASES) {
  const got = todayAt(iso);
  ok(got === want, `${why}: ${iso} -> ${got} (want ${want})`);
}

// ── 3. the old behaviour, shown failing ─────────────────────────────────────
// Not a regression guard — a demonstration that these cases actually
// discriminate. If toISOString() and the Eastern formatter agreed at 21:00,
// every assertion above would pass on the broken code too.
const brokenAt = (iso) => new Date(iso).toISOString().split('T')[0];
ok(brokenAt('2026-08-10T01:00:00Z') === '2026-08-10'
   && todayAt('2026-08-10T01:00:00Z') === '2026-08-09',
  'at 21:00 EDT the old UTC expression and the fixed one genuinely differ');
ok(brokenAt('2026-08-09T11:00:00Z') === todayAt('2026-08-09T11:00:00Z'),
  'at 07:00 EDT they agree — which is why this shipped unnoticed');

// ── 4. the value is what actually reaches the forms ─────────────────────────
ok(/router\.push\(`\/logbooks\/\$\{logType\}\?projectId=\$\{projectId\}&date=\$\{today\}`\)/.test(src),
  '`today` is the date every logbook form is navigated with');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
console.log('ALL PASSED');
