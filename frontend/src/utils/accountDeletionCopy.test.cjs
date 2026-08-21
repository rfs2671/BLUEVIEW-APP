/**
 * THE COPY IS THE FEATURE.
 *
 * This is a legal-retention statement made to a man about records that carry
 * his own signature. Get the mechanism right and the wording wrong and it is
 * either a lie (promising erasure that cannot happen) or a stall (a category
 * with no reason attached). Both are worse than not shipping it.
 *
 * Four things have to be said, and they are asserted here rather than left to
 * whoever edits the screen next:
 *
 *   1. WHAT GOES        the account and the sign-in, plainly.
 *   2. WHAT STAYS       filed compliance documents, WITH HIS NAME ON THEM.
 *   3. WHY THEY STAY    "kept by law" — the REASON, not the category. "For
 *                       compliance" tells him a policy exists; naming DOB
 *                       record-keeping tells him why, which is the difference
 *                       between honest and evasive.
 *   4. THE WARNING      unsynced work cannot be recovered after access ends.
 *                       This is the only line that can save a signed record.
 *
 *   node frontend/src/utils/accountDeletionCopy.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const SETTINGS = fs.readFileSync(path.join(FRONTEND, 'app', 'settings.jsx'), 'utf8');
const ADMIN = fs.readFileSync(path.join(FRONTEND, 'app', 'admin', 'users.jsx'), 'utf8');
const API = fs.readFileSync(path.join(FRONTEND, 'src', 'utils', 'api.js'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}
/** Collapse JSX line wrapping so assertions test the SENTENCE, not the layout. */
const flat = (s) => s.replace(/\s+/g, ' ');
const SET = flat(SETTINGS);
const ADM = flat(ADMIN);

console.log('\n-- it is reachable in the app, which is the whole guideline --');
{
  // 5.1.1(v) exists to stop "email us to delete your account". A mailto is the
  // failure mode, not the fallback.
  ok(/Request account deletion/.test(SET), 'the entry point is in settings');
  ok(!/mailto:/.test(SETTINGS), 'and there is no mailto anywhere on the screen');
  ok(/requestAccountDeletion/.test(API) && /withdrawAccountDeletion/.test(API),
    'both request and withdraw are real endpoints, not a compose-mail link');
  ok(/auth\/me\/deletion-request/.test(API), 'pointed at the deletion-request route');
}

console.log('\n-- 1. what goes --');
{
  ok(/Your account and your access to LeveLog will be removed/.test(SET),
    'the account and the access, said plainly');
  ok(/You will not be able to sign in/.test(SET),
    'and the consequence he will actually notice');
}

console.log('\n-- 2 and 3. what stays, and WHY --');
{
  ok(/Your signed records stay/.test(SET), 'stated as a heading, not buried');
  ok(/Logbooks, daily logs, signatures and check-ins you filed/.test(SET),
    'named specifically — "your data" would leave him guessing which data');
  // THE CORRECTION THAT MATTERS. "Kept by law" names the reason; "kept for
  // compliance" names a category and tells him only that a policy exists.
  ok(/NYC DOB record-keeping requires the site to keep them/.test(SET),
    'THE REASON IS NAMED: DOB record-keeping, not "for compliance"');
  ok(/not yours to erase and we will not delete them/.test(SET),
    'and it refuses plainly instead of implying erasure might happen later');
  ok(/They keep your name on them, because a filed attestation has to say who made it/.test(SET),
    'HIS NAME STAYS, and why — otherwise he finds out afterwards, from a PDF');
}

console.log('\n-- 4. the one warning that can save him something --');
{
  ok(/Before you request this/.test(SET), 'it comes BEFORE the destructive action');
  ok(/unsynced/.test(SET), 'names the state he can actually look for');
  ok(/cannot be recovered once your access ends/.test(SET),
    'and says what is lost — a CP whose token stops authenticating strands '
    + 'every signed draft still on his handset');
}

console.log('\n-- the request is a request, and it is answerable --');
{
  ok(/Your administrator will action this request and can contact you first/.test(SET),
    'he is told a person handles it, so it does not read as a void');
  ok(/Deletion requested/.test(SET),
    'and the state persists on screen afterwards — a toast is gone in four '
    + 'seconds, which is what makes a request feel like it went nowhere');
  ok(/Withdraw request/.test(SET),
    'and he can take it back; a request he cannot withdraw is a trap');
  ok(/deletionRequestedAt/.test(SETTINGS) && /user\?\.deletion_requested_at/.test(SETTINGS),
    'seeded from the server, so the request survives a reinstall');
}

console.log('\n-- not offered on a shared site device --');
{
  ok(/\{!siteMode && \(/.test(SETTINGS),
    'a jobsite tablet is not somebody\'s personal account');
}

console.log('\n-- the admin is told the same facts, from the other side --');
{
  ok(/removes their account and sign-in/.test(ADM), 'what he is ending');
  ok(/filed logbooks, signatures and check-ins stay on the project/.test(ADM),
    'what he is NOT ending');
  ok(/with their name on them/.test(ADM),
    'and that the attestation keeps its author — the thing he would assume '
    + 'deletion breaks');
  ok(/unsynced work on their phone it will not/.test(ADM)
    && /reach the server after this/.test(ADM),
    'THE CHECK HE MUST DO FIRST, in front of him at the moment he acts');
  ok(/Ask them to open the app on a connection/.test(ADM),
    'phrased as an instruction he can follow, not a caveat');
  ok(/deleteUserBody\(userName\)/.test(ADM),
    'and the body names the person, so a mis-tap on the wrong row is visible');
}

console.log('\n-- the admin sees it where he already looks --');
{
  ok(/userItem\.deletion_requested_at/.test(ADMIN),
    'the request is a field on the user\'s own row in the list he already uses');
  ok(/Requested deletion/.test(ADM), 'labelled on that row');
  ok(!/deletion-queue|DeletionQueue/.test(ADMIN),
    'and NOT a new screen — an unread queue is the "contact support" stall '
    + 'in a different costume');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
