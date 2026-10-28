/**
 * What a phone runs: the WebView viewer, and nothing native that has to be compiled into the app.
 * Run:  node src/viewer/phonePlatform.test.cjs
 */
const fs = require('fs'); const path = require('path'); const babel = require('@babel/core');
let passed = 0; let failed = 0;
function ok(c, l) { if (c) { passed += 1; console.log(`  PASS  ${l}`); } else { failed += 1; console.log(`  FAIL  ${l}`); } }
const ROOT = path.join(__dirname, '..', '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');

function walk(dir, out = []) {
  for (const n of fs.readdirSync(dir)) {
    const p = path.join(dir, n);
    if (fs.statSync(p).isDirectory()) walk(p, out); else out.push(p);
  }
  return out;
}

console.log('nothing native is needed');
const pkg = JSON.parse(read('package.json'));
ok(!Object.keys({ ...pkg.dependencies, ...pkg.devDependencies }).some((k) => /skia/i.test(k)), 'Skia is not a dependency');
const code = walk(path.join(ROOT, 'src')).concat(walk(path.join(ROOT, 'app'))).filter((f) => /\.(js|jsx)$/.test(f) && !/sheetWebViewHtml\.js$/.test(f));
ok(!code.some((f) => /react-native-skia/.test(fs.readFileSync(f, 'utf8'))), 'no source file imports Skia');
ok(!/worklet/.test(read('src/viewer/tileMath.js')), 'the geometry has no Reanimated worklets (it runs in the page, not on a native thread)');
ok(fs.existsSync(path.join(ROOT, 'src/viewer/SheetPane.jsx')) && fs.existsSync(path.join(ROOT, 'src/viewer/SheetPane.web.jsx')) && !fs.existsSync(path.join(ROOT, 'src/viewer/SheetPane.native.jsx')),
  'a phone resolves ./SheetPane to an empty placeholder; only the web has a canvas pane');
ok(fs.existsSync(path.join(ROOT, 'src/viewer/SheetWebViewPane.native.jsx')) && fs.existsSync(path.join(ROOT, 'src/viewer/SheetWebViewPane.jsx')), 'the phone WebView host has a placeholder for the web build');

console.log('the phone platform');
function load(modules) {
  const PLAT = path.join(__dirname, 'sheetPlatform.native.js');
  const src = babel.transformSync(fs.readFileSync(PLAT, 'utf8'), { filename: PLAT, plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')], configFile: false, babelrc: false }).code;
  const mod = { exports: {} }; const asked = [];
  const sh = (n) => { asked.push(n); if (n === 'react-native') return { PixelRatio: { get: () => 2.625 } }; if (n in modules) { if (modules[n] instanceof Error) throw modules[n]; return modules[n]; } throw new Error(`unstubbed ${n}`); };
  new Function('exports', 'module', 'require', src)(mod.exports, mod, sh);
  return { p: mod.exports.platform, asked };
}
let { p, asked } = load({ 'react-native-webview': { WebView() {} } });
ok(p.mode() === 'webview' && p.available() === true, 'with react-native-webview: the WebView viewer');
ok(asked.every((n) => ['react-native', 'react-native-webview'].includes(n)), 'it loads nothing but react-native and react-native-webview');
ok(p.dpr() === 2.625 && p.disk === null && p.decode === null, 'the app keeps no tile decoder or disk store; the page owns them');
({ p } = load({ 'react-native-webview': new Error('no webview') }));
ok(p.mode() === null && p.available() === false, 'without a WebView: the PDF viewer is kept');

console.log(`\n${passed} passed, ${failed} failed`); process.exit(failed ? 1 : 0);
