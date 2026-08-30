/**
 * THE FLOOR, and the two things it must never do.
 *
 * A device whose NATIVE build predates the current `expo.version` receives no
 * OTA update at all, forever, and is told nothing — `runtimeVersion:
 * {policy: "appVersion"}` makes it ineligible rather than merely behind. On
 * 2026-08-28 that produced a filed log rendering as a blank editable form on
 * one phone and correctly on another, and six source traces were built before
 * anyone read the bundle id off the screen.
 *
 * `Updates.checkForUpdateAsync` cannot catch it: it asks whether a newer update
 * exists for the runtimeVersion the device is ALREADY STRANDED ON, so the
 * stranded phone is told it is current. The comparison has to come from
 * something that knows the product's floor, which is the server.
 *
 * Run:  node src/utils/clientVersion.test.cjs
 */
const fs = require('fs');
const path = require('path');

const UTILS = __dirname;
const FRONTEND = path.join(UTILS, '..', '..');
const REPO = path.join(FRONTEND, '..');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); }
  else { failed += 1; console.log(`  FAIL  ${label}`); }
}

const src = fs.readFileSync(path.join(UTILS, 'clientVersion.js'), 'utf8')
  .replace(/^export default[\s\S]*$/m, '')
  .replace(/^export /gm, '');
// eslint-disable-next-line no-new-func
const { parseVersion, compareVersions, isBehindMinimum } = new Function(
  `${src}; return { parseVersion, compareVersions, isBehindMinimum };`)();

console.log('\n-- comparing --');

ok(compareVersions('1.2.0', '1.3.0') === -1, '1.2.0 is below 1.3.0');
ok(compareVersions('1.3.0', '1.3.0') === 0, 'equal is equal');
ok(compareVersions('1.10.0', '1.9.0') === 1,
  '1.10.0 beats 1.9.0 — string comparison would get this backwards');
ok(compareVersions('2.0.0', '1.99.99') === 1, 'major wins');
ok(compareVersions('1.3', '1.3.0') === 0, 'a short version is zero-filled');
ok(compareVersions('1.3.0-rc1', '1.3.0') === 0,
  'a build suffix is not a version bump — a release channel must not read as behind');

console.log('\n-- the stranded device --');

ok(isBehindMinimum('1.2.0', '1.3.0') === true,
  'the case this exists for: a 1.2.x native build under a 1.3.0 floor');
ok(isBehindMinimum('1.3.0', '1.3.0') === false, 'at the floor is not below it');
ok(isBehindMinimum('1.4.0', '1.3.0') === false, 'ahead is not behind');

console.log('\n-- unknown is NOT behind --');

for (const [installed, minimum, why] of [
  ['1.2.0', null, 'an older server that does not report a floor'],
  ['1.2.0', undefined, 'a missing field'],
  ['1.2.0', '', 'an empty floor'],
  [null, '1.3.0', 'an install that cannot say what it is'],
  ['', '1.3.0', 'an empty version'],
  ['garbage', '1.3.0', 'an unparseable version'],
  ['1.2.0', 'garbage', 'an unparseable floor'],
]) {
  ok(isBehindMinimum(installed, minimum) === false,
    `silent for ${why} — an install we cannot judge must not be accused`);
}

console.log('\n-- the declaration, and who reads it --');

const appJson = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'app.json'), 'utf8'));
const declared = appJson.expo.extra.minimumSupportedVersion;
ok(typeof declared === 'string' && parseVersion(declared) !== null,
  `app.json declares a parseable minimumSupportedVersion (${declared})`);
ok(compareVersions(declared, appJson.expo.version) <= 0,
  'the floor is never ABOVE the version being shipped — that would mark every '
  + 'install, including the newest one, as out of date');

const server = fs.readFileSync(path.join(REPO, 'backend', 'server.py'), 'utf8');
// INVERTED BY THE OUTAGE OF 2026-08-29. This asserted the server derives the
// floor from app.json. It did -- by reading frontend/app.json at MODULE SCOPE,
// in a Railway image that contains backend/ only. FileNotFoundError on every
// boot, and the except handler called `logger` ~280 lines before logger exists,
// so the fallback raised NameError and uvicorn died at import. 502 on every
// path until the read was removed.
//
// app.json STILL DECLARES minimumSupportedVersion (asserted above) and the
// value is still the right one to ship from. What must never come back is the
// backend reaching across the deploy boundary to read it. Baking it in at image
// build time is the open option; see the outage commit.
ok(!/minimumSupportedVersion/.test(server),
  'THE SERVER DOES NOT READ frontend/app.json -- it cannot, the deploy image '
  + 'contains backend/ only, and doing so crash-looped production');
ok(/"client_minimum_supported": CLIENT_MINIMUM_SUPPORTED/.test(server),
  'and /api/version still reports the field -- now null, which every reader '
  + 'already treats as UNKNOWN, i.e. NOT BEHIND on both surfaces');

console.log('\n-- the two surfaces --');

const marker = fs.readFileSync(
  path.join(FRONTEND, 'src', 'components', 'BuildMarker.jsx'), 'utf8');
const admin = fs.readFileSync(
  path.join(FRONTEND, 'app', 'admin', 'users.jsx'), 'utf8');
const api = fs.readFileSync(path.join(UTILS, 'api.js'), 'utf8');

ok(/isBehindMinimum/.test(marker), 'the CP strip judges its own install');
ok(/out of date/.test(marker), '...and says so');
ok(!/Modal|blocking|disabled/.test(marker),
  'NON-BLOCKING. A compliance app that stops a CP filing his day because its '
  + 'own update pipeline fell behind has substituted one failure for a worse one');
ok(/isBehindMinimum/.test(admin),
  'and the admin row flags it, because the person who can act on a stale '
  + 'install is not the person holding the phone');
ok(/X-Client-Version/.test(api),
  'every request reports the installed version, so the admin row has something '
  + 'to read without anyone holding the phone');
ok(!/checkForUpdateAsync|fetchUpdateAsync/.test(marker + admin + api),
  'nothing asks Expo whether an update exists — that question answers '
  + '"current" to exactly the stranded device this is built to find');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) { console.log('FAILURES ABOVE'); process.exit(1); }
console.log('ALL PASSED');
