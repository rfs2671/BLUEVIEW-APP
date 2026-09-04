/**
 * ONE OUTPUT FOR THREE STATES, ON THE SURFACE AN OPERATOR IS TOLD TO TRUST.
 *
 * The card printed "MISMATCH — the app and the backend are on different
 * commits" whenever two seven-character strings differed. That is true of a
 * failed OTA, of a deploy that has not landed, and of a BACKEND-ONLY change
 * where nothing under frontend/ moved, the OTA workflow correctly did not run,
 * and the phone is exactly right.
 *
 * On 2026-09-04 the third case produced an acceptance test telling the CP to
 * wait for a version line that was never going to change. Same wrong
 * conclusion as the stale-bundle case, from the opposite cause.
 *
 * Run:  node src/utils/buildVerdict.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const src = fs.readFileSync(path.join(UTILS, 'buildVerdict.js'), 'utf8')
  .replace(/^export default[\s\S]*$/m, '')
  .replace(/^export const /gm, 'const ')
  .replace(/^export function /gm, 'function ');
// eslint-disable-next-line no-new-func
const M = new Function(
  `${src}; return { buildVerdict, IN_SYNC, BACKEND_AHEAD, APP_AHEAD, DIFFERENT, UNKNOWN };`)();
const { buildVerdict: V } = M;

const A = 'aaaaaaa1111111';
const B = 'bbbbbbb2222222';
const EARLY = '2026-09-04T06:45:52.000Z';
const LATE  = '2026-09-04T14:20:00.000Z';

console.log('\n-- the three states, which is the whole point --');

ok(V(A, A, EARLY, LATE).state === M.IN_SYNC, 'same commit is in sync');
ok(V(A, B, EARLY, LATE).state === M.BACKEND_AHEAD,
  'backend deployed after the bundle was published -> backend is ahead');
ok(V(A, B, LATE, EARLY).state === M.APP_AHEAD,
  'bundle published after the backend deployed -> the deploy has not landed');

console.log('\n-- the case that caused this --');

const backendOnly = V(A, B, EARLY, LATE);
ok(backendOnly.ok === true,
  'a backend-only change is NOT flagged as a fault');
ok(!/mismatch/i.test(backendOnly.text),
  'and the word MISMATCH does not appear — it is what sent the wrong acceptance test out');
ok(/needs no app update/i.test(backendOnly.text),
  'it says the actionable thing: no app update is needed');

console.log('\n-- a real fault still reads as one --');

const notLanded = V(A, B, LATE, EARLY);
ok(notLanded.ok === false, 'a deploy that has not landed is a fault');
ok(/deploy has not landed/i.test(notLanded.text), 'and it says which side');

console.log('\n-- it never asserts a direction the evidence does not carry --');

ok(V(A, B, EARLY, EARLY).state === M.DIFFERENT,
  'EQUAL timestamps say only that the commits differ, never a direction');
ok(V(A, B, null, LATE).state === M.DIFFERENT, 'a missing bundle time is not a direction');
ok(V(A, B, EARLY, null).state === M.DIFFERENT, 'a missing deploy time is not a direction');
ok(V(A, B, 'not-a-date', LATE).state === M.DIFFERENT, 'an unparseable time is not a direction');
ok(!/mismatch/i.test(V(A, B, null, null).text),
  'and even the bare different-commits case drops the alarm wording');

console.log('\n-- not comparable is its own answer, ahead of everything --');

ok(V(A, null, EARLY, LATE).state === M.UNKNOWN, 'unreachable backend is not a mismatch');
ok(/unreachable/i.test(V(A, null, EARLY, LATE).text), 'and says so');
ok(V(null, B, EARLY, LATE).state === M.UNKNOWN, 'an uninjected bundle commit is not a mismatch');
ok(/not injected/i.test(V(null, B, EARLY, LATE).text), 'and says so');
ok(V(null, null, null, null).state === M.UNKNOWN, 'neither side known');

console.log('\n-- the seven-character rule is unchanged --');

ok(V('abc1234deadbeef', 'abc1234', EARLY, LATE).state === M.IN_SYNC,
  'a full sha matches its own short form');
ok(V('abc1234', 'abc1235', EARLY, LATE).state !== M.IN_SYNC,
  'and a one-character difference in the first seven is NOT a match');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
