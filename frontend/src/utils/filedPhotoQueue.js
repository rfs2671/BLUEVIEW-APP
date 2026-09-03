import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import { AppState } from 'react-native';
import { appendPhotoToFiledLog } from './logbookDrafts';
import { isOfflineError } from './offlineState';

/**
 * A PHOTOGRAPH FOR A FILED LOG, HELD ON THE DEVICE UNTIL IT CAN GO.
 *
 * WHY THIS EXISTS AND WHY IT IS NOT THE GENERIC QUEUE. offlineQueue.js posts
 * JSON bodies to four collection endpoints; this carries a FILE, by multipart,
 * to a route addressed by logbook id. It cannot ride that queue without
 * teaching it about multipart, so it is its own store — and it follows the
 * house idioms that queue established (an AsyncStorage list, a named
 * queue/clear pair, a drain wired to NetInfo) rather than inventing a shape.
 *
 * THE REASON IT IS NOT A FOLLOW-UP: photographs are taken in cellars. A screen
 * that only works online is the wrong shape for the only place photographs
 * come from, and a photo that fails silently because there was no signal is
 * the same defect class as everything else this codebase has been bitten by.
 *
 * ── WHAT IS QUEUED ─────────────────────────────────────────────────────────
 *
 * UNREACHABLE, OR A 5xx. Nothing is wrong with the photograph; the world is
 * away. A 4xx is NOT queued and never will be: it names THIS photograph — the
 * row has no identity, the log is gone, the file is not an image — and
 * replaying a refusal never succeeds. A queue that holds one retries it until
 * the install is wiped. This is the same split uploadPendingActivityPhotos
 * makes with `upload_rejected`, and `shouldQueueError` below is the one place
 * it is written so the screen and the drain cannot disagree.
 *
 * ── WHAT IS NEVER CLAIMED ──────────────────────────────────────────────────
 *
 * That the photograph is on the record. It is on the DEVICE. The screen says
 * that, with toast.warning, and en.logbookPhotos owns the wording.
 *
 * ── IDEMPOTENCY IS THE SERVER'S ────────────────────────────────────────────
 *
 * The R2 key is a pure function of (project_id, activity_id, photo_id) and the
 * document write carries an $elemMatch precondition refusing a photo already
 * on the row, so a replayed upload cannot double-post. NOTHING HERE ADDS A
 * SECOND MECHANISM — a third rule to keep in agreement with those two is a
 * liability, not a safety net. The client's ONE obligation is that the photo id
 * is minted ONCE, at queue time, and reused on every replay: a fresh id is a
 * fresh key, and the record would carry two tiles of one photograph.
 *
 * ── AND THE DRAIN IS ACTUALLY INVOKED ──────────────────────────────────────
 *
 * setupFiledPhotoAutoDrain wires reconnect, foreground and startup, and
 * app/_layout.jsx calls it. `sendPendingSignatures` is why that sentence is
 * written down: it existed, it was correct, and nothing ever called it.
 */

const QUEUE_KEY = 'logbook_filed_photo_queue';
const REJECTED_KEY = 'logbook_filed_photo_rejected';

// How many refusals to remember. Bounded because this is a diagnostic surface,
// not a record: the RECORD is the server's, and a device that has been refused
// two hundred times has one problem, not two hundred.
const REJECTED_MAX = 50;

async function readList(key) {
  try {
    const raw = await AsyncStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (_e) {
    return [];
  }
}

async function writeList(key, list) {
  try {
    await AsyncStorage.setItem(key, JSON.stringify(list));
    return true;
  } catch (e) {
    // ANNOUNCED, NOT SWALLOWED. A device that has stopped storing looks
    // exactly like one that is working, and the thing it stops storing here is
    // the only copy of a photograph that has not been uploaded.
    console.warn('[filedPhotoQueue] write FAILED for', key, '—', e?.message || e);
    return false;
  }
}

/**
 * TRY THIS AGAIN LATER, OR NEVER? The one place that decision is made.
 *
 * True for unreachable and for 5xx (including a thrown error carrying no
 * response at all, which is what axios gives on a dead radio). False for every
 * 4xx: that is the server judging this photograph, and the answer will not
 * change on the next attempt.
 */
export function shouldQueueError(e) {
  if (!e) return false;
  const status = e?.response?.status || 0;
  if (status >= 400 && status < 500) return false;
  if (status >= 500) return true;
  return isOfflineError(e) || !status;
}

/**
 * Hold ONE photograph for a filed log.
 *
 * `uri` MUST already be a persistent documentDirectory path (persistPhoto).
 * A cache uri is evicted by the OS, and a queue entry pointing at an evicted
 * file is a photograph the app reports as safe and cannot produce.
 *
 * `photoId` is the caller's, minted once at capture — see the idempotency note
 * at the top. It is also the dedupe key: re-queueing the same id replaces the
 * earlier entry rather than adding a second attempt at the same object.
 */
export async function queueFiledPhoto({
  logbookId, activityId, photoId, uri, logType = null, label = null,
}) {
  if (!logbookId || !activityId || !photoId || !uri) {
    throw new Error(
      'queueFiledPhoto needs logbookId, activityId, photoId and uri',
    );
  }
  const queue = await readList(QUEUE_KEY);
  const next = queue.filter((it) => it && it.photoId !== photoId);
  next.push({
    logbookId: String(logbookId),
    activityId: String(activityId),
    photoId: String(photoId),
    uri: String(uri),
    logType,
    label,
    queuedAt: Date.now(),
  });
  return writeList(QUEUE_KEY, next);
}

/** Everything still held, optionally narrowed to one log. */
export async function getQueuedFiledPhotos(logbookId = null) {
  const queue = await readList(QUEUE_KEY);
  if (!logbookId) return queue;
  return queue.filter((it) => it && it.logbookId === String(logbookId));
}

/** Drop one held photograph — used when the same one just landed online. */
export async function clearQueuedFiledPhoto(photoId) {
  if (!photoId) return;
  const queue = await readList(QUEUE_KEY);
  const next = queue.filter((it) => it && it.photoId !== String(photoId));
  if (next.length !== queue.length) await writeList(QUEUE_KEY, next);
}

/** Photographs the server REFUSED, so the screen can say so rather than lose them. */
export async function getRejectedFiledPhotos(logbookId = null) {
  const list = await readList(REJECTED_KEY);
  if (!logbookId) return list;
  return list.filter((it) => it && it.logbookId === String(logbookId));
}

/** Acknowledge a refusal — the CP has read it. */
export async function clearRejectedFiledPhoto(photoId) {
  if (!photoId) return;
  const list = await readList(REJECTED_KEY);
  const next = list.filter((it) => it && it.photoId !== String(photoId));
  if (next.length !== list.length) await writeList(REJECTED_KEY, next);
}

async function recordRejection(item, e) {
  const detail = e?.response?.data?.detail;
  const code = (detail && typeof detail === 'object' && detail.code)
    || e?.code || null;
  const list = await readList(REJECTED_KEY);
  const next = list.filter((it) => it && it.photoId !== item.photoId);
  next.push({
    ...item,
    rejectedAt: Date.now(),
    status: e?.response?.status || 0,
    code,
    remediable: Boolean(detail && typeof detail === 'object' && detail.remediable),
  });
  await writeList(REJECTED_KEY, next.slice(-REJECTED_MAX));
}

// Serialised: two drains racing would post the same object twice. Harmless
// against the server's precondition, wasteful against a jobsite LTE bill.
let _draining = false;

/**
 * Send every held photograph. Safe to call repeatedly. NEVER THROWS.
 *
 * STOPS ON THE FIRST UNREACHABLE-OR-5xx, exactly as uploadPendingActivityPhotos
 * does and for the same reason: there is one network and one storage backend,
 * so ninety-nine more attempts fail identically and do it on the CP's battery.
 */
export async function drainFiledPhotoQueue() {
  const out = {
    attempted: 0, uploaded: 0, remaining: 0, rejected: 0, offline: false,
  };
  if (_draining) return out;
  _draining = true;
  try {
    const queue = await readList(QUEUE_KEY);
    if (!queue.length) return out;

    const keep = [];
    let stop = false;
    for (const item of queue) {
      if (!item || !item.logbookId || !item.activityId || !item.photoId || !item.uri) {
        // Not a queue entry. Dropping it is the only option that terminates.
        continue;
      }
      if (stop) { keep.push(item); out.remaining += 1; continue; }
      out.attempted += 1;
      try {
        await appendPhotoToFiledLog({
          logbookId: item.logbookId,
          activityId: item.activityId,
          photoId: item.photoId,
          uri: item.uri,
        });
        out.uploaded += 1;
      } catch (e) {
        if (shouldQueueError(e)) {
          out.offline = out.offline || isOfflineError(e);
          keep.push(item);
          out.remaining += 1;
          stop = true;
          continue;
        }
        // A 4xx NAMES THIS PHOTOGRAPH. It leaves the queue — retrying it is a
        // loop with no exit — and it is RECORDED, because a photograph that
        // silently disappears is the failure this whole feature exists to
        // prevent. The local file is untouched; the screen offers the refusal.
        out.rejected += 1;
        await recordRejection(item, e);
      }
    }
    await writeList(QUEUE_KEY, keep);
    if (out.uploaded) {
      console.log(`[filedPhotoQueue] uploaded ${out.uploaded} held photograph(s)`);
    }
    return out;
  } catch (e) {
    console.warn('[filedPhotoQueue] drain failed:', e?.message || e);
    return out;
  } finally {
    _draining = false;
  }
}

/**
 * WIRE THE DRAIN. Returns an unsubscribe.
 *
 * THREE TRIGGERS, and none of them is redundant:
 *
 *   STARTUP    the app was killed in the cellar with a photograph held. A
 *              listener alone waits forever for a transition that already
 *              happened. This is the line sendPendingSignatures never had.
 *   RECONNECT  offline -> online. The cellar case: he walks up the stairs.
 *   FOREGROUND the phone was in his pocket with the screen off and the radio
 *              asleep; NetInfo may report no transition at all, and the first
 *              thing that happens on the way back is the app becoming active.
 *
 * The reconnect fires on the TRANSITION only. NetInfo emits on every network
 * change — a cell handoff, a signal-strength blip — and draining on each would
 * be an upload attempt per event.
 */
export function setupFiledPhotoAutoDrain() {
  let wasOnline = true;
  let lastAppState = (AppState && AppState.currentState) || 'active';

  const fire = () => { drainFiledPhotoQueue().catch(() => {}); };

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

export default drainFiledPhotoQueue;
