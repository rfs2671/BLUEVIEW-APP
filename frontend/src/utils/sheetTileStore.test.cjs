/**
 * The tile viewer's offline store: round trips, atomic writes, old builds removed,
 * a broken disk never throws, and the budget sweep keeps what it cannot measure.
 * Run:  node src/utils/sheetTileStore.test.cjs
 */
const fs = require('fs'); const path = require('path'); const babel = require('@babel/core');
let passed = 0; let failed = 0;
function ok(c, l) { if (c) { passed += 1; console.log(`  PASS  ${l}`); } else { failed += 1; console.log(`  FAIL  ${l}`); } }
const cache = {};
function load(file, shims) {
  const abs = path.resolve(file);
  const { code } = babel.transformSync(fs.readFileSync(abs, 'utf8'), { filename: abs, plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')], configFile: false, babelrc: false });
  const mod = { exports: {} };
  const req = (p) => {
    if (shims[p]) return shims[p];
    if (p.startsWith('.')) { const c = [p, `${p}.js`].map((q) => path.resolve(path.dirname(abs), q)).find((q) => fs.existsSync(q) && fs.statSync(q).isFile()); if (!cache[c]) { cache[c] = load(c, shims); } return cache[c]; }
    throw new Error(`unstubbed import ${p}`);
  };
  new Function('exports', 'module', 'require', code)(mod.exports, mod, req);
  return mod.exports;
}
function device(opts = {}) {
  const files = new Map(); const dirs = new Set(); const log = [];
  const FS = {
    documentDirectory: '/doc/', EncodingType: { Base64: 'base64' },
    getInfoAsync: async (u, o) => {
      if (opts.broken) throw new Error('disk');
      if (u.endsWith('/')) { const kids = [...files.keys()].filter((k) => k.startsWith(u)); return { exists: dirs.has(u) || kids.length > 0, size: opts.noDirSize ? undefined : kids.reduce((a, k) => a + files.get(k).size, 0), modificationTime: (opts.mtime || {})[u] || 0 }; }
      return files.has(u) ? { exists: true, size: files.get(u).size } : { exists: false };
    },
    makeDirectoryAsync: async (u) => { dirs.add(u); },
    writeAsStringAsync: async (u, d, o) => { if (opts.broken || opts.full) throw new Error('full'); files.set(u, { data: d, size: Math.ceil(d.length * 0.75), b64: o && o.encoding === 'base64' }); },
    readAsStringAsync: async (u) => files.get(u).data,
    moveAsync: async ({ from, to }) => { log.push(['move', from, to]); files.set(to, files.get(from)); files.delete(from); },
    deleteAsync: async (u) => { for (const k of [...files.keys()]) if (k === u || (u.endsWith('/') && k.startsWith(u))) files.delete(k); },
    readDirectoryAsync: async (u) => { if (opts.broken) throw new Error('disk'); const out = new Set(); for (const k of files.keys()) if (k.startsWith(u)) out.add(k.slice(u.length).split('/')[0]); return [...out]; },
  };
  return { FS, files, log };
}
const S = (d, os = 'ios') => load(path.join(__dirname, 'sheetTileStore.js'), { 'expo-file-system/legacy': d.FS, 'react-native': { Platform: { OS: os } } }).sheetTileStore;
const desc = (x) => ({ key: `1/2/${x}/0`, page: 1, z: 2, x, y: 0 });

(async () => {
  {
    const d = device(); const s = S(d);
    const bytes = new Uint8Array([82, 73, 70, 70, 0, 255, 128]);
    ok((await s.getTile('f1', 'B1', desc(0))) === null, 'a tile never seen is a miss');
    await s.putTile('f1', 'B1', desc(0), bytes);
    const back = await s.getTile('f1', 'B1', desc(0));
    ok(back && Buffer.compare(Buffer.from(back), Buffer.from(bytes)) === 0, 'a tile round-trips byte for byte');
    ok(d.log.some((l) => l[1].endsWith('.tmp') && !l[2].endsWith('.tmp')), 'writes are atomic (temp file then move)');
    ok(!([...d.files.keys()].some((k) => k.endsWith('.tmp'))), 'no temp file is left behind');
    await s.putTile('f1', 'B1', desc(1), bytes.buffer);
    ok((await s.getTile('f1', 'B1', desc(1))) !== null, 'an ArrayBuffer (from fetch) is accepted');
    ok((await s.getTile('f1', 'B2', desc(0))) === null && (await s.getTile('f2', 'B1', desc(0))) === null, 'other builds and files do not collide');
    await s.putJson('f1', 'B1', 'index-1', { a: [1, 2] });
    ok(JSON.stringify(await s.getJson('f1', 'B1', 'index-1')) === '{"a":[1,2]}' && (await s.getJson('f1', 'B1', 'nope')) === null, 'json round-trips; a miss is null');
    await s.putJson('f1', 'latest', 'manifest', { build: 'B1' });
    await s.putTile('f1', 'B2', desc(0), bytes);
    ok((await s.getTile('f1', 'B1', desc(0))) === null, 'writing a new build removes the old one');
    ok((await s.getJson('f1', 'latest', 'manifest')).build === 'B1', 'the offline manifest survives a build change');
    await s.purgeFile('f1');
    ok((await s.getTile('f1', 'B2', desc(0))) === null, 'purgeFile removes everything of a file');
  }
  {
    const d = device({ broken: true }); const s = S(d);
    let threw = false;
    try { await s.putTile('f', 'B', desc(0), new Uint8Array([1])); await s.putJson('f', 'B', 'n', {}); const g = await s.getTile('f', 'B', desc(0)); const j = await s.getJson('f', 'B', 'n'); ok(g === null && j === null, 'a broken disk reads as a miss'); } catch (e) { threw = true; }
    ok(!threw, 'a broken disk never throws');
    const f = device({ full: true }); const t = S(f);
    await t.putTile('f', 'B', desc(0), new Uint8Array([1]));
    ok((await t.getTile('f', 'B', desc(0))) === null, 'a full disk is just "not cached"');
  }
  {
    const w = device(); const s = S(w, 'web');
    await s.putTile('f', 'B', desc(0), new Uint8Array([1]));
    ok(w.files.size === 0 && (await s.getTile('f', 'B', desc(0))) === null, 'no filesystem (web): nothing is written');
  }
  {
    const mk = () => { const d = device({ mtime: { '/doc/sheet-tiles/old/': 1, '/doc/sheet-tiles/mid/': 2, '/doc/sheet-tiles/new/': 3 } }); for (const n of ['old', 'mid', 'new']) d.files.set(`/doc/sheet-tiles/${n}/B/t.webp`, { data: 'x', size: 100 }); return d; };
    let d = mk(); let s = S(d);
    let r = await s.sweep({ maxBytes: 1000 });
    ok(r.deleted.length === 0, 'under budget: nothing is deleted');
    r = await s.sweep({ maxBytes: 150 });
    ok(r.deleted.join() === 'old,mid' && d.files.size === 1, 'over budget: oldest directories go first, until under');
    d = mk(); s = S(d);
    await s.putTile('old', 'B', desc(0), new Uint8Array([1]));
    r = await s.sweep({ maxBytes: 50 });
    ok(!r.deleted.includes('old'), 'a file used in this session is never swept');
    d = mk(); d.FS.getInfoAsync = (async (orig) => async (u, o) => { const i = await orig(u, o); return u.endsWith('/') ? { ...i, size: undefined } : i; })(d.FS.getInfoAsync);
    s = S(d);
    r = await s.sweep({ maxBytes: 1 });
    ok(r.skipped && d.files.size === 3, 'cannot measure -> deletes nothing');
    const e = device({ broken: true }); r = await S(e).sweep({}); ok(r.skipped, 'unreadable store -> declines');
  }
  console.log(`\n${passed} passed, ${failed} failed`); process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
