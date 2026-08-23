/**
 * THE API 36 MIGRATION, GUARDED BY ASSERTIONS RATHER THAN BY MEMORY.
 *
 * Every rule below is INERT TODAY — the tree is SDK 52 and each check passes
 * trivially. They exist to bite during the 52 → 53 → 54 hops, at the moment
 * the mistake is made, instead of surfacing hours later as a native build
 * failure with no obvious cause.
 *
 * The runbook (docs/runbooks/api36-path-a-migration.md) states these as prose.
 * Prose is read once, at the start of an eight-day change, by someone who then
 * runs `npx expo install --fix` forty times.
 *
 * THE ONE THAT MATTERS MOST: SDK 54 pins react-native-reanimated to ~4.1.1,
 * and Reanimated 4 is NEW-ARCHITECTURE-ONLY. Path A runs on legacy arch,
 * because react-native-nfc-manager's New-Arch support exists only in
 * 4.0.0-beta.7 and NFC is load-bearing for worker check-in. So the command the
 * runbook tells you to trust will install a package that cannot run on the
 * architecture the migration deliberately chose — and it will do it silently,
 * every single time --fix is run.
 *
 *   node frontend/src/utils/api36MigrationInvariants.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const PKG = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'package.json'), 'utf8'));
const APP = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'app.json'), 'utf8')).expo;
const DEPS = { ...PKG.dependencies, ...PKG.devDependencies };

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

/** Leading integer of a semver range: "~3.16.1" -> 3, "^54.0.0" -> 54. */
const major = (range) => {
  const m = String(range || '').match(/(\d+)/);
  return m ? parseInt(m[1], 10) : null;
};
/** [major, minor, patch] from a range, for ordered comparisons. */
const parts = (range) => (String(range || '').match(/(\d+)\.(\d+)\.(\d+)/) || [])
  .slice(1).map(Number);
const atLeast = (range, target) => {
  const a = parts(range); const b = parts(target);
  if (a.length !== 3 || b.length !== 3) return false;
  for (let i = 0; i < 3; i += 1) {
    if (a[i] !== b[i]) return a[i] > b[i];
  }
  return true;
};

const buildProps = (APP.plugins || []).find(
  (p) => Array.isArray(p) && p[0] === 'expo-build-properties',
);
const ANDROID = (buildProps && buildProps[1] && buildProps[1].android) || {};
const TARGET_SDK = ANDROID.targetSdkVersion;
const RN = DEPS['react-native'];
const NEW_ARCH = APP.newArchEnabled === true;

console.log(`\n-- where the tree actually is: SDK ${major(DEPS.expo)}, RN ${RN}, `
  + `targetSdk ${TARGET_SDK}, newArch ${NEW_ARCH} --`);

console.log('\n-- reanimated 4 can never appear on legacy architecture --');
{
  // THE TRAP. Not "prefer 3.x": reanimated 4 CANNOT RUN with
  // newArchEnabled: false. If --fix installs 4.x while the migration has
  // flipped the arch off, the build fails somewhere unrelated-looking.
  const rea = DEPS['react-native-reanimated'];
  ok(!!rea, 'ANCHOR: reanimated is installed');
  if (!NEW_ARCH) {
    ok(major(rea) === 3,
      `reanimated must stay 3.x on legacy arch — found ${rea}. `
      + 'SDK 54 pins ~4.1.1 and v4 is New-Architecture-ONLY; `expo install '
      + '--fix` will install it every time unless the pin is re-asserted.');
  } else {
    ok(true, `New Arch is still on, so reanimated ${rea} is unconstrained here`);
  }

  // 3.16.x does NOT support RN 0.81. The 3.x line splits: keep 3.16 on RN
  // 0.76, and the only 3.x that works on 0.81 is 3.19.x. Getting this wrong
  // gives a green install and a broken native build.
  if (atLeast(RN, '0.81.0')) {
    ok(atLeast(rea, '3.19.0'),
      `RN is ${RN}, so reanimated must be >= 3.19 — found ${rea}. `
      + '3.16.x does not support RN 0.81.');
  } else {
    ok(true, `RN ${RN} predates 0.81, so the 3.19 floor does not apply yet`);
  }
}

console.log('\n-- NFC is load-bearing, and its version is why arch is legacy --');
{
  const nfc = DEPS['react-native-nfc-manager'];
  ok(!!nfc, 'ANCHOR: nfc-manager is installed');
  ok(major(nfc) === 3,
    `nfc-manager must stay on the stable 3.x line — found ${nfc}. `
    + 'New-Arch support exists ONLY in 4.0.0-beta.7, and the Activity/intent '
    + 'fix foreground dispatch needs is beta-only. NFC programs the gate tags; '
    + 'a beta is not shippable.');
  if (atLeast(RN, '0.81.0')) {
    ok(atLeast(nfc, '3.17.2'),
      `RN is ${RN}, so nfc-manager must be >= 3.17.2 — found ${nfc}.`);
  } else {
    ok(true, `RN ${RN} predates 0.81, so the 3.17.2 floor does not apply yet`);
  }
}

console.log('\n-- the architecture flip and targetSdk move together --');
{
  // Path A's whole shape: targetSdk 36 requires SDK 54 requires RN 0.81, and
  // nfc-manager forces legacy arch there. Arriving at 36 with New Arch still
  // on means the flip was forgotten, and nfc-manager 3.x will not work.
  if (TARGET_SDK >= 36) {
    ok(!NEW_ARCH,
      'targetSdk 36 is Path A, which runs LEGACY arch — newArchEnabled must '
      + 'be false. nfc-manager 3.x has no New-Arch support.');
    ok(major(DEPS.expo) >= 54,
      `targetSdk 36 needs SDK 54+ — found expo ${DEPS.expo}. `
      + 'SDK 52 / RN 0.76 cannot build against 36.');
  } else {
    ok(TARGET_SDK === 35,
      `targetSdk is ${TARGET_SDK}; Play blocks new uploads below 36 from `
      + '2026-10-31, so this is the thing the migration exists to change');
    ok(true, 'the arch flip is not yet due');
  }
}

console.log('\n-- vision-camera needs no patch, and must not acquire one --');
{
  const vc = DEPS['react-native-vision-camera'];
  ok(atLeast(vc, '4.7.2'),
    `vision-camera must be >= 4.7.2 — found ${vc}. The RN 0.81 Android break `
    + '(MapBuilder converted to Kotlin, build() returning an immutable Map) '
    + 'was fixed in 4.7.2 and 4.7.3 carries it.');
  // NARROWED, not deleted. This forbade a `patches/` directory OUTRIGHT, which
  // was the right instinct aimed at the wrong target: the thing that must never
  // come back is a VISION-CAMERA patch, because 4.7.2 already carries the RN
  // 0.81 fix upstream and re-patching it would re-break what is already fixed.
  //
  // A blanket ban also forbids patches that are the only available fix. The
  // case that proved it: nfc-manager 3.17.2 AND 4.0.0-beta.7 both call the
  // untyped `intent.getParcelableExtra(NfcAdapter.EXTRA_TAG)`, deprecated since
  // API 33, which returns null on newer Android — so `parseNfcIntent` bails and
  // no tag ever reaches JS. There is no alternative library (`expo-nfc` is a
  // 0.0.0 placeholder from 2022) and no upstream fix in either release, so a
  // one-line local patch is the fix rather than a workaround.
  const patchDir = path.join(FRONTEND, 'patches');
  const patches = fs.existsSync(patchDir) ? fs.readdirSync(patchDir) : [];
  const camPatch = patches.filter((f) => /vision-camera/i.test(f));
  ok(camPatch.length === 0,
    `NO vision-camera patch — 4.7.2 already contains the RN 0.81 Android fix `
    + `(MapBuilder to Kotlin, immutable Map), verified by tarball diff. A patch `
    + `would re-break it. Found: ${JSON.stringify(camPatch)}`);

  // Every patch that DOES exist must actually apply, or the build silently
  // ships unpatched code. `postinstall` runs patch-package, and EAS Build runs
  // `npm ci`, so a stale patch fails there rather than here.
  if (patches.length > 0) {
    const PKG = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'package.json'), 'utf8'));
    ok(PKG.scripts && PKG.scripts.postinstall === 'patch-package',
      'patches/ exists, so postinstall must run patch-package — EAS runs '
      + '`npm ci`, and without the hook the cloud build gets unpatched sources '
      + 'while the local one looks fine');
    ok(!!(PKG.devDependencies && PKG.devDependencies['patch-package']),
      'and patch-package is a devDependency rather than assumed present');
    // The filename encodes the version it was cut against. If the dependency
    // moves, patch-package refuses to apply and the build fails - which is
    // correct, but the name should still match what is installed.
    for (const f of patches) {
      const m = f.match(/^(.+)\+(\d+\.\d+\.\d+.*)\.patch$/);
      if (!m) continue;
      const [, name, ver] = m;
      const installed = (PKG.dependencies || {})[name] || (PKG.devDependencies || {})[name];
      ok(!installed || installed.includes(ver),
        `${f} targets ${ver} and package.json pins ${installed} — a patch cut `
        + 'against a different version will not apply');
    }
  }
}

console.log('\n-- async-storage 2.x is the ceiling, not a floor --');
{
  const as = DEPS['@react-native-async-storage/async-storage'];
  ok(major(as) <= 2,
    `async-storage must not reach 3.x — found ${as}. 2.2.0 is a verified `
    + 'near-no-op (the Android SQLite files are byte-identical, so on-device '
    + 'drafts survive); 3.x has real breaking changes and this app stores '
    + 'signed compliance drafts in it.');
}

console.log('\n-- the dead weight stays dead --');
{
  for (const gone of ['react-native-quick-crypto', '@nozbe/watermelondb',
    '@babel/plugin-proposal-decorators', '@babel/plugin-proposal-class-properties']) {
    ok(!DEPS[gone], `${gone} is not back — removed in API 36 phase 0`);
  }
  // Comments STRIPPED first: babel.config.js explains in prose why the two
  // plugin-proposal-* entries were removed, and a naive grep matches that
  // explanation and fails on the note describing the fix.
  const babel = fs.readFileSync(path.join(FRONTEND, 'babel.config.js'), 'utf8')
    .replace(new RegExp('//.*$', 'gm'), '')      // line comments
    .replace(new RegExp('\\*[\s\S]*?\\*/', 'g'), ''); // block comments
  ok(!/plugin-proposal-/.test(babel),
    'and babel.config.js references neither — class-properties was never in '
    + 'devDependencies and resolved transitively, which babel-preset-expo@54 '
    + 'stops doing');
}

console.log('\n-- expo-file-system: the import path moves with the SDK --');
{
  // In SDK 54 the NEW api takes the bare specifier and the classic one moves
  // to `expo-file-system/legacy`. Rewriting early breaks SDK 52; rewriting
  // late breaks SDK 54. So the correct path is a function of the SDK.
  const walk = (dir, out = []) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== 'node_modules') walk(p, out); }
      else if (/\.(js|jsx)$/.test(e.name)) out.push(p);
    }
    return out;
  };
  const src = [...walk(path.join(FRONTEND, 'app')), ...walk(path.join(FRONTEND, 'src'))]
    .map((p) => fs.readFileSync(p, 'utf8')).join('\n');
  const classic = (src.match(/['"]expo-file-system['"]/g) || []).length;
  const legacy = (src.match(/['"]expo-file-system\/legacy['"]/g) || []).length;
  ok(classic + legacy > 0, 'ANCHOR: expo-file-system is imported somewhere');
  if (major(DEPS.expo) >= 54) {
    ok(classic === 0,
      `SDK 54 moved the classic API to expo-file-system/legacy — ${classic} `
      + 'bare import(s) remain. The bare specifier is now the NEW api.');
  } else {
    ok(legacy === 0,
      `SDK ${major(DEPS.expo)} has no expo-file-system/legacy — ${legacy} `
      + 'import(s) were rewritten too early and will not resolve.');
  }
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
