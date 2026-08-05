import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';
import * as FileSystem from 'expo-file-system';

// ── Persistent photos for offline drafts ────────────────────────────────────
// Captured photos land in the OS cache dir (ImageManipulator / picker), which
// can be evicted — so a URI stored in a draft can dangle after quit. Copy the
// file into documentDirectory (persistent) and store THAT uri in the draft;
// base64 is never stored (it would blow AsyncStorage's size cap). No-op on web
// (no FileSystem) and idempotent (already-persistent uris are returned as-is).
const PHOTO_DIR = (FileSystem.documentDirectory || '') + 'logbook_photos/';

async function _ensurePhotoDir() {
  try {
    const info = await FileSystem.getInfoAsync(PHOTO_DIR);
    if (!info.exists) await FileSystem.makeDirectoryAsync(PHOTO_DIR, { intermediates: true });
  } catch (_e) { /* non-fatal */ }
}

export async function persistPhoto(uri, id) {
  if (Platform.OS === 'web' || !FileSystem.documentDirectory) return uri;
  if (!uri || typeof uri !== 'string' || uri.startsWith(PHOTO_DIR)) return uri;
  try {
    await _ensurePhotoDir();
    const ext = ((uri.split('?')[0].split('.').pop()) || 'jpg').slice(0, 5);
    const dest = `${PHOTO_DIR}${id || Date.now()}_${Math.abs((id || '').length || 0)}.${ext}`;
    await FileSystem.copyAsync({ from: uri, to: dest });
    return dest;
  } catch (_e) {
    return uri; // fall back to the original uri if the copy fails
  }
}

/** Persist every photo uri across a daily_jobsite activities array (base64 dropped). */
export async function persistActivityPhotos(activities) {
  if (!Array.isArray(activities)) return activities;
  return Promise.all(activities.map(async (a) => ({
    ...a,
    photos: await Promise.all((a.photos || []).map(async (p) => {
      const uri = await persistPhoto(p.uri, p.id);
      const { base64, ...rest } = p; // never store base64 in the draft
      return { ...rest, uri };
    })),
  })));
}

/**
 * Phase A — local-first CP logbook drafts on AsyncStorage.
 *
 * Modelled on the app's proven write-through cache pattern (useCpProfile.js's
 * CP_PROFILE_CACHE_KEY, and `blueview_user`): read local first, write local on
 * every change, push to the server best-effort. Deliberately NOT WatermelonDB
 * (dormant/abandoned — see the followup) and NOT the check-in queue — pure
 * AsyncStorage key/value, so it OTAs and adds no native module, no DB init, no
 * schema migration, no startup cost.
 *
 * Keys are namespaced under `logbook_draft:` and keyed by the logbook's natural
 * identity (project, log_type, date [, worker_id]) — the same key the server
 * dedups on — so a draft never collides with a different day/type/project, and
 * never with check-in storage (which uses its own unrelated keys). AsyncStorage
 * falls back to localStorage on web, so this works on web too.
 *
 * `logbook_pending_push` is a list of draft keys whose server push has not yet
 * landed. Phase A only records into it (on a failed/offline push); the Phase B
 * reconnect flush is what drains it.
 */

const PREFIX = 'logbook_draft:';
const PENDING_KEY = 'logbook_pending_push';

export function draftKey({ projectId, logType, date, workerId }) {
  const base = `${PREFIX}${projectId}:${logType}:${date}`;
  return workerId ? `${base}:${workerId}` : base;
}

/** Returns { data, cp_signature, cp_name, status, backend_id } or null. */
export async function readDraft(key) {
  try {
    const raw = await AsyncStorage.getItem(key);
    if (!raw) return null;
    const p = JSON.parse(raw);
    return {
      data: p.data || {},
      cp_signature: p.cp_signature ?? null,
      cp_name: p.cp_name ?? null,
      status: p.status || 'draft',
      backend_id: p.backend_id ?? null,
    };
  } catch (_e) {
    return null;
  }
}

/**
 * Persist the draft locally. `patch` may carry any of
 * { data, cp_signature, cp_name, status, backend_id }; fields left `undefined`
 * are preserved from the existing draft — so a per-field autosave (which omits
 * `status`) never downgrades a 'submitted' log back to 'draft', and a
 * server-id bind never wipes the payload.
 */
export async function writeDraft(key, patch) {
  try {
    const prev = await readDraft(key);
    // Tier 1 (1): a FINALIZED (locked) log is immutable — the offline draft store
    // refuses further edits, mirroring the backend 423 guard. Only a patch that
    // explicitly sets `finalized` (the markFinalized call) passes, so the lock
    // itself can be recorded. Corrections happen through an amendment (a NEW key).
    if (prev?.finalized && patch.finalized === undefined) {
      return false;
    }
    const merged = {
      data: patch.data !== undefined ? patch.data : (prev?.data || {}),
      cp_signature: patch.cp_signature !== undefined ? patch.cp_signature : (prev?.cp_signature ?? null),
      cp_name: patch.cp_name !== undefined ? patch.cp_name : (prev?.cp_name ?? null),
      status: patch.status !== undefined ? patch.status : (prev?.status || 'draft'),
      backend_id: patch.backend_id !== undefined ? patch.backend_id : (prev?.backend_id ?? null),
      finalized: patch.finalized !== undefined ? patch.finalized : (prev?.finalized ?? false),
      updated_at: Date.now(),
    };
    await AsyncStorage.setItem(key, JSON.stringify(merged));
    return true;
  } catch (_e) {
    return false;
  }
}

/** Bind the server document id onto the local draft after a successful push. */
export async function setDraftBackendId(key, backendId) {
  return writeDraft(key, { backend_id: backendId });
}

/**
 * Tier 1 (1): mark a local draft FINALIZED (locked). After this, writeDraft
 * no-ops for this key, so a finalized log can never be re-edited offline. An
 * editor calls this when it loads a log whose server doc is `is_locked`.
 */
export async function markFinalized(key) {
  return writeDraft(key, { finalized: true });
}

// ── pending-push index (Phase B drains this; Phase A only records) ──────────

export async function markPending(key) {
  try {
    const raw = await AsyncStorage.getItem(PENDING_KEY);
    const list = raw ? JSON.parse(raw) : [];
    if (!list.includes(key)) {
      list.push(key);
      await AsyncStorage.setItem(PENDING_KEY, JSON.stringify(list));
    }
  } catch (_e) { /* non-fatal — the draft itself is already safe locally */ }
}

export async function clearPending(key) {
  try {
    const raw = await AsyncStorage.getItem(PENDING_KEY);
    if (!raw) return;
    const list = JSON.parse(raw).filter((k) => k !== key);
    await AsyncStorage.setItem(PENDING_KEY, JSON.stringify(list));
  } catch (_e) { /* non-fatal */ }
}

export async function getPendingKeys() {
  try {
    const raw = await AsyncStorage.getItem(PENDING_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (_e) {
    return [];
  }
}
