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

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
