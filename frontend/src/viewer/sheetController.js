/**
 * One open drawing: its layout, camera, tile cache, page indexes, search and
 * overlays. Platform-free; the Canvas2D (web) and Skia (native) renderers only
 * paint what `frame()` returns and feed gestures back through `setCamera`.
 *
 *   const c = createSheetController({ api, projectId, fileId, manifest, decode, ... });
 *   c.on('change', redraw);            // camera, tiles, search, indexes, overlays
 *   c.setViewport(w, h);
 *   c.frame()                          // {previews, tiles} to paint, in world coords
 *
 * COLD START. `setViewport` fits the first page and asks for its preview and the
 * level 0 tiles at once; the preview (about 10 KB) is the first frame, level 0
 * replaces it, and deeper levels arrive as the reader zooms. Nothing is parsed.
 */
import {
  PAGE_W, boxToWorld, clampCamera, easeOutCubic, fitRectCamera, fitWidthCamera, layoutPages, lerpCamera,
  pageAt, panBy as panCamera, parentOf, pageToWorld, rectsOverlap, screenToWorld, tileKey,
  tilesFor, tileWorldRect, visibleWorldRect, worldToPage, worldToScreen, zoomAt as zoomCamera, zoomLimits,
} from './tileMath';
import { createTileCache } from './tileCache';
import { hitCallout, searchIndexes, stepIndex } from './sheetIndex';

const PIN_HIT_PX = 20;
const PAGE_W_ = PAGE_W;
const INDEX_CONCURRENCY = 3;

export function createSheetController({
  api, projectId, fileId, manifest, decode, dispose, disk = null, dpr = 1,
  maxBytes = 128 * 1024 * 1024, requestFrame = null, now = () => Date.now(),
}) {
  const build = manifest.build;
  const layout = layoutPages(manifest.pages);
  const listeners = { change: new Set(), fly: new Set() };
  let vp = { width: 0, height: 0 };
  let limits = { min: 0.1, max: 20 };
  let cam = { x: 500, y: 0, zoom: 1 };
  let needed = [];
  let neededSig = '';
  let destroyed = false;
  let anim = null;                    // {from, to, start, ms}
  let overlays = { pins: [], callouts: true };
  let bounds = null;                  // a portal confines the camera to its crop

  const previews = new Map();         // page -> decoded preview image
  const previewLoading = new Set();
  const indexes = new Map();          // page -> sheet_index
  const indexLoading = new Set();
  const indexFailed = new Set();
  let search = { query: '', matches: [], current: 0 };
  let searchAll = false;

  const emit = (name, ...a) => { for (const f of listeners[name]) { try { f(...a); } catch (_e) { /* a bad listener must not stop the frame */ } } };
  const changed = () => { if (!destroyed) emit('change'); };

  const tiles = createTileCache({
    fetchTile: (desc, signal) => api.tile(projectId, fileId, build, desc, signal),
    decode, dispose, maxBytes,
    disk: disk ? { get: (d) => disk.getTile(fileId, build, d), put: (d, b) => disk.putTile(fileId, build, d, b) } : null,
    onUpdate: changed,
  });

  function updateNeeded() {
    needed = vp.width > 0 ? tilesFor(layout, cam, vp, dpr) : [];
    const sig = needed.map((t) => t.key).join('|');
    if (sig === neededSig) return;
    neededSig = sig;
    tiles.want(needed);
    for (const pg of layout.pages) {
      if (rectsOverlap({ x: pg.x, y: pg.y, w: pg.w, h: pg.h }, visibleWorldRect(cam, vp))) {
        loadPreview(pg.page);
        loadIndex(pg.page);
      }
    }
  }

  async function loadPreview(page) {
    const pg = layout.pages.find((p) => p.page === page);
    if (!pg || !pg.preview || previews.has(page) || previewLoading.has(page)) return;
    previewLoading.add(page);
    try {
      let bytes = disk ? await disk.getTile(fileId, build, { key: `${page}/preview`, page, z: -1, x: 0, y: 0 }).catch(() => null) : null;
      if (!bytes) {
        bytes = await api.preview(projectId, fileId, build, page);
        if (disk) Promise.resolve(disk.putTile(fileId, build, { key: `${page}/preview`, page, z: -1, x: 0, y: 0 }, bytes)).catch(() => {});
      }
      if (destroyed) return;
      const dec = await decode(bytes, { page, z: -1 });
      if (destroyed) { dispose && dispose(dec.image); return; }
      previews.set(page, dec);
      changed();
    } catch (_e) {
      // the preview is a courtesy; tiles still draw
    } finally {
      previewLoading.delete(page);
    }
  }

  async function loadIndex(page) {
    const pg = layout.pages.find((p) => p.page === page);
    if (!pg || indexes.has(page) || indexLoading.has(page) || indexFailed.has(page)) return;
    const meta = (manifest.pages || []).find((p) => p.page === page);
    if (meta && meta.has_index === false) return;
    indexLoading.add(page);
    try {
      let ix = disk && disk.getJson ? await disk.getJson(fileId, build, `index-${page}`).catch(() => null) : null;
      if (!ix) {
        ix = await api.index(projectId, fileId, page, build);
        if (disk && disk.putJson) Promise.resolve(disk.putJson(fileId, build, `index-${page}`, ix)).catch(() => {});
      }
      if (destroyed) return;
      indexes.set(page, ix);
      if (search.query) runSearch(search.query, { keepCurrent: true });
      changed();
    } catch (e) {
      if (!destroyed) indexFailed.add(page);              // a page with no index is still viewable
    } finally {
      indexLoading.delete(page);
    }
  }

  async function loadAllIndexes() {
    searchAll = true;
    const pending = layout.pages.map((p) => p.page).filter((p) => !indexes.has(p) && !indexFailed.has(p));
    let i = 0;
    const worker = async () => {
      while (i < pending.length && !destroyed) { const p = pending[i]; i += 1; await loadIndex(p); }
    };
    await Promise.all(Array.from({ length: INDEX_CONCURRENCY }, worker));
  }

  function runSearch(query, { keepCurrent = false } = {}) {
    const matches = searchIndexes(indexes, query);
    const current = keepCurrent ? Math.min(search.current, Math.max(0, matches.length - 1)) : 0;
    search = { query, matches, current };
  }

  // ── camera ────────────────────────────────────────────────────────────────

  function setCamera(next) {
    cam = clampCamera(next, layout, vp, limits, bounds);
    updateNeeded();
    changed();
  }

  function stepAnim(t) {
    if (!anim) return false;
    const k = Math.min(1, (t - anim.start) / anim.ms);
    cam = clampCamera(lerpCamera(anim.from, anim.to, easeOutCubic(k)), layout, vp, limits, bounds);
    updateNeeded();
    if (k >= 1) anim = null;
    changed();
    return anim !== null;
  }

  function flyTo(target, ms = 320) {
    const to = clampCamera(target, layout, vp, limits, bounds);
    if (emitFly(to, ms)) return;                         // the native renderer animates on its own thread
    anim = { from: cam, to, start: now(), ms };
    if (requestFrame) requestFrame();
    changed();                                           // wakes the renderer's loop, which steps the animation
  }
  function emitFly(to, ms) {
    let handled = false;
    for (const f of listeners.fly) { try { handled = f(to, ms) === true || handled; } catch (_e) { /* ignore */ } }
    return handled;
  }

  const api2 = {
    layout,
    build,
    get camera() { return cam; },
    get limits() { return limits; },
    get bounds() { return bounds; },
    get viewport() { return vp; },
    get dpr() { return dpr; },
    manifest,
    on(name, fn) { listeners[name].add(fn); return () => listeners[name].delete(fn); },

    setViewport(width, height) {
      const first = vp.width === 0;
      vp = { width, height };
      limits = zoomLimits(layout, vp, dpr);
      if (first && width > 0) cam = fitWidthCamera(layout, vp);
      cam = clampCamera(cam, layout, vp, limits, bounds);
      neededSig = '';
      updateNeeded();
      changed();
    },
    setCamera,
    /** Gestures call these; they are plain functions of the camera so a worklet can do the same maths. */
    panBy(dx, dy) { setCamera(panCamera(cam, dx, dy)); },
    zoomAt(factor, sx, sy) { setCamera(zoomCamera(cam, factor, sx, sy, vp, limits)); },
    fit() { flyTo(fitWidthCamera(layout, vp)); },
    flyTo,
    tick(t) { return stepAnim(t); },

    // ── what to paint ──
    frame() {
      const vis = visibleWorldRect(cam, vp);
      const prev = [];
      for (const pg of layout.pages) {
        if (!rectsOverlap({ x: pg.x, y: pg.y, w: pg.w, h: pg.h }, vis)) continue;
        const dec = previews.get(pg.page);
        if (dec) prev.push({ key: `${pg.page}/preview`, image: dec.image, rect: { x: pg.x, y: pg.y, w: pg.w, h: pg.h } });
      }
      const fallbacks = new Map();
      const exact = [];
      for (const t of needed) {
        const img = tiles.get(t.key);
        if (img !== undefined) { exact.push({ key: t.key, image: img, rect: t.rect, z: t.z }); continue; }
        let anc = parentOf(t);
        while (anc) {
          const k = tileKey(anc.page, anc.z, anc.x, anc.y);
          const aimg = tiles.get(k);
          if (aimg !== undefined) {
            if (!fallbacks.has(k)) {
              const pg = layout.pages.find((p) => p.page === anc.page);
              const lv = pg.levels.find((l) => l.z === anc.z);
              if (pg && lv) fallbacks.set(k, { key: k, image: aimg, rect: tileWorldRect(pg, lv, anc.x, anc.y), z: anc.z });
            }
            break;
          }
          anc = parentOf(anc);
        }
      }
      const fb = Array.from(fallbacks.values()).sort((a, b) => a.z - b.z);
      return { previews: prev, tiles: fb.concat(exact) };
    },
    /** True while tiles the screen needs are still on their way (for a quiet progress hint). */
    get loading() { return needed.some((t) => !tiles.has(t.key) && !tiles.isMissing(t.key)); },

    // ── overlays: pins ride the same transform as the tiles ──
    setPins(pins) { overlays = { ...overlays, pins: pins || [] }; changed(); },
    get pins() { return overlays.pins; },
    pinScreen(pin) {
      const pg = layout.pages.find((p) => p.page === (pin.page || 1)) || layout.pages[0];
      if (!pg) return null;
      const w = pageToWorld(pg, pin.x, pin.y);
      return worldToScreen(cam, vp, w.x, w.y);
    },

    /** What is under a screen point: a pin, a callout, or a spot on a page (to place a pin). */
    hitTest(sx, sy) {
      for (let i = overlays.pins.length - 1; i >= 0; i -= 1) {
        const p = overlays.pins[i];
        const s = api2.pinScreen(p);
        if (s && Math.hypot(s.x - sx, s.y - (sy + 12)) <= PIN_HIT_PX) return { type: 'pin', pin: p };
      }
      const w = screenToWorld(cam, vp, sx, sy);
      const pg = pageAt(layout, w.x, w.y);
      if (!pg) return null;
      const f = worldToPage(pg, w.x, w.y);
      const callout = hitCallout(indexes.get(pg.page), f.x, f.y);
      if (callout) return { type: 'callout', callout, page: pg.page, x: f.x, y: f.y };
      return { type: 'page', page: pg.page, x: Math.max(0, Math.min(1, f.x)), y: Math.max(0, Math.min(1, f.y)) };
    },

    // ── search ──
    indexFor(page) { return indexes.get(page) || null; },
    get indexProgress() { return { loaded: indexes.size, total: layout.pages.length, failed: indexFailed.size }; },
    async search(query) {
      runSearch(query);
      changed();
      if (!query || !String(query).trim()) return search;
      if (!searchAll) await loadAllIndexes();
      if (destroyed) return search;
      runSearch(query, { keepCurrent: true });
      changed();
      if (search.matches.length) api2.goToMatch(search.current);     // take the reader to the first hit
      return search;
    },
    clearSearch() { search = { query: '', matches: [], current: 0 }; changed(); },
    get searchState() { return search; },
    stepMatch(dir) {
      if (!search.matches.length) return null;
      search = { ...search, current: stepIndex(search.current, search.matches.length, dir) };
      api2.goToMatch(search.current);
      changed();
      return search.matches[search.current];
    },
    goToMatch(i) {
      const m = search.matches[i];
      if (!m) return;
      const pg = layout.pages.find((p) => p.page === m.page);
      if (!pg) return;
      const rect = boxToWorld(pg, m.bbox);
      const target = fitRectCamera(rect, vp, 6, limits);        // the match sits in a generous frame
      flyTo({ ...target, zoom: Math.max(cam.zoom, Math.min(target.zoom, limits.max)) });
    },
    /** World rects (with the page's tile transform) of every match, for painting. */
    matchRects() {
      const out = [];
      search.matches.forEach((m, i) => {
        const pg = layout.pages.find((p) => p.page === m.page);
        if (pg) out.push({ rect: boxToWorld(pg, m.bbox), current: i === search.current });
      });
      return out;
    },
    /** Callout boxes on the pages in view, as world rects (tap targets painted subtly). */
    calloutRects() {
      if (!overlays.callouts) return [];
      const vis = visibleWorldRect(cam, vp);
      const out = [];
      for (const pg of layout.pages) {
        const ix = indexes.get(pg.page);
        if (!ix || !rectsOverlap({ x: pg.x, y: pg.y, w: pg.w, h: pg.h }, vis)) continue;
        for (const c of ix.callouts || []) if (c.bbox && c.target) out.push({ rect: boxToWorld(pg, c.bbox), callout: c, page: pg.page });
      }
      return out;
    },

    /** Confine the camera to a normalised box of a page (a portal shows only its detail). */
    setBounds(page, box, pad = 0.12) {
      const pg = layout.pages.find((p) => p.page === page);
      if (!pg || !box) { bounds = null; limits = zoomLimits(layout, vp, dpr); return; }
      const r = boxToWorld(pg, box);
      bounds = { x: r.x - r.w * pad, y: r.y - r.h * pad, w: r.w * (1 + 2 * pad), h: r.h * (1 + 2 * pad) };
      const full = zoomLimits(layout, vp, dpr);
      limits = { min: fitRectCamera(bounds, vp, 0).zoom, max: full.max };
      limits.max = Math.max(limits.max, limits.min * 2);
    },
    /** Frame a normalised box of a page (a portal's crop). */
    frameBox(page, box, pad = 0.06) {
      const pg = layout.pages.find((p) => p.page === page);
      if (!pg) return;
      setCamera(fitRectCamera(boxToWorld(pg, box), vp, pad, limits));
    },
    /** Bring a whole page into view (top-aligned, fit to width). */
    goToPage(page) {
      const pg = layout.pages.find((p) => p.page === page);
      if (!pg) return;
      const zoom = vp.width / PAGE_W_;
      flyTo({ x: pg.x + pg.w / 2, y: pg.y + vp.height / 2 / zoom, zoom });
    },
    pageBounds(page) { const pg = layout.pages.find((p) => p.page === page); return pg ? { x: pg.x, y: pg.y, w: pg.w, h: pg.h } : null; },

    stats() { return tiles.stats(); },
    destroy() {
      destroyed = true;
      tiles.destroy();
      for (const dec of previews.values()) { try { dispose && dispose(dec.image); } catch (_e) { /* ignore */ } }
      previews.clear();
      listeners.change.clear();
      listeners.fly.clear();
    },
  };
  return api2;
}
