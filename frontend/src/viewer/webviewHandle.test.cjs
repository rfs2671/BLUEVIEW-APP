/**
 * The WebView-hosted viewer's contract: the app's handle, the page's message handlers,
 * and the generated page, which must match its sources. Run:  node src/viewer/webviewHandle.test.cjs
 */
const fs = require('fs'); const path = require('path'); const babel = require('@babel/core'); const { execFileSync } = require('child_process');
let passed = 0; let failed = 0;
function ok(c, l) { if (c) { passed += 1; console.log(`  PASS  ${l}`); } else { failed += 1; console.log(`  FAIL  ${l}`); } }
const ROOT = path.join(__dirname, '..', '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
function load(file) {
  const abs = path.resolve(file);
  const { code } = babel.transformSync(fs.readFileSync(abs, 'utf8'), { filename: abs, plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')], configFile: false, babelrc: false });
  const mod = { exports: {} }; new Function('exports', 'module', 'require', code)(mod.exports, mod, require); return mod.exports;
}
const { createWebViewHandle } = load(path.join(__dirname, 'webviewHandle.js'));

console.log('handle');
{
  const h = createWebViewHandle(); const sent = [];
  h.setPins([{ id: 'a', page: 1, x: 0.1, y: 0.2 }]);
  h.attach((m) => sent.push(m));
  h.fit();
  ok(sent.length === 0, 'nothing is posted into a page that has not said it is ready');
  h.setManifest({ build: 'B1', pages: [] });
  h.receive({ type: 'ready' });
  ok(sent.map((m) => m.type).join() === 'pins,manifest', 'on ready the pins and the latest manifest are replayed');
  ok(sent[0].pins[0].id === 'a', 'pins set before the page loaded arrive');
  sent.length = 0;
  h.zoomBy(2); h.goToPage(3); h.stepMatch(-1); h.setPins([]);
  ok(sent.map((m) => m.type).join() === 'zoom,goToPage,step,pins' && sent[0].factor === 2 && sent[1].page === 3 && sent[2].dir === -1, 'commands are posted as messages');
  let changes = 0; const off = h.on('change', () => { changes += 1; });
  h.receive({ type: 'state', total: 5, current: 2, query: 'door', progress: { loaded: 3, total: 4, failed: 0 }, zoom: 1.5 });
  ok(h.searchState.total === 5 && h.searchState.matches.length === 5 && h.searchState.current === 2 && h.searchState.query === 'door', 'search state mirrors the page');
  ok(h.indexProgress.loaded === 3 && changes === 1, 'index progress mirrors the page and listeners hear it');
  h.clearSearch();
  ok(h.searchState.total === 0 && h.searchState.query === '' && changes === 2, 'clearing search resets at once, without waiting for the page');
  off(); h.receive({ type: 'state', total: 1 }); ok(changes === 2, 'an unsubscribed listener hears nothing');
  const taps = []; h.onTap((hit) => taps.push(hit));
  h.receive({ type: 'tap', hit: { type: 'pin', id: 'a' } });
  h.receive({ type: 'tap', hit: { type: 'page', page: 2, x: 0.5, y: 0.5 } });
  h.receive({ type: 'tap', hit: null });
  ok(taps[0].pin.id === 'a' && taps[1].page === 2 && taps[2] === null, 'taps reach the app in the shape SheetViewerPane reads');
  const errs = []; h.onError((m) => errs.push(m)); h.receive({ type: 'error', message: 'boom' }); ok(errs[0] === 'boom', 'page errors reach the app');
  h.receive(null); h.receive('x'); h.receive({ type: 'nope' }); ok(true, 'garbage from the page is ignored');
  h.attach(null); sent.length = 0; h.fit(); ok(sent.length === 0 && h.ready === false, 'after the WebView unmounts nothing is posted, and it must say ready again');
}

console.log('message contract');
{
  const handleSrc = read('src/viewer/webviewHandle.js'); const main = read('src/viewer/webview/main.js');
  const posted = [...handleSrc.matchAll(/post\(\{ type: '(\w+)'/g)].map((m) => m[1]);
  const handled = [...main.matchAll(/^  (\w+)(?::| *\()/gm)].map((m) => m[1]);
  const handlers = main.slice(main.indexOf('const handlers = {'), main.indexOf('window.__sheetRecv ='));
  const names = [...handlers.matchAll(/^  (\w+)[:,]/gm)].map((m) => m[1]);
  for (const t of new Set(posted)) ok(names.includes(t), `the page handles "${t}"`);
  const fromPage = [...main.matchAll(/post\(\{ type: '(\w+)'/g)].map((m) => m[1]);
  const receivable = new Set(['loaded', 'ready', 'state', 'tap', 'error']);
  for (const t of new Set(fromPage)) ok(receivable.has(t), `the app understands "${t}" from the page`);
}

console.log('the generated page');
{
  let up = true; try { execFileSync('node', ['scripts/build-sheet-webview.cjs', '--check'], { cwd: ROOT, stdio: 'pipe' }); } catch (e) { up = false; }
  ok(up, 'webview/sheetWebViewHtml.js matches its sources (node scripts/build-sheet-webview.cjs)');
  const gen = read('src/viewer/webview/sheetWebViewHtml.js');
  const html = JSON.parse(gen.match(/SHEET_WEBVIEW_HTML = (.*);\n/)[1]);
  ok(html.startsWith('<!doctype html>') && html.includes('id="root"') && html.includes('user-scalable=no'), 'a complete HTML document that cannot be pinch-zoomed by the browser');
  ok(!/token=/i.test(html) && !/localStorage|sessionStorage|document\.cookie/.test(html), 'no token in any URL, and no browser storage');
  ok(html.length < 120 * 1024, `small enough to load instantly (${(html.length / 1024).toFixed(0)} KB)`);
  ok((html.match(/<\/script/gi) || []).length === 1, 'the bundle cannot close its own script tag');
  ok(!/\bimport\s+[\w{*]/.test(html.replace(/"[^"\n]*"/g, '')), 'no unresolved ES imports remain');
  const pane = read('src/viewer/SheetWebViewPane.native.jsx');
  ok(/baseUrl: PAGE_ORIGIN/.test(pane) && /app\.levelog\.com/.test(pane), 'the page runs at an origin the API already allows (CORS)');
  ok(/getToken\(\)/.test(pane) && /type: 'init'.*token/.test(pane) && !/uri:.*token/.test(pane), 'the token is handed over in a message, never in the source uri');
  ok(/onRenderProcessGone/.test(pane) && /onContentProcessDidTerminate/.test(pane), 'a killed WebView falls back to the PDF viewer instead of showing a blank');
}

console.log(`\n${passed} passed, ${failed} failed`); process.exit(failed ? 1 : 0);
