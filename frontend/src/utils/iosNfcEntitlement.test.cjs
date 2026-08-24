/**
 * The iOS NFC entitlement Apple will actually accept.
 *
 *   ERROR ITMS-90778: Invalid entitlement for core nfc framework. The sdk
 *   version '26.0' and min OS version '15.1' are not compatible for the
 *   entitlement 'com.apple.developer.nfc.readersession.formats' because
 *   'NDEF is disallowed'.
 *
 * Under the iOS 26 SDK Apple refuses the VALUE `NDEF`, replaced by `TAG`, which
 * is a superset. The error's wording about "min OS version" is misleading —
 * this repo already tried deployment targets 16.0 and 17.0 in two separate
 * commits (23a1fbe, 8d1654e) and got the identical rejection each time.
 * Climbing the OS floor is the wrong knob.
 *
 * The entitlement is NOT declared in app.json. nfc-manager's config plugin
 * writes it and DEFAULTS TO ['NDEF', 'TAG'], so the only lever is
 * `includeNdefEntitlement: false` in the plugin's props.
 *
 * This test EXECUTES THE REAL PLUGIN rather than asserting on the prop, because
 * the prop is only an input — what gets rejected is the array the plugin emits,
 * and the plugin's default could change under us.
 *
 *   node frontend/src/utils/iosNfcEntitlement.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const APP = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'app.json'), 'utf8')).expo;
const HELPER = fs.readFileSync(
  path.join(FRONTEND, 'src', 'utils', 'nfcHelper.js'), 'utf8');

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

const KEY = 'com.apple.developer.nfc.readersession.formats';

(async () => {
  console.log('\n-- what the plugin actually emits --');
  {
    const withNfc = require('react-native-nfc-manager/app.plugin.js');
    const props = APP.plugins.find(
      (p) => Array.isArray(p) && p[0] === 'react-native-nfc-manager')[1];
    let cfg = { name: APP.name, slug: APP.slug, ios: {}, android: {}, mods: {} };
    cfg = withNfc(cfg, props);
    const out = await cfg.mods.ios.entitlements(
      { ...cfg, modResults: {}, modRequest: {}, modRawConfig: cfg });
    const formats = out.modResults[KEY];

    ok(Array.isArray(formats), 'ANCHOR: the plugin emits the formats entitlement');
    ok(formats.includes('TAG'),
      `TAG is present (${JSON.stringify(formats)}) — the superset session, `
      + 'which reaches ISO14443, ISO15693 and FeliCa');
    ok(!formats.includes('NDEF'),
      'NDEF is ABSENT — its presence is the exact ITMS-90778 upload rejection '
      + 'under the iOS 26 SDK');
  }

  console.log('\n-- and the lever that produces it is set --');
  {
    const props = APP.plugins.find(
      (p) => Array.isArray(p) && p[0] === 'react-native-nfc-manager')[1];
    ok(props.includeNdefEntitlement === false,
      'includeNdefEntitlement: false — the plugin DEFAULTS to [NDEF, TAG], so '
      + 'omitting this is what got the binary refused');
  }

  console.log('\n-- iOS asks for Ndef alone, and is not pinned to a tag family --');
  {
    // requestTechnology opens an NFCTagReaderSession polling ISO14443 AND
    // ISO15693, and the detect handler treats "Ndef" as a special case that
    // connects to whatever tag appears.
    ok(/Platform\.OS === 'ios'/.test(HELPER),
      'the write techs are branched by platform');
    ok(/\? \[NfcTech\.Ndef\]/.test(HELPER),
      'iOS requests Ndef alone');

    // THE THING THAT MUST NOT COME BACK. The 588 Thomas tag type is
    // unconfirmed — pre-formatted NTAG213 is ISO14443A, and pinning ISO15693
    // would make exactly those tags unwritable from an iPhone.
    // NfcTech.Iso15693IOS, the CODE form - the comment above the branch in
    // nfcHelper.js explains why it is not used and names it, so a bare
    // name match fails on the prose describing the fix.
    ok(!/NfcTech[.]Iso15693IOS/.test(HELPER),
      'NOT pinned to Iso15693IOS — the tag family at 588 Thomas is '
      + 'unconfirmed, and polling both is the point of the TAG session');

    // Android is device-verified and must not be disturbed by an iOS fix.
    ok(/: \[NfcTech\.NdefFormatable, NfcTech\.Ndef\]/.test(HELPER),
      'Android keeps [NdefFormatable, Ndef] — verified on device against a '
      + 'blank NfcV tag, and a virgin tag is NdefFormatable, not Ndef');
  }

  console.log('\n-- the runtime version does not move --');
  {
    // runtimeVersion.policy is appVersion, so the RV is expo.version. A
    // buildNumber change is invisible to it, and no device goes stale.
    ok(APP.runtimeVersion.policy === 'appVersion',
      'ANCHOR: the RV is derived from expo.version');
    ok(APP.version === '1.3.0', `expo.version unchanged at ${APP.version}`);
    ok(APP.ios.buildNumber === '2', 'iOS buildNumber 2 — build 1 is spent');
    ok(APP.android.versionCode === 1030001,
      'Android versionCode untouched — this is an iOS-only change and the '
      + 'Android submission already went through');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASSED');
})();
