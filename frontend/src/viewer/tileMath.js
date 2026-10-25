/**
 * The deep-zoom viewer's geometry. Pure functions, no React, no platform: the
 * Canvas2D (web) and Skia (native) renderers both draw what these return, so a
 * pin, a search highlight and a tile can never disagree about where they are.
 *
 * WORLD COORDINATES. Every page is PAGE_W world units wide (its height follows
 * its own aspect) and pages stack top to bottom with PAGE_GAP between them. A
 * position on a page is stored as a FRACTION of the page ({x, y} in 0..1), which
 * is what annotations and the sheet index already use, and is mapped to the world
 * by `pageToWorld`. The camera is {x, y, zoom}: the world point at the centre of
 * the viewport and screen pixels per world unit.
 *
 * LEVELS. The backend (lib/sheet_tiles.py) builds level z with a long side of
 * 1024 * 2^z pixels, cut into TILE x TILE tiles, and skips all-white tiles; each
 * level carries a `present` bitmap (row-major, LSB first, base64) saying which
 * tiles exist.
 */

export const TILE = 512;
export const PAGE_W = 1000;
export const PAGE_GAP = 40;
const DEFAULT_ASPECT = 0.75;                 // a page whose size we were not told

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const B64_INDEX = (() => {
  const m = new Int16Array(128).fill(-1);
  for (let i = 0; i < B64.length; i += 1) m[B64.charCodeAt(i)] = i;
  return m;
})();

/** base64 -> Uint8Array without atob/Buffer (neither is guaranteed on every runtime). */
export function decodeBase64(b64) {
  const s = String(b64 || '').replace(/[^A-Za-z0-9+/]/g, '');
  const out = new Uint8Array(Math.floor((s.length * 3) / 4));
  let o = 0;
  for (let i = 0; i < s.length; i += 4) {
    const a = B64_INDEX[s.charCodeAt(i)];
    const b = B64_INDEX[s.charCodeAt(i + 1)];
    const c = i + 2 < s.length ? B64_INDEX[s.charCodeAt(i + 2)] : -1;
    const d = i + 3 < s.length ? B64_INDEX[s.charCodeAt(i + 3)] : -1;
    if (o < out.length) out[o++] = (a << 2) | (b >> 4);
    if (c >= 0 && o < out.length) out[o++] = ((b & 15) << 4) | (c >> 2);
    if (d >= 0 && o < out.length) out[o++] = ((c & 3) << 6) | d;
  }
  return out;
}

/** Uint8Array -> base64 (the inverse of decodeBase64). */
export function encodeBase64(bytes) {
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i];
    const b = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const c = i + 2 < bytes.length ? bytes[i + 2] : 0;
    out += B64[a >> 2] + B64[((a & 3) << 4) | (b >> 4)];
    out += i + 1 < bytes.length ? B64[((b & 15) << 2) | (c >> 6)] : '=';
    out += i + 2 < bytes.length ? B64[c & 63] : '=';
  }
  return out;
}

export function bitIsSet(bytes, cols, x, y) {
  const i = y * cols + x;
  return (i >> 3) < bytes.length && (bytes[i >> 3] & (1 << (i & 7))) !== 0;
}

const _bitmaps = new WeakMap();
function presentBytes(level) {
  let b = _bitmaps.get(level);
  if (!b) {
    b = decodeBase64(level.present);
    _bitmaps.set(level, b);
  }
  return b;
}

/** Does the backend have tile (x, y) of this level? (false = blank, nothing to fetch.) */
export function tileExists(level, x, y) {
  if (x < 0 || y < 0 || x >= level.cols || y >= level.rows) return false;
  if (level.present == null) return true;                        // a level that carries no bitmap: assume it
  return bitIsSet(presentBytes(level), level.cols, x, y);
}

// ── layout ───────────────────────────────────────────────────────────────────

/**
 * Lay the manifest's pages out in the world.
 * Returns {pages: [{page, x, y, w, h, levels, zMax, ready, preview}], width, height}.
 */
export function layoutPages(manifestPages) {
  const pages = [];
  let y = 0;
  for (const p of manifestPages || []) {
    const aspect = p.width_pt && p.height_pt ? p.height_pt / p.width_pt : DEFAULT_ASPECT;
    const h = PAGE_W * aspect;
    const levels = (p.levels || []).slice().sort((a, b) => a.z - b.z);
    pages.push({
      page: p.page, x: 0, y, w: PAGE_W, h, levels,
      zMax: levels.length ? levels[levels.length - 1].z : -1,
      ready: Boolean(p.ready), preview: p.preview || null,
    });
    y += h + PAGE_GAP;
  }
  return { pages, width: PAGE_W, height: Math.max(0, y - PAGE_GAP) };
}

export function pageToWorld(pg, fx, fy) {
  return { x: pg.x + fx * pg.w, y: pg.y + fy * pg.h };
}

export function worldToPage(pg, wx, wy) {
  return { x: (wx - pg.x) / pg.w, y: (wy - pg.y) / pg.h };
}

/** The page under a world point, or null in a gap / outside. */
export function pageAt(layout, wx, wy) {
  for (const pg of layout.pages) {
    if (wx >= pg.x && wx <= pg.x + pg.w && wy >= pg.y && wy <= pg.y + pg.h) return pg;
  }
  return null;
}

/** A normalised box [x0,y0,x1,y1] on a page -> a world rect {x,y,w,h}. */
export function boxToWorld(pg, box) {
  return { x: pg.x + box[0] * pg.w, y: pg.y + box[1] * pg.h, w: (box[2] - box[0]) * pg.w, h: (box[3] - box[1]) * pg.h };
}

// ── camera ───────────────────────────────────────────────────────────────────

export function screenToWorld(cam, vp, sx, sy) {
  'worklet';
  return { x: (sx - vp.width / 2) / cam.zoom + cam.x, y: (sy - vp.height / 2) / cam.zoom + cam.y };
}

export function worldToScreen(cam, vp, wx, wy) {
  return { x: (wx - cam.x) * cam.zoom + vp.width / 2, y: (wy - cam.y) * cam.zoom + vp.height / 2 };
}

export function visibleWorldRect(cam, vp) {
  const w = vp.width / cam.zoom;
  const h = vp.height / cam.zoom;
  return { x: cam.x - w / 2, y: cam.y - h / 2, w, h };
}

/** Zoom limits: the whole widest/tallest page fits (min), and no deeper than
 *  twice the sharpest tile level at device resolution (max). */
export function zoomLimits(layout, vp, dpr = 1) {
  let maxH = 0;
  let sharpest = 1024;
  for (const pg of layout.pages) {
    maxH = Math.max(maxH, pg.h);
    for (const lv of pg.levels) sharpest = Math.max(sharpest, lv.width);
  }
  const fitW = vp.width / PAGE_W;
  const fitAll = maxH ? Math.min(fitW, vp.height / maxH) : fitW;
  const min = Math.min(fitAll * 0.95, fitW);
  const max = Math.max(min * 2, (2 * sharpest) / (PAGE_W * dpr));
  return { min, max };
}

/** Fit the first page to the viewport width, its top at the top edge. */
export function fitWidthCamera(layout, vp) {
  const zoom = vp.width / PAGE_W;
  const top = layout.pages.length ? layout.pages[0].y : 0;
  return { x: PAGE_W / 2, y: top + vp.height / 2 / zoom, zoom };
}

/** The camera that frames a world rect with `pad` (fraction of the rect) around it. */
export function fitRectCamera(rect, vp, pad = 0.08, limits = null) {
  const w = rect.w * (1 + pad * 2);
  const h = rect.h * (1 + pad * 2);
  let zoom = Math.min(vp.width / w, vp.height / h);
  if (limits) zoom = Math.max(limits.min, Math.min(limits.max, zoom));
  return { x: rect.x + rect.w / 2, y: rect.y + rect.h / 2, zoom };
}

/** Keep the camera inside the content: zoom in range; each axis clamped so the
 *  content cannot be flung away, and centred when it is smaller than the view. */
export function clampCamera(cam, layout, vp, limits, bounds = null) {
  'worklet';
  const zoom = Math.max(limits.min, Math.min(limits.max, cam.zoom));
  const b = bounds || { x: 0, y: 0, w: layout.width, h: layout.height };
  const halfW = vp.width / zoom / 2;
  const halfH = vp.height / zoom / 2;
  const clampAxis = (c, lo, size, half) => {
    if (size <= half * 2) return lo + size / 2;                  // smaller than the view: centred
    const slack = half * 0.25;                                   // a quarter of the view may go past the edge
    return Math.max(lo + half - slack, Math.min(lo + size - half + slack, c));
  };
  return { zoom, x: clampAxis(cam.x, b.x, b.w, halfW), y: clampAxis(cam.y, b.y, b.h, halfH) };
}

/** Zoom by `factor` keeping the world point under screen (sx, sy) where it is. */
export function zoomAt(cam, factor, sx, sy, vp, limits) {
  'worklet';
  const zoom = Math.max(limits.min, Math.min(limits.max, cam.zoom * factor));
  const before = screenToWorld(cam, vp, sx, sy);
  return {
    zoom,
    x: before.x - (sx - vp.width / 2) / zoom,
    y: before.y - (sy - vp.height / 2) / zoom,
  };
}

export function panBy(cam, dxScreen, dyScreen) {
  'worklet';
  return { zoom: cam.zoom, x: cam.x - dxScreen / cam.zoom, y: cam.y - dyScreen / cam.zoom };
}

export function lerpCamera(a, b, t) {
  // zoom interpolates geometrically so a zoom-in does not feel like it accelerates
  const zoom = a.zoom * Math.pow(b.zoom / a.zoom, t);
  return { zoom, x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

export const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

// ── choosing tiles ───────────────────────────────────────────────────────────

/** The level to draw a page at: the shallowest one at least as sharp as the screen. */
export function levelFor(pg, zoom, dpr = 1) {
  if (!pg.levels.length) return null;
  const need = PAGE_W * zoom * dpr * 0.9;                        // 10% slack: fewer, bigger levels
  for (const lv of pg.levels) if (lv.width >= need) return lv;
  return pg.levels[pg.levels.length - 1];
}

export function tileKey(page, z, x, y) {
  return `${page}/${z}/${x}/${y}`;
}

/** The world rect of tile (x, y) of a level of a page. */
export function tileWorldRect(pg, level, x, y) {
  const px0 = x * TILE;
  const py0 = y * TILE;
  const px1 = Math.min(px0 + TILE, level.width);
  const py1 = Math.min(py0 + TILE, level.height);
  return {
    x: pg.x + (px0 / level.width) * pg.w, y: pg.y + (py0 / level.height) * pg.h,
    w: ((px1 - px0) / level.width) * pg.w, h: ((py1 - py0) / level.height) * pg.h,
  };
}

/**
 * The tiles the viewport needs, nearest the centre first.
 * `margin` is how far past the view (as a fraction of it) to load ahead.
 */
export function tilesFor(layout, cam, vp, dpr = 1, margin = 0.25) {
  const out = [];
  const vis = visibleWorldRect(cam, vp);
  const mx = vis.w * margin;
  const my = vis.h * margin;
  const x0 = vis.x - mx;
  const x1 = vis.x + vis.w + mx;
  const y0 = vis.y - my;
  const y1 = vis.y + vis.h + my;
  for (const pg of layout.pages) {
    if (pg.y > y1 || pg.y + pg.h < y0 || pg.x > x1 || pg.x + pg.w < x0) continue;
    const lv = levelFor(pg, cam.zoom, dpr);
    if (!lv) continue;
    // visible part of the page, as fractions
    const fx0 = Math.max(0, (x0 - pg.x) / pg.w);
    const fx1 = Math.min(1, (x1 - pg.x) / pg.w);
    const fy0 = Math.max(0, (y0 - pg.y) / pg.h);
    const fy1 = Math.min(1, (y1 - pg.y) / pg.h);
    const tx0 = Math.max(0, Math.floor((fx0 * lv.width) / TILE));
    const tx1 = Math.min(lv.cols - 1, Math.floor((fx1 * lv.width - 1e-6) / TILE));
    const ty0 = Math.max(0, Math.floor((fy0 * lv.height) / TILE));
    const ty1 = Math.min(lv.rows - 1, Math.floor((fy1 * lv.height - 1e-6) / TILE));
    for (let ty = ty0; ty <= ty1; ty += 1) {
      for (let tx = tx0; tx <= tx1; tx += 1) {
        if (!tileExists(lv, tx, ty)) continue;
        const rect = tileWorldRect(pg, lv, tx, ty);
        const dx = rect.x + rect.w / 2 - cam.x;
        const dy = rect.y + rect.h / 2 - cam.y;
        out.push({ key: tileKey(pg.page, lv.z, tx, ty), page: pg.page, z: lv.z, x: tx, y: ty, rect, priority: dx * dx + dy * dy });
      }
    }
  }
  out.sort((a, b) => a.priority - b.priority);
  return out;
}

/** The tile one level up that covers (z, x, y), or null at level 0. */
export function parentOf(t) {
  return t.z > 0 ? { page: t.page, z: t.z - 1, x: t.x >> 1, y: t.y >> 1 } : null;
}

/** Does a rect intersect the visible world rect? */
export function rectsOverlap(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}
