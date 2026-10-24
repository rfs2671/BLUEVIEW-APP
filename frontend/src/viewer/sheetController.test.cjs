/**
 * The controller end to end with a fake API and decoder: cold start, tile
 * selection, fallbacks while a level loads, search, pins, hit-testing, fly-to and
 * the portal's bounds. Run:  node src/viewer/sheetController.test.cjs
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

let passed = 0; let failed = 0;
function ok(cond, label) { if (cond) { passed += 1; console.log(`  PASS  ${label}`); } else { failed += 1; console.log(`  FAIL  ${label}`); } }
const cache = {};
function load(file) {
  const abs = path.resolve(file);
  if (cache[abs]) return cache[abs].exports;
  const { code } = babel.transformSync(fs.readFileSync(abs, 'utf8'), { filename: abs, plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')], configFile: false, babelrc: false });
  const mod = { exports: {} }; cache[abs] = mod;
  const req = (p) => { if (p.startsWith('.')) { const c = [p, `${p}.js`].map((q) => path.resolve(path.dirname(abs), q)).find((q) => fs.existsSync(q) && fs.statSync(q).isFile()); return load(c); } return require(p); };
  new Function('exports', 'module', 'require', code)(mod.exports, mod, req);
  return mod.exports;
}
const K = load(path.join(__dirname, 'sheetController.js'));
const T = load(path.join(__dirname, 'tileMath.js'));
const wait = () => new Promise((r) => setImmediate(r));
const settle = async (n = 30) => { for (let i = 0; i < n; i += 1) await wait(); };

function level(z, w, h) {
  const cols = Math.ceil(w / 512); const rows = Math.ceil(h / 512);
  const bytes = new Uint8Array(Math.ceil((cols * rows) / 8)).fill(255);
  return { z, width: w, height: h, cols, rows, tiles: cols * rows, present: Buffer.from(bytes).toString('base64') };
}
const manifest = {
  status: 'complete', build: 'B1', tile: 512,
  pages: [1, 2].map((page) => ({ page, ready: true, width_pt: 2592, height_pt: 1728, z_max: 4, has_index: true,
    preview: { width: 512, height: 341 }, levels: [0, 1, 2, 3, 4].map((z) => level(z, 1024 * 2 ** z, Math.round(1024 * 2 ** z * 2 / 3))) })),
};
const idx = (page) => ({ page, own_sheet: `A-10${page}`, words: [
  { text: 'DOOR', bbox: [0.1, 0.1, 0.15, 0.12], line: 1 }, { text: 'A-402', bbox: [0.5, 0.5, 0.56, 0.52], line: 2 }],
  callouts: [{ label: '3/A-402', bbox: [0.5, 0.5, 0.56, 0.52], target: { file_id: 'f1', page: 2, sheet: 'A-102', crop: [0.4, 0.4, 0.7, 0.7], crop_exact: false } }] });

let decodes = 0;
function harness(over = {}) {
  const log = { tiles: [], previews: [], indexes: [], disposed: [] };
  const api = {
    tile: async (p, f, b, d, signal) => { log.tiles.push(d.key); await wait(); return new Uint8Array([d.z]); },
    preview: async (p, f, b, page) => { log.previews.push(page); await wait(); return new Uint8Array([9]); },
    index: async (p, f, page, b) => { log.indexes.push(page); await wait(); return idx(page); },
    ...over.api,
  };
  const c = K.createSheetController({
    api, projectId: 'p1', fileId: 'f1', manifest: (over.opts && over.opts.manifest) || manifest, decode: async (bytes, d) => { decodes += 1; return { image: { tag: `${d.key || `p${d.page}`}#${decodes}` }, bytes: 10 }; },
    dispose: (img) => log.disposed.push(img.tag), dpr: 1, ...over.opts,
  });
  return { c, log };
}

(async () => {
  console.log('cold start');
  {
    const { c, log } = harness();
    let changes = 0; c.on('change', () => { changes += 1; });
    c.setViewport(1000, 700);
    ok(c.camera.zoom === 1 && c.camera.x === 500, 'opens fit to width on the first page');
    await settle();
    ok(log.tiles.length > 0 && log.tiles.every((k) => k.split('/')[1] === '0'), `only level 0 tiles at fit (${log.tiles.length})`);
    ok(log.previews.length >= 1 && log.previews.includes(1), 'the page preview is fetched');
    ok(log.indexes.includes(1), 'the visible page index is fetched in the background');
    const f = c.frame();
    ok(f.tiles.length === log.tiles.length && f.complete === true && f.previews.length === 0, 'with every level 0 tile in, the frame is complete and the preview underneath is not painted');
    ok(changes > 0, 'listeners hear about arrivals');
    ok(!c.loading, 'nothing left loading');
    c.zoomAt(8, 500, 350);
    const g = c.frame();
    ok(g.complete === false && g.previews.length >= 1, 'while deeper tiles are still on their way the preview stays underneath');
    c.destroy();
  }
  console.log('zoom, fallbacks');
  {
    const { c, log } = harness();
    c.setViewport(1000, 700); await settle();
    const z0 = c.frame().tiles.length;
    c.zoomAt(8, 500, 350);
    ok(c.camera.zoom > 4, 'zoomed in');
    const fb = c.frame();
    ok(fb.tiles.length >= 1 && fb.tiles.every((t) => t.z === 0), 'while deeper tiles load, the coarse tile covers the screen (no blank flash)');
    ok(c.loading, 'reports it is still loading');
    await settle();
    const deep = c.frame();
    ok(deep.tiles.some((t) => t.z >= 3), 'deep tiles replace the coarse ones');
    ok(deep.tiles.findIndex((t) => t.z >= 3) >= deep.tiles.findIndex((t) => t.z === 0), 'coarse fallback is painted underneath');
    ok(log.tiles.length > z0 && new Set(log.tiles).size === log.tiles.length, 'no tile is fetched twice');
    const before = log.tiles.length;
    c.zoomAt(1 / 8, 500, 350); await settle();
    c.zoomAt(8, 500, 350); await settle();
    ok(log.tiles.length === before + 0 || log.tiles.length <= before + 6, 'zooming back reuses cached tiles');
    c.destroy();
  }
  console.log('pan clamps; fit; fly');
  {
    const { c } = harness();
    c.setViewport(1000, 700);
    c.panBy(-1e7, -1e7);
    ok(c.camera.y < c.layout.height + 500 && c.camera.x < 2000, 'a fling cannot leave the drawing');
    c.fit();
    for (let t = 0; t < 40 && c.tick(Date.now() + t * 20); t += 1);
    ok(Math.abs(c.camera.zoom - 1) < 1e-6 && Math.abs(c.camera.x - 500) < 1e-6, 'fit returns to width-fit after the animation');
    let flown = null;
    c.on('fly', (to) => { flown = to; return true; });
    c.flyTo({ x: 300, y: 300, zoom: 2 });
    ok(flown && Math.abs(flown.zoom - 2) < 1e-9 && c.camera.zoom === 1, 'a native renderer can take over the animation');
    c.destroy();
  }
  console.log('search');
  {
    const { c, log } = harness();
    c.setViewport(1000, 700); await settle();
    const r = await c.search('door');
    ok(log.indexes.includes(2), 'searching loads the indexes of every page');
    ok(r.matches.length === 2 && r.matches[0].page === 1 && r.matches[1].page === 2, 'matches from both pages, in order');
    const rects = c.matchRects();
    ok(rects.length === 2 && rects[0].current && !rects[1].current, 'match rects, the current one marked');
    const m = c.stepMatch(1);
    ok(m.page === 2 && c.searchState.current === 1, 'next match is on page 2');
    ok(c.stepMatch(1).page === 1, 'stepping wraps');
    const before = c.camera;
    c.stepMatch(1);
    for (let t = 0; t < 40 && c.tick(Date.now() + 1000 + t * 20); t += 1);
    ok(c.camera.y > before.y || c.camera.zoom !== before.zoom, 'stepping flies to the match');
    const t0 = Date.now();
    const again = await c.search('a402');
    ok(Date.now() - t0 < 50 && again.matches.length === 2, 'a second search is answered from memory');
    c.clearSearch();
    ok(c.searchState.matches.length === 0 && c.matchRects().length === 0, 'clearing removes highlights');
    ok((await c.search('   ')).matches.length === 0, 'a blank query finds nothing');
    c.destroy();
  }
  console.log('failed index');
  {
    const { c } = harness({ api: { index: async () => { throw new Error('boom'); } } });
    c.setViewport(1000, 700); await settle();
    const r = await c.search('door');
    ok(r.matches.length === 0 && c.indexProgress.failed === 2, 'a page whose index failed is skipped, not fatal');
    c.destroy();
  }
  console.log('pins and hit-testing');
  {
    const { c } = harness();
    c.setViewport(1000, 700); await settle();
    c.setPins([{ id: 'a1', page: 1, x: 0.25, y: 0.5 }]);
    const s = c.pinScreen(c.pins[0]);
    const w = T.pageToWorld(c.layout.pages[0], 0.25, 0.5);
    const expect = T.worldToScreen(c.camera, c.viewport, w.x, w.y);
    ok(Math.abs(s.x - expect.x) < 1e-9 && Math.abs(s.y - expect.y) < 1e-9, 'a pin sits at its page fraction');
    const before = c.pinScreen(c.pins[0]);
    c.zoomAt(4, 800, 300);
    const after = c.pinScreen(c.pins[0]);
    const wb = T.screenToWorld(c.camera, c.viewport, after.x, after.y);
    ok(Math.abs(wb.x - w.x) < 1e-6 && Math.abs(wb.y - w.y) < 1e-6 && (before.x !== after.x), 'a pin stays on its spot of the drawing through a zoom');
    c.fit(); for (let t = 0; t < 40 && c.tick(Date.now() + 5000 + t * 20); t += 1);
    const sp = c.pinScreen(c.pins[0]);
    ok(c.hitTest(sp.x, sp.y - 12).type === 'pin', 'tapping a pin hits the pin');
    const pg = c.layout.pages[0];
    const open = T.worldToScreen(c.camera, c.viewport, pg.x + pg.w * 0.8, pg.y + pg.h * 0.2);
    const h = c.hitTest(open.x, open.y);
    ok(h.type === 'page' && h.page === 1 && Math.abs(h.x - 0.8) < 1e-6 && Math.abs(h.y - 0.2) < 1e-6, 'tapping bare drawing gives the page fraction (to place a pin)');
    const co = T.worldToScreen(c.camera, c.viewport, pg.x + pg.w * 0.53, pg.y + pg.h * 0.51);
    const hc = c.hitTest(co.x, co.y);
    ok(hc.type === 'callout' && hc.callout.label === '3/A-402', 'tapping a callout hits the callout');
    ok(c.calloutRects().length >= 1, 'callout boxes are listed for painting');
    c.destroy();
  }
  console.log('portal: whole sheet, crop only frames');
  {
    const { c } = harness();
    c.setViewport(300, 200); await settle();
    const crop = [0.4, 0.4, 0.7, 0.7];
    c.setBounds(2, [0, 0, 1, 1], 0);
    c.frameBox(2, crop, 0.4);
    const pg = c.layout.pages[1];
    const cw = T.boxToWorld(pg, crop);
    ok(Math.abs(c.camera.x - (cw.x + cw.w / 2)) < 1 && Math.abs(c.camera.y - (cw.y + cw.h / 2)) < 1, 'the first view is centred on the crop');
    const vis = T.visibleWorldRect(c.camera, c.viewport);
    ok(vis.w >= cw.w * 1.79 && vis.h >= cw.h * 1.79, 'the first view shows the crop with a 40% margin on every side');
    ok(vis.x < cw.x && vis.y < cw.y && vis.x + vis.w > cw.x + cw.w && vis.y + vis.h > cw.y + cw.h, 'the crop is inside the view, with room around it');
    // the estimate is wrong: the real detail is outside the crop. The reader can still get there.
    const far = T.boxToWorld(pg, [0.02, 0.02, 0.1, 0.1]);
    c.setCamera({ x: far.x + far.w / 2, y: far.y + far.h / 2, zoom: c.camera.zoom });
    const v2 = T.visibleWorldRect(c.camera, c.viewport);
    ok(v2.x <= far.x && v2.y <= far.y && v2.x + v2.w >= far.x + far.w && v2.y + v2.h >= far.y + far.h, 'the camera can leave the crop: the far corner of the sheet comes into view');
    c.setCamera({ x: far.x + far.w / 2, y: far.y + far.h / 2, zoom: c.limits.max });
    await settle();
    ok(c.frame().tiles.some((t) => t.z >= 3), 'tiles outside the crop load at full depth');
    c.panBy(1e7, 1e7);
    ok(c.camera.x >= pg.x - 1000 && c.camera.y >= pg.y - 1000, 'it stays on the target sheet');
    c.setCamera({ x: 500, y: -1e6, zoom: c.limits.min });
    ok(c.camera.y >= pg.y - 1 || c.camera.y > c.layout.pages[0].y, 'and never wanders into the other pages of the file');
    ok(c.limits.min > 0.1 && c.limits.min <= 300 / 1000 + 1e-9, 'it can zoom out until the whole sheet fits the portal');
    c.destroy();
  }
  console.log('eviction never leaves a freed image on screen');
  {
    const freed = new Set();
    const { c } = harness({ opts: { maxBytes: 25, dispose: (img) => freed.add(img.tag) } });
    c.setViewport(1000, 700); await settle();
    const seen = [];
    for (const [f, sx, sy] of [[6, 300, 200], [2, 800, 500], [0.2, 100, 100], [9, 700, 150], [0.3, 400, 400]]) {
      c.zoomAt(f, sx, sy); await settle();
      const fr = c.frame();
      seen.push(...fr.tiles.map((t) => t.image.tag), ...fr.previews.map((p) => p.image.tag));
      ok(fr.tiles.every((t) => !freed.has(t.image.tag)) && fr.previews.every((p) => !freed.has(p.image.tag)), `frame after zoom x${f} holds no freed image`);
    }
    ok(freed.size > 0, 'a small budget really did evict and free tiles');
    const held = c.frame().tiles.map((t) => t.image.tag);
    c.destroy();
    ok(held.every((tag) => freed.has(tag)), 'destroy frees what was still held');
  }
  console.log('second pass arrives mid-session');
  {
    const first = { ...manifest, status: 'ready', pages: manifest.pages.map((p) => ({ ...p, levels: p.levels.filter((l) => l.z <= 2) })) };
    const { c, log } = harness({ opts: { manifest: first } });
    c.setViewport(1000, 700); await settle();
    const lim0 = c.limits.max;
    c.zoomAt(1000, 500, 350); await settle();
    ok(c.frame().tiles.every((t) => t.z <= 2), 'on the first pass only levels 0-2 can be drawn');
    ok(c.refreshManifest(manifest) === true, 'a manifest with more levels is accepted');
    const camBefore = { ...c.camera };
    await settle();
    ok(c.limits.max > lim0, 'the zoom limit deepens');
    ok(c.frame().tiles.some((t) => t.z >= 3), 'deep tiles are fetched and drawn without reopening');
    ok(c.refreshManifest(manifest) === false, 'the same manifest again changes nothing');
    ok(c.refreshManifest({ ...manifest, build: 'OTHER' }) === false, 'a manifest of another build is ignored');
    ok(Math.abs(c.camera.zoom - camBefore.zoom) < 1e-9, 'the camera is not moved by a refresh');
    c.destroy();
  }
  console.log('keepPortalFramed does not recurse');
  {
    const PF = load(path.join(__dirname, 'portalFrame.js'));
    const { c } = harness();
    c.setViewport(300, 200); await settle();
    let frames = 0; const orig = c.frameBox.bind(c);
    c.frameBox = (...a) => { frames += 1; if (frames > 50) throw new Error('runaway'); return orig(...a); };
    const off = PF.keepPortalFramed(c, { page: 2, box: [0.4, 0.4, 0.7, 0.7] });
    ok(frames === 1, 'framed once when attached');
    c.setViewport(520, 380);
    ok(frames === 2, `a resize frames once more, not hundreds of times (${frames})`);
    c.setViewport(520, 380); c.panBy(5, 5);
    ok(frames === 2, 'moving the camera does not reframe');
    off(); c.setViewport(300, 200);
    ok(frames === 2, 'detached: nothing more');
    c.destroy();
  }
  console.log('destroy');
  {
    const { c, log } = harness();
    c.setViewport(1000, 700); await settle();
    const n = c.stats().ready;
    c.destroy();
    ok(log.disposed.length >= n && n > 0, 'every decoded image is freed');
    c.setViewport(900, 600);
    ok(true, 'using a destroyed controller does not throw');
  }
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
