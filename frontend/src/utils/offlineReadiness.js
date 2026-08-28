/**
 * WHAT "SAVED FOR OFFLINE" MEANS, COMPUTED FROM THE DISK.
 *
 * The CP is standing on a site with signal, about to walk into a cellar. The
 * only question that matters to him is "can I read these drawings down there",
 * and until now nothing on the plans screen answered it. The bytes were being
 * cached — correctly, to documentDirectory rather than the OS-evictable
 * cacheDirectory — and there was no way to know whether it had worked.
 *
 * A PROJECT-LEVEL PROMISE MADE OF PER-FILE FACTS. The headline is the project
 * because that is the decision he is making. It is never STORED as a project
 * flag, because such a flag goes stale the instant one drawing changes in
 * Dropbox and bumps its cache_version, and because the failure modes are
 * per-file — one un-synced drawing must not make a whole project read "not
 * saved".
 *
 * UNSAVABLE FILES COME OUT OF THE DENOMINATOR. A file whose R2 upload failed
 * during the sync carries `r2_url: ""` and can never be downloaded; retrying
 * will not fix it. Leaving it in the count means the CP can never reach a clean
 * state, and a number that can never be satisfied is one he learns to ignore.
 * It is reported separately, with its own reason.
 */

import { listIsComplete, syncRunState, SYNC_NEVER } from './dropboxSyncState';

/** Nothing is known about this project's list yet — it has not synced under a
 *  build that records run state. NOT the same as "not saved", and the
 *  difference is the whole reason this state exists: telling a CP his plans are
 *  missing when they may be entirely on his device is worse than saying
 *  nothing. */
export const READY_UNCHECKED = 'unchecked';
/** Every savable file is on the device, at its current version. */
export const READY_ALL = 'all';
/** Some are. */
export const READY_PARTIAL = 'partial';
/** None are. */
export const READY_NONE = 'none';

const isPdfName = (name) => String(name || '').toLowerCase().endsWith('.pdf');

/** The URL a file would be fetched from, or '' if it has none. */
export const fileRemoteUrl = (f) => String(f?.r2_url || f?.directUrl || '').trim();

/**
 * A file the device could hold. PDFs only: everything else is handed to another
 * app over the network and has no offline story at all, so counting it would
 * make the promise unkeepable by construction.
 */
export const isSavable = (f) => isPdfName(f?.name) && fileRemoteUrl(f) !== '';

/**
 * A PDF that cannot be saved however many times he asks. `r2_url` is empty
 * because the sync downloaded the file from Dropbox and the R2 upload failed;
 * there is no source for the bytes.
 */
export const isUnsavable = (f) => isPdfName(f?.name) && fileRemoteUrl(f) === '';

/**
 * Readiness for one project.
 *
 * `cachedNames` is the Set from listCachedDocs(); `nameOf` builds the on-disk
 * name for a file. Both are injected so this module stays pure and testable
 * without a filesystem.
 */
export function readinessOf({ files, cachedNames, nameOf, sync }) {
  const list = Array.isArray(files) ? files : [];
  const names = cachedNames instanceof Set ? cachedNames : new Set();

  const savable = list.filter(isSavable);
  const unsavable = list.filter(isUnsavable);

  const saved = savable.filter((f) => names.has(nameOf(f)));
  const missing = savable.filter((f) => !names.has(nameOf(f)));
  const bytesRemaining = missing.reduce(
    (n, f) => n + (Number.isFinite(Number(f?.size)) ? Number(f.size) : 0), 0,
  );

  // THE LIST ITSELF MUST BE TRUSTWORTHY BEFORE ANY COUNT OVER IT MEANS
  // ANYTHING. #252 exists because a mid-sync read can produce a list that is a
  // strict subset of the project: "All 15 saved" over a list that should hold
  // 20 is a worse lie than silence, because he acts on it.
  const state = !listIsComplete(sync)
    ? READY_UNCHECKED
    : missing.length === 0
      ? (savable.length === 0 ? READY_UNCHECKED : READY_ALL)
      : saved.length === 0
        ? READY_NONE
        : READY_PARTIAL;

  return {
    state,
    saved: saved.length,
    savable: savable.length,
    missing,
    unsavable: unsavable.length,
    bytesRemaining,
    // Distinguishes "we have never seen a sync" from "a sync ran and lost
    // files", which the copy says differently.
    neverSynced: syncRunState(sync) === SYNC_NEVER,
  };
}

/**
 * The order Save all should download in: THE ORDER HE IS LOOKING AT.
 *
 * Not Mongo's natural order, and not the "newest first" a docstring once
 * promised while the code did neither. What is on screen is what he is thinking
 * about, so it should land first. Already-saved files are skipped rather than
 * reordered — re-checking them is what makes this resumable after a failure.
 */
export function saveQueue({ files, cachedNames, nameOf }) {
  const names = cachedNames instanceof Set ? cachedNames : new Set();
  return (Array.isArray(files) ? files : [])
    .filter(isSavable)
    .filter((f) => !names.has(nameOf(f)));
}

/** Whole megabytes, for copy. Deliberately coarse: a CP deciding whether to
 *  wait does not need three significant figures. */
export const megabytes = (bytes) => Math.max(1, Math.round((Number(bytes) || 0) / 1048576));

/**
 * Is there room? Returns null when free space cannot be determined, and null
 * must be treated as "go ahead" — refusing on an unknown would block a CP for
 * a reason we cannot even state.
 *
 * The margin exists because the download writes a temp file before it settles,
 * and because filling a device to zero is its own failure.
 */
export const HEADROOM_BYTES = 50 * 1024 * 1024;
export function hasRoomFor(bytesNeeded, freeBytes) {
  if (freeBytes === null || freeBytes === undefined) return null;
  if (!Number.isFinite(Number(freeBytes))) return null;
  return Number(freeBytes) > (Number(bytesNeeded) || 0) + HEADROOM_BYTES;
}

export default {
  READY_UNCHECKED,
  READY_ALL,
  READY_PARTIAL,
  READY_NONE,
  HEADROOM_BYTES,
  fileRemoteUrl,
  isSavable,
  isUnsavable,
  readinessOf,
  saveQueue,
  megabytes,
  hasRoomFor,
};
