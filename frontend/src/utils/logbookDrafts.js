import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';
import * as FileSystem from 'expo-file-system';
import apiClient from './api';
import { isOfflineError } from './offlineState';

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

// Source uri -> persistent dest already copied this session.
//
// LATENCY: the persisted uri is NOT written back into screen state (the draft
// gets it, the form keeps its cache uri), so without this every debounced
// autosave re-copied EVERY photo in the log — O(photos) file copies per
// keystroke/capture, on the same JS thread the camera shutter needs. A given
// source uri always yields identical bytes, so one copy per source is enough.
// Process-scoped on purpose: a fresh launch re-copies, which is also the repair
// path if the documentDirectory file ever went missing.
const _persistedByUri = new Map();

/**
 * A failed copy, RAISED instead of swallowed.
 *
 * persistPhoto used to catch a failed copy and return the ORIGINAL cache uri.
 * That is exactly the mechanism the offline guarantee rests on: if the copy
 * fails, the draft keeps a CACHE uri, the OS evicts the file, and the photo is
 * gone with nothing anywhere having reported it. The write underneath "a photo
 * taken offline is never lost" cannot be allowed to fail invisibly, so it
 * doesn't any more. Every caller decides what to do; none of them may ignore it.
 */
export const PHOTO_PERSIST_FAILED = 'PHOTO_PERSIST_FAILED';

export const photoPersistError = (uri, cause) => Object.assign(
  new Error(`photo could not be persisted: ${(cause && cause.message) || cause}`),
  { name: 'PhotoPersistError', code: PHOTO_PERSIST_FAILED, sourceUri: uri, cause },
);

export async function persistPhoto(uri, id) {
  if (Platform.OS === 'web' || !FileSystem.documentDirectory) return uri;
  if (!uri || typeof uri !== 'string' || uri.startsWith(PHOTO_DIR)) return uri;
  const cached = _persistedByUri.get(uri);
  if (cached) return cached;
  await _ensurePhotoDir();
  const ext = ((uri.split('?')[0].split('.').pop()) || 'jpg').slice(0, 5);
  const dest = `${PHOTO_DIR}${id || Date.now()}_${Math.abs((id || '').length || 0)}.${ext}`;
  try {
    await FileSystem.copyAsync({ from: uri, to: dest });
  } catch (e) {
    throw photoPersistError(uri, e);
  }
  _persistedByUri.set(uri, dest);
  return dest;
}

/**
 * Does this photo have a copy that outlives the local file?
 *
 * The distinction matters because a photo can carry a `uri` from a DIFFERENT
 * device: a saved log round-trips its photo entries, stale capture paths and
 * all. A copy that fails for one of those is meaningless — the bytes are in R2
 * or inline, and the dead path is simply dropped. A copy that fails for a
 * FRESH capture is the data-loss case, and only that one is reported.
 */
export const hasDurableCopy = (p) => Boolean(
  p && (p.original_r2_key || p.enhanced_r2_key || p.thumb_r2_key
        || p.base64 || p.thumb_base64),
);

/** Persist every photo uri across a daily_jobsite activities array (base64 dropped). */
export async function persistActivityPhotos(activities) {
  if (!Array.isArray(activities)) return activities;
  return Promise.all(activities.map(async (a) => ({
    ...a,
    photos: await Promise.all((a.photos || []).map(async (p) => {
      const { base64, ...rest } = p; // never store base64 in the draft
      try {
        return { ...rest, uri: await persistPhoto(p.uri, p.id) };
      } catch (_e) {
        // NEVER RECORD A URI THE APP CANNOT PROVE IT OWNS. The draft is what
        // survives an app kill, so a cache path written here reads later as a
        // photo that exists — right up until it is opened and does not. The
        // uri is dropped instead, and a fresh capture is FLAGGED so the editor
        // can tell the CP to retake it. Never throws: one unpersistable photo
        // must not take the whole draft write down with it.
        const { uri, ...withoutUri } = rest;   // eslint-disable-line no-unused-vars
        return hasDurableCopy(rest)
          ? withoutUri
          : { ...withoutUri, persist_failed: true };
      }
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

/** Returns { data, cp_signature, cp_name, status, backend_id, finalized } or null. */
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
      // BUGFIX: writeDraft/markFinalized persist `finalized`, but readDraft did
      // not return it — so every editor's `draft.finalized` lock check was
      // silently ALWAYS FALSE and the offline finalize-lock never engaged (only
      // the server's is_locked did). Returning it makes the offline lock real.
      finalized: p.finalized ?? false,
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
    // itself can be recorded.
    //
    // CORRECTED (device round 5, finding 19). This used to say "corrections
    // happen through an amendment (a NEW key)" — and that was never true. The
    // key is (project, logType, date) and `amend_logbook` copies all three onto
    // the child, so parent and amendment collide on ONE key. Nothing ever
    // produced a new one. The lock was made absolute on the strength of an
    // escape hatch that did not exist, and for months the amendment a CP was
    // handed could not be reached: the editor read this finalized draft, locked,
    // and returned before asking the server for the child.
    //
    // WHAT ACTUALLY HAPPENS NOW: the lock stays absolute — a finalized draft is
    // never edited in place — and the correction escapes by REPLACING this
    // draft, not by writing beside it. `discardFinalizedDraft` below deletes the
    // record once the server confirms an unlocked child exists, and the next
    // load rebuilds from that child. See src/utils/amendmentAdopt.js.
    //
    // A finalized draft's CONTENT is immutable. Two exceptions, both metadata:
    //   • `finalized` itself (so markFinalized can set the flag), and
    //   • `backend_id` — binding the server id after a deferred push is
    //     bookkeeping, not a content edit. Without this the reconnect drain
    //     could never record where a log signed OFFLINE finally landed.
    if (prev?.finalized && patch.finalized === undefined) {
      const onlyBackendId =
        patch.backend_id !== undefined &&
        patch.data === undefined && patch.cp_signature === undefined &&
        patch.cp_name === undefined && patch.status === undefined;
      if (!onlyBackendId) return false;
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

/**
 * DELETE a draft outright, finalized or not.
 *
 * The ONE way past the finalize lock, and deliberately not a write: writeDraft
 * refuses to edit a finalized draft's content, and it should — a filed record
 * must never be mutated in place. An amendment is not an edit of the original;
 * it is a DIFFERENT server document. So the local record of the original is
 * discarded and the next load rebuilds from the child.
 *
 * Callers must have SERVER CONFIRMATION that the child exists before calling
 * this. Discarding on a hunch would drop the only offline copy of a filed log.
 */
export async function discardFinalizedDraft(key) {
  try {
    await AsyncStorage.removeItem(key);
    return true;
  } catch (_e) {
    return false;
  }
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

// ── CAPTURE-TIME PHOTO UPLOAD ───────────────────────────────────────────────
//
// A logbook is ONE MongoDB document with a 16MB ceiling. Inlining each photo
// as base64 cost ~200KB apiece, so ten subcontractors at ten photos each was
// ~20.5MB and the END-OF-DAY save was rejected outright — on a signed record,
// after the CP had done the whole day. So the bytes go to R2 as the photo is
// taken and the row carries only the key.
//
// THREE GUARANTEES, none of which is negotiable:
//
//   CAPTURE NEVER BLOCKS ON THE NETWORK. Nothing here is awaited on the
//   shutter path. The photo is in the row on the same frame it was taken, and
//   the upload is fired afterwards, unawaited.
//
//   A PHOTO TAKEN OFFLINE IS NEVER LOST. It is a real file in
//   documentDirectory (persistPhoto above) with its uri in the draft, so it
//   survives an app kill; the draft is in the pending index, so the reconnect
//   drain re-reads it and retries; and the upload key is a pure function of
//   three stable ids, so a retry overwrites its own object rather than
//   orphaning one.
//
//   THE CP NEVER SEES A BLANK TILE IN HIS OWN LOG. A row carries BOTH the
//   local uri AND `upload_pending`, and every reader tries the local file
//   first, so a photo with no key yet still draws from the device.

/** A photo whose bytes are not on the server yet, and that we can still send. */
export const photoNeedsUpload = (p) => Boolean(
  p && !p.original_r2_key && !p.upload_rejected && !p.persist_failed
    && !p.base64 && !p.thumb_base64 && p.uri,
);

/**
 * Upload ONE capture. Returns the R2 key. Throws on any failure.
 *
 * The server derives the object key from (project_id, activity_id, photo_id),
 * so this is idempotent: a retry after a dropped connection overwrites the
 * same object with the same bytes.
 */
export async function uploadCapturePhoto({ projectId, activityId, photoId, uri }) {
  if (!projectId || !photoId || !uri) {
    throw new Error('uploadCapturePhoto needs projectId, photoId and uri');
  }
  const form = new FormData();
  // A row created before `activity_id` existed has none. The photo id is the
  // fallback rather than the row's INDEX: an index stops naming the same row
  // the moment one is added, removed or reordered, which is the whole reason
  // the key is not positional in the first place.
  form.append('activity_id', String(activityId || photoId));
  form.append('photo_id', String(photoId));
  const isWeb = typeof window !== 'undefined' && !!window.document;
  if (isWeb) {
    const blob = await (await fetch(uri)).blob();
    form.append('file', blob, `${photoId}.jpg`);
  } else {
    form.append('file', { uri, name: `${photoId}.jpg`, type: 'image/jpeg' });
  }
  // The header dance dropboxAPI.uploadFile already documents: on web axios
  // must be allowed to set its own boundary, on native it must not
  // JSON-stringify the FormData.
  const response = await apiClient.post(
    `/api/projects/${projectId}/logbook-photo`, form,
    {
      timeout: 60000,
      headers: isWeb ? { 'Content-Type': undefined } : { 'Content-Type': 'multipart/form-data' },
      transformRequest: (d) => d,
    },
  );
  const key = response?.data?.original_r2_key;
  if (!key) throw new Error('upload returned no key');
  return key;
}

/**
 * Upload every photo in an activities array that still needs it.
 *
 * Returns { activities, uploaded, remaining, offline } and NEVER throws — a
 * failed upload is a deferral, not an error, and the caller's job is to leave
 * the draft pending rather than to fail.
 *
 * WHY IT STOPS EARLY. On the first OFFLINE failure, or the first 5xx, it
 * abandons the rest of the loop: there is one network and one storage backend,
 * so ninety-nine more attempts would fail identically and would do it while
 * the CP is waiting on his own save. An individual 4xx does NOT stop the loop
 * — that photo is being refused on its own merits, so it is marked
 * `upload_rejected` and never retried, and its siblings still go.
 */
export async function uploadPendingActivityPhotos(projectId, activities) {
  const out = { activities, uploaded: 0, remaining: 0, offline: false };
  if (!projectId || !Array.isArray(activities)) return out;

  let stop = false;
  const next = [];
  for (const activity of activities) {
    const photos = (activity && activity.photos) || [];
    const nextPhotos = [];
    for (const photo of photos) {
      if (stop || !photoNeedsUpload(photo)) {
        if (photoNeedsUpload(photo)) {
          // Skipped because the loop already gave up, not because it is fine.
          // It gets the marker too: the guarantee is that a row with no key
          // carries BOTH its local uri AND a pending-upload flag, so every
          // reader falls back to the device file instead of drawing a blank.
          out.remaining += 1;
          nextPhotos.push({ ...photo, upload_pending: true });
        } else {
          nextPhotos.push(photo);
        }
        continue;
      }
      try {
        const key = await uploadCapturePhoto({
          projectId,
          activityId: activity.activity_id,
          photoId: photo.id || photo.photo_id,
          uri: photo.uri,
        });
        const { upload_pending, ...rest } = photo;  // eslint-disable-line no-unused-vars
        nextPhotos.push({ ...rest, original_r2_key: key });
        out.uploaded += 1;
      } catch (e) {
        const status = e?.response?.status || 0;
        if (isOfflineError(e) || status >= 500 || !status) {
          // Nothing is wrong with the photo; the world is unreachable.
          out.offline = out.offline || isOfflineError(e);
          out.remaining += 1;
          nextPhotos.push({ ...photo, upload_pending: true });
          stop = true;
          continue;
        }
        // A 4xx names THIS photo. Retrying it forever would be a loop with no
        // exit; the local file and its uri stay, so the CP keeps seeing it.
        nextPhotos.push({ ...photo, upload_pending: true, upload_rejected: true });
      }
    }
    next.push(activity ? { ...activity, photos: nextPhotos } : activity);
  }
  out.activities = next;
  return out;
}

/** Are any photos in this activities array still waiting on an upload? */
export const hasPendingPhotoUploads = (activities) => (
  Array.isArray(activities)
  && activities.some((a) => ((a && a.photos) || []).some(photoNeedsUpload))
);
