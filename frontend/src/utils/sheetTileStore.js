import * as FileSystem from 'expo-file-system/legacy';
import { Platform } from 'react-native';
import { decodeBase64, encodeBase64 } from '../viewer/tileMath';

/**
 * PROGRESSIVE OFFLINE CACHE FOR THE TILE VIEWER.
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
 *
 * `build` names one version of one file's tiles (backend lib/sheet_pipeline.build_id),
 * so a changed drawing writes a new build directory and the old one is removed the
 * first time the new one is written. The manifest of the last build seen lives in
 * `{fileId}/latest/` so the viewer can open offline without asking which build.
 *
 * EVERY FAILURE RESOLVES TO "NOT CACHED". A full disk or an unreadable file means
 * the network is used; it never fails a tile that is already on screen. Writes are
 * atomic (temp file, then move) so a killed app cannot leave a half tile that
 * decodes to garbage. The budget sweep only deletes directories it can measure
 * and never one touched in this session.
 */

const ROOT = (FileSystem.documentDirectory || '') + 'sheet-tiles/';
const canUseFs = () => Platform.OS !== 'web' && !!FileSystem.documentDirectory;
const safe = (s) => String(s).replace(/[^A-Za-z0-9_-]/g, '_');
const dirOf = (fileId, build) => `${ROOT}${safe(fileId)}/${safe(build)}/`;
const nameOf = (desc) => `${String(desc.key).replace(/[^A-Za-z0-9]+/g, '_')}.webp`;

export const DEFAULT_BUDGET_BYTES = 1.5 * 1024 * 1024 * 1024;
const touched = new Set();           // fileIds used in this session: never swept
const ensured = new Set();           // directories known to exist
const purged = new Set();            // `${file}/${build}` already cleaned of other builds

async function ensureDir(dir) {
  if (ensured.has(dir)) return;
  const info = await FileSystem.getInfoAsync(dir);
  if (!info.exists) await FileSystem.makeDirectoryAsync(dir, { intermediates: true });
  ensured.add(dir);
}

async function writeAtomic(uri, base64) {
  const tmp = `${uri}.tmp`;
  await FileSystem.writeAsStringAsync(tmp, base64, { encoding: FileSystem.EncodingType ? FileSystem.EncodingType.Base64 : 'base64' });
  await FileSystem.moveAsync({ from: tmp, to: uri });
}

async function dropOtherBuilds(fileId, build) {
  const k = `${fileId}/${build}`;
  if (purged.has(k)) return;
  purged.add(k);
  try {
    const base = `${ROOT}${safe(fileId)}/`;
    const names = await FileSystem.readDirectoryAsync(base);
    for (const n of names || []) {
      if (n !== safe(build) && n !== 'latest') await FileSystem.deleteAsync(`${base}${n}/`, { idempotent: true });
    }
  } catch (_e) { /* housekeeping only */ }
}

export const sheetTileStore = {
  async getTile(fileId, build, desc) {
    if (!canUseFs()) return null;
    try {
      touched.add(String(fileId));
      const uri = dirOf(fileId, build) + nameOf(desc);
      const info = await FileSystem.getInfoAsync(uri);
      if (!info.exists || !(info.size > 0)) return null;
      const b64 = await FileSystem.readAsStringAsync(uri, { encoding: FileSystem.EncodingType ? FileSystem.EncodingType.Base64 : 'base64' });
      return b64 ? decodeBase64(b64) : null;
    } catch (_e) { return null; }
  },

  async putTile(fileId, build, desc, bytes) {
    if (!canUseFs()) return;
    try {
      touched.add(String(fileId));
      const dir = dirOf(fileId, build);
      await ensureDir(dir);
      await dropOtherBuilds(fileId, build);
      await writeAtomic(dir + nameOf(desc), encodeBase64(bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)));
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
      touched.add(String(fileId));
      const dir = dirOf(fileId, build);
      await ensureDir(dir);
      const uri = `${dir}${safe(name)}.json`;
      const tmp = `${uri}.tmp`;
      await FileSystem.writeAsStringAsync(tmp, JSON.stringify(value));
      await FileSystem.moveAsync({ from: tmp, to: uri });
    } catch (_e) { /* best effort */ }
  },

  /** Remove every cached tile of a file (it was deleted, or the user cleared it). */
  async purgeFile(fileId) {
    if (!canUseFs()) return;
    try { await FileSystem.deleteAsync(`${ROOT}${safe(fileId)}/`, { idempotent: true }); } catch (_e) { /* ignore */ }
  },

  /**
   * Keep the cache under `maxBytes` by removing the least recently used file
   * directories. Declines (deletes nothing) when it cannot measure.
   */
  async sweep({ maxBytes = DEFAULT_BUDGET_BYTES, dryRun = false } = {}) {
    if (!canUseFs()) return { skipped: true, reason: 'no-fs' };
    let names;
    try { names = await FileSystem.readDirectoryAsync(ROOT); } catch (_e) { return { skipped: true, reason: 'unreadable-dir' }; }
    const dirs = [];
    let total = 0;
    for (const n of names || []) {
      let info;
      try { info = await FileSystem.getInfoAsync(`${ROOT}${n}/`, { size: true }); } catch (_e) { return { skipped: true, reason: 'unmeasurable' }; }
      if (!info.exists || !Number.isFinite(info.size)) return { skipped: true, reason: 'unmeasurable' };
      total += info.size;
      dirs.push({ name: n, size: info.size, mtime: info.modificationTime || 0 });
    }
    if (total <= maxBytes) return { scanned: dirs.length, deleted: [], bytes: total };
    const deleted = [];
    for (const d of dirs.sort((a, b) => a.mtime - b.mtime)) {
      if (total <= maxBytes) break;
      if (touched.has(d.name)) continue;
      if (!dryRun) {
        try { await FileSystem.deleteAsync(`${ROOT}${d.name}/`, { idempotent: true }); } catch (_e) { continue; }
      }
      total -= d.size;
      deleted.push(d.name);
    }
    return { scanned: dirs.length, deleted, bytes: total };
  },
};
export default sheetTileStore;
