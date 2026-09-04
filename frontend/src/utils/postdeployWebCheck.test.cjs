/**
 * THE POST-DEPLOY WEB GATE'S OWN LOGIC, tested rather than trusted.
 *
 * The gate itself needs a live site and a browser, so it cannot run here. Its
 * decision function can, and that is the half that decides whether a deploy is
 * accepted. `postdeploy_login_check.py` keeps `evaluate()` pure for exactly
 * this reason and this mirrors it.
 *
 * THE ASSERTION THAT MATTERS MOST is the vacuity guard: a run in which the
 * page made NO cross-origin request must FAIL. "No CORS errors" is free when
 * nothing was requested, and a check that can be satisfied without running is
 * how the mount smoke reported 37/37 clean for a week while the web app could
 * not sign in.
 *
 *   node frontend/src/utils/postdeployWebCheck.test.cjs
 */
const path = require('path');
const { evaluate, shaMatches, isCorsFailure } = require(
  path.join(__dirname, '..', '..', 'scripts', 'postdeploy-web-check.cjs'));

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS  ', label); }
  else { failed += 1; console.log('  FAIL  ', label); }
}
function section(t) {
  console.log(`\n-- ${t} ${'-'.repeat(Math.max(0, 58 - t.length))}`);
}

const GOOD = {
  deployedSha: 'a'.repeat(40),
  expectSha: 'a'.repeat(40),
  corsErrors: [],
  apiOk: true,
  apiFailed: 0,
};
const only = (over) => evaluate({ ...GOOD, ...over });

section('the happy path is the only thing that passes');
ok(only({}).length === 0, 'right SHA, no CORS errors, API reached -> accepted');

section('THE VACUITY GUARD — the assertion this file exists for');
{
  const f = only({ apiOk: false });
  ok(f.length === 1, 'a run that reached the API zero times is REFUSED');
  ok(/NOT ONE request/.test(f[0]),
    '...and says so in those words, because "no CORS errors" is free when '
    + 'nothing was requested');
  const clean = only({ apiOk: false, corsErrors: [] });
  ok(clean.length > 0,
    'a perfectly clean run with no traffic still fails — silence is not proof');
}

section('provenance: the check must run against the build that was pushed');
{
  ok(only({ deployedSha: 'b'.repeat(40) }).length === 1,
    'a live SHA that is not the pushed one is refused — otherwise this tests '
    + 'whatever build happens to still be up');
  ok(/has not landed/.test(only({ deployedSha: 'b'.repeat(40) })[0]),
    '...naming the reason, so a slow deploy is not read as a broken one');
  ok(only({ deployedSha: '' }).length === 1,
    'an unstamped build is refused, not assumed current');
  ok(only({ deployedSha: 'c'.repeat(40), expectSha: '' }).length === 0,
    'with no expected SHA, any stamped build is accepted — the manual case');
}

section('short and long SHAs are the same SHA');
{
  ok(shaMatches('abcdef1234567890', 'abcdef1'), 'a short SHA matches its long form');
  ok(shaMatches('abcdef1', 'abcdef1234567890'), '...in either direction');
  ok(shaMatches('ABCDEF1234', 'abcdef1'), 'and case does not matter');
  ok(!shaMatches('abcdef1234', 'fedcba9'), 'but a different commit does not match');
  ok(only({ deployedSha: 'a'.repeat(40), expectSha: 'a'.repeat(7) }).length === 0,
    'a 7-char EXPECT_SHA against a 40-char deployed one is accepted');
}

section('a blocked request fails the deploy');
{
  const f = only({
    corsErrors: ["Access to XMLHttpRequest at 'https://api.levelog.com/api/auth/me' "
      + 'from origin \'https://www.levelog.com\' has been blocked by CORS policy'],
  });
  ok(f.length === 1, 'one CORS error is enough to refuse the deploy');
  ok(/blocked by CORS/.test(f[0]), '...and the message is carried through, not summarised away');
}

section('what counts as the browser refusing to make the request');
{
  ok(isCorsFailure("has been blocked by CORS policy: Response to preflight request "
    + "doesn't pass access control check: It does not have HTTP ok status."),
    'the exact wording Chromium produced during the outage');
  ok(isCorsFailure('Access to fetch at ... has been blocked by CORS policy'),
    'the fetch wording as well as the XHR wording');
  ok(!isCorsFailure('Failed to load resource: the server responded with a status of 500'),
    'a 500 is the SERVER answering badly, not the browser refusing to ask — '
    + 'this gate is about the second thing');
  ok(!isCorsFailure('Download the React DevTools'), 'ordinary console noise is not a failure');
}

section('every failure is reported, not just the first');
{
  const f = evaluate({
    deployedSha: 'b'.repeat(40), expectSha: 'a'.repeat(40),
    corsErrors: ['blocked by CORS policy'], apiOk: false, apiFailed: 9,
  });
  ok(f.length === 3,
    'a stale build AND a CORS block AND no traffic report as three findings, '
    + 'so fixing one does not hide the others');
}

section('the stamp the gate polls for is actually written');
{
  const fs = require('fs');
  const build = require(path.join(__dirname, '..', '..', 'scripts', 'build-with-sourcemaps.js'));
  // The real emitter, writing to the real path the build writes to.
  const dest = path.join(build.DIST, 'version.json');
  const had = fs.existsSync(dest) ? fs.readFileSync(dest) : null;
  try {
    build.writeVersionFile('deadbeefdeadbeefdeadbeefdeadbeefdeadbeef');
    const body = JSON.parse(fs.readFileSync(dest, 'utf8'));
    ok(body.commit === 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef',
      'version.json carries the full commit the bundle was built from');
    ok(body.short === 'deadbee', '...and the short form, as /api/version reports it');
    ok(typeof body.built_at === 'string' && !Number.isNaN(Date.parse(body.built_at)),
      '...and a parseable build timestamp — the thing nobody could read');
    ok(only({ deployedSha: body.commit, expectSha: 'deadbee' }).length === 0,
      'and the gate ACCEPTS what the emitter writes — the two halves agree, '
      + 'which is the only reason polling for a SHA means anything');

    // AN UNSTAMPED BUILD WRITES EMPTY, NOT "unknown". A reader polling for a
    // commit must never match a placeholder and call the deploy landed.
    build.writeVersionFile('');
    const blank = JSON.parse(fs.readFileSync(dest, 'utf8'));
    ok(blank.commit === '' && blank.short === '',
      'a build with no SHA stamps an EMPTY commit, never a placeholder');
    ok(only({ deployedSha: blank.commit, expectSha: 'deadbee' }).length > 0,
      '...which the gate then refuses, instead of matching on it');
  } finally {
    if (had) fs.writeFileSync(dest, had);
    else if (fs.existsSync(dest)) fs.unlinkSync(dest);
  }
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) { console.log('FAILURES ABOVE'); process.exit(1); }
console.log('ALL PASSED');
