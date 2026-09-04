import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import { getToken, newRequestId, REQUEST_ID_HEADER } from './api';

const QUEUE_KEY = 'blueview_offline_queue';
const MAX_RETRIES = 3;

/**
 * ONE DRAIN AT A TIME, DECIDED SYNCHRONOUSLY.
 *
 * WHAT THIS REPLACES, AND WHY IT WAS NOT A LOCK. `acquireSyncLock` read
 * `blueview_sync_lock` from AsyncStorage, and if it was absent or older than
 * 30s, wrote it back:
 *
 *     const existing = await AsyncStorage.getItem(SYNC_LOCK_KEY);   // await
 *     if (existing) { ... }
 *     await AsyncStorage.setItem(SYNC_LOCK_KEY, ...);               // await
 *
 * There is an AWAIT BETWEEN THE CHECK AND THE SET, so two callers entering the
 * window both read "no lock", both write it, and BOTH WIN. AsyncStorage offers
 * no compare-and-set, so no arrangement of those two calls is a lock. And
 * processQueue read the queue BEFORE even asking for it, so the second drain
 * was already holding its own copy of every item by the time it "acquired".
 *
 * IT ALSO OUTLIVED THE PROCESS. The key was removed in a `finally`, which does
 * not run when the OS kills a backgrounded app mid-drain — so a phone killed in
 * a cellar came back with a lock on disk and REFUSED TO DRAIN AT ALL for the
 * next 30 seconds, silently. A lock that cannot exclude, and can strand.
 *
 * THE REPLACEMENT IS THE ONE filedPhotoQueue ALREADY USES — `let _draining =
 * false`, checked and set with NO AWAIT BETWEEN. A module-scope flag in a
 * single-threaded JS runtime is decided in one uninterruptible step, which is
 * exactly the property the storage lock could never have. There is one JS
 * context per app, so there was never a second process for a cross-process
 * lock to exclude in the first place.
 *
 * (The stale `blueview_sync_lock` key on installs that carry one is now read by
 * nothing and is inert.)
 */
let _processing = false;

const API_URL = process.env.NEXT_PUBLIC_API_URL || process.env.EXPO_PUBLIC_API_URL || 'https://api.levelog.com';

/**
 * Offline queue item structure:
 * {
 *   id: string,
 *   type: 'create' | 'update' | 'delete' | 'review',
 *   table: 'workers' | 'projects' | 'check_ins' | 'daily_logs',
 *   data: object,
 *   timestamp: number,
 *   retries: number,
 *
 *   // Optional, added for sub-resource actions (see processQueueItem).
 *   // Existing create/update/delete callers set none of these and are
 *   // routed exactly as before.
 *   path: string,        // appended to the table endpoint, e.g. '/{id}/review'
 *   method: string,      // HTTP verb for a `path` item (default POST)
 *   dedupeKey: string,   // replaces an earlier queued item with the same key
 *   meta: object,        // client-only; never sent to the API
 * }
 */

/**
 * Get current queue
 */
async function getQueue() {
  try {
    const queue = await AsyncStorage.getItem(QUEUE_KEY);
    return queue ? JSON.parse(queue) : [];
  } catch (error) {
    console.error('Failed to get queue:', error);
    return [];
  }
}

/**
 * Save queue
 */
async function saveQueue(queue) {
  try {
    await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  } catch (error) {
    console.error('Failed to save queue:', error);
  }
}

/**
 * Add item to queue.
 *
 * If the item carries a `dedupeKey`, any earlier queued item with the same key
 * is dropped first, so re-deciding the same thing offline (approve, then send
 * home) leaves ONE pending action — the last one — instead of replaying both
 * against the server in order. Items without a `dedupeKey` are appended
 * unconditionally, exactly as before.
 */
export async function addToQueue(item) {
  const queue = await getQueue();
  if (item.dedupeKey) {
    for (let i = queue.length - 1; i >= 0; i -= 1) {
      if (queue[i].dedupeKey === item.dedupeKey) queue.splice(i, 1);
    }
  }
  queue.push({
    ...item,
    id: `${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
    // ── MINTED HERE, AT ENQUEUE, AND REUSED ON EVERY ATTEMPT ──────────────
    // The queue retries a failed item up to MAX_RETRIES times, and the item
    // may be replayed once more after the app is killed mid-request. Those
    // are all ONE logical write — a create that inserts — so they must all
    // carry ONE id, or the server cannot tell a replay of the same write from
    // a genuinely new one. Minting at DISPATCH time instead would make the
    // header decoration: every attempt would look like a different write,
    // which is precisely the state we are in today.
    requestId: item.requestId || newRequestId(),
    timestamp: Date.now(),
    retries: 0,
  });
  await saveQueue(queue);
  console.log(`📋 Added to offline queue: ${item.type} ${item.table}`);
}

/**
 * Map queue item to an API call
 */
async function processQueueItem(item, token) {
  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  };

  // The id the item was minted with at enqueue — the SAME one on every attempt.
  // This path uses bare fetch, not apiClient, so it does not pass through the
  // request interceptor that stamps the header on axios calls; it stamps its
  // own, from the value it has been carrying since the tap.
  if (item.requestId) headers[REQUEST_ID_HEADER] = item.requestId;

  const tableEndpoints = {
    workers: '/api/workers',
    projects: '/api/projects',
    check_ins: '/api/checkins',
    daily_logs: '/api/daily-logs',
  };

  const endpoint = tableEndpoints[item.table];
  if (!endpoint) {
    throw new Error(`Unknown table: ${item.table}`);
  }

  let url = `${API_URL}${endpoint}`;
  let method = 'POST';

  if (item.path) {
    // Sub-resource action on an existing row — the collection endpoint alone
    // cannot express it. e.g. a check-in review decision:
    //   POST /api/checkins/{id}/review  { decision }
    url = `${url}${item.path}`;
    method = item.method || 'POST';
  } else if (item.type === 'update' && item.data._id) {
    url = `${url}/${item.data._id}`;
    method = 'PUT';
  } else if (item.type === 'delete' && item.data._id) {
    url = `${url}/${item.data._id}`;
    method = 'DELETE';
  }

  const response = await fetch(url, {
    method,
    headers,
    body: method !== 'DELETE' ? JSON.stringify(item.data) : undefined,
  });

  if (!response.ok) {
    const status = response.status;
    throw new Error(`API call failed with status ${status}`);
  }

  return await response.json();
}

/**
 * Process the queue - try to sync all pending items via direct API calls.
 * Serialized with a shared AsyncStorage lock so concurrent drains don't
 * double-post.
 */
export async function processQueue() {
  // ── THE GUARD, AND IT IS THE FIRST STATEMENT FOR A REASON ────────────────
  //
  // Checked and set with NO AWAIT BETWEEN, and before ANY await in the whole
  // function. Every await is a point at which a second caller can enter, so a
  // guard placed even one await later is not a guard: the old code read the
  // network state and then THE WHOLE QUEUE before it asked for the lock, which
  // is why a second drain already held its own copy of every item by the time
  // it was told to defer.
  //
  // Three callers reach here and none of them coordinates with the others:
  // the startup drain in DatabaseContext, the NetInfo reconnect timer 2s
  // later, and the manual Sync button. `performSync`'s own `isSyncing` check
  // cannot serialise them — it reads a per-render state value, so it sees the
  // value captured at render and never the one just set — and it could not
  // serialise the NetInfo timer in any case, because that path does not go
  // through it. Serialising HERE is what covers all three.
  if (_processing) {
    // NO `error` KEY, AND THAT IS DELIBERATE. SyncButton renders
    // `result.error` verbatim into toast.error('Sync Failed', ...), so a
    // machine token here would be shown to a CP as the explanation for a
    // sync that is in fact running perfectly well two lines away. The old
    // storage-lock path returned this exact shape and fell through to the
    // generic copy; that is preserved rather than quietly made worse.
    //
    // (Reporting a DEFERRED drain as a failure at all is wrong, but the
    // decision belongs to DatabaseContext and SyncButton, not here.)
    console.log('Queue drain already running, deferring');
    return { success: false, processed: 0 };
  }
  _processing = true;
  try {
    const state = await NetInfo.fetch();
    const isOnline = state.isConnected && state.isInternetReachable !== false;

    if (!isOnline) {
      console.log('❌ Cannot process queue - offline');
      return { success: false, processed: 0 };
    }

    const queue = await getQueue();

    if (queue.length === 0) {
      return { success: true, processed: 0 };
    }

    console.log(`📤 Processing ${queue.length} queued items...`);

    const token = await getToken();
    if (!token) {
      return { success: false, processed: 0, error: 'no_token' };
    }

    // ── THE DISK IS BROUGHT UP TO DATE AFTER EVERY ITEM ────────────────────
    //
    // It used to be written ONCE, on the way out, which made the entire drain
    // a window: a drain that never reaches its end never writes anything, so
    // an app killed while item 2 was in flight came back with item 1 — already
    // posted, already landed — still on the queue, and posted it again. That
    // is a duplicate on a non-idempotent create with no concurrency in it at
    // all, so no lock could ever have fixed it.
    //
    // `settled` records the outcome of each item as it is decided; `persist`
    // rewrites the queue in its ORIGINAL ORDER, dropping what landed and
    // replacing what failed with its bumped retry count. A failure does not
    // jump the line, and an item not yet attempted is left exactly as it was.
    //
    // AT-LEAST-ONCE, DELIBERATELY. The item in flight when the process dies
    // stays on the queue and is replayed, because losing a compliance record
    // silently is worse than sending it twice. What makes that replay honest
    // rather than reckless is `requestId`: it was minted at enqueue and is
    // unchanged, so the replay is identifiable AS a replay of one write.
    const settled = new Map(); // item.id -> null (landed) | replacement item
    const persist = async () => {
      const next = [];
      for (const q of queue) {
        if (!settled.has(q.id)) { next.push(q); continue; }
        const replacement = settled.get(q.id);
        if (replacement) next.push(replacement);
      }
      await saveQueue(next);
    };

    let processedCount = 0;
    let failedCount = 0;

    for (const item of queue) {
      if (item.retries >= MAX_RETRIES) {
        console.log(`⚠️ Max retries reached for item ${item.id}`);
        settled.set(item.id, { ...item, error: 'max_retries' });
        failedCount += 1;
        await persist();
        continue;
      }

      try {
        await processQueueItem(item, token);
        processedCount++;
        settled.set(item.id, null);
      } catch (error) {
        console.error(`Failed to process item ${item.id}:`, error.message);
        settled.set(item.id, {
          ...item,
          retries: item.retries + 1,
          lastError: error.message,
        });
        failedCount += 1;
      }
      await persist();
    }

    return {
      success: failedCount === 0,
      processed: processedCount,
      failed: failedCount,
    };
  } finally {
    _processing = false;
  }
}

/**
 * Get queue size
 */
export async function getQueueSize() {
  const queue = await getQueue();
  return queue.length;
}

/**
 * Clear the queue
 */
export async function clearQueue() {
  await AsyncStorage.removeItem(QUEUE_KEY);
  console.log('🗑️ Queue cleared');
}

/* ---------------------------------------------------------------------------
 * Check-in review decisions (site-device screen)
 *
 * An Approve / Send-home decision on a flagged check-in is a compliance record,
 * so it must survive a dead zone: the site tablet takes the decision, we store
 * it here, and the existing processQueue()/auto-processing drain posts it on
 * reconnect. Routed through the generic `path` support above — attribution
 * (reviewed_by) is still derived server-side from the token, never sent.
 * ------------------------------------------------------------------------- */

const REVIEW_DEDUPE_PREFIX = 'check_ins:review:';

/** Queue an offline Approve / Send-home decision. decision: 'approved' | 'sent_home'. */
export async function queueCheckInReview(checkinId, decision) {
  if (!checkinId || !decision) return;
  await addToQueue({
    type: 'review',
    table: 'check_ins',
    path: `/${checkinId}/review`,
    method: 'POST',
    data: { decision },
    dedupeKey: `${REVIEW_DEDUPE_PREFIX}${checkinId}`,
    meta: { checkinId, decision },
  });
}

/**
 * Decisions still waiting to sync, keyed by check-in id:
 *   { [checkinId]: { decision, queuedAt } }
 * The screen merges this over both live and cached rows so a pending decision
 * keeps showing after an app restart instead of looking like it never happened.
 */
export async function getQueuedCheckInReviews() {
  const queue = await getQueue();
  const byCheckin = {};
  for (const item of queue) {
    const checkinId = item.meta && item.meta.checkinId;
    if (item.table === 'check_ins' && item.type === 'review' && checkinId) {
      byCheckin[checkinId] = { decision: item.meta.decision, queuedAt: item.timestamp };
    }
  }
  return byCheckin;
}

/** Drop a queued decision — used when the same decision just landed online. */
export async function clearQueuedCheckInReview(checkinId) {
  if (!checkinId) return;
  const queue = await getQueue();
  const key = `${REVIEW_DEDUPE_PREFIX}${checkinId}`;
  const remaining = queue.filter((item) => item.dedupeKey !== key);
  if (remaining.length !== queue.length) await saveQueue(remaining);
}

/**
 * Setup auto-processing when coming online.
 * Waits for connection to stabilize, then processes.
 */
export function setupAutoQueueProcessing() {
  let wasOffline = false;
  let reconnectTimer = null;

  const unsubscribe = NetInfo.addEventListener(async (state) => {
    const isCurrentlyOnline = state.isConnected && state.isInternetReachable !== false;

    if (wasOffline && isCurrentlyOnline) {
      console.log('📶 Back online - scheduling queue processing...');

      // Clear any pending timer
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }

      // Wait for connection to stabilize
      reconnectTimer = setTimeout(async () => {
        reconnectTimer = null;
        const result = await processQueue();
        if (result.success) {
          console.log(`✅ Successfully processed ${result.processed} queued items`);
        } else if (result.failed) {
          console.log(`⚠️ Processed ${result.processed}, ${result.failed} failed`);
        }
      }, 2000);
    }

    wasOffline = !isCurrentlyOnline;
  });

  // Return cleanup function that also clears pending timer
  return () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    unsubscribe();
  };
}

/**
 * Get queue status for UI
 */
export async function getQueueStatus() {
  const queue = await getQueue();
  const state = await NetInfo.fetch();

  return {
    size: queue.length,
    isOnline: state.isConnected && state.isInternetReachable !== false,
    oldestItem: queue.length > 0 ? queue[0].timestamp : null,
    newestItem: queue.length > 0 ? queue[queue.length - 1].timestamp : null,
  };
}
