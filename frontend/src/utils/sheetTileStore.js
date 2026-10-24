import * as FileSystem from 'expo-file-system/legacy';
import { Platform } from 'react-native';
import { decodeBase64, encodeBase64 } from '../viewer/tileMath';

/**
 * PROGRESSIVE OFFLINE CACHE FOR THE TILE VIEWER, WITH ITS OWN DISK QUOTA.
 *
 * A tile (or a manifest / page index) seen once is kept on the device, so
 * re-opening a drawing, or opening it underground, needs no network for what was
 * already viewed. Nothing is downloaded ahead of the reader: the cache fills as
 * the drawing is explored.
 *
 * SEPARATE FROM docCache's `documents/` ON PURPOSE. That directory is flat, shared
 * by every project and swept against the stored file lists (sweepDocCache); a
 * tile directory inside it would be deleted by the next sweep. This one has its
 * own layout and its own budget:
 *
 *   {documentDirectory}sheet-tiles/{fileId}/{build}/{name}
 *   {documentDirectory}sheet-tiles/_usage.json     bytes per file/build + last use
 *
 * THE QUOTA (DEFAULT 500 MB) IS ENFORCED ON EVERY WRITE, from the usage index, not
 * by measuring directories (which the platforms do not report reliably). When a
 * write takes the total over the cap, whole drawings are removed least recently
 * used first, never the one being written. A single drawing that alone reaches the
 * cap stops caching new tiles rather than evicting itself. The index is
 * rebuilt from nothing if it is missing or unreadable: this is a cache, so the
 * safe repair is to clear it, never to guess.
 *
 * `build` names one version of one file's tiles (backend lib/sheet_pipeline.build_id),
 * so a changed drawing writes a new build directory and the old one is removed the
 * first time the new one is written. The manifest of the last build seen lives in
 * `{fileId}/latest/` so the viewer can open offline without asking which build.
 *
 * EVERY FAILURE RESOLVES TO "NOT CACHED". A full disk or an unreadable file means
 * the network is used; it never fails a tile that is already on screen. Writes are
 * atomic (temp file, then move) so a killed app cannot leave a half tile that
 * decodes to garbage.
 */

const ROOT = (FileSystem.documentDirectory || '') + 'sheet-tiles/';
const USAGE_FILE = `${ROOT}_usage.json`;
const canUseFs = () => Platform.OS !== 'web' && !!FileSystem.documentDirectory;
const safe = (s) => String(s).replace(/[^A-Za-z0-9_-]/g, '_');
const dirOf = (fileId, build) => `${ROOT}${safe(fileId)}/${safe(build)}/`;
const nameOf = (desc) => `${String(desc.key).replace(/[^A-Za-z0-9]+/g, '_')}.webp`;
const b64 = () => (FileSystem.EncodingType ? FileSystem.EncodingType.Base64 : 'base64');

export const DEFAULT_QUOTA_BYTES = 500 * 1024 * 1024;
const PERSIST_DELAY_MS = 3000;

let quota = DEFAULT_QUOTA_BYTES;
let usage = null;                    // {files: {[safeFileId]: {builds: {[safeBuild]: bytes}, last}}}
let usageLoading = null;
let dirty = false;
let persistTimer = null;
const ensured = new Set();           // directories known to exist
const purged = new Set();            // `${file}/${build}` already cleaned of other builds

let lastStamp = 0;
/** A strictly increasing "last used" stamp: wall-clock time, never equal to the one before. */
const stamp = () => { lastStamp = Math.max(Date.now(), lastStamp + 1); return lastStamp; };

const fileBytes = (e) => Object.values(e.builds).reduce((a, n) => a + n, 0);
const totalBytes = () => Object.values(usage.files).reduce((a, e) => a + fileBytes(e), 0);

async function ensureDir(dir) {
  if (ensured.has(dir)) return;
  const info = await FileSystem.getInfoAsync(dir);
  if (!info.exists) await FileSystem.makeDirectoryAsync(dir, { intermediates: true });
  ensured.add(dir);
}

async function writeAtomic(uri, data, opts) {
  const tmp = `${uri}.tmp`;
  await FileSystem.writeAsStringAsync(tmp, data, opts);
  await FileSystem.moveAsync({ from: tmp, to: uri });
}

/** Load the usage index once. A missing or unreadable index with files on disk means
 *  we cannot know what is there, so the store is cleared and starts over. */
function loadUsage() {
  if (usage) return Promise.resolve(usage);
  if (!usageLoading) {
    usageLoading = (async () => {
      let loaded = null;
      try {
        const info = await FileSystem.getInfoAsync(USAGE_FILE);
        if (info.exists) {
          const parsed = JSON.parse(await FileSystem.readAsStringAsync(USAGE_FILE));
          if (parsed && parsed.v === 1 && parsed.files && typeof parsed.files === 'object') loaded = parsed;
        }
      } catch (_e) { loaded = null; }
      if (!loaded) {
        let names = [];
        try { names = (await FileSystem.readDirectoryAsync(ROOT)) || []; } catch (_e) { names = []; }
        if (names.some((n) => n !== '_usage.json' && n !== '_usage.json.tmp')) {
          try { await FileSystem.deleteAsync(ROOT, { idempotent: true }); } catch (_e) { /* fall through */ }
          ensured.clear(); purged.clear();
        }
        loaded = { v: 1, files: {} };
      }
      usage = loaded;
      for (const e of Object.values(usage.files)) lastStamp = Math.max(lastStamp, Number(e.last) || 0);
      return usage;
    })().finally(() => { usageLoading = null; });
  }
  return usageLoading;
}

function schedulePersist() {
  dirty = true;
  if (persistTimer) return;
  persistTimer = setTimeout(() => { persistTimer = null; flush(); }, PERSIST_DELAY_MS);
}

async function flush() {
  if (!usage || !dirty || !canUseFs()) return;
  dirty = false;
  try {
    await ensureDir(ROOT);
    await writeAtomic(USAGE_FILE, JSON.stringify(usage));
  } catch (_e) { dirty = true; /* retried on the next change */ }
}

function entry(fileId) {
  const k = safe(fileId);
  if (!usage.files[k]) usage.files[k] = { builds: {}, last: stamp() };
  return usage.files[k];
}

function account(fileId, build, delta) {
  const e = entry(fileId);
  e.builds[safe(build)] = Math.max(0, (e.builds[safe(build)] || 0) + delta);
  e.last = stamp();
  schedulePersist();
}

/** Remove least recently used drawings (never `keepFileId`) until the total fits the quota. */
async function enforce(keepFileId) {
  if (!usage) return [];
  const removed = [];
  const keep = keepFileId == null ? null : safe(keepFileId);
  while (totalBytes() > quota) {
    const victims = Object.entries(usage.files).filter(([k]) => k !== keep).sort((a, b) => a[1].last - b[1].last);
    if (!victims.length) break;
    const [k] = victims[0];
    try { await FileSystem.deleteAsync(`${ROOT}${k}/`, { idempotent: true }); } catch (_e) { /* keep the record: retried next time */ break; }
    delete usage.files[k];
    for (const key of [...purged]) if (key.startsWith(`${k}/`)) purged.delete(key);
    removed.push(k);
  }
  if (removed.length) schedulePersist();
  return removed;
}

async function dropOtherBuilds(fileId, build) {
  const k = `${safe(fileId)}/${safe(build)}`;
  if (purged.has(k)) return;
  purged.add(k);
  try {
    const base = `${ROOT}${safe(fileId)}/`;
    const names = await FileSystem.readDirectoryAsync(base);
    const e = entry(fileId);
    for (const n of names || []) {
      if (n === safe(build) || n === 'latest') continue;
      await FileSystem.deleteAsync(`${base}${n}/`, { idempotent: true });
      delete e.builds[n];
    }
    schedulePersist();
  } catch (_e) { /* housekeeping only */ }
}

export const sheetTileStore = {
  /** Change the quota (bytes). */
  configure({ maxBytes } = {}) { if (Number.isFinite(maxBytes) && maxBytes > 0) quota = maxBytes; },

  async getTile(fileId, build, desc) {
    if (!canUseFs()) return null;
    try {
      await loadUsage();
      const uri = dirOf(fileId, build) + nameOf(desc);
      const info = await FileSystem.getInfoAsync(uri);
      if (!info.exists || !(info.size > 0)) return null;
      const data = await FileSystem.readAsStringAsync(uri, { encoding: b64() });
      const e = usage.files[safe(fileId)];
      if (e) { e.last = stamp(); dirty = true; }              // reading a tile is use: the drawing stays
      return data ? decodeBase64(data) : null;
    } catch (_e) { return null; }
  },

  async putTile(fileId, build, desc, bytes) {
    if (!canUseFs()) return;
    try {
      await loadUsage();
      const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
      const e = entry(fileId);
      if (fileBytes(e) + u8.length > quota) return;               // one drawing alone cannot outgrow the quota
      const dir = dirOf(fileId, build);
      await ensureDir(dir);
      await dropOtherBuilds(fileId, build);
      await writeAtomic(dir + nameOf(desc), encodeBase64(u8), { encoding: b64() });
      account(fileId, build, u8.length);
      await enforce(fileId);
    } catch (_e) { /* a full disk must not fail a tile already on screen */ }
  },

  async getJson(fileId, build, name) {
    if (!canUseFs()) return null;
    try {
      const uri = `${dirOf(fileId, build)}${safe(name)}.json`;
      const info = await FileSystem.getInfoAsync(uri);
      if (!info.exists) return null;
      return JSON.parse(await FileSystem.readAsStringAsync(uri));
    } catch (_e) { return null; }
  },

  async putJson(fileId, build, name, value) {
    if (!canUseFs()) return;
    try {
      await loadUsage();
      const text = JSON.stringify(value);
      const e = entry(fileId);
      if (fileBytes(e) + text.length > quota) return;
      const dir = dirOf(fileId, build);
      await ensureDir(dir);
      await writeAtomic(`${dir}${safe(name)}.json`, text);
      account(fileId, build, text.length);
      await enforce(fileId);
    } catch (_e) { /* best effort */ }
  },

  /** Remove every cached tile of a file (it was deleted, or the user cleared it). */
  async purgeFile(fileId) {
    if (!canUseFs()) return;
    try {
      await loadUsage();
      await FileSystem.deleteAsync(`${ROOT}${safe(fileId)}/`, { idempotent: true });
      delete usage.files[safe(fileId)];
      for (const key of [...purged]) if (key.startsWith(`${safe(fileId)}/`)) purged.delete(key);
      schedulePersist();
    } catch (_e) { /* ignore */ }
  },

  /** Bring the store under the quota now (called when a tiled drawing opens, in case the
   *  quota was lowered or an earlier session was killed before it could evict). */
  async sweep({ maxBytes, activeFileId } = {}) {
    if (!canUseFs()) return { skipped: true, reason: 'no-fs' };
    try {
      await loadUsage();
      if (Number.isFinite(maxBytes) && maxBytes > 0) quota = maxBytes;
      const deleted = await enforce(activeFileId);
      await flush();
      return { deleted, bytes: totalBytes(), quota };
    } catch (_e) { return { skipped: true, reason: 'error' }; }
  },

  /** Bytes the index says are cached. */
  async bytes() { if (!canUseFs()) return 0; try { await loadUsage(); return totalBytes(); } catch (_e) { return 0; } },

  /** Write the usage index now (tests, app backgrounding). */
  flush,

  /** Forget in-memory state (tests). */
  _reset() { lastStamp = 0; usage = null; usageLoading = null; dirty = false; quota = DEFAULT_QUOTA_BYTES; ensured.clear(); purged.clear(); if (persistTimer) { clearTimeout(persistTimer); persistTimer = null; } },
};
export default sheetTileStore;
