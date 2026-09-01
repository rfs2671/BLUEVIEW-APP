import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system/legacy';
import { Platform } from 'react-native';
import apiClient, { getToken } from './api';

/**
 * DOCUMENT CACHE — cache-on-fetch, no sync-back (the VIEW-screen pattern).
 *
 * Two halves, and a screen needs BOTH:
 *   1. the LIST  (AsyncStorage)  — offline the screen must have something to
 *      enumerate, even if the bytes are already on disk.
 *   2. the BYTES (FileSystem)    — the actual file, for opening offline.
 *
 * Why documentDirectory and not cacheDirectory: cacheDirectory is OS-evictable,
 * which is exactly wrong for a dead zone. Same choice logbookDrafts.js made for
 * photos.
 *
 * Cache key is `{fileId}.{cache_version}` — `cache_version` already ships on
 * every project_files record, so a changed file re-downloads and an unchanged
 * one is a pure local hit.
 *
 * URL note: project files resolve to a PERMANENT authenticated backend proxy
 * (/api/projects/{pid}/files/{id}/content), not a presigned URL — so there is
 * no expiry to design around. The JWT goes in the Authorization HEADER here,
 * never in the URL (a URL-borne token leaks into history/logs).
 */

const LIST_PREFIX = 'bv_doclist:';
const DOC_DIR = (FileSystem.documentDirectory || '') + 'documents/';
const canUseFs = () => Platform.OS !== 'web' && !!FileSystem.documentDirectory;

// ── LIST half ──────────────────────────────────────────────────────────────
export async function cacheDocList(scopeKey, list) {
  if (!scopeKey || !Array.isArray(list)) return false;
  try {
    await AsyncStorage.setItem(LIST_PREFIX + scopeKey, JSON.stringify(list));
    return true;
  } catch (_e) { return false; }
}

export async function readCachedDocList(scopeKey) {
  if (!scopeKey) return [];
  try {
    const raw = await AsyncStorage.getItem(LIST_PREFIX + scopeKey);
    return raw ? (JSON.parse(raw) || []) : [];
  } catch (_e) { return []; }
}

// ── BYTES half ─────────────────────────────────────────────────────────────
function safeName(fileId, cacheVersion, ext = 'pdf') {
  const id = String(fileId || 'file').replace(/[^a-zA-Z0-9_-]/g, '_');
  const v = String(cacheVersion ?? '0').replace(/[^a-zA-Z0-9_-]/g, '_');
  return `${id}.${v}.${ext}`;
}

async function ensureDir() {
  try {
    const info = await FileSystem.getInfoAsync(DOC_DIR);
    if (!info.exists) await FileSystem.makeDirectoryAsync(DOC_DIR, { intermediates: true });
  } catch (_e) { /* best effort */ }
}

/** Local uri if this exact {id}.{version} is already on disk, else null. */
export async function getCachedDocFile(fileId, cacheVersion, ext = 'pdf') {
  if (!canUseFs() || !fileId) return null;
  try {
    const uri = DOC_DIR + safeName(fileId, cacheVersion, ext);
    const info = await FileSystem.getInfoAsync(uri);
    return info.exists && info.size > 0 ? uri : null;
  } catch (_e) { return null; }
}

/**
 * Download a document to the persistent cache. `remoteUrl` may be the relative
 * proxy path the API returns; it is resolved against the API base. Auth rides
 * in the header. Returns the local uri, or null on failure (never throws — a
 * caching failure must not break viewing while online).
 */
export async function cacheDocFile({ fileId, cacheVersion, remoteUrl, ext = 'pdf' }) {
  if (!canUseFs() || !fileId || !remoteUrl) return null;
  try {
    await ensureDir();
    const dest = DOC_DIR + safeName(fileId, cacheVersion, ext);
    const existing = await FileSystem.getInfoAsync(dest);
    if (existing.exists && existing.size > 0) return dest;

    const base = apiClient?.defaults?.baseURL || '';
    const url = /^https?:\/\//i.test(remoteUrl) ? remoteUrl : `${base}${remoteUrl}`;
    const token = await getToken();
    const res = await FileSystem.downloadAsync(url, dest, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (res?.status === 200 && res?.uri) return res.uri;
    // A failed download can leave a 0-byte / error-body file behind.
    try { await FileSystem.deleteAsync(dest, { idempotent: true }); } catch (_e) {}
    return null;
  } catch (_e) { return null; }
}

/**
 * EVERY cached filename, in ONE call.
 *
 * The readiness strip has to answer "which of these files are on this device"
 * on every render, and it must answer from the DISK rather than from a flag we
 * set once -- a stored "saved" boolean goes stale the moment a drawing changes
 * in Dropbox and bumps its cache_version.
 *
 * One readDirectoryAsync instead of a getInfoAsync per file: the filename
 * already encodes `{fileId}.{cache_version}`, so intersecting this set with the
 * file list gives exact per-file state INCLUDING staleness, for the cost of a
 * single directory read.
 *
 * Returns a Set of bare names. An unreadable directory yields an empty set,
 * which reads as "nothing saved" -- honest, and it never blocks the screen.
 */
export async function listCachedDocs() {
  if (!canUseFs()) return new Set();
  try {
    const names = await FileSystem.readDirectoryAsync(DOC_DIR);
    return new Set(Array.isArray(names) ? names : []);
  } catch (_e) {
    return new Set();
  }
}

/** The on-disk name for a file, so callers can test membership of the set
 *  above without knowing how the name is built. */
export function cachedDocName(fileId, cacheVersion, ext = 'pdf') {
  return safeName(fileId, cacheVersion, ext);
}

/** Free bytes on the device, or null if it cannot be determined.
 *  Used to refuse a Save all BEFORE it starts rather than dying on file 9. */
export async function freeDiskBytes() {
  if (!canUseFs()) return null;
  try {
    const n = await FileSystem.getFreeDiskStorageAsync();
    return Number.isFinite(n) ? n : null;
  } catch (_e) {
    return null;
  }
}

// ── SWEEP ──────────────────────────────────────────────────────────────────
//
// NOTHING HAS EVER DELETED FROM THIS DIRECTORY. It is documentDirectory, chosen
// deliberately because the OS will never evict it, and it is included in device
// backups. Superseded versions accumulate for ever: when a drawing changes in
// Dropbox its cache_version bumps, the new copy lands as {id}.2.pdf, and
// {id}.1.pdf stays on the phone until the app is uninstalled. Files removed from
// a project stay too. The readiness strip makes this worse by design -- it
// encourages a CP to save every drawing on every project.
//
// THE DIRECTORY IS FLAT AND SHARED BY EVERY PROJECT. Names are
// {fileId}.{cache_version}.{ext} with no project prefix, so a sweep keyed on ONE
// project's list would delete every other project's plans. The keep-set is
// therefore the union of EVERY cached list, not the list of the screen that
// happened to trigger the sweep.
//
// DELETING A FILE THE CP IS RELYING ON UNDERGROUND IS WORSE THAN NOT SAVING IT,
// so every ambiguity resolves to keeping:
//   - lists unreadable, or none stored     -> delete NOTHING
//   - a name that does not parse           -> keep
//   - a name any list mentions             -> keep
// Only a file that parses AND is named by no list at all is removed.

// NOT EVERY CACHED LIST IS A FLAT LIST OF FILE RECORDS.
//
// cacheDocList stores whatever array a screen hands it, and the screens do not
// agree on a shape. Plans and documents store [{id, cache_version, ...}].
// site/logbooks.jsx stores [{date, logs:[...]}] — the records are one level
// down, and NOTHING at the top level carries an id. A keep-set built by
// reading `f.id` off each element therefore came back EMPTY for that key while
// the logbook PDFs on disk (written by warmDocCache as {logId}.{version}.pdf)
// matched SWEEPABLE exactly. sweepDocCache runs from the plans screen on every
// successful list load, so opening Plans deleted the super's offline logbooks —
// the compliance record, the one file a DOB inspector asks for.
//
// So: descend into array-valued properties as well, and treat any object with
// an id as a record wherever it is found.
const NEST_DEPTH = 3;

// THE VERSION FIELD IS NOT AGREED ON EITHER. Plans key the cached bytes on
// `cache_version`; logbooks key theirs on `updated_at || submitted_at ||
// created_at` (an amendment bumps updated_at, so the corrected PDF
// re-downloads). collectKeepNames cannot know which screen wrote which record,
// and guessing wrong deletes a file someone is relying on underground — so it
// keeps the name for EVERY version this cache could have written for that id.
// The extra names cost nothing: a name no file bears keeps no file.
const VERSION_FIELDS = ['cache_version', 'updated_at', 'submitted_at', 'created_at'];

function addRecordNames(keep, rec) {
  const id = rec.id || rec._id;
  if (!id) return;
  // `?? 0` is the plans default when the record carries no cache_version, and
  // has to stay in the set even when other version fields are present.
  const versions = new Set([rec.cache_version ?? 0]);
  for (const field of VERSION_FIELDS) {
    const v = rec[field];
    if (v !== undefined && v !== null && v !== '') versions.add(v);
  }
  for (const v of versions) {
    // Extension is not on the record, so keep every extension this cache
    // can produce for that id+version rather than guessing one.
    keep.add(safeName(id, v, 'pdf'));
  }
}

function collectFromNode(keep, node, depth) {
  if (!node || typeof node !== 'object' || depth > NEST_DEPTH) return;
  if (Array.isArray(node)) {
    for (const el of node) collectFromNode(keep, el, depth);
    return;
  }
  addRecordNames(keep, node);
  // Only ARRAY-valued properties. A container is `{date, logs:[...]}`; walking
  // every object-valued property instead would wander into `log.data` and the
  // base64 photo blobs under it for no gain.
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) collectFromNode(keep, value, depth + 1);
  }
}

/** The on-disk names every cached list currently refers to, across all
 *  projects. Null -- distinct from an empty Set -- when the lists could not be
 *  read, because "I could not look" must never be treated as "nothing to
 *  keep". */
export async function collectKeepNames() {
  if (!canUseFs()) return null;
  try {
    const keys = (await AsyncStorage.getAllKeys()) || [];
    const listKeys = keys.filter((k) => String(k).startsWith(LIST_PREFIX));
    if (listKeys.length === 0) return null;   // no lists => no basis to delete

    const keep = new Set();
    for (const k of listKeys) {
      const raw = await AsyncStorage.getItem(k);
      if (!raw) continue;
      let list;
      try { list = JSON.parse(raw); } catch (_e) { return null; }
      if (!Array.isArray(list)) continue;
      collectFromNode(keep, list, 0);
    }
    return keep;
  } catch (_e) {
    return null;
  }
}

/** `{id}.{version}.{ext}` -> true. A name this cache did not write is left
 *  alone; we only remove what we can prove we created. */
const SWEEPABLE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9]+$/;

/**
 * Remove cached documents no stored list refers to any more.
 *
 * Returns {scanned, deleted, kept, skipped} — or {skipped: true, reason} when it
 * declined to act. Never throws: a housekeeping failure must not disturb a
 * screen, and must never cascade into deleting more than intended.
 */
export async function sweepDocCache({ dryRun = false } = {}) {
  if (!canUseFs()) return { skipped: true, reason: 'no-fs' };

  const keep = await collectKeepNames();
  // NULL MEANS WE COULD NOT LOOK. Deleting on an unknown keep-set would empty
  // the cache of a man about to go into a cellar.
  if (keep === null) return { skipped: true, reason: 'no-keep-set' };

  let names;
  try {
    names = await FileSystem.readDirectoryAsync(DOC_DIR);
  } catch (_e) {
    return { skipped: true, reason: 'unreadable-dir' };
  }
  if (!Array.isArray(names)) return { skipped: true, reason: 'unreadable-dir' };

  const deleted = [];
  let kept = 0;
  for (const name of names) {
    if (keep.has(name) || !SWEEPABLE.test(name)) { kept += 1; continue; }
    if (dryRun) { deleted.push(name); continue; }
    try {
      await FileSystem.deleteAsync(DOC_DIR + name, { idempotent: true });
      deleted.push(name);
    } catch (_e) {
      kept += 1;   // could not remove it; it stays, which is the safe direction
    }
  }
  return { scanned: names.length, deleted, kept };
}

/** Cached copy if present, else download it. Null if unavailable offline. */
export async function ensureCachedDocFile({ fileId, cacheVersion, remoteUrl, ext = 'pdf' }) {
  const hit = await getCachedDocFile(fileId, cacheVersion, ext);
  if (hit) return hit;
  return cacheDocFile({ fileId, cacheVersion, remoteUrl, ext });
}

/**
 * Warm the cache for a list of documents, newest first, bounded so a big
 * project doesn't pull hundreds of files on one screen open. Fire-and-forget:
 * callers should NOT await this on the render path.
 */
export async function warmDocCache(files, { limit = 25, idOf, versionOf, urlOf } = {}) {
  if (!canUseFs() || !Array.isArray(files)) return 0;
  let n = 0;
  for (const f of files.slice(0, limit)) {
    const fileId = idOf ? idOf(f) : (f.id || f._id);
    const remoteUrl = urlOf ? urlOf(f) : (f.r2_url || f.directUrl);
    const cacheVersion = versionOf ? versionOf(f) : (f.cache_version ?? 0);
    if (!fileId || !remoteUrl) continue;
    const got = await cacheDocFile({ fileId, cacheVersion, remoteUrl });
    if (got) n += 1;
  }
  return n;
}
