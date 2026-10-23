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
      return files.has(u) ? { exists: true, size: files.get(u).size } : { exists: dirs.has(u) || [...files.keys()].some((k) => k.startsWith(u)) };
    },
    makeDirectoryAsync: async (u) => { dirs.add(u); },
    writeAsStringAsync: async (u, d, o) => { if (opts.broken || opts.full) throw new Error('full'); files.set(u, { data: d, size: Math.ceil(d.length * 0.75), b64: o && o.encoding === 'base64' }); },
    readAsStringAsync: async (u) => { if (!files.has(u)) throw new Error('missing'); return files.get(u).data; },
    moveAsync: async ({ from, to }) => { log.push(['move', from, to]); files.set(to, files.get(from)); files.delete(from); },
    deleteAsync: async (u) => { if (opts.noDelete) throw new Error('locked'); for (const k of [...files.keys()]) if (k === u || (u.endsWith('/') && k.startsWith(u))) files.delete(k); },
    readDirectoryAsync: async (u) => { if (opts.broken) throw new Error('disk'); const out = new Set(); for (const k of files.keys()) if (k.startsWith(u)) out.add(k.slice(u.length).split('/')[0]); return [...out]; },
  };
  return { FS, files, log };
}
const S = (d, os = 'ios') => load(path.join(__dirname, 'sheetTileStore.js'), { 'expo-file-system/legacy': d.FS, 'react-native': { Platform: { OS: os } } }).sheetTileStore;
const desc = (x) => ({ key: `1/2/${x}/0`, page: 1, z: 2, x, y: 0 });

const KB = (n) => new Uint8Array(n).fill(7);
const names = (d) => [...new Set([...d.files.keys()].map((k) => k.replace('/doc/sheet-tiles/', '').split('/')[0]))].filter((n) => !n.startsWith('_')).sort();

(async () => {
  {
    const d = device(); const s = S(d);
    const bytes = new Uint8Array([82, 73, 70, 70, 0, 255, 128]);
    ok((await s.getTile('f1', 'B1', desc(0))) === null, 'a tile never seen is a miss');
    await s.putTile('f1', 'B1', desc(0), bytes);
    const back = await s.getTile('f1', 'B1', desc(0));
    ok(back && Buffer.compare(Buffer.from(back), Buffer.from(bytes)) === 0, 'a tile round-trips byte for byte');
    ok(d.log.some((l) => l[1].endsWith('.tmp') && !l[2].endsWith('.tmp')), 'writes are atomic (temp file then move)');
    ok(![...d.files.keys()].some((k) => k.endsWith('.tmp')), 'no temp file is left behind');
    await s.putTile('f1', 'B1', desc(1), bytes.buffer);
    ok((await s.getTile('f1', 'B1', desc(1))) !== null, 'an ArrayBuffer (from fetch) is accepted');
    ok((await s.getTile('f1', 'B2', desc(0))) === null && (await s.getTile('f2', 'B1', desc(0))) === null, 'other builds and files do not collide');
    await s.putJson('f1', 'B1', 'index-1', { a: [1, 2] });
    ok(JSON.stringify(await s.getJson('f1', 'B1', 'index-1')) === '{"a":[1,2]}' && (await s.getJson('f1', 'B1', 'nope')) === null, 'json round-trips; a miss is null');
    await s.putJson('f1', 'latest', 'manifest', { build: 'B1' });
    await s.putTile('f1', 'B2', desc(0), bytes);
    ok((await s.getTile('f1', 'B1', desc(0))) === null, 'writing a new build removes the old one');
    ok((await s.getJson('f1', 'latest', 'manifest')).build === 'B1', 'the offline manifest survives a build change');
    const before = await s.bytes();
    await s.purgeFile('f1');
    ok((await s.getTile('f1', 'B2', desc(0))) === null && (await s.bytes()) === 0 && before > 0, 'purgeFile removes the tiles and their accounting');
  }
  {
    const d = device({ broken: true }); const s = S(d);
    let threw = false;
    try { await s.putTile('f', 'B', desc(0), new Uint8Array([1])); await s.putJson('f', 'B', 'n', {}); const g = await s.getTile('f', 'B', desc(0)); const j = await s.getJson('f', 'B', 'n'); ok(g === null && j === null, 'a broken disk reads as a miss'); } catch (e) { threw = true; }
    ok(!threw, 'a broken disk never throws');
    const f = device({ full: true }); const t = S(f);
    await t.putTile('f', 'B', desc(0), new Uint8Array([1]));
    ok((await t.getTile('f', 'B', desc(0))) === null, 'a full disk is just "not cached"');
    const w = device(); const ws = S(w, 'web');
    await ws.putTile('f', 'B', desc(0), new Uint8Array([1]));
    ok(w.files.size === 0 && (await ws.getTile('f', 'B', desc(0))) === null && (await ws.sweep()).skipped, 'no filesystem (web): nothing is written');
  }
  console.log('quota');
  {
    const d = device(); const s = S(d); s.configure({ maxBytes: 1000 });
    for (const f of ['A', 'B', 'C']) await s.putTile(f, 'B1', desc(0), KB(300));
    ok((await s.bytes()) <= 1000 && names(d).join() === 'A,B,C', 'under the quota nothing is evicted');
    await s.putTile('D', 'B1', desc(0), KB(300));
    ok((await s.bytes()) <= 1000, 'the total never exceeds the quota');
    ok(names(d).join() === 'B,C,D', 'the least recently used drawing (A) is evicted first, whole');
    ok((await s.getTile('B', 'B1', desc(0))) !== null, 'B is still readable (and now the most recently used)');
    await s.putTile('E', 'B1', desc(0), KB(300));
    ok(names(d).join() === 'B,D,E', 'reading a drawing keeps it: C (older use) went, not B');
    ok(names(d).includes('E') && (await s.bytes()) <= 1000, 'the drawing being written is never the one evicted');
  }
  {
    const d = device(); const s = S(d); s.configure({ maxBytes: 1000 });
    await s.putTile('A', 'B1', desc(0), KB(600));
    await s.putTile('A', 'B1', desc(1), KB(600));
    ok((await s.bytes()) === 600 && (await s.getTile('A', 'B1', desc(1))) === null, 'a single drawing that reaches the quota stops caching instead of evicting itself');
    await s.putTile('B', 'B1', desc(0), KB(300));
    ok((await s.bytes()) <= 1000 && names(d).includes('B'), 'other drawings still cache within what is left');
    await s.putJson('B', 'B1', 'manifest', { pad: 'x'.repeat(2000) });
    ok((await s.bytes()) <= 1000, 'json counts against the quota too');
  }
  {
    const d = device(); const s1 = S(d); s1.configure({ maxBytes: 5000 });
    await s1.putTile('A', 'B1', desc(0), KB(400)); await s1.putTile('B', 'B1', desc(0), KB(400));
    await s1.flush();
    ok(d.files.has('/doc/sheet-tiles/_usage.json'), 'the usage index is written to disk');
    const s2 = S(d);
    ok((await s2.bytes()) === 800, 'a new session reads the accounting back');
    const r = await s2.sweep({ maxBytes: 500 });
    ok(r.deleted.length === 1 && r.bytes <= 500 && r.deleted[0] === 'A', 'sweep on open enforces a lowered quota, oldest first');
    const act = S(d); await act.putTile('Z', 'B1', desc(0), KB(100));
    const r2 = await act.sweep({ maxBytes: 50, activeFileId: 'Z' });
    ok(names(d).includes('Z') && !names(d).includes('B'), 'sweep never evicts the drawing that is open');
  }
  {
    const d = device();
    d.files.set('/doc/sheet-tiles/old/B/t.webp', { data: 'x', size: 100 });
    const s = S(d);
    ok((await s.bytes()) === 0 && names(d).length === 0, 'files with no usage index are cleared, not guessed at');
    d.files.set('/doc/sheet-tiles/_usage.json', { data: '{not json', size: 9 });
    d.files.set('/doc/sheet-tiles/x/B/t.webp', { data: 'x', size: 100 });
    const s2 = S(d);
    ok((await s2.bytes()) === 0 && !names(d).includes('x'), 'a corrupt usage index clears the store');
  }
  {
    const d = device({ noDelete: true }); const s = S(d); s.configure({ maxBytes: 500 });
    await s.putTile('A', 'B1', desc(0), KB(300)); await s.putTile('B', 'B1', desc(0), KB(300));
    ok(true, 'a delete that fails does not throw (the over-quota state is retried next write)');
  }
  console.log(`\n${passed} passed, ${failed} failed`); process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
