/**
 * Fetches, decodes and remembers tiles.
 *
 *   - `fetchTile(desc, signal)` -> bytes (an ArrayBuffer / Uint8Array / Blob); the
 *     caller adds the Authorization header, so no token ever rides in a URL.
 *   - `decode(bytes, desc)` -> {image, bytes: <decoded size>} (an ImageBitmap on
 *     web, a Skia image on native).
 *   - `disk` (optional) -> {get(desc) -> bytes|null, put(desc, bytes)}: the
 *     progressive offline cache. A tile seen once is never fetched again.
 *   - `dispose(image)` frees a decoded image when it is evicted.
 *
 * `want(tiles)` states what the screen needs RIGHT NOW (nearest first). Anything
 * in flight that is no longer wanted is aborted: a fast pinch must not leave 40
 * stale requests ahead of the tiles the finger stopped on. Decoded images live in
 * an LRU bounded by bytes, so a 100 MB drawing cannot exhaust memory.
 */

const RETRY_DELAYS_MS = [1500, 4000, 10000];

export class TileFetchError extends Error {
  constructor(status, message) {
    super(message || `tile fetch failed (${status})`);
    this.name = 'TileFetchError';
    this.status = status;
  }
}

export function createTileCache({
  fetchTile, decode, dispose = () => {}, disk = null, onUpdate = () => {},
  maxBytes = 128 * 1024 * 1024, concurrency = 12, now = () => Date.now(),
  setTimer = (fn, ms) => setTimeout(fn, ms), clearTimer = (h) => clearTimeout(h),
}) {
  const ready = new Map();            // key -> {image, bytes, desc}   (insertion order = recency)
  const state = new Map();            // key -> {tries, missing, retryAt, timer}
  const inflight = new Map();         // key -> AbortController
  let wanted = [];                    // the latest want() list
  let wantedKeys = new Set();
  let used = 0;
  let destroyed = false;
  let generation = 0;

  const st = (key) => {
    let s = state.get(key);
    if (!s) { s = { tries: 0, missing: false, retryAt: 0, timer: null }; state.set(key, s); }
    return s;
  };

  function touch(key) {
    const e = ready.get(key);
    if (e) { ready.delete(key); ready.set(key, e); }
    return e;
  }

  function evict() {
    if (used <= maxBytes) return;
    for (const [key, e] of ready) {
      if (used <= maxBytes) break;
      if (wantedKeys.has(key)) continue;                         // never evict what is on screen
      ready.delete(key);
      used -= e.bytes;
      try { dispose(e.image); } catch (_e) { /* a failed free must not stop the sweep */ }
    }
  }

  async function load(desc) {
    const key = desc.key;
    const ctl = new AbortController();
    inflight.set(key, ctl);
    const gen = generation;
    try {
      let bytes = null;
      if (disk) {
        try { bytes = await disk.get(desc); } catch (_e) { bytes = null; }
      }
      if (ctl.signal.aborted) return;
      let fromNet = false;
      if (!bytes) {
        bytes = await fetchTile(desc, ctl.signal);
        fromNet = true;
      }
      if (ctl.signal.aborted || destroyed || gen !== generation) return;
      const dec = await decode(bytes, desc);
      if (ctl.signal.aborted || destroyed || gen !== generation) {
        try { dispose(dec.image); } catch (_e) { /* ignore */ }
        return;
      }
      ready.set(key, { image: dec.image, bytes: dec.bytes || 0, desc });
      used += dec.bytes || 0;
      st(key).tries = 0;
      if (fromNet && disk) {
        // best effort: a full disk must not fail a tile that is already on screen
        Promise.resolve().then(() => disk.put(desc, bytes)).catch(() => {});
      }
      evict();
      onUpdate(key);
    } catch (e) {
      if (ctl.signal.aborted || destroyed) return;
      const s = st(key);
      if (e && (e.status === 404 || e.status === 403 || e.status === 401)) {
        s.missing = true;                                        // not coming back by asking again
        onUpdate(key, e);
      } else {
        s.tries += 1;
        if (s.tries > RETRY_DELAYS_MS.length) { s.missing = true; onUpdate(key, e); }
        else {
          s.retryAt = now() + RETRY_DELAYS_MS[s.tries - 1];
          s.timer = setTimer(() => { s.timer = null; s.retryAt = 0; pump(); }, RETRY_DELAYS_MS[s.tries - 1]);
        }
      }
    } finally {
      inflight.delete(key);
      if (!destroyed) pump();
    }
  }

  function pump() {
    if (destroyed) return;
    for (const desc of wanted) {
      if (inflight.size >= concurrency) break;
      const key = desc.key;
      if (ready.has(key) || inflight.has(key)) continue;
      const s = st(key);
      if (s.missing || s.retryAt > now()) continue;
      load(desc);
    }
  }

  return {
    /** The decoded tile, or undefined. Marks it recently used. */
    get(key) { const e = touch(key); return e ? e.image : undefined; },
    has(key) { return ready.has(key); },
    isMissing(key) { const s = state.get(key); return Boolean(s && s.missing); },
    /** State the tiles the screen needs now (nearest first). */
    want(tiles) {
      if (destroyed) return;
      wanted = tiles;
      wantedKeys = new Set(tiles.map((t) => t.key));
      for (const [key, ctl] of inflight) {
        if (!wantedKeys.has(key)) { ctl.abort(); inflight.delete(key); }
      }
      pump();
    },
    /** Warm tiles without making them "wanted" (e.g. level 0/1 of the next pages). */
    prefetch(tiles) {
      if (destroyed) return;
      const keys = new Set(wanted.map((t) => t.key));
      wanted = wanted.concat(tiles.filter((t) => !keys.has(t.key)));
      wantedKeys = new Set(wanted.map((t) => t.key));
      pump();
    },
    stats() { return { ready: ready.size, inflight: inflight.size, bytes: used }; },
    destroy() {
      destroyed = true;
      generation += 1;
      for (const ctl of inflight.values()) ctl.abort();
      inflight.clear();
      for (const s of state.values()) if (s.timer) clearTimer(s.timer);
      for (const e of ready.values()) { try { dispose(e.image); } catch (_e) { /* ignore */ } }
      ready.clear();
      used = 0;
    },
  };
}
