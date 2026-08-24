/**
 * WHAT THE BINARY DECLARES MUST BE WHAT THE BINARY DOES.
 *
 * A purpose string is a promise to Apple and to the person tapping Allow. A
 * privacy-manifest entry is stronger still — it is an affirmative statement
 * that the app COLLECTS a category of data. Both were carrying capabilities
 * this app has never had, on a submission already two rejections deep.
 *
 * So this file does not check the config against a list I typed. It re-derives
 * the capability from the SOURCE each run — if someone adds real location or
 * real audio recording, the assertion flips and tells them to add the string
 * back rather than failing for the sake of it.
 *
 *   node frontend/src/utils/iosSubmissionConfig.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const APP_JSON = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'app.json'), 'utf8')).expo;

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

/** Every .js/.jsx under app/ and src/, minus this file's own neighbours. */
function sources() {
  const out = [];
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== 'node_modules') walk(p); }
      else if (/\.(js|jsx)$/.test(e.name) && !/\.test\.cjs$/.test(e.name)) out.push(p);
    }
  };
  walk(path.join(FRONTEND, 'app'));
  walk(path.join(FRONTEND, 'src'));
  return out;
}
const ALL = sources().map((p) => fs.readFileSync(p, 'utf8')).join('\n');
const DEPS = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'package.json'), 'utf8')).dependencies;
const IP = APP_JSON.ios.infoPlist;
const COLLECTED = APP_JSON.ios.privacyManifests.NSPrivacyCollectedDataTypes
  .map((d) => d.NSPrivacyCollectedDataType);

console.log('\n-- the version is the one being submitted --');
{
  // 1.2.0, not 1.1.4. Eleven weeks past the 1.1.0 (5) Apple last saw, and
  // `runtimeVersion.policy: "appVersion"` makes this the OTA lane too.
  // The RULE, not the number. Pinning a literal version means editing this
  // test every release, and a test edited on every release is one nobody
  // reads. What must hold is that the version is a real semver and that the
  // Android versionCode below is derived from it.
  ok(/^[0-9]+[.][0-9]+[.][0-9]+$/.test(APP_JSON.version),
    `expo.version is a three-part semver (found ${APP_JSON.version})`);
  ok(APP_JSON.runtimeVersion?.policy === 'appVersion',
    'and the RV policy still derives the runtime from it, so the lane moves with the build');
}

console.log('\n-- the build numbers are stated, not counted up to --');
{
  const EAS = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'eas.json'), 'utf8'));
  // Under `appVersionSource: "remote"` the two numbers below are IGNORED and
  // EAS derives them from a counter. That is what has to stop: iOS build 5 is
  // burned on the rejected 1.1.0, and the Android versionCode — which must
  // increase monotonically forever or Play refuses the upload — has never
  // once been read.
  ok(EAS.cli.appVersionSource === 'local',
    'the REPO is the source of truth for both numbers, so they are in the diff');
  ok(!('autoIncrement' in EAS.build.production),
    'and autoIncrement is gone — with both, the explicit value is only ever '
    + 'the first one, and the next build silently goes back to counting');
  // THE RULE, not the number. CFBundleVersion need only be unique WITHIN a
  // CFBundleShortVersionString train, so it starts at 1 for a new version and
  // climbs from there — 1.3.0 build 1 was refused at processing for the NDEF
  // entitlement, so that pair is spent and this is 2. Pinning a literal means
  // editing the test on every resubmission.
  ok(/^[0-9]+$/.test(APP_JSON.ios.buildNumber),
    `iOS buildNumber is a positive integer string (found ${APP_JSON.ios.buildNumber})`);
  ok(Number(APP_JSON.ios.buildNumber) >= 1,
    'and at least 1');
  const vc = APP_JSON.android.versionCode;
  ok(Number.isInteger(vc) && vc > 0 && vc < 2100000000,
    `Android versionCode is a valid integer (${vc})`);
  // major*1000000 + minor*10000 + patch*100 + build, derived from the version
  // string so the two cannot drift apart.
  const [maj, min, pat] = APP_JSON.version.split('.').map(Number);
  const floor = maj * 1000000 + min * 10000 + pat * 100;
  ok(vc > floor && vc < floor + 100,
    `and it encodes ${APP_JSON.version} with a build slot (${floor} < ${vc} < ${floor + 100}) `
    + '— a resubmission after a rejection needs a new versionCode WITHOUT a '
    + 'new version string, so the slot has to exist');
  ok(!('autoIncrement' in EAS.build['preview-prod']),
    'the internal-distribution profile has not quietly gained one either');
}

console.log('\n-- location: declared nowhere, because it exists nowhere --');
{
  const hasLocationDep = Object.keys(DEPS).some((d) => /expo-location|geolocation/.test(d));
  const callsLocation = /getCurrentPositionAsync|watchPositionAsync|navigator\.geolocation/.test(ALL);
  const real = hasLocationDep || callsLocation;
  ok(!real, 'ANCHOR: the app still has no way to read a position');
  if (real) {
    ok(!!IP.NSLocationWhenInUseUsageDescription,
      'location IS used now — put the purpose string BACK');
  } else {
    ok(!IP.NSLocationWhenInUseUsageDescription,
      'no NSLocationWhenInUseUsageDescription — a purpose string for an API the '
      + 'binary never calls invites "explain why you need this"');
    ok(!COLLECTED.includes('NSPrivacyCollectedDataTypePreciseLocation'),
      'and precise location is NOT declared as collected — declaring collection '
      + 'of something the app cannot gather is a false statement to Apple and to '
      + 'the user, which is worse than omitting it');
  }
}

console.log('\n-- microphone: same test, same answer --');
{
  const records = /startRecording\s*\(|audio:\s*true/.test(ALL);
  const pluginMic = JSON.stringify(APP_JSON.plugins || [])
    .includes('"enableMicrophonePermission":true');
  const real = records || pluginMic;
  ok(!real, 'ANCHOR: nothing records audio or video, and the camera plugin keeps mic off');
  if (real) ok(!!IP.NSMicrophoneUsageDescription, 'audio IS captured now — restore the string');
  else ok(!IP.NSMicrophoneUsageDescription, 'no NSMicrophoneUsageDescription');
}

console.log('\n-- the three that are real stay --');
{
  // Removing a string the app DOES need is a launch-time crash, not a rejection.
  ok(/react-native-vision-camera|expo-camera/.test(Object.keys(DEPS).join(',')),
    'ANCHOR: a camera module is installed');
  ok(!!IP.NSCameraUsageDescription, 'NSCameraUsageDescription kept');
  ok(/expo-image-picker/.test(Object.keys(DEPS).join(',')),
    'ANCHOR: the photo picker is installed');
  ok(!!IP.NSPhotoLibraryUsageDescription, 'NSPhotoLibraryUsageDescription kept');
  ok(/react-native-nfc-manager/.test(Object.keys(DEPS).join(',')),
    'ANCHOR: nfc-manager is installed');
  ok(!!IP.NFCReaderUsageDescription,
    'NFCReaderUsageDescription kept — this is the capability Apple asked about');
}

console.log('\n-- the Play submit key can never be committed --');
{
  // eas.json points submit.production.android at a service-account JSON. That
  // key can publish to the Play Store on the account holder's behalf, so the
  // one thing that must be true of it is that git refuses to take it.
  const easCfg = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'eas.json'), 'utf8'));
  const droid = (easCfg.submit && easCfg.submit.production
    && easCfg.submit.production.android) || {};
  const keyPath = droid.serviceAccountKeyPath;
  ok(!!keyPath, 'the android submit profile names a service-account key');
  if (keyPath) {
    const ign = fs.readFileSync(path.join(FRONTEND, '.gitignore'), 'utf8');
    const base = keyPath.replace(/^\.\//, '');
    ok(ign.includes(base) || /\*-service-account\.json/.test(ign),
      `${base} is gitignored — a committed Play key is a publish credential`);
    // NOT "absent". The key MUST exist on the machine that runs eas submit —
    // what must never happen is git taking it. Asking git directly is the
    // real check; reading .gitignore only proves a pattern is written down.
    const { execSync } = require('child_process');
    let refused = false;
    try {
      execSync(`git check-ignore -q ${JSON.stringify(base)}`, { cwd: FRONTEND });
      refused = true;
    } catch (e) { refused = false; }
    ok(refused, `${base} is refused by git check-ignore`);
    let tracked = true;
    try {
      execSync(`git ls-files --error-unmatch ${JSON.stringify(base)}`,
        { cwd: FRONTEND, stdio: 'ignore' });
    } catch (e) { tracked = false; }
    ok(!tracked, `${base} is not tracked — a committed Play key is a `
      + 'publish credential in the repo');
  }
  // Draft, not live. The first upload should land in the console for a person
  // to look at, not go straight to testers.
  ok(droid.releaseStatus === 'draft',
    'the first Play upload lands as a DRAFT rather than going live');
  ok(droid.track === 'internal',
    'and on the internal track -- Play blocks production uploads that have not '
    + 'passed review, and internal testing is the lane that accepts a first AAB');
}

console.log('\n-- the rest of the manifest is untouched --');
{
  ok(APP_JSON.ios.privacyManifests.NSPrivacyAccessedAPITypes.length === 4,
    'the four required-reason API declarations are intact');
  ok(APP_JSON.ios.privacyManifests.NSPrivacyTracking === false
    && APP_JSON.ios.privacyManifests.NSPrivacyTrackingDomains.length === 0,
    'no tracking declared, and no tracking domains');
  ok(COLLECTED.length === 7, `seven collected types remain (found ${COLLECTED.length})`);
  ok(IP.ITSAppUsesNonExemptEncryption === false,
    'encryption compliance still answered, or the upload stalls awaiting it');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
