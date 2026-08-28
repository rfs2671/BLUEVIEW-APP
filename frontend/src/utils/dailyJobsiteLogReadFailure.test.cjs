/**
 * A LOG READ THAT FAILED IS NOT A DAY WITH NO LOG.
 *
 * The existing-log read was `.catch(() => [])`, so a request that never came
 * back handed an empty array to everything downstream: `existing` came out
 * null, `hydrate` never ran, `locked` stayed false, and the screen rendered an
 * EDITABLE EMPTY FORM for a day that may already be filed. On 2026-08-28 a
 * second device showed exactly that — a submitted daily jobsite log rendered
 * blank — and the only thing between it and the record was one tap.
 *
 * The same function already draws this distinction for the ROSTER: `null` means
 * the read did not come back and nothing is rebuilt, because "a roster read
 * that FAILED is not an empty jobsite". This asserts the log read now says the
 * same thing about itself.
 *
 * SOURCE TEXT, like its sibling dailyJobsiteStepper.test.cjs: what is asserted
 * here is ordering and the absence of a swallowed failure, which is what source
 * can show and execution cannot without mounting the screen.
 *
 * Run:  node src/utils/dailyJobsiteLogReadFailure.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const src = fs.readFileSync(
  path.join(FRONTEND, 'app', 'logbooks', 'daily_jobsite.jsx'), 'utf8');
const stepper = fs.readFileSync(
  path.join(FRONTEND, 'src', 'components', 'logbookStepper', 'LogbookStepper.jsx'), 'utf8');
const en = fs.readFileSync(path.join(FRONTEND, 'src', 'i18n', 'en.js'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

console.log('\n-- the read is settled, not swallowed --');

ok(!/getByProject\(projectId, 'daily_jobsite', date\)\.catch\(\(\) => \[\]\)/.test(src),
  'the failure-swallowing form is GONE — `.catch(() => [])` on the existing-log '
  + 'read is what made a failed request indistinguishable from an unfiled day');

ok(/settleFetch\(\(\) => logbooksAPI\.getByProject\(projectId, 'daily_jobsite', date\)\)/.test(src),
  'the read goes through settleFetch — the app-wide three-way discriminator, '
  + 'the same one the roster and every other guarded read on this screen use');

console.log('\n-- and a failed read fails CLOSED --');

const guard = /if \(existingLogsRes\.status !== 'ok'\) \{[\s\S]*?\n      \}/.exec(src);
ok(!!guard, 'there is a guard on the read outcome');
ok(!!guard && /setLocked\(true\)/.test(guard[0]),
  'the guard LOCKS the screen — no editable fields on a day it could not read');
ok(!!guard && /\breturn;/.test(guard[0]),
  'and RETURNS: nothing below it may run on a read that did not come back');

// ORDERING IS THE PROPERTY. A guard that sits after hydrate/buildCrewsFromRoster
// would let the form fill itself in from the gate roster first, which is the
// blank editable day this exists to prevent.
const iGuard = src.indexOf("if (existingLogsRes.status !== 'ok')");
const iHydrate = src.indexOf('hydrate(existing.data || {})');
const iBuild = src.indexOf('builtCrews = buildCrewsFromRoster(');
ok(iGuard > 0 && iHydrate > iGuard,
  'the guard runs BEFORE hydrate');
ok(iGuard > 0 && iBuild > iGuard,
  'the guard runs BEFORE the crews are rebuilt from the roster — otherwise the '
  + 'CP is looking at a day the app filled in, on a read that failed');

ok(/const existingLogs = Array\.isArray\(existingLogsRes\.data\)/.test(src),
  'the array guard survives for the SUCCESS path — an ok read still has to be '
  + 'an array before chooseEditableLog sees it');

console.log('\n-- the reason is stated, and it is not a lock claim --');

ok(/unavailable=\{logReadFailed \?/.test(src),
  'the screen passes `unavailable` when the read failed');
ok(/failureDetail\(\s*\n?\s*logReadFailed, logReadError/.test(src.replace(/\s+/g, ' '))
  || /failureDetail\(/.test(src),
  'the second half of the sentence comes from failureDetail — offline vs 404 '
  + 'vs 403 vs 500, rather than one fixed line for four different causes');

const branch = /if \(unavailable\) \{[\s\S]*?\n  \}/.exec(stepper);
ok(!!branch, 'the stepper has an `unavailable` branch');
ok(!!branch && !/LogbookLockBar/.test(branch[0]),
  'it does NOT render the lock bar — "FINALIZED, read-only" plus an Amend '
  + 'button would be a claim about a document this device could not read');
ok(!!branch && !/submitLabel|footer/.test(branch[0]),
  'and no footer: there is nothing to submit');
ok(!!branch && /onPress=\{onExit\}/.test(branch[0]),
  'the CP can still get out of the screen');

console.log('\n-- the copy exists --');

// The quote style differs per line (the title carries an apostrophe, so it is
// double-quoted), and a button label is not a sentence — so the match is
// quote-aware and the length floor is per key rather than one number for all
// three.
for (const [key, minLen] of [
  ['logUnavailableTitle', 12],
  ['logUnavailableBody', 60],
  ['logUnavailableRetry', 3],
]) {
  const line = en.split('\n').find((l) => l.trim().startsWith(`${key}:`)) || '';
  const raw = line.slice(line.indexOf(':') + 1).trim().replace(/,$/, '');
  const value = raw.slice(1, -1);
  ok(value.trim().length >= minLen, `${key} is present and non-empty`);
}

ok(/do not fill the day in again from here/i.test(en),
  'the body tells the CP the one thing he must not do — re-entering a day that '
  + 'is already filed is how the record gets written over');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) { console.log('FAILURES ABOVE'); process.exit(1); }
console.log('ALL PASSED');
