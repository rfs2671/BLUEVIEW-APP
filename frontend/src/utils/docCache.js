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

/**
 * The same read, but ABSENT IS DISTINGUISHABLE FROM EMPTY.
 *
 * readCachedDocList above answers `[]` to both "no such key" and "a list that
 * really is empty", which is right for a screen — it has nothing to enumerate
 * either way. It is exactly wrong for a reader assembling a list out of
 * indexed chunks: a missing chunk is a BROKEN manifest and an empty one is a
 * legitimate (if odd) part of a whole one, and collapsing them is how a
 * half-written manifest comes back looking complete and short.
 *
 * Returns null for absent, unparseable, or not-an-array.
 */
export async function readCachedDocListOrNull(scopeKey) {
  if (!scopeKey) return null;
  try {
    const raw = await AsyncStorage.getItem(LIST_PREFIX + scopeKey);
    if (raw === null || raw === undefined) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : null;
  } catch (_e) { return null; }
}

/** Every stored scope key, prefix stripped. The prefix stays private to this
 *  module — collectKeepNames below is keyed on it, so a caller inventing its
 *  own keys outside it would write lists the sweep cannot see, and the sweep
 *  would delete the files those lists were keeping. */
export async function listDocListScopes() {
  try {
    const keys = (await AsyncStorage.getAllKeys()) || [];
    return keys
      .filter((k) => String(k).startsWith(LIST_PREFIX))
      .map((k) => String(k).slice(LIST_PREFIX.length));
  } catch (_e) { return []; }
}

/** Drop a stored list. Returns whether it went. Never throws: this is only
 *  ever housekeeping, and housekeeping that can throw becomes a caller that
 *  abandons a correctly written manifest halfway through tidying up after it. */
export async function removeDocList(scopeKey) {
  if (!scopeKey) return false;
  try {
    await AsyncStorage.removeItem(LIST_PREFIX + scopeKey);
    return true;
  } catch (_e) { return false; }
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

/**
 * A LENGTH WE CAN ACTUALLY CHECK AGAINST, OR NOTHING.
 *
 * The backend writes `size` on every file record, and defaults it to 0 when
 * Dropbox did not report one (server.py: `entry.get("size", 0)`). 0 is
 * therefore "unknown", not "empty" — enforcing it would reject every good
 * download of a file whose size the listing lost. Same for a missing field, a
 * string, NaN. Only a positive finite number is a length.
 */
function expectedBytes(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * Local uri if this exact {id}.{version} is already on disk, else null.
 *
 * `expectedSize` is optional and comes from the list record. WHY THE READ PATH
 * CHECKS IT AT ALL, when the write path below can no longer produce a short
 * file: every tablet in the field is already carrying fragments written by the
 * old non-atomic download, and the only thing that removes them is
 * sweepDocCache — whose one call site is the CP files screen, unreachable from
 * /site/*. A gate tablet would serve its corrupt copy for ever. Comparing
 * against the length the list already carries clears them on first open, at
 * the cost of one number.
 */
export async function getCachedDocFile(fileId, cacheVersion, ext = 'pdf', { expectedSize } = {}) {
  if (!canUseFs() || !fileId) return null;
  try {
    const uri = DOC_DIR + safeName(fileId, cacheVersion, ext);
    const info = await FileSystem.getInfoAsync(uri);
    if (!info.exists || !(info.size > 0)) return null;
    const want = expectedBytes(expectedSize);
    if (want !== null && Number(info.size) !== want) return null;
    return uri;
  } catch (_e) { return null; }
}

/**
 * Download a document to the persistent cache. `remoteUrl` may be the relative
 * proxy path the API returns; it is resolved against the API base. Auth rides
 * in the header. Returns the local uri, or null on failure (never throws — a
 * caching failure must not break viewing while online).
 *
 * NOTHING PARTIAL EVER WEARS THE REAL NAME.
 *
 * expo-file-system 19.0.24's legacy downloadAsync streams the response body
 * straight into the path it is handed. On Android (FileSystemLegacyModule.kt,
 * inside OkHttp's onResponse) that is literally
 *
 *     val file = uri.toFile(); file.delete()
 *     val sink = file.sink().buffer()
 *     sink.writeAll(response.body!!.source())
 *
 * — an okio buffered sink flushing 8KiB segments to the destination as they
 * arrive. A connection dropped mid-body throws out of writeAll and leaves every
 * flushed segment on disk under that exact name. Worse, OkHttp 4.9.2 has
 * already set `signalledCallback = true` before calling onResponse, so the
 * IOException is only LOGGED: the promise never settles, and the `catch` here
 * never runs at all. There is no error handler that can clean up after that.
 *
 * So the download is aimed at `{name}.part` and only ever RENAMED into place
 * once it is complete and (when a length is known) the right length. Android's
 * moveAsync is File.renameTo on the same volume — one atomic rename that
 * replaces the destination; iOS' removes the destination and moves. Either way
 * a reader sees the old whole file or the new whole file, never a fragment.
 *
 * A `.part` left behind by a hung promise or a killed process is bounded at one
 * per file — the temp name is deterministic, so the next attempt overwrites it
 * — and it deliberately does NOT match the sweep's `{id}.{version}.{ext}`
 * grammar, so a sweep can never delete a transfer that is still running.
 *
 * `expectedSize` is optional: the plans and documents screens carry `size` on
 * every record, the logbook screens carry none, and both must work.
 */
export async function cacheDocFile({ fileId, cacheVersion, remoteUrl, ext = 'pdf', expectedSize } = {}) {
  if (!canUseFs() || !fileId || !remoteUrl) return null;
  const dest = DOC_DIR + safeName(fileId, cacheVersion, ext);
  const part = `${dest}.part`;
  const want = expectedBytes(expectedSize);
  const scrub = async () => {
    try { await FileSystem.deleteAsync(part, { idempotent: true }); } catch (_e) {}
  };

  try {
    await ensureDir();

    // ALREADY ON DISK — but only if it is the file we were asked for. The old
    // early-return took any non-empty file, which is what made a truncated
    // plan permanent: it was never re-downloaded, so nothing could correct it.
    const existing = await FileSystem.getInfoAsync(dest);
    if (existing.exists && existing.size > 0 && (want === null || Number(existing.size) === want)) {
      return dest;
    }
    // A WRONG-LENGTH FILE IS NOT DELETED HERE, only refused as a hit. Deleting
    // it up front and then losing the connection would take a drawing off a
    // phone in a cellar and put nothing back — the failure this module refuses
    // everywhere else. It stays where it is, unserved (getCachedDocFile checks
    // the same length), until the rename below replaces it with a whole file.

    const base = apiClient?.defaults?.baseURL || '';
    const url = /^https?:\/\//i.test(remoteUrl) ? remoteUrl : `${base}${remoteUrl}`;
    const token = await getToken();
    const res = await FileSystem.downloadAsync(url, part, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (res?.status !== 200 || !res?.uri) { await scrub(); return null; }

    // VERIFY BEFORE PROMOTING. A 200 whose body was cut short still resolves —
    // the transport reports success and the file is simply the wrong size.
    const got = await FileSystem.getInfoAsync(part);
    if (!got.exists || !(got.size > 0)) { await scrub(); return null; }
    if (want !== null && Number(got.size) !== want) { await scrub(); return null; }

    try {
      await FileSystem.moveAsync({ from: part, to: dest });
    } catch (_e) {
      // A rename that refuses because the destination exists: clear it and
      // retry once. Still atomic from a reader's point of view in the sense
      // that matters — the only thing that can appear at `dest` is whole.
      try { await FileSystem.deleteAsync(dest, { idempotent: true }); } catch (_e2) {}
      await FileSystem.moveAsync({ from: part, to: dest });
    }
    return dest;
  } catch (_e) {
    // THE OUTER CATCH CLEANS UP. This is the path a dropped connection takes,
    // and it used to return null having deleted nothing.
    await scrub();
    return null;
  }
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

/**
 * Can this platform hold files at all?
 *
 * listCachedDocs() returns an EMPTY SET both for "the directory is empty" and
 * for "there is no directory on this platform" — correct for its own callers,
 * which only ever ask whether a specific name is present, and wrong for a
 * caller that wants to COUNT. On web the empty set would read as "nothing is
 * saved", and a screen would print "0 of 15 saved" about a device that has no
 * such thing as saving. This separates the two so a count can be withheld
 * rather than fabricated.
 */
export function canCacheDocs() {
  return canUseFs();
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

/** Cached copy if present, else download it. Null if unavailable offline.
 *  `expectedSize` (the list record's `size`, when it has one) is checked on
 *  BOTH halves: a fragment already on disk fails the hit, and a short download
 *  fails the fetch. */
export async function ensureCachedDocFile({ fileId, cacheVersion, remoteUrl, ext = 'pdf', expectedSize } = {}) {
  const hit = await getCachedDocFile(fileId, cacheVersion, ext, { expectedSize });
  if (hit) return hit;
  return cacheDocFile({ fileId, cacheVersion, remoteUrl, ext, expectedSize });
}

/**
 * Warm the cache for a list of documents, newest first, bounded so a big
 * project doesn't pull hundreds of files on one screen open. Fire-and-forget:
 * callers should NOT await this on the render path.
 */
export async function warmDocCache(files, { limit = 25, idOf, versionOf, urlOf, sizeOf } = {}) {
  if (!canUseFs() || !Array.isArray(files)) return 0;
  let n = 0;
  for (const f of files.slice(0, limit)) {
    const fileId = idOf ? idOf(f) : (f.id || f._id);
    const remoteUrl = urlOf ? urlOf(f) : (f.r2_url || f.directUrl);
    const cacheVersion = versionOf ? versionOf(f) : (f.cache_version ?? 0);
    // `size` on the Dropbox/upload record. Absent on logbook records, which is
    // why it is read defensively rather than required.
    const expectedSize = sizeOf ? sizeOf(f) : f?.size;
    if (!fileId || !remoteUrl) continue;
    const got = await cacheDocFile({ fileId, cacheVersion, remoteUrl, expectedSize });
    if (got) n += 1;
  }
  return n;
}
