/**
 * IS THE FILE LIST I JUST READ THE WHOLE LIST?
 *
 * The plans screen keeps an offline copy of the project's file list, and it was
 * writing that copy from whatever it happened to read. `POST /sync-dropbox`
 * returns as soon as the background task is SCHEDULED, so a read taken straight
 * afterwards catches the sync partway through — and the saved-for-offline list
 * could be a strict SUBSET of the project. A CP in a cellar would be missing
 * drawings with nothing on screen to say so.
 *
 * The server now records a sync run and mirrors a summary onto the project
 * document as `dropbox_sync`. This module is the one place that decides what
 * that summary means.
 *
 * WHY A RULE AND NOT A HEURISTIC — the next reader will wonder, because the
 * obvious heuristic is right there: "don't replace a longer cached list with a
 * shorter one." It does not work. A shorter list is often CORRECT — files get
 * deleted from Dropbox, a folder gets re-pointed, a subfolder allow-list
 * changes — and a rule that refuses to shrink would pin deleted drawings on a
 * CP's device for ever and call it caching. Length cannot distinguish "the sync
 * is halfway through" from "there are genuinely fewer files now". Only the sync
 * itself knows, so the sync is asked.
 */

/** The bounded window in which a `running` record is still believed.
 *
 *  Must match DROPBOX_SYNC_STALE_AFTER_SECONDS on the server. It is duplicated
 *  rather than fetched because the client has to reach a decision offline, when
 *  no server is reachable to ask. */
export const SYNC_STALE_AFTER_MS = 15 * 60 * 1000;

export const SYNC_NEVER = 'never';
export const SYNC_RUNNING = 'running';
export const SYNC_COMPLETE = 'complete';
export const SYNC_FAILED = 'failed';
export const SYNC_UNKNOWN = 'unknown';

/**
 * What the project's `dropbox_sync` summary says right now.
 *
 * A `running` record older than the window reads UNKNOWN, not running. The
 * process can die mid-sync — a restart, an error above the try — and a record
 * left at "running" for ever would make the client decline to refresh its
 * offline list permanently. That is the failure this rule exists to avoid, and
 * it is worse than the one it is guarding against.
 */
export function syncRunState(sync, now = Date.now()) {
  if (!sync || typeof sync !== 'object') return SYNC_NEVER;

  const status = String(sync.status || '').trim();
  if (status === SYNC_COMPLETE) return SYNC_COMPLETE;
  if (status === SYNC_FAILED) return SYNC_FAILED;
  if (status !== SYNC_RUNNING) return SYNC_NEVER;

  const startedAt = Date.parse(sync.started_at || '');
  // An unparseable or absent start time cannot be aged, and a record we cannot
  // age must not be believed indefinitely.
  if (!Number.isFinite(startedAt)) return SYNC_UNKNOWN;
  return (now - startedAt) < SYNC_STALE_AFTER_MS ? SYNC_RUNNING : SYNC_UNKNOWN;
}

/**
 * May this freshly-read list REPLACE the saved offline copy?
 *
 * FALSE IN EXACTLY ONE CASE: a sync is genuinely in flight. Everything else is
 * true, including UNKNOWN, and that direction is deliberate.
 *
 * UNKNOWN LETS THE MAN USE WHAT HE HAS. The only thing withholding the write
 * buys is protection from overwriting a good list with a partial one during a
 * short, known window. It is not a safety mechanism worth extending: a client
 * that refuses to cache because it cannot tell what the server is doing would
 * leave a CP with a list that never updates again, which is the exact failure
 * this whole change is about.
 *
 * NEVER is true as well, and that is what makes this safe to ship. No project
 * carries `dropbox_sync` until its next sync, so on the day this lands every
 * project behaves exactly as it does today.
 */
export function mayCacheList(sync, now = Date.now()) {
  return syncRunState(sync, now) !== SYNC_RUNNING;
}

/**
 * Is the list KNOWN to be the whole list? Stricter than mayCacheList, and a
 * different question — this one is for telling a CP that his plans are
 * complete, which PR 2's readiness strip will need.
 *
 * Only a completed run that lost no files can say yes. `failed` counts the
 * per-file skips the sync now records; they are not retried here, but a list
 * missing three drawings must never be described as whole.
 */
export function listIsComplete(sync, now = Date.now()) {
  if (syncRunState(sync, now) !== SYNC_COMPLETE) return false;
  const expected = Number(sync?.expected);
  const synced = Number(sync?.synced);
  if (!Number.isFinite(expected) || !Number.isFinite(synced)) return false;
  return Number(sync?.failed || 0) === 0 && synced >= expected;
}

export default {
  SYNC_STALE_AFTER_MS,
  SYNC_NEVER,
  SYNC_RUNNING,
  SYNC_COMPLETE,
  SYNC_FAILED,
  SYNC_UNKNOWN,
  syncRunState,
  mayCacheList,
  listIsComplete,
};
