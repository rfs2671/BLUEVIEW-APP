/**
 * Step 1 has no skip, and a company-less owner has a way back in.
 *
 * THE TRAP. "I'll do this later" on step 1 PATCHed onboarding_step="skipped",
 * which is terminal on both sides: _userInOnboarding() stops redirecting,
 * _onboarding_in_flight() 409s POST /onboarding/company, and
 * ALLOWED_USER_FIELDS carries neither company_id nor onboarding_step so no
 * admin or platform operator can repair it. The account is permanently without
 * a company, and every company-scoped read and write refuses it.
 *
 * It was the ONLY in-app route to that state, reachable exclusively by
 * declining the step that would have prevented it. One tap, first screen.
 *
 * THREE THINGS ARE ASSERTED, because removing the button alone fixes nobody
 * who is already stuck:
 *
 *   1. step 1 renders no skip control, and cannot PATCH "skipped"
 *   2. steps 2/3/4 keep theirs — those are real deferrals
 *   3. Settings offers re-entry to a company-less owner, and ONLY to one
 *
 * Plus: a failed write must not look like a successful one.
 *
 *   node frontend/src/utils/onboardingSkipTrap.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const ONB = fs.readFileSync(path.join(FRONTEND, 'app', 'onboarding.jsx'), 'utf8');
const SETTINGS = fs.readFileSync(path.join(FRONTEND, 'app', 'settings.jsx'), 'utf8');

/** Source with comments stripped — assertions must read CODE, not prose that
 *  describes the defect. This file explains the old behaviour at length, and a
 *  bare search would match the explanation and pass for the wrong reason. */
function code(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/.*$/gm, '');
}
const ONB_CODE = code(ONB);
const SETTINGS_CODE = code(SETTINGS);

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

console.log('\n-- step 1 cannot reach "skipped" --');
{
  // The label is the button. No label, no control.
  const labels = ONB_CODE.slice(
    ONB_CODE.indexOf('const skipLabels'),
    ONB_CODE.indexOf('return (', ONB_CODE.indexOf('const skipLabels')),
  );
  ok(labels.length > 20, 'ANCHOR: the skipLabels map exists');
  ok(!/\b1:\s*["'`]/.test(labels),
    'skipLabels has NO entry for step 1 — absent rather than blanked, so '
    + 'adding one back is a decision someone has to type');
  ok(/2:\s*'Skip this step'/.test(labels) && /3:\s*'Skip this step'/.test(labels),
    'steps 2 and 3 keep theirs — project and filing reps are real deferrals');
  ok(/4:\s*'Use Critical only'/.test(labels),
    "and step 4 keeps its dismissal, which finalizes rather than skips");

  ok(!/patchStep\(\s*['"]skipped['"]\s*\)/.test(ONB_CODE),
    'NOTHING in the screen PATCHes "skipped" any more — the one call site was '
    + "step 1's");

  ok(/skipLabels\[currentStep\]\s*&&/.test(ONB_CODE)
    || /!!skipLabels\[currentStep\]\s*&&/.test(ONB_CODE),
    'the control is conditionally rendered on a label existing, so step 1 '
    + 'shows no skip affordance at all');

  const fn = ONB_CODE.slice(ONB_CODE.indexOf('const skipFromCurrentStep'));
  ok(/currentStep === '1'\) return;/.test(fn.slice(0, 900)),
    'and skipFromCurrentStep returns early on step 1, so a stale render '
    + 'cannot drive it either');
}

console.log('\n-- a failed write does not look like a successful one --');
{
  const fin = ONB_CODE.slice(
    ONB_CODE.indexOf('const finalizeAndExit'),
    ONB_CODE.indexOf('const skipFromCurrentStep'),
  );
  ok(fin.length > 100, 'ANCHOR: finalizeAndExit body found');
  ok(/toast\.error\(/.test(fin),
    'a failed "completed" PATCH is SURFACED — it used to be swallowed, so the '
    + 'user believed setup finished while the server still held step 4');
  ok(/return;/.test(fin.slice(0, fin.indexOf('validateSession'))),
    'and it stops rather than routing out, so "Finish setup" can be retried');
}

console.log('\n-- Settings offers the way back, and only to who needs it --');
{
  const i = SETTINGS_CODE.indexOf('!user?.company_id');
  ok(i > -1, 'Settings gates a block on the user having NO company_id');

  const block = SETTINGS_CODE.slice(i, i + 1600);
  ok(/isAdmin\s*&&\s*!user\?\.company_id/.test(SETTINGS_CODE),
    'shown only to an owner/admin with no company — a finished account never '
    + 'sees it. Same discriminator the server uses: the COMPANY is the fact, '
    + 'the onboarding_step field is a claim that can be wrong');
  ok(/router\.push\('\/onboarding'\)/.test(block),
    'and it routes to /onboarding, the only screen that can create a company');
  ok(/touchTarget\.min/.test(block),
    "the CTA carries the app's 56pt minimum");
  ok(/semantic\.attention/.test(block),
    'rendered as attention, not critical — the account is incomplete, not '
    + 'broken, and nothing has been lost');
  ok(!/#[0-9a-fA-F]{6}/.test(block), 'tokens only, no colour literals');
}

console.log('\n-- the copy says what is wrong, not what a company_id is --');
{
  const i = SETTINGS.indexOf('No company on your account');
  ok(i > -1, 'the heading names the state plainly');
  const copy = SETTINGS.slice(i, i + 700);
  ok(/Projects, workers and reports/.test(copy),
    'the body names the CONSEQUENCE the user actually noticed');
  ok(/Finish setting up/.test(copy),
    'and the CTA names the action, not the mechanism');
  ok(!/company_id|onboarding_step|409/.test(copy),
    'no field names or status codes in user-facing copy');
}

console.log('\n-- onboarding has a way out of the SESSION --');
{
  // It was the ONLY confined state in the app without one. The site device
  // has it, Inspector Mode has it (its comment: "/login stays reachable so a
  // logout is still possible"), the CP reaches it through Settings, and
  // /demo renders this exact control. A user who wanted to abandon setup or
  // switch accounts had to clear site data.
  //
  // The guard already permits /login; what made it unreachable is that
  // login.jsx evicts an authenticated user, so the URL bounced
  // /login -> / -> /onboarding. Clearing the session is what makes /login
  // stick, which is why the fix is a control and not a guard change.
  ok(/logout/.test(ONB_CODE),
    'the screen takes logout from the context that already exports it');
  ok(/useAuth\(\)/.test(ONB_CODE) && /,\s*logout\s*}\s*=\s*useAuth/.test(ONB_CODE),
    'destructured from useAuth, the same way demo.jsx does it');
  ok(/onPress=\{logout\}/.test(ONB_CODE),
    'and a control calls it directly - no wrapper that could quietly do more');

  // logout() must not touch onboarding_step. The step is a fact about the
  // ACCOUNT, not the session: a user at step 3 has a company and a project on
  // the server, and resetting the marker would desynchronise it from the data
  // it describes. Asserted at the source, since that is where it would break.
  const AUTH = code(fs.readFileSync(
    path.join(FRONTEND, 'src', 'context', 'AuthContext.js'), 'utf8'));
  const fn = AUTH.slice(AUTH.indexOf('const logout'), AUTH.indexOf('const logout') + 800);
  ok(fn.length > 100, 'ANCHOR: the logout body was found');
  ok(!/onboarding/.test(fn),
    'logout touches NO onboarding field - the step survives the session, so a '
    + 'user at step 3 resumes at step 3');

  ok(/accessibilityRole="button"/.test(ONB_CODE),
    'it is a button to a screen reader');
  ok(/minHeight: touchTarget\.min/.test(ONB_CODE),
    "and carries the app-wide 56pt floor - it sits above a form the user is "
    + 'mid-way through, so a mis-tap costs them the session');
}

console.log('\n-- and the copy does not promise an escape from the flow --');
{
  // SCOPED TO THE CONTROL ITSELF, not a byte window around it. A window wide
  // enough to catch the label also catches skipLabels and the step-2/3 skip
  // styles, and then the assertion fails on code that is entirely correct.
  // The block between signOutRow and its closing View IS the control.
  const start = ONB_CODE.indexOf('<View style={styles.signOutRow}>');
  ok(start > -1, 'ANCHOR: the sign-out row exists');
  const block = ONB_CODE.slice(start, ONB_CODE.indexOf('</View>', start));

  const visible = [...block.matchAll(/>([^<>{}]+)</g)]
    .map((m) => m[1].trim()).filter(Boolean);
  ok(JSON.stringify(visible) === JSON.stringify(['Log out']),
    'the ONLY visible string in the control is "Log out", matching /demo. '
    + 'Found: ' + JSON.stringify(visible));

  // Since #208, _onboarding_in_flight returns True for ANY company-less user
  // whatever the step, so signing back in returns them here. That is correct,
  // and the copy must not suggest otherwise.
  ok(!/[Ss]kip|[Ll]ater|[Ee]xit|[Aa]bandon/.test(block),
    'no word in the control implies escaping the FLOW - this leaves the '
    + 'SESSION, and a company-less user who signs back in lands here again');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
