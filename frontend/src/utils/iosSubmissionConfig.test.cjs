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
  ok(APP_JSON.version === '1.2.0', `expo.version is 1.2.0 (found ${APP_JSON.version})`);
  ok(APP_JSON.runtimeVersion?.policy === 'appVersion',
    'and the RV policy still derives the runtime from it, so the lane moves with the build');
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
