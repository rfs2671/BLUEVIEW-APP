/**
 * A STORED INSURANCE EXPIRY PRINTS THE DAY THAT IS STORED.
 *
 * Two formats live in `companies.gc_insurance_records[].expiration_date` —
 * `2029-07-21` (what everything writes now) and `07/21/2029` (what was written
 * before). They name THE SAME DAY, so the owner panel and the Settings cards
 * must print the same thing for both. They did not:
 *
 *     new Date('2029-07-21').getDate()   // 20, in America/New_York
 *     new Date('07/21/2029').getDate()   // 21
 *
 * A date-only string is UTC midnight by specification, so east of UTC every
 * ISO expiry rendered one day early. The legacy form rendered correctly, which
 * is why nobody saw it: the screens only started receiving ISO with #590.
 *
 * ── THIS TEST REFUSES TO RUN WHERE IT CANNOT SEE THE DEFECT ─────────────────
 *
 * The shift only happens in a zone behind UTC. On a UTC runner
 * `new Date('2029-07-21').getDate()` is 21 and every assertion below passes
 * against the BROKEN code — a green that means nothing. So the file pins
 * America/New_York (the operator's zone, where the app is used) and then
 * CHECKS that the pin took effect, exiting non-zero if it did not.
 *
 * Run:  node src/utils/insuranceExpiry.test.cjs
 */
process.env.TZ = 'America/New_York';

const fs = require('fs');
const path = require('path');
const { loadEsm } = require('./esmHarness.cjs');

const FRONTEND = path.resolve(__dirname, '..', '..');

// ── THE INSTRUMENT, CHECKED BEFORE IT IS USED ───────────────────────────────
if (new Date('2029-07-21').getDate() !== 20) {
  console.error(
    '\nREFUSING TO RUN: this process is not in a zone behind UTC, so the '
    + 'one-day shift\n  this file exists to catch is invisible here and every '
    + 'assertion below would pass\n  against the broken code. Set '
    + 'TZ=America/New_York.\n');
  process.exit(2);
}

const E = loadEsm('src/utils/insuranceExpiry.js');

let failures = 0;
const check = (name, fn) => {
  try {
    fn();
    console.log(`  ok  ${name}`);
  } catch (e) {
    failures += 1;
    console.error(`FAIL  ${name}\n      ${e.message}`);
  }
};
const eq = (a, b, what) => {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    throw new Error(`${what}: expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
  }
};
const ok = (cond, msg) => { if (!cond) throw new Error(msg); };

console.log('\ninsurance expiry\n');

// ── 1. THE RULING: ONE DAY, TWO STORED FORMATS, ONE RENDERED DAY ────────────

check('a stored ISO and a stored MM/DD/YYYY for the same day print the same day', () => {
  eq(E.formatInsuranceExpiryShort('2029-07-21'),
     E.formatInsuranceExpiryShort('07/21/2029'), 'short form');
  eq(E.formatInsuranceExpiryLong('2029-07-21'),
     E.formatInsuranceExpiryLong('07/21/2029'), 'long form');
});

check('and that day is the 21st — not merely the same wrong day on both', () => {
  // AGREEING IS NOT ENOUGH. Two readers can agree by being wrong together, so
  // the day itself is named. 7/20/29 is the exact output of the code this
  // replaces, on this machine, for the ISO input.
  eq(E.formatInsuranceExpiryShort('2029-07-21'), '7/21/29', 'ISO short');
  eq(E.formatInsuranceExpiryShort('07/21/2029'), '7/21/29', 'legacy short');
  eq(E.formatInsuranceExpiryLong('2029-07-21'), 'Jul 21, 2029', 'ISO long');
  eq(E.formatInsuranceExpiryLong('07/21/2029'), 'Jul 21, 2029', 'legacy long');
});

check('every month prints its own day in both formats', () => {
  // ONE DAY IS ONE SAMPLE. July is inside DST; January is not, and the shift
  // is a fixed offset either way, so a fix that happened to work for one
  // month would be caught here.
  for (let m = 1; m <= 12; m += 1) {
    const mm = String(m).padStart(2, '0');
    const iso = `2029-${mm}-01`;
    const legacy = `${mm}/01/2029`;
    eq(E.formatInsuranceExpiryShort(iso), `${m}/1/29`, `month ${mm} ISO`);
    eq(E.formatInsuranceExpiryShort(legacy), `${m}/1/29`, `month ${mm} legacy`);
  }
});

check('the first of a month does not fall back into the month before', () => {
  // THE WORST CASE OF THE SHIFT. 2029-03-01 read as UTC midnight is
  // 2029-02-28 in New York, so the badge changed MONTH, not just day.
  eq(E.formatInsuranceExpiryLong('2029-03-01'), 'Mar 1, 2029', 'March 1st');
  eq(E.formatInsuranceExpiryLong('2029-01-01'), 'Jan 1, 2029', 'New Year');
  // And a year boundary: 2030-01-01 rendered as 12/31/29 is the wrong YEAR on
  // a compliance badge.
  eq(E.formatInsuranceExpiryShort('2030-01-01'), '1/1/30', 'year boundary');
});

// ── 2. THE COLOUR BAND SHIFTED AT ITS EDGES TOO ─────────────────────────────

const AT_NOON = new Date(2026, 8, 17, 12, 0, 0);   // 2026-09-17 12:00, local
// THE TIME OF DAY IS PART OF THE TEST, and finding that out is what this pair
// of constants records. The replaced code compared a UTC-midnight instant to
// `new Date()` and took `Math.ceil`, so whether it got the day right depended
// on the HOUR: at noon the -16h gap ceils to 0 and the answer is accidentally
// correct, and after 20:00 EDT the same stored date is more than a day behind
// and the badge flips to EXPIRED on a policy still in force. A control run of
// this file with only the noon case reported the colour band as passing.
const AT_EVENING = new Date(2026, 8, 17, 21, 0, 0);  // the same day, 21:00

check('days left is a calendar-day count, identical for both stored forms', () => {
  for (const [label, now] of [['noon', AT_NOON], ['evening', AT_EVENING]]) {
    eq(E.insuranceExpiryDaysLeft('2026-09-17', now), 0, `today, ISO, ${label}`);
    eq(E.insuranceExpiryDaysLeft('09/17/2026', now), 0, `today, legacy, ${label}`);
    eq(E.insuranceExpiryDaysLeft('2026-09-18', now), 1, `tomorrow, ${label}`);
    eq(E.insuranceExpiryDaysLeft('2026-09-16', now), -1, `yesterday, ${label}`);
  }
});

check('a policy expiring TODAY is not expired, at any hour of that day', () => {
  // THE EDGE THE SHIFT MOVED. A certificate is valid THROUGH its expiry day,
  // so a stored 2026-09-17 must not read red until the 18th — and it must not
  // change answer at 20:00 because that is when UTC midnight of the stored day
  // falls more than 24 hours behind a New York clock.
  for (const [label, now] of [['noon', AT_NOON], ['evening', AT_EVENING]]) {
    eq(E.insuranceExpiryState('2026-09-17', now), 'soon', `today, ISO, ${label}`);
    eq(E.insuranceExpiryState('09/17/2026', now), 'soon', `today, legacy, ${label}`);
    eq(E.insuranceExpiryState('2026-09-16', now), 'expired', `yesterday, ${label}`);
  }
});

check('the 60-day boundary is the same day in both stored forms', () => {
  eq(E.insuranceExpiryDaysLeft('2026-11-16', AT_NOON), 60, 'day 60');
  eq(E.insuranceExpiryState('2026-11-16', AT_NOON), 'soon', 'day 60 is soon');
  eq(E.insuranceExpiryState('11/16/2026', AT_NOON), 'soon', 'day 60, legacy');
  eq(E.insuranceExpiryState('2026-11-17', AT_NOON), 'ok', 'day 61 is ok');
  eq(E.insuranceExpiryState('11/17/2026', AT_NOON), 'ok', 'day 61, legacy');
});

check('a day count across a DST change is still a whole number of days', () => {
  // 2026-11-01 is the fall-back in America/New_York: that local day is 25
  // hours long. A `Math.ceil` over the raw quotient reports 2 days for a
  // 3-day gap on one side and shifts an expired policy to "0 days left" on
  // the other, which colours amber instead of red.
  const beforeFallBack = new Date(2026, 9, 30, 12, 0, 0);   // Oct 30
  eq(E.insuranceExpiryDaysLeft('2026-11-03', beforeFallBack), 4, 'forward over DST');
  eq(E.insuranceExpiryDaysLeft('2026-10-27', beforeFallBack), -3, 'backward');
  const afterSpringForward = new Date(2026, 2, 10, 12, 0, 0);  // Mar 10
  eq(E.insuranceExpiryDaysLeft('2026-03-05', afterSpringForward), -5, 'back over spring');
});

// ── 3. UNREADABLE IS ITS OWN ANSWER ─────────────────────────────────────────

check('a blank expiry and an unreadable one are told apart', () => {
  eq(E.insuranceExpiryState('', AT_NOON), 'blank', 'empty string');
  eq(E.insuranceExpiryState(null, AT_NOON), 'blank', 'null');
  eq(E.insuranceExpiryState('7/2/29', AT_NOON), 'unreadable', 'two-digit year');
  eq(E.insuranceExpiryState('2029', AT_NOON), 'unreadable', 'a year alone');
  eq(E.insuranceExpiryState('21/07/2029', AT_NOON), 'unreadable', 'day first');
  eq(E.insuranceExpiryState('2029-02-30', AT_NOON), 'unreadable', 'no such day');
});

check('an unreadable expiry never reads as ok, soon or expired', () => {
  // THE FAILURE MODE THIS CLOSES ON THE SCREEN. `new Date('illegible')` is
  // NaN, the old helper returned grey, and grey on that row is what "no
  // record" looks like. It must SAY the word.
  for (const raw of ['illegible', 'see attached', '7/2/29', '{}']) {
    const state = E.insuranceExpiryState(raw, AT_NOON);
    eq(state, 'unreadable', `state of ${JSON.stringify(raw)}`);
    eq(E.insuranceExpiryDaysLeft(raw, AT_NOON), null, `days of ${JSON.stringify(raw)}`);
  }
});

check('the badge prints a word, not a truncated quote', () => {
  eq(E.formatInsuranceExpiryShort('illegible'), 'unreadable', 'short');
  eq(E.formatInsuranceExpiryLong('illegible'), 'insurance date unreadable', 'long');
  eq(E.formatInsuranceExpiryShort(''), '--', 'blank short');
  eq(E.formatInsuranceExpiryLong(null), '--', 'blank long');
});

check('the screen and the server name the unreadable condition identically', () => {
  // ONE CONDITION, ONE SENTENCE. backend/lib/insurance_expiry.py logs it and
  // puts it in the permit-renewal blocking reasons; if the two drift, an
  // admin reading the badge and an admin reading the email are told about
  // what looks like two different problems.
  const py = fs.readFileSync(
    path.resolve(FRONTEND, '..', 'backend', 'lib', 'insurance_expiry.py'), 'utf8');
  const m = /^INSURANCE_DATE_UNREADABLE\s*=\s*"([^"]+)"/m.exec(py);
  ok(m, 'INSURANCE_DATE_UNREADABLE not found in backend/lib/insurance_expiry.py');
  eq(E.INSURANCE_DATE_UNREADABLE, m[1], 'the sentence');
});

// ── 4. THE CALL SITES, BECAUSE A CORRECT MODULE NOBODY CALLS FIXES NOTHING ──
//
// The module could be perfect and both screens could still hold their own
// `new Date(rec.expiration_date)`. That is what was there before, in two
// copies, and it is the shape this repo has shipped more than once: a right
// answer wired to nothing.

/** Comments removed, newlines kept so a line number is the file's own. */
function stripComments(src) {
  const blank = (s) => s.replace(/[^\n]/g, '');
  return src.split('\r\n').join('\n')
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, blank)
    .replace(/\/\*[\s\S]*?\*\//g, blank)
    .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
}

const SCREENS = ['app/owner/index.jsx', 'app/settings.jsx'];

check('both screens import the shared reader', () => {
  for (const rel of SCREENS) {
    const code = stripComments(fs.readFileSync(path.join(FRONTEND, rel), 'utf8'));
    ok(/from ['"][^'"]*utils\/insuranceExpiry['"]/.test(code),
       `${rel} does not import src/utils/insuranceExpiry`);
  }
});

check('no screen builds a Date out of an insurance date field', () => {
  // THE FIELD NAMES, not the helper names: a renamed local helper would slip
  // past a check on `getInsColor`. `effective_date` is included because it is
  // rendered on the same card from the same store and shifts the same way.
  const bad = [];
  for (const rel of SCREENS) {
    const code = stripComments(fs.readFileSync(path.join(FRONTEND, rel), 'utf8'));
    code.split('\n').forEach((line, i) => {
      if (/new Date\([^)]*\b(expiration_date|effective_date)\b/.test(line)) {
        bad.push(`${rel}:${i + 1}  ${line.trim()}`);
      }
    });
  }
  eq(bad, [], 'a Date built from an insurance date string');
});

check('the owner panel keeps no local expiry formatter of its own', () => {
  // Both of these read `new Date(expStr)` / `new Date(s)` where the argument
  // is ALREADY narrowed to an expiration_date by the caller, so the field-name
  // scan above cannot see them. Named directly, and named as gone rather than
  // as rewritten, because the point is that there is one reader.
  const code = stripComments(
    fs.readFileSync(path.join(FRONTEND, 'app/owner/index.jsx'), 'utf8'));
  ok(!/const\s+getInsColor\s*=/.test(code), 'getInsColor is still defined');
  ok(!/const\s+fmtShort\s*=/.test(code), 'fmtShort is still defined');
});

check('no insurance record goes through settings\' own formatDate', () => {
  // NOT A CLEAN SWEEP, deliberately, and the two survivors are not survivors
  // for the same reason:
  //
  //   gc_last_verified       IS A TIMESTAMP. `new Date` is the correct reader
  //                          and `parseStoredDate` would call it unreadable.
  //                          Nothing to fix.
  //   gc_license_expiration  IS A CALENDAR DAY and DOES shift. It is left
  //                          because BIS hands it over as
  //                          `\d{1,2}/\d{1,2}/\d{2,4}` ('7/2/29'), looser than
  //                          the stored-date reader accepts, so swapping the
  //                          reader under it would print "unreadable" rather
  //                          than the right day. It needs its own ruling and
  //                          is on the operator's list.
  //
  // Both are asserted as STILL THERE, so this check fails if a later sweep
  // takes them without deciding about them — the swap is not safe for the
  // second one.
  const code = stripComments(
    fs.readFileSync(path.join(FRONTEND, 'app/settings.jsx'), 'utf8'));
  ok(!/const\s+getExpirationColor\s*=/.test(code),
     'getExpirationColor is still defined');
  ok(/formatDate\(insData\.gc_last_verified\)/.test(code),
     'the gc_last_verified timestamp render changed; it was correct as it was');
  ok(/formatDate\(insData\.gc_license_expiration\)/.test(code),
     'gc_license_expiration moved without a ruling — see this comment');
  ok(!/formatDate\(rec\.(expiration|effective)_date\)/.test(code),
     'an insurance record still goes through formatDate');
});

console.log(failures ? `\n${failures} failure(s)\n` : '\nall passed\n');
process.exit(failures ? 1 : 0);
