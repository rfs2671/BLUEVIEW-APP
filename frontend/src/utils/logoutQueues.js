import NetInfo from '@react-native-community/netinfo';
import { processQueue } from './offlineQueue';
import { syncPendingDrafts } from './draftSync';
import { drainFiledPhotoQueue } from './filedPhotoQueue';
import { clearAccountQueues, countPendingWrites } from './accountQueues';

/**
 * THE ACCOUNT LEAVES, AND ITS UNSENT WRITES GO WITH IT — SENT IF POSSIBLE.
 *
 * Before a logout clears the token, the queued writes get one bounded chance
 * to go under the account that made them. Whatever has not gone by then is
 * deleted (accountQueues.clearAccountQueues), never left for the next person.
 *
 * BOUNDED, because a logout that hangs on a cellar's signal is a logout nobody
 * can finish: one budget across all three drains, then the clear runs whatever
 * they have reached. SKIPPED OFFLINE, because a request that cannot leave the
 * phone only spends the budget.
 *
 * Forced logouts (a 401 the server means, a session that cannot be restored)
 * do not come here: the token they would drain with is the one just refused or
 * missing. They clear through clearAuth.
 */

export const LOGOUT_DRAIN_BUDGET_MS = 5000;

const isOnlineState = (s) => Boolean(s && s.isConnected && s.isInternetReachable !== false);

/**
 * Try to send everything queued, with the current token, within the budget.
 * Returns { attempted, outcome, remaining } — `remaining` is a fresh count, the
 * number the logout confirm shows.
 */
export async function drainAccountQueues({ timeoutMs = LOGOUT_DRAIN_BUDGET_MS } = {}) {
  const before = await countPendingWrites();
  if (before.total === 0) return { attempted: false, outcome: 'empty', remaining: before };

  let online = false;
  try { online = isOnlineState(await NetInfo.fetch()); } catch (_e) { online = false; }
  if (!online) return { attempted: false, outcome: 'offline', remaining: before };

  let timer = null;
  const deadline = new Promise((resolve) => { timer = setTimeout(() => resolve('timeout'), timeoutMs); });
  // Each drain carries its own one-at-a-time guard and never throws to here;
  // allSettled is so one that does cannot cut the others short.
  const work = Promise.allSettled([
    processQueue(),
    syncPendingDrafts(),
    drainFiledPhotoQueue(),
  ]).then(() => 'done');
  const outcome = await Promise.race([work, deadline]);
  if (timer) clearTimeout(timer);

  return { attempted: true, outcome, remaining: await countPendingWrites() };
}

/**
 * THE ONE ROUTINE FOR AN ACCOUNT LEAVING THIS DEVICE. Logout calls it; an
 * account switcher, when there is one, must call the same thing.
 *
 * `drain: false` when the caller already drained and the person chose to
 * delete what was left ("Log out anyway").
 */
export async function drainAndClearAccountQueues({ drain = true, timeoutMs } = {}) {
  let drained = null;
  if (drain) {
    try {
      drained = await drainAccountQueues(timeoutMs === undefined ? {} : { timeoutMs });
    } catch (_e) {
      drained = null; // a drain that failed still ends in the clear
    }
  }
  const cleared = await clearAccountQueues();
  return { drained, cleared };
}
