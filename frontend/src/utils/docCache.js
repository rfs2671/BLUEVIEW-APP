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
