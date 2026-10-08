import NetInfo from '@react-native-community/netinfo';
import { AppState, Platform } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import apiClient from './api';

/**
 * RECOVERING PHOTOS THAT EXIST ONLY ON THE PHONE THAT TOOK THEM.
 *
 * Operator's ruling, 2026-10-08. Two filed daily jobsite logs list photos that
 * never reached the server: each entry is `upload_pending` with a `file://`
 * path in this app's own documents folder. Nothing outside the app can read
 * that folder on a production build, so this is the only way to find out
 * whether the photos still exist -- and to bring them back if they do.
 *
 * WHY THEY WERE STRANDED. photoForPayload sends photos without their `id`
 * (deliberately: it is client bookkeeping), so the stored record has none. A
 * draft reloaded from the server then held pending photos with no id;
 * uploadCapturePhoto refused those before any request was made, and the upload
 * loop read that as "offline" and stopped. Fixed in logbookDrafts.js: an
 * id-less photo is named from its own file (photoIdFromUri), and a refusal
 * before any request no longer stops the loop.
 *
 * THE ORDER IS THE RULING: THE PROBE REPORTS WHAT IS ON THE PHONE BEFORE
 * ANYTHING UPLOADS.
 *   1. GET /photo-recovery/pending -- this account's stranded entries.
 *   2. For EVERY entry, read the file's presence (exists, size, time, md5)
 *      and POST it to /photo-recovery/{id}/presence. All reports are sent
 *      before step 3 begins.
 *   3. Only then, upload each file that exists to /photo-recovery/{id}/recover,
 *      which matches the entry by its own path and capture time. A file named
 *      by more than one entry is HELD there for the operator, not attached.
 *
 * QUIET BY DESIGN. Nothing here is shown to the CP: a failure is left for the
 * next startup, reconnect or foreground, exactly like the filed-photo drain.
 */

let inFlight = null;

const canReadFiles = () => Platform.OS !== 'web' && !!FileSystem.documentDirectory;

async function fileFacts(uri) {
  try {
    const info = await FileSystem.getInfoAsync(uri, { md5: true, size: true });
    if (!info || !info.exists) return { exists: false };
    return {
      exists: true,
      size: typeof info.size === 'number' ? info.size : null,
      modification_time: typeof info.modificationTime === 'number' ? info.modificationTime : null,
      md5: info.md5 || null,
    };
  } catch (_e) {
    // AN UNREADABLE FILE IS REPORTED AS NOT THERE: the server is told what the
    // phone could establish, never more.
    return { exists: false };
  }
}

async function uploadOne(logbookId, item) {
  const form = new FormData();
  form.append('activity_index', String(item.activity_index));
  form.append('photo_index', String(item.photo_index));
  form.append('uri', item.uri);
  form.append('timestamp', item.timestamp || '');
  const name = String(item.uri).split('/').pop() || 'photo.jpg';
  form.append('file', { uri: item.uri, name, type: 'image/jpeg' });
  const res = await apiClient.post(
    `/api/photo-recovery/${encodeURIComponent(logbookId)}/recover`, form,
    {
      timeout: 60000,
      headers: { 'Content-Type': 'multipart/form-data' },
      transformRequest: (d) => d,
    },
  );
  return res && res.data;
}

/**
 * One pass. Returns {pending, reported, present, uploaded, held, failed,
 * outcome} -- `outcome` is where it stopped ('done', 'no-files', 'unreachable').
 */
export async function runPhotoRecovery(opts = {}) {
  const fs = opts.canReadFiles || canReadFiles;
  const out = { pending: 0, reported: 0, present: 0, uploaded: 0, held: 0, failed: 0, outcome: 'done' };
  if (!fs()) return { ...out, outcome: 'no-files' };

  let items;
  try {
    const res = await apiClient.get('/api/photo-recovery/pending', { timeout: 30000 });
    items = (res && res.data && Array.isArray(res.data.items)) ? res.data.items : [];
  } catch (_e) {
    return { ...out, outcome: 'unreachable' };
  }
  out.pending = items.length;
  if (items.length === 0) return out;

  // ── 1. THE PROBE, FOR EVERY ENTRY, BEFORE ANY UPLOAD ──────────────────────
  const facts = [];
  for (const it of items) facts.push({ it, f: await fileFacts(it.uri) });
  const byLog = new Map();
  for (const { it, f } of facts) {
    if (!byLog.has(it.logbook_id)) byLog.set(it.logbook_id, []);
    byLog.get(it.logbook_id).push({
      activity_index: it.activity_index, photo_index: it.photo_index,
      uri: it.uri, timestamp: it.timestamp || null, ...f,
    });
    if (f.exists) out.present += 1;
  }
  for (const [logId, reports] of byLog) {
    try {
      await apiClient.post(`/api/photo-recovery/${encodeURIComponent(logId)}/presence`,
        { reports, device: { platform: Platform.OS } }, { timeout: 30000 });
      out.reported += reports.length;
    } catch (_e) {
      // NO UPLOAD WITHOUT A REPORT. If the phone's account of itself did not
      // land, nothing is sent this pass; the next one reports first again.
      return { ...out, outcome: 'unreachable' };
    }
  }

  // ── 2. ONLY NOW, THE BYTES ────────────────────────────────────────────────
  for (const { it, f } of facts) {
    if (!f.exists) continue;
    try {
      const r = await uploadOne(it.logbook_id, it);
      if (r && r.status === 'held_for_review') out.held += 1;
      else out.uploaded += 1;
    } catch (_e) {
      out.failed += 1;
    }
  }
  return out;
}

/** Once at a time; a second trigger while one runs shares it. */
export function runPhotoRecoveryOnce(opts) {
  if (!inFlight) {
    inFlight = runPhotoRecovery(opts).finally(() => { inFlight = null; });
  }
  return inFlight;
}

/** Startup, reconnect and foreground -- the filed-photo drain's three moments. */
export function setupPhotoRecovery() {
  let wasOnline = true;
  let lastAppState = (AppState && AppState.currentState) || 'active';
  const fire = () => { runPhotoRecoveryOnce().catch(() => {}); };
  const unsubNet = NetInfo.addEventListener((state) => {
    const online = state.isConnected && state.isInternetReachable !== false;
    if (online && !wasOnline) fire();
    wasOnline = online;
  });
  const appSub = AppState.addEventListener('change', (next) => {
    if (next === 'active' && lastAppState !== 'active') fire();
    lastAppState = next;
  });
  fire();
  return () => {
    try { if (typeof unsubNet === 'function') unsubNet(); } catch (_e) { /* best effort */ }
    try { if (appSub && typeof appSub.remove === 'function') appSub.remove(); } catch (_e) { /* best effort */ }
  };
}

export default runPhotoRecovery;
