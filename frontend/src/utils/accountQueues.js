import AsyncStorage from '@react-native-async-storage/async-storage';
import { decodeJwtPayload } from './sessionSurvival';

/**
 * WHOSE WRITES ARE THESE? The device-side queues belong to an ACCOUNT.
 *
 * Three stores on this device hold writes that replay against the API on their
 * own, at startup and on every reconnect:
 *
 *   blueview_offline_queue      offlineQueue.js — worker create/update/delete,
 *                               check-in review decisions (bare fetch)
 *   logbook_pending_push        logbookDrafts.js / draftSync.js — logbook draft
 *                               pushes, plus the logbook_draft:* records they
 *                               name (apiClient)
 *   logbook_filed_photo_queue   filedPhotoQueue.js — photographs for filed logs
 *                               (apiClient, multipart)
 *
 * None of them knew whose they were, and logout cleared none of them. So a
 * write one person made offline was sent after the NEXT login, under whatever
 * account signed in — possibly another company's. Two things close that:
 *
 *   1. LOGOUT EMPTIES THEM. clearAccountQueues below, called from clearAuth
 *      (every path that drops the token: explicit logout, a 401 the server
 *      means, a session that cannot be restored at boot) and, after a bounded
 *      drain, from AuthContext.logout via logoutQueues.drainAndClearAccountQueues.
 *
 *   2. REPLAY REFUSES ANOTHER ACCOUNT'S ITEM. Every item is stamped with its
 *      owner when it is queued, and each drain asks `openReplay().judge()`
 *      before sending one. That is the defence for the paths that do not go
 *      through a logout at all — a token that ran out and a different person
 *      signing in over it — and for a drain still in flight when the clear ran.
 *
 * ── THE OWNER IS READ OFF THE TOKEN, NOT OFF THE CACHED USER ──────────────────
 *
 * The account a request is sent under IS the token's subject; the cached user
 * (`blueview_user`) is a copy that lags it. AuthContext.login writes the new
 * token first and the new user only after /auth/me answers, so for one round
 * trip the cache still names the previous person while the token is already
 * the next one's. Comparing against the cache would send A's item under B's
 * token in exactly that window.
 *
 * The owner is `sub|company_id`, both claims create_token signs. The company is
 * part of it on purpose: one person reaching two companies must not carry a
 * write made in one into the other.
 */

// One source for the storage keys, imported by the modules that own them.
export const OFFLINE_QUEUE_KEY = 'blueview_offline_queue';
export const DRAFT_PENDING_KEY = 'logbook_pending_push';
export const FILED_PHOTO_QUEUE_KEY = 'logbook_filed_photo_queue';
// { [draftKey]: owner } — the pending index is a list of strings that every
// editor and test already reads, so the owner rides beside it, not inside it.
export const DRAFT_OWNER_KEY = 'logbook_pending_owner';
// The owner of the queues as a whole, for items queued before items carried
// their own stamp. Claimed by the first owner seen, removed with the queues.
export const QUEUE_OWNER_KEY = 'bv_queue_owner';

const DRAFT_PREFIX = 'logbook_draft:';
// api.js's getToken reads this key. Read here directly rather than imported:
// api.js imports THIS module (clearAuth), and the cycle is not worth one string.
const TOKEN_KEY = 'blueview_token';

/**
 * Everything else that belongs to the account and goes with it: the refusal
 * records the queues leave behind (they name another account's logs), and the
 * offline read caches of projects, check-ins and workers.
 */
const ACCOUNT_KEYS = [
  'logbook_filed_photo_rejected',
  'logbook_finalize_errors',
  'bv_projects_cache',
];
const ACCOUNT_PREFIXES = [
  'bv_project:',
  'bv_checkins_today:',
  'bv_checkins:',
  'bv_worker:',
  'bv_worker_osha:',
];

/** `sub|company_id` from a JWT, or null when the token names nobody. */
export function ownerOfToken(token) {
  const payload = decodeJwtPayload(token);
  if (!payload) return null;
  const sub = payload.sub;
  if (sub === undefined || sub === null || String(sub) === '') return null;
  return `${sub}|${payload.company_id || ''}`;
}

/** The owner of the session on disk right now, or null. */
export async function currentOwner() {
  try {
    return ownerOfToken(await AsyncStorage.getItem(TOKEN_KEY));
  } catch (_e) {
    return null;
  }
}

export const SEND = 'send';
export const DROP = 'drop';
export const HOLD = 'hold';

/**
 * Send, drop, or hold one queued item. PURE.
 *
 *   stamped item       sent only under its owner; any other account drops it;
 *                      no identity at all holds it (nobody to send it as).
 *   unstamped (legacy) judged by the queue's recorded owner the same way.
 *                      With no record either, it is sent — the old behaviour —
 *                      and the caller claims the record for whoever sent it, so
 *                      the next different account to sign in drops the rest.
 */
export function replayVerdict(itemOwner, me, queueOwner) {
  const owner = itemOwner || queueOwner || null;
  if (!owner) return SEND;
  if (!me) return HOLD;
  return owner === me ? SEND : DROP;
}

async function readJson(key, fallback) {
  try {
    const raw = await AsyncStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : fallback;
  } catch (_e) {
    return fallback;
  }
}

async function readList(key) {
  const v = await readJson(key, []);
  return Array.isArray(v) ? v : [];
}

async function claimQueueOwner(me) {
  if (!me) return;
  try {
    const existing = await AsyncStorage.getItem(QUEUE_OWNER_KEY);
    if (!existing) await AsyncStorage.setItem(QUEUE_OWNER_KEY, me);
  } catch (_e) { /* the item stamp still carries the owner */ }
}

/**
 * The owner to stamp on an item being queued now. Also claims the queue record
 * if nobody holds it, so legacy items already queued are judged as this
 * account's — they were queued in this same session.
 */
export async function ownerForEnqueue() {
  const me = await currentOwner();
  await claimQueueOwner(me);
  return me;
}

/** Record who queued a logbook draft push. Called by markPending. */
export async function stampDraftOwner(key) {
  if (!key) return;
  const me = await ownerForEnqueue();
  if (!me) return;
  try {
    const pending = await readList(DRAFT_PENDING_KEY);
    const owners = await readJson(DRAFT_OWNER_KEY, {});
    const next = {};
    // Pruned to what is still pending, so the map cannot outgrow the index.
    for (const k of pending) if (owners[k]) next[k] = owners[k];
    next[key] = me;
    await AsyncStorage.setItem(DRAFT_OWNER_KEY, JSON.stringify(next));
  } catch (_e) { /* the queue-owner record still covers it */ }
}

// Bumped by every clear. A drain that started before the clear sees it change
// and stops WRITING BACK — otherwise its final persist would put the cleared
// account's items back on disk for the next account's drain.
let _epoch = 0;
export const queueEpoch = () => _epoch;

/**
 * One drain's view of ownership. `token`, when given, is the token THIS drain
 * sends with (offlineQueue's bare fetch); otherwise the token on disk is read
 * at each judgement, because apiClient reads it at each request.
 */
export async function openReplay(token) {
  const epoch = _epoch;
  let queueOwner = null;
  try { queueOwner = await AsyncStorage.getItem(QUEUE_OWNER_KEY); } catch (_e) { /* none */ }
  let draftOwners = null;

  const judge = async (itemOwner) => {
    const me = token !== undefined ? ownerOfToken(token) : await currentOwner();
    const verdict = replayVerdict(itemOwner || null, me, queueOwner);
    if (verdict === SEND && !itemOwner && !queueOwner && me) {
      queueOwner = me;
      await claimQueueOwner(me);
    }
    return {
      verdict, me, send: verdict === SEND, drop: verdict === DROP, hold: verdict === HOLD,
    };
  };

  return {
    stale: () => _epoch !== epoch,
    judge,
    /** Judge a pending logbook draft by its key. */
    judgeDraft: async (key) => {
      if (!draftOwners) draftOwners = await readJson(DRAFT_OWNER_KEY, {});
      return judge(draftOwners[key] || null);
    },
    /**
     * Another account's pending draft: off the index, and its record deleted.
     * Left on disk it would still open in the next person's editor, and his
     * own save would file it under his name.
     */
    dropDraft: async (key) => {
      try {
        const pending = await readList(DRAFT_PENDING_KEY);
        await AsyncStorage.setItem(DRAFT_PENDING_KEY, JSON.stringify(pending.filter((k) => k !== key)));
        if (typeof key === 'string' && key.startsWith(DRAFT_PREFIX)) await AsyncStorage.removeItem(key);
      } catch (_e) { /* best effort; the next drain judges it again */ }
    },
  };
}

/** How many writes are still waiting on this device. */
export async function countPendingWrites() {
  const [offline, drafts, photos] = await Promise.all([
    readList(OFFLINE_QUEUE_KEY),
    readList(DRAFT_PENDING_KEY),
    readList(FILED_PHOTO_QUEUE_KEY),
  ]);
  return {
    offline: offline.length,
    drafts: drafts.length,
    photos: photos.length,
    total: offline.length + drafts.length + photos.length,
  };
}

/**
 * EMPTY EVERY QUEUE AND THE ACCOUNT'S CACHES. Sends nothing.
 *
 * The one routine for "this account is leaving the device": logout, a forced
 * logout, and — when one exists — an account switch. A drain, if wanted, comes
 * BEFORE this and is logoutQueues.drainAndClearAccountQueues' job.
 *
 * Deletes the logbook_draft:* records the pending index names (unsent work the
 * next person's editor would otherwise open), not every draft on the device.
 * NEVER THROWS: it runs inside clearAuth, and a logout must complete.
 */
export async function clearAccountQueues() {
  _epoch += 1;
  let counts = { offline: 0, drafts: 0, photos: 0, total: 0 };
  try { counts = await countPendingWrites(); } catch (_e) { /* still clear */ }
  const pending = await readList(DRAFT_PENDING_KEY);
  let allKeys = [];
  try { allKeys = (await AsyncStorage.getAllKeys()) || []; } catch (_e) { /* fixed keys only */ }
  const keys = [...new Set([
    OFFLINE_QUEUE_KEY, DRAFT_PENDING_KEY, DRAFT_OWNER_KEY, FILED_PHOTO_QUEUE_KEY, QUEUE_OWNER_KEY,
    ...ACCOUNT_KEYS,
    ...pending.filter((k) => typeof k === 'string' && k.startsWith(DRAFT_PREFIX)),
    ...allKeys.filter((k) => ACCOUNT_PREFIXES.some((p) => String(k).startsWith(p))),
  ])];
  try {
    await AsyncStorage.multiRemove(keys);
  } catch (_e) {
    for (const k of keys) {
      try { await AsyncStorage.removeItem(k); } catch (_e2) { /* best effort */ }
    }
  }
  if (counts.total) console.log(`[accountQueues] cleared ${counts.total} unsent write(s) at logout`);
  return counts;
}
