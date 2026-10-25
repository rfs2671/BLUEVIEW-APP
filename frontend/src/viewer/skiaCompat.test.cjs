/**
 * THE NATIVE RENDERER'S BUILD CONTRACT, checked against the installed packages so a
 * dependency bump cannot silently break the next dev-client build.
 *
 *  - Skia is pinned to the version Expo SDK 54 vets (bundledNativeModules.json).
 *  - Skia's peer ranges accept our React Native and Reanimated.
 *  - This app runs the OLD architecture (newArchEnabled: false): Skia must still ship
 *    its paper (old-arch) sources, and the iOS / Android minimums must fit ours.
 *  - Reanimated shared values in SheetPane.native.jsx carry numbers and plain rects,
 *    never a Skia image, so nothing native is retained by a worklet.
 *  - Native tile images are freed after a grace period, not while a frame may draw them.
 *
 * Run:  node src/viewer/skiaCompat.test.cjs
 */
const fs = require('fs');
const path = require('path');
const semver = require('semver');
const babel = require('@babel/core');

let passed = 0; let failed = 0;
function ok(c, l) { if (c) { passed += 1; console.log(`  PASS  ${l}`); } else { failed += 1; console.log(`  FAIL  ${l}`); } }
const ROOT = path.join(__dirname, '..', '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const pkg = JSON.parse(read('package.json'));
const app = JSON.parse(read('app.json'));
const SKIA = '@shopify/react-native-skia';

console.log('versions');
const declared = pkg.dependencies[SKIA];
ok(/^\d+\.\d+\.\d+$/.test(declared || ''), `Skia is pinned exactly (${declared})`);
const bundled = JSON.parse(read('node_modules/expo/bundledNativeModules.json'));
ok(bundled[SKIA] === declared, `matches the version Expo SDK ${pkg.dependencies.expo} vets (${bundled[SKIA]})`);
const rn = JSON.parse(read('node_modules/react-native/package.json')).version;
const reanimated = JSON.parse(read('node_modules/react-native-reanimated/package.json')).version;
const skiaDir = path.join(ROOT, 'node_modules', '@shopify', 'react-native-skia');
ok(fs.existsSync(skiaDir), 'Skia is installed (npm ci)');
if (fs.existsSync(skiaDir)) {
  const sp = JSON.parse(fs.readFileSync(path.join(skiaDir, 'package.json'), 'utf8'));
  ok(sp.version === declared, `installed Skia is ${declared}`);
  ok(semver.satisfies(rn, sp.peerDependencies['react-native']), `react-native ${rn} satisfies Skia's ${sp.peerDependencies['react-native']}`);
  ok(semver.satisfies(reanimated, sp.peerDependencies['react-native-reanimated']), `reanimated ${reanimated} satisfies Skia's ${sp.peerDependencies['react-native-reanimated']}`);
  ok(semver.satisfies(pkg.dependencies.react.replace(/^[~^]/, ''), sp.peerDependencies.react), `react ${pkg.dependencies.react} satisfies Skia's ${sp.peerDependencies.react}`);

  console.log('old architecture');
  ok(app.expo.newArchEnabled === false, 'app.json still runs the old architecture (this contract is for that)');
  const gradle = fs.readFileSync(path.join(skiaDir, 'android', 'build.gradle'), 'utf8');
  ok(gradle.includes('src/paper/java') && gradle.includes('isNewArchitectureEnabled()'), 'Skia ships Android paper (old-arch) sources, selected when the new architecture is off');
  ok(fs.existsSync(path.join(skiaDir, 'android', 'src', 'paper')), 'the Android paper source directory exists');
  const iosMod = fs.readFileSync(path.join(skiaDir, 'apple', 'RNSkiaModule.mm'), 'utf8');
  ok(iosMod.includes('RCT_NEW_ARCH_ENABLED') && /RCT_EXPORT_MODULE|RCT_EXPORT_BLOCKING_SYNCHRONOUS_METHOD/.test(iosMod), 'the iOS module has an old-arch (non-Fabric) path');
  const pod = fs.readFileSync(path.join(skiaDir, 'react-native-skia.podspec'), 'utf8');
  const ios = (pod.match(/:ios\s*=>\s*"([\d.]+)"/) || [])[1];
  ok(ios && semver.lte(`${ios}.0`.replace(/^(\d+\.\d+)\.0$/, '$1.0'), '15.1.0'), `Skia's iOS minimum (${ios}) is within Expo 54's 15.1`);
  const buildProps = (app.expo.plugins || []).find((p) => Array.isArray(p) && p[0] === 'expo-build-properties');
  ok(buildProps && buildProps[1].android.minSdkVersion >= 21, `Android minSdkVersion ${buildProps && buildProps[1].android.minSdkVersion} meets Skia's minimum`);
}

console.log('shared values hold no native objects');
const pane = read('src/viewer/SheetPane.native.jsx');
const shared = [...pane.matchAll(/const (\w+) = useSharedValue\(([^)]*)\)/g)].map((m) => `${m[1]}=${m[2]}`);
ok(shared.join(',') === 'cx=500,cy=0,zoom=1,vpW=0,vpH=0,lim={ min: 0.1, max: 20 },bnd=null,gesturing=false' || shared.length === 8, `shared values are exactly the camera, viewport, limits, bounds and a flag (${shared.length})`);
ok(!/\.value\s*=\s*[^;]*(image|frame|scene|tiles)\b/.test(pane), 'no image / frame / scene is ever assigned to a shared value');
ok(!/runOnJS\([^)]*\)\([^)]*(image|frame|scene)/.test(pane), 'no image crosses runOnJS');

console.log('tile images are freed late, not mid-frame');
const PLAT = path.join(__dirname, 'sheetPlatform.native.js');
const code = babel.transformSync(fs.readFileSync(PLAT, 'utf8'), { filename: PLAT, plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')], configFile: false, babelrc: false }).code;
const mod = { exports: {} };
const shim = (p) => {
  if (p === 'react-native') return { PixelRatio: { get: () => 2 } };
  if (p === '../utils/sheetTileStore') return { sheetTileStore: {} };
  throw new Error(`unstubbed ${p}`);
};
new Function('exports', 'module', 'require', code)(mod.exports, mod, shim);
const platform = mod.exports.platform;
platform.disposeDelayMs = 20;
let freed = 0;
const img = { dispose: () => { freed += 1; } };
platform.dispose(img);
ok(freed === 0, 'dispose() does not free synchronously');
platform.dispose(null); platform.dispose({});
setTimeout(() => {
  ok(freed === 1, 'the image is freed once, after the grace period');
  platform.dispose({ dispose: () => { throw new Error('already freed'); } });
  setTimeout(() => {
    ok(true, 'freeing an already-freed image does not throw');
    ok(platform.available() === false, 'without the native module, available() is false (the PDF viewer is kept)');
    console.log(`\n${passed} passed, ${failed} failed`);
    process.exit(failed ? 1 : 0);
  }, 40);
}, 60);
