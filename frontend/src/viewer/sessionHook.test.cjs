/**
 * useSheetSession and viewerMode, run for real against a tiny hook runner (no DOM):
 * the decision table, the manifest offline fallback, and the follow-up polling that
 * brings in the second compile pass while the drawing is open.
 * Run:  node src/viewer/sessionHook.test.cjs
 */
const fs = require('fs'); const path = require('path'); const babel = require('@babel/core');
let passed = 0; let failed = 0;
function ok(c, l) { if (c) { passed += 1; console.log(`  PASS  ${l}`); } else { failed += 1; console.log(`  FAIL  ${l}`); } }

// ── a minimal hook runner ───────────────────────────────────────────────────
let hooks; let idx; let effects; let deps; let cleanups;
const React = {
  useState(init) { const i = idx; idx += 1; if (!(i in hooks)) hooks[i] = typeof init === 'function' ? init() : init; return [hooks[i], (v) => { hooks[i] = typeof v === 'function' ? v(hooks[i]) : v; }]; },
  useRef(init) { const i = idx; idx += 1; if (!(i in hooks)) hooks[i] = { current: init }; return hooks[i]; },
  useEffect(fn, d) { const i = idx; idx += 1; effects.push({ i, fn, d }); },
};
function mount(hook) {
  hooks = {}; deps = {}; cleanups = {};
  const run = () => {
    idx = 0; effects = [];
    const out = hook();
    for (const e of effects) {
      const changed = !deps[e.i] || e.d.length !== deps[e.i].length || e.d.some((v, k) => v !== deps[e.i][k]);
      if (changed) { if (cleanups[e.i]) cleanups[e.i](); deps[e.i] = e.d; cleanups[e.i] = e.fn() || null; }
    }
    return out;
  };
  return { render: run, unmount() { for (const k of Object.keys(cleanups)) if (cleanups[k]) cleanups[k](); } };
}

const cache = {};
function load(file) {
  const abs = path.resolve(file);
  if (cache[abs]) return cache[abs].exports;
  const { code } = babel.transformSync(fs.readFileSync(abs, 'utf8'), { filename: abs, plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')], configFile: false, babelrc: false });
  const mod = { exports: {} }; cache[abs] = mod;
  const req = (p) => { if (p === 'react') return React; if (p.startsWith('.')) { const c = [p, `${p}.js`].map((q) => path.resolve(path.dirname(abs), q)).find((q) => fs.existsSync(q) && fs.statSync(q).isFile()); return load(c); } return require(p); };
  new Function('exports', 'module', 'require', code)(mod.exports, mod, req);
  return mod.exports;
}
const S = load(path.join(__dirname, 'useSheetSession.js'));
const settle = async (n = 20) => { for (let i = 0; i < n; i += 1) await new Promise((r) => setImmediate(r)); };

// fake timers for the polling loop
const realSet = global.setTimeout; const realClear = global.clearTimeout;
let timers = []; let tid = 0;
global.setTimeout = (fn, ms) => { tid += 1; timers.push({ id: tid, fn, ms }); return tid; };
global.clearTimeout = (id) => { timers = timers.filter((t) => t.id !== id); };
const fire = async () => { const t = timers.shift(); if (t) { await t.fn(); await settle(); } return Boolean(t); };

function lv(z) { const w = 1024 * 2 ** z; const h = Math.round(w * 2 / 3); const cols = Math.ceil(w / 512); const rows = Math.ceil(h / 512); return { z, width: w, height: h, cols, rows, tiles: cols * rows, present: Buffer.from(new Uint8Array(Math.ceil(cols * rows / 8)).fill(255)).toString('base64') }; }
const mf = (status, maxZ) => ({ status, build: 'B1', tile: 512, pages: [{ page: 1, ready: true, width_pt: 2592, height_pt: 1728, z_max: 4, has_index: false, preview: null, levels: Array.from({ length: maxZ + 1 }, (_, z) => lv(z)) }] });

(async () => {
  console.log('viewerMode');
  ok(S.viewerMode({ enabled: false, state: 'idle', failed: false }) === 'legacy', 'flag off: the PDF viewer, at once');
  ok(S.viewerMode({ enabled: true, state: 'idle', failed: false }) === 'pending', 'flag on but the session has not started: PENDING (no PDF download yet)');
  ok(S.viewerMode({ enabled: true, state: 'loading', failed: false }) === 'pending', 'deciding: pending');
  ok(S.viewerMode({ enabled: true, state: 'tiled', failed: false }) === 'tiled', 'tiles ready: tiled');
  ok(S.viewerMode({ enabled: true, state: 'tiled', failed: true }) === 'legacy', 'a render error falls back to the PDF viewer');
  ok(S.viewerMode({ enabled: true, state: 'legacy', failed: false }) === 'legacy', 'no tiles: the PDF viewer');

  console.log('useSheetSession');
  const platform = { available: () => true, decode: async () => ({ image: {}, bytes: 1 }), dispose() {}, disk: null, dpr: () => 1, maxBytes: 1e6 };
  const manifests = [mf('ready', 2)];
  let calls = 0;
  const api = { manifest: async () => { calls += 1; return manifests[Math.min(calls - 1, manifests.length - 1)]; }, tile: async () => new Uint8Array(1), preview: async () => new Uint8Array(1), index: async () => ({}) };
  manifests.push(mf('ready', 2), mf('complete', 4));
  const m = mount(() => S.useSheetSession({ enabled: true, projectId: 'p', fileId: 'f', cacheVersion: 1, platform, api }));
  let s = m.render();
  ok(s.state === 'idle', 'first render: idle');
  s = m.render(); await settle(); s = m.render();
  ok(s.state === 'tiled' && s.controller, 'then tiled once the manifest arrives');
  s.controller.setViewport(1000, 700);
  ok(s.controller.layout.pages[0].levels.length === 3 && timers.length === 1, 'opened on the first pass: levels 0-2, one follow-up scheduled');
  await fire();
  ok(s.controller.layout.pages[0].levels.length === 3 && timers.length === 1, 'still the first pass: keeps asking');
  await fire();
  ok(s.controller.layout.pages[0].levels.length === 5, 'second pass done: levels 3-4 are folded into the open viewer');
  ok(timers.length === 0, 'and it stops asking');
  m.unmount();

  console.log('cleanup');
  calls = 0; manifests.length = 0; manifests.push(mf('ready', 2));
  const m2 = mount(() => S.useSheetSession({ enabled: true, projectId: 'p', fileId: 'f', cacheVersion: 1, platform, api }));
  m2.render(); m2.render(); await settle(); m2.render();
  ok(timers.length === 1, 'a pending follow-up exists');
  m2.unmount();
  ok(timers.length === 0, 'closing the drawing cancels it');

  console.log('offline');
  const store = { m: mf('complete', 4) };
  const offlineApi = { ...api, manifest: async () => { const e = new Error('down'); e.status = 0; throw e; } };
  const disk = { getJson: async () => store.m, putJson: async () => {} };
  const r = await S.resolveManifest({ api: offlineApi, platform: { ...platform, disk }, projectId: 'p', fileId: 'f', cacheVersion: 1, timeoutMs: 50 });
  ok(r.offline === true && r.manifest.status === 'complete', 'no network: the saved manifest opens the drawing');
  const r2 = await S.resolveManifest({ api: { manifest: async () => { const e = new Error('no'); e.status = 403; throw e; } }, platform: { ...platform, disk }, projectId: 'p', fileId: 'f', cacheVersion: 1 });
  ok(r2.manifest === null, 'a 403 is an answer: the saved copy is not used to get around it');

  global.setTimeout = realSet; global.clearTimeout = realClear;
  console.log(`\n${passed} passed, ${failed} failed`); process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
