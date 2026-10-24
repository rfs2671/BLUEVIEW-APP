/**
 * The deep-zoom viewer's engine: geometry, tile selection, the tile cache, the
 * word index and the API client. Runs the REAL modules (babel-transformed) with
 * fakes for fetch / decode. No React, no device.
 * Run:  node src/viewer/viewerEngine.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0;
let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log(`  PASS  ${label}`); } else { failed += 1; console.log(`  FAIL  ${label}`); }
}
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;

const cache = {};
function load(file) {
  const abs = path.resolve(file);
  if (cache[abs]) return cache[abs].exports;
  const { code } = babel.transformSync(fs.readFileSync(abs, 'utf8'), {
    filename: abs, plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')], configFile: false, babelrc: false,
  });
  const mod = { exports: {} };
  cache[abs] = mod;
  const localRequire = (p) => {
    if (p.startsWith('.')) {
      const cand = [p, `${p}.js`].map((q) => path.resolve(path.dirname(abs), q)).find((q) => fs.existsSync(q) && fs.statSync(q).isFile());
      return load(cand);
    }
    return require(p);
  };
  // eslint-disable-next-line no-new-func
  new Function('exports', 'module', 'require', code)(mod.exports, mod, localRequire);
  return mod.exports;
}
const T = load(path.join(__dirname, 'tileMath.js'));
const X = load(path.join(__dirname, 'sheetIndex.js'));
const C = load(path.join(__dirname, 'tileCache.js'));
const A = load(path.join(__dirname, 'sheetApi.js'));
const G = load(path.join(__dirname, 'gestures.js'));

// a manifest like the backend's for a 36x24in sheet (z0..z4)
function level(z, w, h, blankFrom = null) {
  const cols = Math.ceil(w / 512);
  const rows = Math.ceil(h / 512);
  const bytes = new Uint8Array(Math.ceil((cols * rows) / 8));
  let n = 0;
  for (let y = 0; y < rows; y += 1) for (let x = 0; x < cols; x += 1) {
    if (blankFrom && x >= blankFrom) continue;
    const i = y * cols + x; bytes[i >> 3] |= 1 << (i & 7); n += 1;
  }
  return { z, width: w, height: h, cols, rows, tiles: n, present: Buffer.from(bytes).toString('base64') };
}
function sheet(page, blankFrom = null) {
  const levels = [0, 1, 2, 3, 4].map((z) => level(z, 1024 * 2 ** z, Math.round(1024 * 2 ** z * (2 / 3)), z >= 3 ? blankFrom : null));
  return { page, ready: true, width_pt: 2592, height_pt: 1728, z_max: 4, levels, preview: { width: 512, height: 341 }, has_index: true };
}
const VP = { width: 1000, height: 700 };

console.log('base64 / bitmap');
{
  const b = Buffer.from([0b00000101, 0b10000000]).toString('base64');
  const bytes = T.decodeBase64(b);
  ok(bytes.length === 2 && bytes[0] === 5 && bytes[1] === 128, 'decodeBase64 matches Buffer');
  ok(T.bitIsSet(bytes, 4, 0, 0) && !T.bitIsSet(bytes, 4, 1, 0) && T.bitIsSet(bytes, 4, 2, 0), 'bits are LSB-first, row-major');
  ok(T.bitIsSet(bytes, 4, 3, 3) && !T.bitIsSet(bytes, 4, 3, 9), 'bit 15 set; out of range is false');
  for (const n of [1, 2, 3, 4, 5, 17, 100]) {
    const raw = Buffer.from(Array.from({ length: n }, (_, i) => (i * 37) & 255));
    const dec = T.decodeBase64(raw.toString('base64'));
    ok(Buffer.compare(Buffer.from(dec), raw) === 0, `decodeBase64 round-trips ${n} bytes`);
  }
}

console.log('layout & camera');
{
  const lay = T.layoutPages([sheet(1), sheet(2)]);
  ok(lay.pages.length === 2 && near(lay.pages[0].h, 1000 * 1728 / 2592), 'page height follows its aspect');
  ok(near(lay.pages[1].y, lay.pages[0].h + T.PAGE_GAP), 'pages stack with a gap');
  ok(near(lay.height, lay.pages[1].y + lay.pages[1].h), 'layout height covers the last page');
  const fit = T.fitWidthCamera(lay, VP);
  ok(near(fit.zoom, 1) && near(fit.x, 500), 'fit-width zoom = viewport / PAGE_W, centred');
  const lim = T.zoomLimits(lay, VP, 2);
  ok(lim.min <= fit.zoom && lim.max > fit.zoom * 4, 'zoom range runs from fit to deep');
  const p = T.screenToWorld(fit, VP, 321, 123);
  const s = T.worldToScreen(fit, VP, p.x, p.y);
  ok(near(s.x, 321) && near(s.y, 123), 'screen <-> world round-trips');
  const z = T.zoomAt(fit, 3, 800, 200, VP, { min: 0.1, max: 100 });
  const before = T.screenToWorld(fit, VP, 800, 200);
  const after = T.screenToWorld(z, VP, 800, 200);
  ok(near(before.x, after.x, 1e-6) && near(before.y, after.y, 1e-6), 'pinch keeps the point under the fingers fixed');
  ok(T.zoomAt(fit, 1e9, 0, 0, VP, { min: 0.1, max: 5 }).zoom === 5, 'zoom clamps to the limit');
  const cl = T.clampCamera({ x: -99999, y: 99999, zoom: 4 }, lay, VP, lim);
  ok(cl.x > -1000 && cl.y < lay.height + 1000, 'a fling is clamped to the content');
  const small = T.clampCamera({ x: 0, y: 0, zoom: lim.min }, T.layoutPages([sheet(1)]), { width: 1000, height: 5000 }, lim);
  ok(near(small.x, 500), 'content smaller than the view is centred');
  const fr = T.fitRectCamera({ x: 100, y: 100, w: 200, h: 100 }, { width: 400, height: 400 }, 0);
  ok(near(fr.zoom, 2) && near(fr.x, 200) && near(fr.y, 150), 'fitRectCamera frames a rect');
  const mid = T.lerpCamera({ x: 0, y: 0, zoom: 1 }, { x: 10, y: 20, zoom: 4 }, 0.5);
  ok(near(mid.zoom, 2) && near(mid.x, 5), 'zoom interpolates geometrically');
  const w = T.pageToWorld(lay.pages[1], 0.5, 0.5);
  const back = T.worldToPage(lay.pages[1], w.x, w.y);
  ok(near(back.x, 0.5) && near(back.y, 0.5) && T.pageAt(lay, w.x, w.y).page === 2, 'page fractions map to the world and back');
  ok(T.pageAt(lay, 500, lay.pages[0].h + 10) === null, 'the gap between pages belongs to no page');
}

console.log('level and tile selection');
{
  const lay = T.layoutPages([sheet(1)]);
  const pg = lay.pages[0];
  ok(T.levelFor(pg, 1, 1).z === 0, 'fit width on a 1x screen uses level 0');
  ok(T.levelFor(pg, 1, 2).z === 1, 'a 2x screen needs level 1');
  ok(T.levelFor(pg, 1000, 2).z === 4, 'deep zoom stops at the deepest level');
  const cam0 = T.fitWidthCamera(lay, VP);
  const t0 = T.tilesFor(lay, cam0, VP, 1);
  ok(t0.length > 0 && t0.every((t) => t.z === 0), 'cold view requests only level 0');
  ok(t0.length <= 4, `level 0 of a sheet is a handful of tiles (${t0.length})`);
  const deep = { x: 500, y: 333, zoom: 8 };
  const td = T.tilesFor(lay, deep, VP, 1);
  ok(td.length > 0 && td.length < 40 && td.every((t) => t.z >= 3), `deep zoom requests few, deep tiles (${td.length})`);
  ok(td.every((t, i) => i === 0 || td[i - 1].priority <= t.priority), 'tiles come nearest the centre first');
  ok(td.every((t) => T.rectsOverlap(t.rect, { x: deep.x - 1000, y: deep.y - 700, w: 2000, h: 1400 })), 'only tiles near the view');
  ok(new Set(td.map((t) => t.key)).size === td.length, 'no tile is listed twice');
  const blanky = T.layoutPages([sheet(1, 1)]);               // from column 1 on, tiles are blank at z>=3
  const tb = T.tilesFor(blanky, { x: 500, y: 333, zoom: 8 }, VP, 1);
  ok(tb.every((t) => t.z < 3 || t.x < 1), 'blank tiles are never requested');
  const far = T.tilesFor(T.layoutPages([sheet(1), sheet(2)]), { x: 500, y: 100, zoom: 1 }, VP, 1);
  ok(far.every((t) => t.page === 1), 'a page off screen requests nothing');
  const par = T.parentOf({ page: 1, z: 3, x: 5, y: 3 });
  ok(par.z === 2 && par.x === 2 && par.y === 1 && T.parentOf({ page: 1, z: 0, x: 0, y: 0 }) === null, 'parent tile one level up');
  // tile rects tile the page exactly
  const lv = pg.levels[2];
  let area = 0;
  for (let y = 0; y < lv.rows; y += 1) for (let x = 0; x < lv.cols; x += 1) { const r = T.tileWorldRect(pg, lv, x, y); area += r.w * r.h; }
  ok(near(area, pg.w * pg.h, 1e-3), 'tile rects cover the page exactly (edge tiles are partial)');
  const empty = T.layoutPages([{ page: 1, ready: false, levels: [] }]);
  ok(T.tilesFor(empty, { x: 500, y: 375, zoom: 1 }, VP, 1).length === 0, 'a page with no levels yet requests nothing');
}

console.log('tile cache');
(async () => {
  const mkDesc = (n) => ({ key: `1/0/${n}/0`, page: 1, z: 0, x: n, y: 0 });
  const wait = () => new Promise((r) => setImmediate(r));
  {
    const calls = []; let active = 0; let maxActive = 0;
    const cache1 = C.createTileCache({
      fetchTile: async (d, signal) => { calls.push(d.key); active += 1; maxActive = Math.max(maxActive, active); await wait(); active -= 1; return new Uint8Array([1]); },
      decode: async (b, d) => ({ image: { k: d.key }, bytes: 100 }),
      concurrency: 2,
    });
    cache1.want([0, 1, 2, 3, 4].map(mkDesc));
    for (let i = 0; i < 20; i += 1) await wait();
    ok(calls.length === 5 && maxActive <= 2, `concurrency is capped (${maxActive}) and every tile is fetched once`);
    ok(cache1.get('1/0/3/0').k === '1/0/3/0', 'a fetched tile is served from memory');
    cache1.want([0, 1, 2, 3, 4].map(mkDesc));
    for (let i = 0; i < 5; i += 1) await wait();
    ok(calls.length === 5, 'wanting tiles already held fetches nothing');
    cache1.destroy();
  }
  {
    const aborted = [];
    const c = C.createTileCache({
      fetchTile: (d, signal) => new Promise((res, rej) => { signal.addEventListener('abort', () => { aborted.push(d.key); rej(new Error('abort')); }); }),
      decode: async () => ({ image: {}, bytes: 1 }), concurrency: 3,
    });
    c.want([0, 1, 2].map(mkDesc));
    await wait();
    c.want([2, 7].map(mkDesc));
    await wait();
    ok(aborted.sort().join() === '1/0/0/0,1/0/1/0', 'requests no longer wanted are aborted');
    c.destroy();
  }
  {
    const disposed = [];
    const c = C.createTileCache({
      fetchTile: async () => new Uint8Array([1]), decode: async (b, d) => ({ image: d.key, bytes: 60 }),
      dispose: (img) => disposed.push(img), maxBytes: 100, concurrency: 1,
    });
    c.want([mkDesc(0)]); for (let i = 0; i < 6; i += 1) await wait();
    c.want([mkDesc(1)]); for (let i = 0; i < 6; i += 1) await wait();
    ok(disposed.length === 1 && disposed[0] === '1/0/0/0' && !c.has('1/0/0/0') && c.has('1/0/1/0'), 'least recently used tile is evicted over budget');
    c.want([mkDesc(1), mkDesc(2)]); for (let i = 0; i < 8; i += 1) await wait();
    ok(c.has('1/0/1/0') && c.has('1/0/2/0'), 'tiles on screen are never evicted');
    c.destroy();
    ok(disposed.includes('1/0/1/0'), 'destroy frees every image');
  }
  {
    let n = 0; const timers = [];
    const c = C.createTileCache({
      fetchTile: async () => { n += 1; if (n < 3) throw new C.TileFetchError(503); return new Uint8Array([1]); },
      decode: async () => ({ image: 'x', bytes: 1 }), concurrency: 1,
      setTimer: (fn, ms) => { timers.push(fn); return timers.length; }, clearTimer: () => {},
    });
    c.want([mkDesc(0)]); for (let i = 0; i < 6; i += 1) await wait();
    ok(!c.has('1/0/0/0') && timers.length === 1, 'a failed fetch is retried later, not hot-looped');
    timers.shift()(); c.want([mkDesc(0)]); for (let i = 0; i < 6; i += 1) await wait();
    timers.shift()(); for (let i = 0; i < 6; i += 1) await wait();
    ok(c.has('1/0/0/0') && n === 3, 'the retry succeeds');
    c.destroy();
  }
  {
    let n = 0;
    const c = C.createTileCache({
      fetchTile: async () => { n += 1; throw new C.TileFetchError(404); },
      decode: async () => ({ image: 'x', bytes: 1 }), concurrency: 1,
    });
    c.want([mkDesc(0)]); for (let i = 0; i < 6; i += 1) await wait();
    c.want([mkDesc(0)]); for (let i = 0; i < 6; i += 1) await wait();
    ok(n === 1 && c.isMissing('1/0/0/0'), 'a 404 is final: not asked again');
    c.destroy();
  }
  {
    const store = new Map(); let net = 0;
    const disk = { get: async (d) => store.get(d.key) || null, put: async (d, b) => { store.set(d.key, b); } };
    const mk = () => C.createTileCache({ fetchTile: async () => { net += 1; return new Uint8Array([9]); }, decode: async (b, d) => ({ image: d.key, bytes: 1 }), disk });
    const a = mk(); a.want([mkDesc(0)]); for (let i = 0; i < 8; i += 1) await wait(); a.destroy();
    const b = mk(); b.want([mkDesc(0)]); for (let i = 0; i < 8; i += 1) await wait();
    ok(net === 1 && b.has('1/0/0/0') && store.size === 1, 'a tile seen once comes from disk the next time');
    b.destroy();
  }
  {
    const throwing = { get: async () => { throw new Error('disk gone'); }, put: async () => { throw new Error('full'); } };
    const c = C.createTileCache({ fetchTile: async () => new Uint8Array([1]), decode: async () => ({ image: 'x', bytes: 1 }), disk: throwing });
    c.want([mkDesc(0)]); for (let i = 0; i < 8; i += 1) await wait();
    ok(c.has('1/0/0/0'), 'a broken disk cache does not break viewing');
    c.destroy();
  }

  console.log('sheet index search');
  {
    const w = (text, x, line) => ({ text, bbox: [x, 0.1 * line, x + 0.05, 0.1 * line + 0.02], line });
    const idx = new Map([
      [1, { words: [w('SEE', 0.1, 1), w('DETAIL', 0.2, 1), w('3/A-402', 0.3, 1), w('WALL', 0.1, 2), w('TYPE', 0.2, 2), w('A', 0.3, 2)] }],
      [2, { words: [w('A-402', 0.1, 1), w('wall', 0.2, 1), w('TYPE', 0.1, 2), w('B', 0.2, 2)] }],
    ]);
    ok(X.norm('A-402') === 'a402' && X.norm(' a 402 ') === 'a402', 'norm drops case and punctuation');
    ok(X.searchIndexes(idx, 'a402').length === 2, 'sheet numbers match however they are typed');
    ok(X.searchIndexes(idx, '402').length === 2, 'a fragment matches inside a word');
    const phrase = X.searchIndexes(idx, 'wall type');
    ok(phrase.map((m) => m.page).join() === '1', 'a phrase must be consecutive words of one line (page 2 breaks across lines)');
    ok(phrase[0].boxes.length === 2 && phrase[0].bbox[0] === 0.1 && phrase[0].bbox[2] > 0.2, 'a phrase box is the union of its words');
    const spaced = new Map([[1, { words: ['B', 'U', 'L', 'K', 'H', 'EA', 'D', '93'].map((t, i) => ({ text: t, bbox: [0.1 + i * 0.03, 0.2, 0.12 + i * 0.03, 0.22], line: 7 })) }]]);
    const sp = X.searchIndexes(spaced, 'bulkhead');
    ok(sp.length === 1 && sp[0].boxes.length === 7 && sp[0].bbox[0] === 0.1, 'tracked-out CAD letters ("B U L K H EA D") are found as one word');
    ok(X.searchIndexes(new Map([[1, { words: [{ text: 'A', bbox: [0.1, 0.1, 0.12, 0.12], line: 1 }, { text: '402', bbox: [0.13, 0.1, 0.2, 0.12], line: 1 }] }]]), 'a-402').length === 1, 'a sheet number split by a space is still found');
    ok(X.searchIndexes(idx, 'zzz').length === 0 && X.searchIndexes(idx, '   ').length === 0 && X.searchIndexes(idx, '--').length === 0, 'nothing / blank / punctuation-only finds nothing');
    ok(X.searchIndexes(idx, 'type')[0].page === 1 && X.searchIndexes(idx, 'type')[1].page === 2, 'results are in page order');
    ok(X.stepIndex(0, 3, -1) === 2 && X.stepIndex(2, 3, 1) === 0 && X.stepIndex(0, 0, 1) === 0, 'stepping wraps');
    ok(X.matchLabel(0, 0, 'abc') === 'No matches' && X.matchLabel(5, 1, 'abc') === '2 of 5' && X.matchLabel(5, 1, '') === '', 'match label');
    const big = new Map([[1, { words: Array.from({ length: 9000 }, (_, i) => w('door', 0.1, i)) }]]);
    ok(X.searchIndexes(big, 'door').length === 5000, 'a runaway search is capped');
    const ix = { callouts: [
      { label: 'outer', bbox: [0.1, 0.1, 0.5, 0.5], target: null },
      { label: 'inner', bbox: [0.2, 0.2, 0.3, 0.3], target: { file_id: 'f', page: 2, sheet: 'A-402', crop: [0.1, 0.1, 0.4, 0.4], crop_exact: false } },
    ] };
    ok(X.hitCallout(ix, 0.25, 0.25).label === 'inner' && X.hitCallout(ix, 0.4, 0.4).label === 'outer' && X.hitCallout(ix, 0.9, 0.9) === null, 'a tap hits the innermost callout');
    ok(X.hitCallout(ix, 0.3005, 0.25).label === 'inner', 'a finger is forgiven a hair outside');
    const pb = X.portalBox(ix.callouts[1]);
    ok(pb.page === 2 && pb.exact === false && pb.box.length === 4, 'portal box carries "approximate"');
    ok(X.portalBox(ix.callouts[0]) === null && X.portalBox(null) === null, 'an unresolved callout has no portal');
  }

  console.log('gestures');
  {
    const a = G.pinchState({ x: 0, y: 0 }, { x: 100, y: 0 });
    const b = G.pinchState({ x: 0, y: 0 }, { x: 200, y: 0 });
    const d = G.pinchDelta(a, b);
    ok(d.factor === 2 && d.cx === 100 && d.dx === 50, 'pinch: spreading fingers doubles the zoom and reports the focal travel');
    ok(G.pinchState({ x: 5, y: 5 }, { x: 5, y: 5 }).dist === 1, 'two touches on one point never divide by zero');
    ok(G.isTap({ x: 10, y: 10, t: 0 }, { x: 13, y: 12 }, 200) && !G.isTap({ x: 10, y: 10, t: 0 }, { x: 40, y: 10 }, 100) && !G.isTap({ x: 0, y: 0, t: 0 }, { x: 0, y: 0 }, 900), 'a tap is short and nearly still');
    const v = G.releaseVelocity([{ x: 0, y: 0, t: 0 }, { x: 30, y: 0, t: 30 }, { x: 60, y: 0, t: 60 }], 70);
    ok(Math.abs(v.vx - 1) < 1e-9 && v.vy === 0, 'release velocity is px per ms over the last moments');
    ok(G.releaseVelocity([{ x: 0, y: 0, t: 0 }, { x: 60, y: 0, t: 60 }], 5000).vx === 0, 'a drag that paused before release does not fling');
    let vel = { vx: 2, vy: 0 }; let dist = 0; let n = 0;
    for (; n < 2000; n += 1) { const st = G.inertiaStep(vel, 16); dist += st.dx; vel = { vx: st.vx, vy: st.vy }; if (!st.moving) break; }
    ok(n < 2000 && dist > 100 && dist < 2000, `a fling coasts to a stop (${Math.round(dist)}px in ${n} frames)`);
    ok(G.wheelAction({ deltaX: 0, deltaY: 100, deltaMode: 0, ctrlKey: false }).type === 'pan' && G.wheelAction({ deltaX: 0, deltaY: 100, deltaMode: 0, ctrlKey: false }).dy === -100, 'wheel scrolls (content moves against the wheel)');
    const zi = G.wheelAction({ deltaX: 0, deltaY: -100, deltaMode: 0, ctrlKey: true });
    ok(zi.type === 'zoom' && zi.factor > 1 && G.wheelAction({ deltaX: 0, deltaY: 100, deltaMode: 0, metaKey: true }).factor < 1, 'ctrl/cmd + wheel (trackpad pinch) zooms');
    ok(G.doubleTapTarget(1, 1).factor === G.DOUBLE_TAP_ZOOM && G.doubleTapTarget(5, 1).fit === true, 'double tap zooms in, or returns to fit when already in');
  }

  console.log('pointer tracker');
  {
    {
      const tr = G.createPointerTracker();
      tr.down(1, { x: 100, y: 100 }, 0); tr.down(2, { x: 200, y: 100 }, 5);
      const pz = tr.move(2, { x: 300, y: 100 }, 20);
      ok(pz.type === 'pinch' && pz.factor === 2, 'tracker: two fingers pinch');
      ok(tr.up(1, { x: 100, y: 100 }, 40).type === 'none', 'tracker: lifting one finger of a pinch is not a tap');
      let threw = false; let pan = null;
      try { pan = tr.move(2, { x: 310, y: 120 }, 60); } catch (e) { threw = true; }
      ok(!threw && pan && pan.type === 'pan' && pan.dx === 10 && pan.dy === 20, 'tracker: the remaining finger keeps panning (no TypeError)');
      ok(tr.up(2, { x: 310, y: 120 }, 80).type !== 'tap', 'tracker: and its release is never a tap');
      ok(tr.move(2, { x: 1, y: 1 }, 90) === null && tr.move(9, { x: 1, y: 1 }, 90) === null, 'tracker: moves from a finger that is not down are ignored');
      const t2 = G.createPointerTracker();
      t2.down(1, { x: 10, y: 10 }, 0);
      const tap = t2.up(1, { x: 11, y: 10 }, 100);
      ok(tap.type === 'tap' && tap.x === 11, 'tracker: a short still press is a tap');
      const t3 = G.createPointerTracker();
      t3.down(1, { x: 0, y: 0 }, 0); t3.move(1, { x: 40, y: 0 }, 20); t3.move(1, { x: 80, y: 0 }, 40);
      const fl = t3.up(1, { x: 80, y: 0 }, 45);
      ok(fl.type === 'fling' && fl.v.vx > 1, 'tracker: a quick drag release flings');
      t3.down(5, { x: 0, y: 0 }, 1000); ok(t3.up(5, { x: 0, y: 0 }, 1900).type === 'none', 'tracker: a long press is neither tap nor fling');
    }
  }

  console.log('api client');
  {
    const seen = [];
    const fakeFetch = async (url, init) => { seen.push({ url, init }); return { ok: !String(url).includes('bad'), status: String(url).includes('bad') ? 404 : 200, json: async () => ({ status: 'ready', pages: [] }), arrayBuffer: async () => new ArrayBuffer(3) }; };
    const api = A.createSheetApi({ apiBase: 'https://api.x/', getToken: async () => 'TKN', fetchImpl: fakeFetch });
    await api.manifest('p1', 'f 1');
    ok(seen[0].url === 'https://api.x/api/projects/p1/files/f%201/sheets', 'manifest url');
    ok(seen[0].init.headers.Authorization === 'Bearer TKN', 'token goes in the Authorization header');
    await api.tile('p1', 'f1', 'B1', { page: 2, z: 3, x: 4, y: 5 }, new AbortController().signal);
    ok(seen[1].url === 'https://api.x/api/projects/p1/files/f1/sheets/2/tiles/3/4/5?b=B1', 'tile url carries the build');
    ok(seen.every((s) => !/token=/i.test(s.url)), 'no token is ever put in a url');
    let err = null;
    try { await api.preview('p1', 'bad', 'B', 1); } catch (e) { err = e; }
    ok(err && err.status === 404 && err.name === 'TileFetchError', 'a failed request throws a TileFetchError with the status');
    const anon = A.createSheetApi({ apiBase: 'https://api.x', getToken: async () => null, fetchImpl: fakeFetch });
    let e2 = null; try { await anon.manifest('p', 'f'); } catch (e) { e2 = e; }
    ok(e2 && e2.status === 401 && seen.length === 3, 'no token: refuses locally, sends nothing');
    ok(A.manifestUsable({ status: 'ready', pages: [{ ready: true }] }) && !A.manifestUsable({ status: 'compiling', pages: [{ ready: true }] })
      && !A.manifestUsable({ status: 'ready', pages: [{ ready: false }] }) && !A.manifestUsable(null), 'only a finished first pass switches the viewer');
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
